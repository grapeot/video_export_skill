# Product Requirements Document: `video_export_skill`

- **Repository:** `https://github.com/grapeot/video_export_skill`
- **License:** MIT (Copyright `grapeot`)
- **Date:** 2026-10-24
- **Status:** Implemented and Smoke-Verified on macOS

## 1. Problem Statement

Creators and engineering teams on macOS rely on **DaVinci Resolve Studio** to edit and render master timelines and **Apple Compressor** to transcode those masters into delivery formats (or use either application independently). Delegating these workflows to coding agents through ad-hoc shell scripts hits failure modes in both applications:

1. **DaVinci Resolve Studio state and IPC hazards:**
   - Resolve's Python scripting API exposes current-folder project listing, timeline inspection, and Deliver queue control (`AddRenderJob`, `StartRendering`, `GetRenderJobStatus`), but provides **no** `GetRenderSettings()` or `GetCurrentRenderPreset()` method and **no** reliable query for unsaved ("dirty") project state.
   - Calling `LoadProject()` against an active GUI session can switch away from a user's open named project.
   - Loading a preset or setting render target paths mutates active render settings in memory without a way to restore all prior settings, and Resolve's Live Save feature may persist those changes.
   - Native scripting libraries (`fusionscript.so`) can emit non-JSON noise to stdout, and sending `SIGTERM` to a headless `Resolve -nogui` process triggers the macOS Crash Reporter dialog unless quit cleanly via `resolve.Quit()`.
2. **Apple Compressor CLI and queue hazards:**
   - `/Applications/Compressor.app/Contents/MacOS/Compressor` requires exact parameter shapes (`-locationpath` must be a full output file path; `-monitor -format json -batchid <ID> -once` fails if `-format json` is placed after `-once`).
   - Submitting a batch returns a `batchID` as soon as the request is queued, and multiple target outputs in a single batch can share a single `jobID`.
   - `Waiting` status indicates the batch is queued rather than failed, and diagnostic text on stdout/stderr can appear around valid JSON payloads.
   - `.compressorsetting` files are custom XML documents (`<setting>`), where `bounds` width/height set to `-100` means follow source dimensions rather than fixed dimensions.
3. **Premature hand-off between Resolve and Compressor:**
   - While Resolve is rendering, the destination file already exists on disk and grows over time. Submitting that file to Compressor before Resolve closes it produces truncated or corrupt transcodes.

## 2. Product Overview

`video_export_skill` provides a stdlib-only Python CLI (`video-export`) and a modular agent skill suite (`skills/video-export/`) with two standalone capabilities and one optional connected pipeline:

1. **DaVinci Resolve Studio Export (`video-export resolve`):** Scripting diagnostics (`doctor`), current-folder project listing (`projects`), timeline and preset inspection (`inspect`), and Deliver queue timeline rendering (`render`).
2. **Apple Compressor Transcode (`video-export compressor`):** Binary and helper diagnostics (`doctor`), `.compressorsetting` XML inspection (`presets`), verified single- or multi-target batch submission (`transcode`), and batch status querying (`status`).
3. **Connected Pipeline (`video-export pipeline run`):** Sequential workflow that renders a master in Resolve (or reuses a manifest-verified master), checks writer closure and media metadata via `lsof` and `ffprobe`, and runs one or more Compressor target transcodes with post-transcode verification.

## 3. Target Users and Configuration Model

### Target users
- Creators, technical instructors, and media engineers on macOS who use coding agents to inspect timelines, render master exports, or generate delivery transcodes with predictable dry-run and verification gates.

### Public/private separation
- **Public repository (`grapeot/video_export_skill`):** Contains generic, reusable CLI code, offline tests, documentation, and agent skills with no personal paths or preset defaults.
- **External TOML profile (`--profile /path/to/profile.toml`):** Holds `[resolve]` (`project`, `timeline`, `preset`, `output`, optional `format`/`codec`), `[outputs]` (`directory`, `keep_master`), and `[[compressor.targets]]` (`setting`, `suffix`, `output`).
- **Local private Markdown overlay (optional):** Lives in the user's workspace skill directory to map personal projects to external TOML profiles while routing technical execution to `skills/video-export/SKILL.md`.
- **Single root skill discovery:** Coding agents index only `skills/video-export/SKILL.md`, loading `resolve.md`, `compressor.md`, or `pipeline.md` on demand.

## 4. Implemented Functional Scope

### 4.1 CLI command surface
- `video-export resolve doctor [--timeout SEC] [--headless]` — Connect to Resolve (or launch `-nogui` when `--headless` is set) and report product name, version, and current database.
- `video-export resolve projects [--timeout SEC] [--headless]` — List projects and folders in the current Resolve database folder (`GetProjectListInCurrentFolder`, `GetFolderListInCurrentFolder`, `GetCurrentFolder`, `GetCurrentDatabase`).
- `video-export resolve inspect [--project NAME] [--timeout SEC] [--headless]` — Inspect active or requested project timelines (name, fps, frame count, duration, width, height), Deliver render presets, current render format/codec, and render queue jobs. May load `--project NAME` only when no project or `"Untitled Project"` is open (or in an owned `--headless` session); never switches away from another named project.
- `video-export resolve render ... [--execute]` — Validate configuration and output path collisions in dry-run mode, or render a full timeline in single-clip Deliver mode and verify the output file under `--execute`.
- `video-export compressor doctor [--timeout SEC]` — Report Compressor binary path/existence and `ffprobe`, `ffmpeg`, and `lsof` locations.
- `video-export compressor presets [--setting PATH ...] [--timeout SEC]` — Parse explicit or auto-discovered `.compressorsetting` XML files and report name, extension, codec, frame rate, bounds, `resolution_mode` (`follow_source` vs `explicit_or_other`), and whether video encoding is enabled.
- `video-export compressor transcode --input PATH ... [--execute]` — Validate preset XML and target output collisions in dry-run mode, or verify source stability/metadata, submit a Compressor batch, poll until `Successful`, and verify all target outputs under `--execute`.
- `video-export compressor status --batch-id ID [--timeout SEC]` — Query `Compressor -monitor -format json -batchid ID -once` and extract the scoped batch status.
- `video-export pipeline run ... [--execute]` — Plan or execute the Resolve master render (or `--reuse-master MANIFEST` provenance check) followed by Compressor transcoding and target verification.

### 4.2 Dry-run vs execute and per-run manifests
- Dry-runs (`render`, `transcode`, `pipeline run` without `--execute`) perform local configuration validation, Compressor XML parsing, and output collision checks only. They do not connect to Resolve, do not verify whether a Resolve preset exists in the project, do not queue jobs, and do not write state manifests.
- Passing `--execute` creates a private run directory (`~/.local/state/video-export/<run-id>/manifest.json` or `--state-dir`, permissions `0o700`/`0o600`) and records the plan, checkpoints, job/batch IDs, media properties, and terminal status.

### 4.3 Verification and master reuse provenance
- Execution requires `lsof` (no open writer descriptors `aw`/`au`), constant non-zero file size and `mtime_ns` across `--stability-window` seconds, and `ffprobe` validation (positive finite duration, video stream presence, duration matching timeline or source within `0.1`s, plus optional `--expect-*` checks and `--verify-decode`).
- `--reuse-master MANIFEST` requires an explicit path to a prior `manifest.json` and verifies that the Resolve configuration identity (`project`, `timeline`, `preset`, `output`, `format`, `codec`) and on-disk file metadata (`path`, `size`, `mtime_ns`) match the verified master record. This metadata check avoids hashing multi-gigabyte files on retry; it does not detect unsaved/saved edits inside the Resolve project, so users must render a fresh master after editing a timeline.

## 5. Non-Goals and Known Limitations

- **No render settings restoration or dirty-state detection in Resolve:** Active Deliver settings are mutated in memory during `render`, and Resolve's Live Save may persist them.
- **No recursive Resolve folder traversal:** `resolve projects` inspects the current database folder only.
- **No Quick Export:** Only standard Deliver queue presets are used.
- **No automatic HDR/Dolby Vision semantic grading check:** `--expect-color-*` checks container/stream tags reported by `ffprobe`, which do not prove subjective display appearance. Large exports, HDR/Dolby Vision workflows, and 8K timelines have not been live-validated.
- **No job cancellation on timeout and no background daemon:** Timeouts leave active Resolve renders or Compressor batches running and retain checkpoint/manifest identifiers for manual inspection.

## 6. Milestones

1. **Milestone 1 — Repository Scaffold (Completed 2026-10-24):** Defined requirements, architecture, CLI/TOML specifications, and skill routing.
2. **Milestone 2 — Runtime Implementation & Verification (Completed 2026-10-24):** Implemented `src/video_export/` and offline `pytest` suite (52 tests passing), and verified live macOS smoke execution across headless Resolve Studio (`ProRes 422 HQ` master + clean `Quit()`) and Apple Compressor (`HEVC .mov` delivery + full `ffmpeg` decode).
3. **Milestone 3 — Skill Ecosystem Registration:** Register `grapeot/video_export_skill` in public agent skill indices and registries.
