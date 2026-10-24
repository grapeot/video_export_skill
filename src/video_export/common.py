"""Shared subprocess and JSON boundaries."""

import json
import subprocess
from pathlib import Path


class ExportError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def run(command, timeout=60, **kwargs):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise ExportError("process_timeout", "Child process timed out", command=command) from exc
    except OSError as exc:
        raise ExportError("process_unavailable", str(exc), command=command) from exc
    if result.returncode:
        raise ExportError("process_failed", "Child process failed", command=command,
                          exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
    return result.stdout


def noisy_json(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, (dict, list)):
            return value
    raise ExportError("invalid_backend_json", "No JSON object found", raw=text)


def path(value):
    return Path(value).expanduser().resolve()


def outputs_available(outputs, inputs=()):
    resolved = [path(item) for item in outputs]
    sources = {path(item) for item in inputs}
    if len(resolved) != len(set(resolved)) or sources.intersection(resolved):
        raise ExportError("output_collision", "Output paths must be distinct from each other and inputs")
    for item in resolved:
        if item.exists() or item.is_symlink():
            raise ExportError("output_collision", "Output already exists", output=str(item))
        if not item.suffix:
            raise ExportError("output_invalid", "Output requires a filename extension", output=str(item))
    return resolved
