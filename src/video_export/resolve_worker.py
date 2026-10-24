"""Resolve IPC worker. Result-file protocol isolates native-library stdout noise."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .common import ExportError, outputs_available, path
from .resolve import APP


def choose_project(manager, name, owned=False):
    current = manager.GetCurrentProject()
    if current and (not name or current.GetName() == name):
        return current
    if current and current.GetName() != "Untitled Project" and not owned:
        raise ExportError("foreign_project_loaded", "Open the requested project in Resolve first")
    project = manager.LoadProject(name) if name else None
    if not project:
        raise ExportError("project_not_found", "Requested project was not found")
    return project


def timeline_info(timeline):
    fps = float(timeline.GetSetting("timelineFrameRate"))
    frames = timeline.GetEndFrame() - timeline.GetStartFrame()
    return {"name": timeline.GetName(), "fps": fps, "frames": frames,
            "duration": frames / fps,
            "width": int(timeline.GetSetting("timelineResolutionWidth")),
            "height": int(timeline.GetSetting("timelineResolutionHeight"))}


def require_budget(request):
    if "deadline" in request and time.monotonic() >= request["deadline"]:
        raise ExportError("resolve_render_timeout", "Resolve deadline reached before job submission")


def operate(resolve, request, owned=False):
    action, options = request["action"], request.get("options", {})
    manager = resolve.GetProjectManager()
    if action == "doctor":
        return {"product": resolve.GetProductName(), "version": resolve.GetVersionString(),
                "database": manager.GetCurrentDatabase()}
    if action == "projects":
        return {"projects": manager.GetProjectListInCurrentFolder(),
                "folders": manager.GetFolderListInCurrentFolder(),
                "folder": manager.GetCurrentFolder(), "database": manager.GetCurrentDatabase()}
    project = choose_project(manager, options.get("project"), owned)
    timelines = [project.GetTimelineByIndex(index)
                 for index in range(1, int(project.GetTimelineCount()) + 1)]
    if action == "inspect":
        return {"project": project.GetName(), "timelines": [timeline_info(t) for t in timelines],
                "presets": project.GetRenderPresetList(),
                "format_codec": project.GetCurrentRenderFormatAndCodec(),
                "render_jobs": project.GetRenderJobList()}
    require_budget(request)
    if project.IsRenderingInProgress():
        raise ExportError("resolve_busy", "Resolve is already rendering")
    matches = [t for t in timelines if t.GetName() == options["timeline"]]
    if len(matches) != 1:
        raise ExportError("timeline_not_found", "Timeline name must identify exactly one timeline")
    if options["preset"] not in project.GetRenderPresetList():
        raise ExportError("preset_not_found", "Requested Deliver preset does not exist")
    output = outputs_available([options["output"]])[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    for label, value in (("timeline", project.SetCurrentTimeline(matches[0])),
                         ("preset", project.LoadRenderPreset(options["preset"])),
                         ("mode", project.SetCurrentRenderMode(1))):
        if not value:
            raise ExportError("resolve_setting_failed", f"Could not select {label}")
    if options.get("format") and not project.SetCurrentRenderFormatAndCodec(
            options["format"], options["codec"]):
        raise ExportError("resolve_setting_failed", "Could not select format/codec")
    selected = project.GetCurrentRenderFormatAndCodec()
    if output.suffix.lower() != "." + selected["format"].lower():
        raise ExportError("output_invalid", "Output extension must match selected render format",
                          selected=selected)
    settings = {"SelectAllFrames": True, "TargetDir": str(output.parent),
                "CustomName": output.stem, "ExportVideo": True, "ExportAudio": True}
    if options.get("resolution"):
        settings["FormatWidth"], settings["FormatHeight"] = map(
            int, options["resolution"].lower().split("x"))
    for key, setting in (("frame_rate", "FrameRate"), ("audio_codec", "AudioCodec"),
                         ("audio_bit_depth", "AudioBitDepth"),
                         ("audio_sample_rate", "AudioSampleRate")):
        if key in options:
            settings[setting] = options[key]
    if not project.SetRenderSettings(settings):
        raise ExportError("resolve_setting_failed", "Could not set render output")
    require_budget(request)
    job_id = project.AddRenderJob()
    if not job_id:
        raise ExportError("render_job_failed", "Could not create render job")
    def checkpoint(status):
        if request.get("checkpoint"):
            path(request["checkpoint"]).write_text(json.dumps(
                {"job_id": job_id, "status": status, "output": str(output)}))
    checkpoint("queued")
    require_budget(request)
    if not project.StartRendering([job_id]):
        raise ExportError("render_job_failed", "Could not start own render job", job_id=job_id)
    deadline = request.get("deadline", time.monotonic() + request.get("timeout", 3600))
    while time.monotonic() < deadline:
        status = project.GetRenderJobStatus(job_id)
        checkpoint(status)
        name = status.get("JobStatus") if status else None
        if name == "Complete":
            info = timeline_info(matches[0])
            # Confirm actual filename from queue metadata, not only requested stem.
            jobs = project.GetRenderJobList() or []
            job = next((j for j in jobs if j.get("JobId") == job_id), {})
            actual = job.get("OutputFilename")
            if actual and Path(actual).name != output.name:
                raise ExportError("output_name_mismatch", "Resolve chose a different output name",
                                  job_id=job_id, actual=actual)
            return {"job_id": job_id, "status": status, "timeline": info,
                    "format_codec": selected, "render_settings": settings, "output": str(output)}
        if name in ("Failed", "Cancelled", "Canceled"):
            raise ExportError("render_job_failed", "Render did not succeed", job_id=job_id, status=status)
        time.sleep(1)
    raise ExportError("resolve_render_timeout", "Render still active; not cancelled", job_id=job_id)


def dispatch(request):
    request["deadline"] = time.monotonic() + request.get("timeout", 3600)
    try:
        import DaVinciResolveScript as dvr
    except ImportError as exc:
        raise ExportError("resolve_api_missing", str(exc)) from exc
    resolve = dvr.scriptapp("Resolve")
    owned = False
    log = None
    if not resolve and request.get("headless"):
        running = subprocess.run(["pgrep", "-x", "Resolve"], capture_output=True, text=True)
        if running.returncode == 0:
            raise ExportError("resolve_not_ready", "Resolve is running but scripting is not reachable")
        log_path = (path(request["checkpoint"]).parent if request.get("checkpoint")
                    else Path(os.environ.get("TMPDIR", "/tmp"))) / "video-export-resolve.log"
        log = log_path.open("a")
        process = subprocess.Popen([os.environ.get("VIDEO_EXPORT_RESOLVE_APP", APP), "-nogui"],
                                   stdout=log, stderr=log)
        owned = True
        deadline = min(time.monotonic() + 120, request["deadline"])
        while not resolve and time.monotonic() < deadline:
            if process.poll() is not None:
                raise ExportError("resolve_start_failed", "Headless process exited", log=str(log_path))
            time.sleep(min(2, max(0, deadline - time.monotonic())))
            resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise ExportError("resolve_not_running", "Open Resolve and enable Local external scripting")
    try:
        require_budget(request)
        return operate(resolve, request, owned)
    finally:
        if owned:
            project = resolve.GetProjectManager().GetCurrentProject()
            if not project or not project.IsRenderingInProgress():
                resolve.Quit()
        if log:
            log.close()


def main():
    result = Path(sys.argv[1])
    try:
        data = dispatch(json.load(sys.stdin))
        payload = {"ok": True, "data": data}
    except ExportError as exc:
        payload = {"ok": False, "error": exc.code, "message": str(exc), "details": exc.details}
    except Exception as exc:
        payload = {"ok": False, "error": "resolve_api_error", "message": str(exc),
                   "details": {"type": type(exc).__name__}}
    result.write_text(json.dumps(payload))


if __name__ == "__main__":
    main()
