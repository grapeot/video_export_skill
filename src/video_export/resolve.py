"""Subprocess-isolated access to the official Resolve scripting API."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import ExportError

API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
APP = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve"


def call(action, options=None, timeout=3600, headless=False, checkpoint=None):
    request = {"action": action, "options": options or {}, "headless": headless,
               "timeout": timeout, "checkpoint": str(checkpoint) if checkpoint else None}
    env = os.environ.copy()
    env["RESOLVE_SCRIPT_API"] = env.get("VIDEO_EXPORT_RESOLVE_API", env.get("RESOLVE_SCRIPT_API", API))
    env["RESOLVE_SCRIPT_LIB"] = env.get("VIDEO_EXPORT_RESOLVE_LIB", env.get("RESOLVE_SCRIPT_LIB", LIB))
    env["PYTHONPATH"] = str(Path(env["RESOLVE_SCRIPT_API"]) / "Modules") + os.pathsep + env.get("PYTHONPATH", "")
    with tempfile.TemporaryDirectory(prefix="video-export-ipc-") as folder:
        result = Path(folder) / "result.json"
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "video_export.resolve_worker", str(result)],
                input=json.dumps(request), capture_output=True, text=True, env=env, timeout=timeout + 30)
        except subprocess.TimeoutExpired as exc:
            raise ExportError("resolve_ipc_timeout", "Resolve helper timed out; application not killed",
                              checkpoint=request["checkpoint"]) from exc
        if not result.exists():
            raise ExportError("resolve_worker_failed", "Resolve helper produced no result",
                              exit_code=completed.returncode, stderr=completed.stderr)
        payload = json.loads(result.read_text())
        if not payload.get("ok"):
            raise ExportError(payload["error"], payload["message"], **payload.get("details", {}))
        return payload["data"]
