# Working Notes

## Changelog

### 2026-10-24

- Implemented the `src/video_export/` runtime package (`cli.py`, `common.py`, `config.py`, `resolve.py`, `resolve_worker.py`, `compressor.py`, `pipeline.py`, `verification.py`, `state.py`) using stdlib-only Python `>=3.11`.
- Added the offline `pytest` suite (`tests/test_scaffold.py`, `tests/test_config_cli.py`, `tests/test_resolve.py`, `tests/test_compressor.py`, `tests/test_pipeline_verification.py`) with 52 passing offline tests and clean `ruff` checks.
- Completed live macOS smoke verification against DaVinci Resolve Studio and Apple Compressor using a generated 2-second / 48-frame / 24 fps audio+video test pattern and a disposable scratch Resolve project/timeline: verified headless attach (`Resolve -nogui`), ProRes 422 HQ master export, Compressor HEVC `.mov` transcode, `duration=2.0`s and full `ffmpeg -v error -xerror` decode on both outputs, manifest-based `--reuse-master`, and clean exit `0` from `resolve.Quit()`.
- Updated documentation and agent skills to match exact implemented CLI flags, TOML profile keys, dry-run boundaries, and metadata provenance behavior.
- Independent code/privacy review identified five issues; fixed source-duration expectation handling, per-target preset verification, short Resolve timeout handling, structured subprocess timeout errors, and remaining-budget Compressor polling. Added regression tests for each.
- Verified manifest-based master reuse with two Compressor targets, full decoding of both deliveries, and the CLI-owned headless diagnostic lifecycle.
- Added and ran `scripts/live_smoke.py`: a fresh 1280x720/24 fps scratch timeline produced matching 2-second ProRes and HEVC outputs with full decode verification. Closed the review follow-up by refusing late job submission after headless startup exhausts its shared deadline.
- Created initial repository scaffold documentation (`README.md`, `AGENTS.md`, `docs/prd.md`, `docs/rfc.md`, `docs/test.md`, `docs/working.md`) and agent skill suite (`skills/video-export/SKILL.md`, `resolve.md`, `compressor.md`, `pipeline.md`).

## Lessons Learned

- DaVinci Resolve Studio's native `fusionscript.so` library can emit non-JSON text to stdout during attach. Isolating Resolve scripting inside `python -m video_export.resolve_worker <result_file>` keeps the parent CLI's single-JSON stdout contract clean.
- Resolve Studio coerces tiny requested timeline resolutions up to its minimum supported dimensions (`256x256` in live smoke testing, where the scratch timeline, ProRes 422 HQ master, and Compressor HEVC target all measured `256x256`). Never assume synthetic input clip dimensions equal the timeline or output dimensions; always read actual timeline and `ffprobe` stream dimensions.
- Calling `resolve.Quit()` over the scripting API cleanly exits an owned headless `Resolve -nogui` process with exit code `0` (whereas `SIGTERM` triggers the macOS Crash Reporter). If a render times out while `IsRenderingInProgress()` is true, do not call `Quit()` or kill the process; leave the render running and retain `resolve-job.json` and `manifest.json` for manual inspection.
- Resolve's `Project` API has no `GetRenderSettings()` or `GetCurrentRenderPreset()` method and no dirty-state query. `resolve render --execute` mutates active Deliver settings in memory (`SetCurrentTimeline`, `LoadRenderPreset`, `SetCurrentRenderMode(1)`, optional `SetCurrentRenderFormatAndCodec`, `SetRenderSettings`) and never calls `SaveProject()`, but Resolve's own Live Save feature may persist those changes if enabled.
- Dry-runs validate configuration, Compressor `.compressorsetting` XML, and output path collisions locally without connecting to Resolve or writing state manifests. Existence of a Resolve project, timeline, or Deliver preset is verified only when running `resolve inspect` or `--execute`.
- Read-only `resolve inspect --project NAME` (and `render --execute`) may call `LoadProject(NAME)` only when no project or `"Untitled Project"` is loaded (or in an owned `--headless` instance), and only searches the current Resolve database folder (`GetProjectListInCurrentFolder`).
- `--reuse-master MANIFEST` takes an explicit prior `manifest.json` path and compares the SHA-256 identity of the Resolve configuration plus the master file's on-disk metadata fingerprint (`path`, `size`, `mtime_ns`). This avoids hashing multi-gigabyte masters on retry, but it does not hash media contents or detect edits inside the Resolve project; users must run a fresh render after editing a timeline.
- Apple Compressor CLI (`/Applications/Compressor.app/Contents/MacOS/Compressor`) requires `-locationpath` to be a complete file path, requires `-format json` immediately after `-monitor` (`-monitor -format json -batchid ID -once`), and may emit diagnostic text around JSON output.
- In Compressor `-monitor` payloads, child job entries or other batches may report `status: "Successful"` while the target batch is still `Waiting` or `Processing`. `batch_status()` must match only the requested `batchID` and verify every target output file via `lsof`, byte-size stability, and `ffprobe` after the batch reaches `Successful`.
