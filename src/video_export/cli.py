"""Single-JSON CLI for local video export operations."""

import argparse
import json
import math
import os
import shutil
import sys

from . import compressor, pipeline, resolve
from .common import ExportError, outputs_available, path
from .config import load_profile, resolve_options
from .state import RunState, reuse_master


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ExportError("invalid_arguments", message)


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def build_parser():
    parser = Parser(prog="video-export")
    groups = parser.add_subparsers(dest="backend", required=True)
    for backend, actions in (("resolve", ("doctor", "projects", "inspect", "render")),
                             ("compressor", ("doctor", "presets", "transcode", "status")),
                             ("pipeline", ("run",))):
        commands = groups.add_parser(backend).add_subparsers(dest="action", required=True)
        for action in actions:
            cmd = commands.add_parser(action)
            cmd.add_argument("--timeout", type=positive, default=3600)
            if backend == "resolve" or backend == "pipeline":
                cmd.add_argument("--headless", action="store_true")
            if action == "inspect":
                cmd.add_argument("--project")
            if action == "presets":
                cmd.add_argument("--setting", action="append")
            if action == "status":
                cmd.add_argument("--batch-id", required=True)
            if action not in ("render", "transcode", "run"):
                continue
            cmd.add_argument("--profile")
            cmd.add_argument("--execute", action="store_true")
            cmd.add_argument("--output")
            cmd.add_argument("--state-dir")
            cmd.add_argument("--directory")
            cmd.add_argument("--verify-decode", action="store_true")
            cmd.add_argument("--stability-window", type=positive, default=2)
            cmd.add_argument("--poll", type=positive, default=5)
            cmd.add_argument("--expect-duration", type=positive)
            cmd.add_argument("--expect-frame-rate", type=positive)
            cmd.add_argument("--expect-codec")
            cmd.add_argument("--expect-resolution")
            for tag in ("color-primaries", "color-transfer", "color-space"):
                cmd.add_argument("--expect-" + tag)
            if backend in ("resolve", "pipeline"):
                for flag in ("project", "timeline", "preset", "format", "codec", "resolution",
                             "frame-rate", "audio-codec", "audio-bit-depth", "audio-sample-rate"):
                    cmd.add_argument("--" + flag)
            if backend == "compressor":
                cmd.add_argument("--input", required=True)
                cmd.add_argument("--setting", action="append")
            if backend in ("compressor", "pipeline"):
                cmd.add_argument("--max-frame-rate", type=positive)
            if backend == "pipeline":
                cmd.add_argument("--setting", action="append")
                cmd.add_argument("--reuse-master", metavar="MANIFEST")
    return parser


def expectations(args):
    result = {"duration": args.expect_duration, "frame_rate": args.expect_frame_rate,
              "codec_name": args.expect_codec,
              "color_primaries": args.expect_color_primaries,
              "color_transfer": args.expect_color_transfer, "color_space": args.expect_color_space}
    if args.expect_resolution:
        try:
            width, height = map(int, args.expect_resolution.lower().split("x"))
            if width <= 0 or height <= 0:
                raise ValueError()
        except ValueError as exc:
            raise ExportError("invalid_arguments", "Resolution must be WIDTHxHEIGHT") from exc
        result.update(width=width, height=height)
    return {key: value for key, value in result.items() if value is not None}


def execute(args):
    if args.action == "doctor" and args.backend == "compressor":
        return {"binary": compressor.binary(), "installed": path(compressor.binary()).is_file(),
                "ffprobe": shutil.which("ffprobe"), "ffmpeg": shutil.which("ffmpeg"),
                "lsof": shutil.which("lsof")}
    if args.backend == "resolve" and args.action in ("doctor", "projects", "inspect"):
        return resolve.call(args.action, {"project": getattr(args, "project", None)},
                            args.timeout, args.headless)
    if args.action == "presets":
        return {"presets": [compressor.preset(file) for file in
                            (args.setting or compressor.discover_presets())]}
    if args.action == "status":
        payload = compressor.status(args.batch_id, timeout=args.timeout)
        return {"batch_id": args.batch_id, "status": compressor.batch_status(payload, args.batch_id),
                "monitor": payload}
    profile = load_profile(args.profile)
    checks = expectations(args)
    config, targets = None, None
    if args.backend in ("resolve", "pipeline"):
        config = resolve_options(args, profile)
        if getattr(args, "reuse_master", None):
            reuse_master(args.reuse_master, config)
        else:
            outputs_available([config["output"]])
    if args.backend in ("compressor", "pipeline"):
        source = config["output"] if config else str(path(args.input))
        if args.backend == "compressor" and not path(source).is_file():
            raise ExportError("source_invalid", "Input file does not exist")
        targets = compressor.plan_targets(source, profile, args.setting,
                                            args.output if args.backend == "compressor" else None,
                                            args.directory, args.max_frame_rate)
    plan = {"resolve": config, "targets": targets,
            "input": str(path(args.input)) if args.backend == "compressor" else None,
            "expected": checks,
            "backend_validation": "performed on execute; dry-run does not connect to Resolve"}
    if not args.execute:
        return {"dry_run": True, "plan": plan}
    for dependency in ("ffprobe", "lsof") + (("ffmpeg",) if args.verify_decode else ()):
        if not shutil.which(dependency):
            raise ExportError("dependency_missing", f"{dependency} is required")
    state = RunState(args.state_dir)
    state.save(plan=plan, command=f"{args.backend}.{args.action}")
    try:
        if args.backend == "resolve":
            result = pipeline.render_master(config, state, args.timeout, args.headless,
                                             args.stability_window, args.verify_decode, checks)
        elif args.backend == "compressor":
            result = compressor.transcode(args.input, targets, state, args.timeout, args.poll,
                                            args.stability_window, args.verify_decode, checks)
        else:
            result = pipeline.execute(config, targets, state, args.reuse_master, args.timeout,
                                       args.headless, args.stability_window, args.verify_decode,
                                       checks, args.poll)
        state.save(status="complete", result=result)
        return {"result": result, "manifest": str(state.filename)}
    except Exception as exc:
        state.save(status="failed", error=str(exc), error_code=getattr(exc, "code", "unexpected"))
        if isinstance(exc, ExportError):
            exc.details["manifest"] = str(state.filename)
        raise


def main(argv=None):
    # Run records and child-created files are private by default.
    os.umask(0o077)
    try:
        args = build_parser().parse_args(argv)
        data = execute(args)
        payload, code = {"ok": True, "data": data}, 0
    except ExportError as exc:
        payload, code = {"ok": False, "error": exc.code, "message": str(exc),
                         "details": exc.details}, 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        payload, code = {"ok": False, "error": "operation_failed", "message": str(exc),
                         "type": type(exc).__name__}, 1
    print(json.dumps(payload, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
