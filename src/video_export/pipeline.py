"""Composition of independent backends with a verified handoff."""

from . import compressor, resolve
from .common import outputs_available
from .state import fingerprint, identity, reuse_master
from .verification import verify


def render_master(config, state, timeout=3600, headless=False, window=2, decode=False, expected=None):
    state.save(resolve_config=config)
    result = resolve.call("render", config, timeout=timeout, headless=headless,
                          checkpoint=state.folder / "resolve-job.json")
    checks = {"duration": result["timeline"]["duration"]}
    if config.get("resolution"):
        checks["width"], checks["height"] = map(int, config["resolution"].lower().split("x"))
    if config.get("frame_rate"):
        checks["frame_rate"] = config["frame_rate"]
    if expected and expected.get("duration") is not None:
        if abs(expected["duration"] - checks["duration"]) > 0.1:
            from .common import ExportError
            raise ExportError("expectation_conflict", "Expected duration conflicts with timeline")
    checks.update({k: v for k, v in (expected or {}).items() if k != "duration"})
    media = verify(config["output"], checks, decode=decode, window=window, timeout=timeout)
    master = {"identity": identity(config), "fingerprint": fingerprint(config["output"]),
              "verified": True, "media": media, "resolve": result}
    state.save(master=master)
    return master


def execute(config, targets, state, reuse=None, timeout=3600, headless=False, window=2,
            decode=False, expected=None, poll=5):
    # Preflight all destinations before doing expensive work.
    outputs_available([t["output"] for t in targets], [config["output"]])
    if reuse:
        master = reuse_master(reuse, config)
        verify(config["output"], {"duration": master["media"]["duration"]}, window=window)
        state.save(master=master, reused_from=str(reuse))
    else:
        outputs_available([config["output"]])
        master = render_master(config, state, timeout, headless, window, decode)
    result = compressor.transcode(config["output"], targets, state, timeout, poll, window,
                                  decode, expected)
    return {"master": master, "compressor": result}
