"""Bounded writer/stability checks and measured media properties."""

import json
import math
import shutil
import subprocess
import time
from fractions import Fraction

from .common import ExportError, path, run


def stable_file(filename, window=2):
    file = path(filename)
    def sample():
        if not file.is_file():
            raise ExportError("source_invalid", "Media file is missing", path=str(file))
        lsof = shutil.which("lsof")
        if not lsof:
            raise ExportError("dependency_missing", "lsof is required for writer checks")
        try:
            result = subprocess.run([lsof, "-Ffa", "--", str(file)], capture_output=True,
                                    text=True, timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise ExportError("writer_check_timeout", "lsof timed out", path=str(file)) from exc
        if result.returncode not in (0, 1) or (result.returncode == 1 and result.stderr.strip()):
            raise ExportError("writer_check_failed", result.stderr or "lsof failed")
        if any(line in ("aw", "au") for line in result.stdout.splitlines()):
            raise ExportError("source_unstable", "Media has an open writer", path=str(file))
        stat = file.stat()
        if stat.st_size <= 0:
            raise ExportError("source_invalid", "Media file is empty")
        return stat.st_size, stat.st_mtime_ns
    first = sample()
    time.sleep(window)
    if sample() != first:
        raise ExportError("source_unstable", "Media changed during stability window")


def inspect_media(filename):
    info = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                           "-of", "json", str(path(filename))]))
    videos = [stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"]
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ExportError("media_invalid", "No valid media duration") from exc
    if not videos or not math.isfinite(duration) or duration <= 0:
        raise ExportError("media_invalid", "Positive duration and a video stream are required")
    return {"duration": duration, "video": videos[0], "format": info["format"]}


def verify(filename, expected=None, decode=False, window=2, timeout=3600):
    stable_file(filename, window)
    media = inspect_media(filename)
    expected = expected or {}
    for key, value in expected.items():
        if value is None:
            continue
        actual = media["duration"] if key == "duration" else media["video"].get(key)
        if key == "duration":
            matches = abs(actual - value) <= expected.get("duration_tolerance", 0.1)
        elif key == "frame_rate":
            try:
                actual = float(Fraction(media["video"]["avg_frame_rate"]))
            except (KeyError, ValueError, ZeroDivisionError) as exc:
                raise ExportError("media_invalid", "Invalid output frame rate") from exc
            matches = abs(actual - value) < 0.01
        elif key == "duration_tolerance":
            continue
        else:
            matches = actual == value
        if not matches:
            raise ExportError("media_mismatch", f"Unexpected {key}", expected=value, actual=actual)
    if decode:
        try:
            stderr = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path(filename)),
                                     "-f", "null", "-"], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ExportError("decode_timeout", "Full decode timed out", path=str(filename)) from exc
        if stderr.returncode or stderr.stderr.strip():
            raise ExportError("decode_failed", "Full decode failed", stderr=stderr.stderr)
    return media
