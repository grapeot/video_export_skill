# Working Notes

## Changelog

### 2026-10-24

- Created initial repository scaffold documentation (`README.md`, `AGENTS.md`, `docs/prd.md`, `docs/rfc.md`, `docs/test.md`, `docs/working.md`) for `grapeot/video_export_skill`.
- Defined the root agent router skill (`skills/video-export/SKILL.md`) and three focused on-demand skills (`skills/video-export/resolve.md`, `skills/video-export/compressor.md`, `skills/video-export/pipeline.md`).
- Specified the `video-export` CLI subcommand contract (`resolve doctor|projects|inspect|render`, `compressor doctor|presets|transcode|status`, `pipeline run`), TOML profile schema (`[resolve]`, `[outputs]`, `[[compressor.targets]]`), dry-run planning defaults, `--execute` gate, and per-run manifest provenance rules.
- Recorded empirically verified DaVinci Resolve Studio 21 scripting behavior and Apple Compressor CLI constraints to guide the upcoming implementation branch.

## Lessons Learned

- DaVinci Resolve Studio 21 external Python scripting works when `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH` point to Resolve's scripting directory and `fusionscript.so`, and headless launch works via `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve -nogui`.
- Resolve's Python API exposes `GetProjectManager`, `GetProjectListInCurrentFolder`, `LoadProject`, `GetTimelineCount`, `GetTimelineByIndex` (1-based), `GetCurrentRenderFormatAndCodec`, and `GetRenderPresetList`, but provides **no** `GetRenderSettings` or `GetCurrentRenderPreset` method and **no** proven query for unsaved ("dirty") project state. Never claim that all prior render settings can be snapshotted and restored, and never silently switch away from a different loaded non-`Untitled` project in GUI mode.
- Resolve `Quick Export` presets appear in preset listings, but their mutability, blocking behavior, and metadata semantics under scripting are unverified. Use standard Deliver presets (`AddRenderJob` / `StartRendering` / `GetRenderJobStatus`) and start only the job ID created by the current run.
- Sending `SIGTERM` to an owned headless `Resolve -nogui` process triggers the macOS Crash Reporter dialog. Always quit an owned headless Resolve instance via the scripting API (`Quit()`) and keep IPC inside a bounded subprocess that never auto-kills a user's GUI Resolve on timeout.
- Apple Compressor CLI (`/Applications/Compressor.app/Contents/MacOS/Compressor`) requires `-locationpath` to be a complete output file path including filename; passing a directory fails with `Destination is a directory`.
- For Compressor status checks, `-format json` must immediately follow `-monitor` (`-monitor -format json -batchid ID -once`); placing `-format json` at the end fails with `Invalid parameter: -format`.
- Compressor batch submission and monitor output may include diagnostic lines (such as `fileURL is NOT a directory`) around the JSON payload, so JSON extraction must be tolerant of surrounding diagnostic text.
- A returned `batchID` means only that the batch was queued. `Waiting` (or `Processing` at `0%` while waiting for an available service) is not a failure; completion must distinguish `Waiting`/`Processing` from terminal `Successful` vs `Failed`/`Cancelled`, and multiple targets in one batch can share a single `jobID`.
- `.compressorsetting` files are custom `<setting>` XML documents (not plists; `plutil` fails on them), and preset filenames do not guarantee output resolution because `bounds` width/height `-100` in `<video-encode>` means follow source dimensions.
- Never submit a source file to Compressor while it is still being written; always enforce bounded file-size stability (`lsof` + `stat`) and `ffprobe` validation before submission, and gate `pipeline run` on both positive Resolve job completion and a verified master file.
