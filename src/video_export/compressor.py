"""Apple Compressor CLI adapter, independent of Resolve."""

import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .common import ExportError, noisy_json, outputs_available, path, run
from .verification import verify

DEFAULT_BINARY = "/Applications/Compressor.app/Contents/MacOS/Compressor"


def binary():
    return os.environ.get("VIDEO_EXPORT_COMPRESSOR", DEFAULT_BINARY)


def preset(filename):
    file = path(filename)
    try:
        root = ET.parse(file).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ExportError("preset_invalid", str(exc), setting=str(file)) from exc
    if root.tag != "setting":
        raise ExportError("preset_invalid", "Expected a Compressor setting XML document")
    video = root.find(".//video-encode")
    bounds = video.find("bounds") if video is not None else None
    width, height = (bounds.get("width"), bounds.get("height")) if bounds is not None else (None, None)
    extension = root.findtext(".//file-extension")
    if not extension or not extension.isalnum():
        raise ExportError("preset_invalid", "Preset has no valid file-extension")
    return {"setting": str(file), "name": root.get("name"), "extension": extension,
            "codec": video.findtext("codec-type") if video is not None else None,
            "frame_rate": video.findtext("frame-rate") if video is not None else None,
            "width": width, "height": height,
            "resolution_mode": "follow_source" if "-100" in (width, height) else "explicit_or_other",
            "video_enabled": video is not None and video.get("isEnabled") != "no"}


def plan_targets(source, profile, settings=None, output=None, directory=None):
    source = path(source)
    targets = profile.get("compressor", {}).get("targets", [])
    if settings:
        targets = [{"setting": setting, "suffix": f"-{index + 1}"}
                   for index, setting in enumerate(settings)]
    if not targets:
        raise ExportError("config_invalid", "At least one Compressor target is required")
    if output and len(targets) != 1:
        raise ExportError("config_invalid", "--output requires exactly one Compressor target")
    base = path(directory or profile.get("outputs", {}).get("directory") or source.parent)
    planned = []
    for target in targets:
        metadata = preset(target["setting"])
        filename = output or target.get("output") or base / (
            source.stem + target.get("suffix", "-delivery") + "." + metadata["extension"])
        if path(filename).suffix.lower() != "." + metadata["extension"].lower():
            raise ExportError("output_invalid", "Output extension must match Compressor preset")
        planned.append({"setting": metadata["setting"], "output": str(path(filename)),
                        "preset": metadata})
    outputs_available([target["output"] for target in planned], [source])
    return planned


def submit_command(source, targets):
    command = [binary(), "-batchname", "video-export", "-priority", "medium"]
    for target in targets:
        command += ["-jobpath", path(source).as_uri(), "-settingpath", target["setting"],
                    "-locationpath", target["output"]]
    return command + ["-outputformat", "json"]


def status(batch_id, timeout=60):
    return noisy_json(run([binary(), "-monitor", "-format", "json", "-batchid", batch_id, "-once"],
                          timeout=timeout))


def batch_status(payload, batch_id):
    """Find only the requested batch, never accept an arbitrary successful child job."""
    if isinstance(payload, dict):
        found = payload.get("batchID", payload.get("batchid", payload.get("id")))
        if str(found) == batch_id and "status" in payload:
            return str(payload["status"])
        # A single batch response may omit its ID; the monitor was scoped by ID.
        batch = payload.get("batch")
        if isinstance(batch, dict) and "status" in batch and not any(
                key in batch for key in ("batchID", "batchid", "id")):
            return str(batch["status"])
        for value in payload.values():
            result = batch_status(value, batch_id)
            if result:
                return result
    elif isinstance(payload, list):
        for value in payload:
            result = batch_status(value, batch_id)
            if result:
                return result
    return None


def preset_expectations(metadata, source_info):
    checks = {}
    codecs = {"hvc1": "hevc", "hev1": "hevc", "avc1": "h264", "apch": "prores",
              "apcn": "prores", "apcs": "prores", "apco": "prores", "ap4h": "prores"}
    if (metadata.get("codec") or "").strip() in codecs:
        checks["codec_name"] = codecs[metadata["codec"].strip()]
    for key in ("width", "height"):
        value = metadata.get(key)
        if value and int(value) > 0:
            checks[key] = int(value)
        # Follow-source dimensions can include cropping or padding; do not infer
        # geometry from -100 alone. Explicit --expect-resolution remains available.
    frame_rate = metadata.get("frame_rate")
    if frame_rate and float(frame_rate) > 0:
        checks["frame_rate"] = float(frame_rate)
    return checks


def transcode(source, targets, state, timeout=3600, poll=5, window=2, decode=False, expected=None):
    expected = expected or {}
    source_info = verify(source, {"duration": expected.get("duration")}, window=window)
    target_checks = []
    for target in targets:
        checks = {"duration": source_info["duration"],
                  **preset_expectations(target.get("preset", {}), source_info)}
        for key, value in expected.items():
            if key in checks and key != "duration" and value != checks[key]:
                raise ExportError("expectation_conflict", "CLI expectation conflicts with preset",
                                  field=key, preset=checks[key], requested=value)
            if key != "duration":
                checks[key] = value
        target_checks.append(checks)
    outputs_available([target["output"] for target in targets], [source])
    for target in targets:
        path(target["output"]).parent.mkdir(parents=True, exist_ok=True)
    response = noisy_json(run(submit_command(source, targets)))
    batch = response.get("batch", {}) if isinstance(response, dict) else {}
    batch_id = batch.get("batchID", batch.get("batchid"))
    if not batch_id:
        raise ExportError("batch_not_submitted", "No batch ID in response", response=response)
    state.save(compressor={"batch_id": batch_id, "submission": response, "status": "queued"})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = status(batch_id, timeout=max(0.001, deadline - time.monotonic()))
        current = batch_status(response, batch_id)
        state.save(compressor={"batch_id": batch_id, "monitor": response, "status": current})
        if time.monotonic() >= deadline:
            raise ExportError("compressor_timeout", "Monitor exceeded budget; batch not cancelled",
                              batch_id=batch_id)
        if current == "Successful":
            break
        if current in ("Failed", "Cancelled", "Canceled"):
            raise ExportError("compressor_batch_failed", "Batch did not succeed", batch_id=batch_id,
                              response=response)
        time.sleep(min(poll, max(0, deadline - time.monotonic())))
    else:
        raise ExportError("compressor_timeout", "Batch still active; not cancelled", batch_id=batch_id)
    results = []
    for target, checks in zip(targets, target_checks, strict=True):
        info = verify(target["output"], checks, decode=decode, window=window, timeout=timeout)
        results.append({"output": target["output"], "media": info})
        state.save(targets=results)
    return {"batch_id": batch_id, "outputs": results}


def discover_presets():
    group_root = Path.home() / "Library/Group Containers"
    return sorted(str(file) for file in group_root.glob(
        "*.com.apple.videoProApps/Library/Application Support/Compressor/Settings/*.compressorsetting"))
