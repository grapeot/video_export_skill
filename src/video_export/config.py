"""External profile validation; no personal preset defaults."""

import tomllib

from .common import ExportError, path


def check_keys(data, allowed, label):
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise ExportError("config_invalid", f"Unknown keys or invalid table: {label}")


def load_profile(filename=None):
    if not filename:
        return {}
    try:
        with path(filename).open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, ValueError) as exc:
        raise ExportError("config_invalid", str(exc)) from exc
    check_keys(data, ("resolve", "outputs", "compressor"), "profile")
    check_keys(data.get("resolve", {}), ("project", "timeline", "preset", "output", "format", "codec"),
               "resolve")
    check_keys(data.get("outputs", {}), ("directory", "keep_master"), "outputs")
    check_keys(data.get("compressor", {}), ("targets",), "compressor")
    if data.get("outputs", {}).get("keep_master", True) is not True:
        raise ExportError("config_invalid", "keep_master must be true")
    targets = data.get("compressor", {}).get("targets", [])
    if not isinstance(targets, list):
        raise ExportError("config_invalid", "compressor.targets must be an array")
    for target in targets:
        check_keys(target, ("setting", "suffix", "output"), "compressor.targets")
        if not isinstance(target.get("setting"), str) or not target["setting"]:
            raise ExportError("config_invalid", "Each target requires a setting path")
        suffix = target.get("suffix", "")
        if not isinstance(suffix, str) or "/" in suffix or "\\" in suffix:
            raise ExportError("config_invalid", "Target suffix must be a filename suffix")
        if not suffix and not target.get("output"):
            raise ExportError("config_invalid", "Each target requires a suffix or output")
    for section in ("resolve", "outputs"):
        for key, value in data.get(section, {}).items():
            if key != "keep_master" and (not isinstance(value, str) or not value):
                raise ExportError("config_invalid", f"{section}.{key} must be a non-empty string")
    for target in targets:
        if "output" in target and (not isinstance(target["output"], str) or not target["output"]):
            raise ExportError("config_invalid", "Target output must be a non-empty string")
    return data


def resolve_options(args, profile):
    values = dict(profile.get("resolve", {}))
    for key in ("project", "timeline", "preset", "output", "format", "codec"):
        if getattr(args, key, None) is not None:
            values[key] = getattr(args, key)
    for key in ("project", "timeline", "preset", "output"):
        if not values.get(key):
            raise ExportError("config_invalid", f"Resolve render requires {key}")
    if bool(values.get("format")) != bool(values.get("codec")):
        raise ExportError("config_invalid", "format and codec must be supplied together")
    values["output"] = str(path(values["output"]))
    return values
