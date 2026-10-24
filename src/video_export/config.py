"""External profile validation; no personal preset defaults."""

import tomllib

from .common import ExportError, path
from .rates import rate

RESOLVE_KEYS = ("project", "timeline", "preset", "output", "format", "codec", "resolution",
                "frame_rate", "audio_codec", "audio_bit_depth", "audio_sample_rate")


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
    check_keys(data.get("resolve", {}), RESOLVE_KEYS, "resolve")
    check_keys(data.get("outputs", {}), ("directory", "keep_master"), "outputs")
    check_keys(data.get("compressor", {}), ("targets", "max_frame_rate"), "compressor")
    if "max_frame_rate" in data.get("compressor", {}):
        rate(data["compressor"]["max_frame_rate"])
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
    for key in RESOLVE_KEYS:
        if getattr(args, key, None) is not None:
            values[key] = getattr(args, key)
    for key in ("project", "timeline", "preset", "output"):
        if not values.get(key):
            raise ExportError("config_invalid", f"Resolve render requires {key}")
    if bool(values.get("format")) != bool(values.get("codec")):
        raise ExportError("config_invalid", "format and codec must be supplied together")
    if "frame_rate" in values:
        values["frame_rate"] = round(float(rate(values["frame_rate"])), 3)
    if "resolution" in values:
        try:
            width, height = map(int, values["resolution"].lower().split("x"))
            if min(width, height) <= 0:
                raise ValueError()
        except ValueError as exc:
            raise ExportError("config_invalid", "Resolution must be WIDTHxHEIGHT") from exc
    for key in ("audio_bit_depth", "audio_sample_rate"):
        if key in values:
            try:
                number = int(values[key])
                if number <= 0:
                    raise ValueError()
            except ValueError as exc:
                raise ExportError("config_invalid", f"{key} must be a positive integer") from exc
            values[key] = number
    values["output"] = str(path(values["output"]))
    return values
