"""Opt-in macOS smoke test using generated media and a disposable scratch project."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from video_export.common import ExportError
from video_export.resolve import API, APP, LIB


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--setting", type=Path, required=True)
    parser.add_argument("--resolve-preset", required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Live smoke requires macOS")
    if subprocess.run(["pgrep", "-x", "Resolve"], capture_output=True).returncode == 0:
        parser.error("Close Resolve before this test; existing sessions are never touched")
    os.umask(0o077)
    folder = args.work_dir.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=False)
    os.environ["RESOLVE_SCRIPT_LIB"] = os.environ.get("VIDEO_EXPORT_RESOLVE_LIB", LIB)
    sys.path.insert(0, str(Path(os.environ.get("VIDEO_EXPORT_RESOLVE_API", API)) / "Modules"))
    import DaVinciResolveScript as dvr

    source = folder / "synthetic.mov"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                    "-c:v", "prores_ks", "-profile:v", "1", "-c:a", "pcm_s16le", str(source)],
                   check=True, timeout=60)
    log = (folder / "resolve.log").open("w")
    process = subprocess.Popen([os.environ.get("VIDEO_EXPORT_RESOLVE_APP", APP), "-nogui"],
                               stdout=log, stderr=log)
    resolve = None
    try:
        deadline = time.monotonic() + 120
        while not resolve and time.monotonic() < deadline:
            if process.poll() is not None:
                raise ExportError("resolve_start_failed", "Headless Resolve exited")
            resolve = dvr.scriptapp("Resolve")
            if not resolve:
                time.sleep(2)
        if not resolve:
            raise ExportError("resolve_start_timeout", "Headless Resolve left running; inspect log")
        manager = resolve.GetProjectManager()
        project = manager.CreateProject("video_export_scratch_" + uuid.uuid4().hex[:12])
        if not project:
            raise ExportError("scratch_failed", "Could not create scratch project")
        for key, value in (("timelineFrameRate", "24"), ("timelineResolutionWidth", "1280"),
                           ("timelineResolutionHeight", "720")):
            if not project.SetSetting(key, value):
                raise ExportError("scratch_failed", f"Could not set {key}")
        pool = project.GetMediaPool()
        timeline = pool.CreateTimelineFromClips("Scratch", pool.ImportMedia([str(source)]))
        if not timeline:
            raise ExportError("scratch_failed", "Could not create scratch timeline")
        profile = folder / "profile.toml"
        profile.write_text("[resolve]\n" + "\n".join(
            f"{key} = {json.dumps(value)}" for key, value in {
                "project": project.GetName(), "timeline": "Scratch", "preset": args.resolve_preset,
                "output": str(folder / "master.mov")}.items()) +
            "\n[[compressor.targets]]\nsetting = " + json.dumps(str(args.setting.resolve())) +
            '\nsuffix = "-delivery"\n')
        command = [sys.executable, "-m", "video_export.cli", "pipeline", "run", "--profile", str(profile),
                   "--state-dir", str(folder / "state"), "--timeout", "180", "--poll", "2",
                   "--verify-decode"]
        for suffix, name in (([], "plan"), (["--execute"], "execution")):
            result = subprocess.run(command + suffix, capture_output=True, text=True, timeout=240)
            (folder / f"{name}.json").write_text(result.stdout)
            (folder / f"{name}.stderr").write_text(result.stderr)
            if result.returncode:
                raise ExportError("smoke_failed", "Inspect private execution output", stage=name)
        print(json.dumps({"ok": True, "work_dir": str(folder), "frames": 48}))
    finally:
        if resolve:
            current = resolve.GetProjectManager().GetCurrentProject()
            if not current or not current.IsRenderingInProgress():
                if current:
                    resolve.GetProjectManager().CloseProject(current)
                resolve.Quit()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    print("Resolve Quit pending; no termination signal sent", file=sys.stderr)
        log.close()


if __name__ == "__main__":
    main()
