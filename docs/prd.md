# Product Requirements Document: `video_export_skill`

- **Repository:** `https://github.com/grapeot/video_export_skill`
- **License:** MIT (Copyright `grapeot`)
- **Date:** 2026-10-24
- **Status:** Scaffold Phase (Specification Complete; Runtime Implementation Planned)

## 1. Problem Statement

Creators and engineering teams on macOS frequently rely on **DaVinci Resolve Studio** to edit and render master timelines and **Apple Compressor** to transcode those masters into one or more delivery formats (or use either application independently). When users delegate these workflows to AI coding agents (such as Codex, Claude Code, Cursor, or OpenCode), ad-hoc scripting regularly hits failure modes in both applications:

1. **DaVinci Resolve Studio state and IPC hazards:**
   - Resolve's official Python scripting API exposes project, timeline, and render preset listing (`GetProjectManager`, `GetProjectListInCurrentFolder`, `LoadProject`, `GetTimelineCount`, `GetTimelineByIndex`, `GetCurrentRenderFormatAndCodec`, `GetRenderPresetList`), as well as render queue control (`AddRenderJob`, `StartRendering`, `GetRenderJobStatus`), but provides **no** `GetRenderSettings()` or `GetCurrentRenderPreset()` method and **no** proven query for unsaved ("dirty") project state.
   - An agent that blindly calls `LoadProject()` against an active GUI session can silently switch away from the user's open project and risk unsaved edits.
   - An agent that mutates render settings cannot restore all prior settings afterward.
   - Sending `SIGTERM` to a headless `Resolve -nogui` process triggers the macOS Crash Reporter dialog unless quit cleanly through the scripting API.
2. **Apple Compressor CLI and queue hazards:**
   - `/Applications/Compressor.app/Contents/MacOS/Compressor` requires exact parameter shapes (`-locationpath` must be a full output file path, not a directory; `-monitor -format json -batchid <ID> -once` fails if `-format json` is placed at the end).
   - Submitting a batch returns a `batchID` as soon as the request is queued—not when encoding starts or succeeds—and multiple target outputs in a single batch can be merged under a single `jobID`.
   - `Waiting` status indicates the batch is queued behind busy transcode services rather than failed, whereas diagnostic text on stdout/stderr (such as `fileURL is NOT a directory`) can appear even on successful submissions.
   - `.compressorsetting` files are custom XML documents (not Apple plists), and preset filenames do not guarantee output dimensions (`bounds` set to `-100` means follow source dimensions).
3. **Premature hand-off between Resolve and Compressor:**
   - While Resolve is rendering, the destination `.mov` file already exists on disk and grows over time. Submitting that file to Compressor before Resolve finishes writing and closes the file produces truncated or corrupt transcodes.

## 2. Product Overview

`video_export_skill` provides a single Python CLI (`video-export`) and a modular agent skill suite (`skills/video-export/`) with two standalone capabilities and one optional connected pipeline:

1. **DaVinci Resolve Studio Export (`video-export resolve`):** Environment diagnostics, project and timeline inspection, and conservative timeline rendering.
2. **Apple Compressor Transcode (`video-export compressor`):** Environment diagnostics, `.compressorsetting` XML inspection, single- or multi-target batch submission, and batch status monitoring.
3. **Connected Pipeline (`video-export pipeline run`):** End-to-end orchestration that renders a master in Resolve (or reuses a provenance-verified master), verifies file completion and stream integrity via `ffprobe`, and runs one or more Compressor target transcodes with post-transcode verification.

## 3. Target Users and Configuration Model

### Target users
- Individual creators, technical instructors, and media engineers on macOS who use coding agents to inspect timelines, render master exports, or generate delivery transcodes without manually clicking through GUI dialogs on every run.

### Public/private separation
- **Public repository (`grapeot/video_export_skill`):** Contains only generic, reusable CLI code, offline tests, documentation, and agent skills. It includes no hardcoded personal paths, project names, or preset defaults.
- **External TOML profile (`/path/to/profile.toml`):** Holds a user's preferred Resolve preset name, master output location, output directory, and Compressor target list (`setting` path + filename `suffix`).
- **Local private Markdown overlay (optional):** Lives in the user's private workspace skill directory to capture personal workflow intent (such as which TOML profile applies to which series) while routing technical execution to `skills/video-export/SKILL.md`.
- **Single root skill discovery:** Coding agents index only `skills/video-export/SKILL.md`, which routes on demand to `resolve.md`, `compressor.md`, or `pipeline.md`.

## 4. Functional Requirements

### 4.1 Planned CLI command surface
- `video-export resolve doctor` — Check Resolve installation, scripting API/library paths, and whether a running Resolve instance is reachable.
- `video-export resolve projects` — List projects in the current Resolve folder alongside the currently open project name.
- `video-export resolve inspect [--project NAME]` — List timelines, frame rates/resolutions where available, current render format/codec, and render preset list without switching away from a different open non-`Untitled` GUI project.
- `video-export resolve render ... [--execute]` — Plan or execute a timeline render using a named Resolve preset and explicit output path.
- `video-export compressor doctor` — Check `/Applications/Compressor.app/Contents/MacOS/Compressor` and `ffprobe`/`ffmpeg` availability.
- `video-export compressor presets --setting /path/to/preset.compressorsetting` — Parse `.compressorsetting` XML and report codec, container, frame rate, and whether dimensions are fixed or source-following (`-100`).
- `video-export compressor transcode ... [--execute]` — Plan or execute a single- or multi-target Compressor transcode batch after validating source stability and `ffprobe` metadata.
- `video-export compressor status --batch-id ID` — Query `-monitor -format json -batchid ID -once`, parse status tolerantly, and distinguish queued (`Waiting`/`Processing`) from terminal (`Successful` vs `Failed`/`Cancelled`) states.
- `video-export pipeline run ... [--execute]` — Plan or execute the connected Resolve render -> verification -> Compressor transcode workflow.

### 4.2 Configuration and precedence
- Support an external TOML profile with sections:
  - `[resolve]`: `preset`, `output`
  - `[outputs]`: `directory`, `keep_master`
  - `[[compressor.targets]]`: `setting`, `suffix`
- Explicit CLI arguments always override TOML profile values.
- Reject unknown TOML keys with a structured validation error so typos in profile files never fail silently.

### 4.3 Dry-run planning, execution gate, and per-run manifest
- Every `render`, `transcode`, and `pipeline run` invocation defaults to dry-run mode: it validates arguments, checks for output path collisions, and prints the resolved plan as JSON without modifying projects, queueing jobs, or writing media files.
- Passing `--execute` is required to queue a Resolve render or Compressor batch.
- Every run writes a private local manifest (`manifest.json`) recording the resolved configuration, Resolve `job_id`, Compressor `batchID` and `jobID`s, output file paths, hashes/sizes, and verification status.

### 4.4 Verification and provenance gating
- Before submitting any file to Compressor under `--execute`, verify that no process holds the source file open for writing (`lsof`), that byte size remains constant across a bounded stability window, and that `ffprobe` confirms valid media streams and expected duration/codec/resolution/color tags when specified.
- In `pipeline run --execute`, Compressor submission proceeds **only** if Resolve reports positive job completion **and** the master file passes the stability and `ffprobe` checks.
- Reusing an existing master file in `pipeline run` (`--reuse-master`) is permitted **only** when a prior per-run `manifest.json` proves the file's provenance and its on-disk size/hash match the manifest.
- Support optional full stream decoding (`--verify-decode` via `ffmpeg -v error -i /path/to/file.mov -f null -`) when explicitly requested by the user or agent.

## 5. Non-Goals and Safety Boundaries

- **No silent project switching or saving in Resolve:** Never switch away from a different loaded non-`Untitled` project in an attached GUI session, and never call `SaveProject()`.
- **No unverified Resolve claims:** Do not claim to snapshot and restore all Resolve render settings, and do not automate or claim safety for Resolve `Quick Export`.
- **No destructive file operations:** Refuse all output path collisions; never overwrite existing files and never automatically delete source clips or master exports.
- **No disruptive queue/service actions:** Never delete other jobs in Resolve's render queue, never cancel existing Compressor batches automatically, and never invoke `Compressor -resetBackgroundProcessing`.
- **No publishing or background daemons:** Never upload files to external platforms, and do not introduce a resident background daemon or plugin framework.

## 6. Milestones and Success Criteria

1. **Milestone 1 — Repository Scaffold (Current):**
   - Author complete English documentation (`README.md`, `AGENTS.md`, `docs/prd.md`, `docs/rfc.md`, `docs/test.md`, `docs/working.md`) and agent skills (`skills/video-export/SKILL.md`, `resolve.md`, `compressor.md`, `pipeline.md`).
   - Initialize and publish `master` with branch protection requiring pull requests, 0 approving reviews, and `enforce_admins=true`.
2. **Milestone 2 — Runtime Implementation & Verification:**
   - Implement `src/video_export/` (`cli`, `config`, `resolve`, `compressor`, `pipeline`, `verification`, `state`) and the offline `pytest` suite on a feature branch.
   - Pass GitHub Actions CI on Ubuntu across Python 3.11, 3.12, and 3.13 (`uv venv` + `uv pip install -e '.[dev]'`, `ruff`, `pytest`).
   - Execute opt-in macOS live verification against generated scratch media and a disposable scratch Resolve project; record sanitized results in `docs/working.md` and merge via pull request.
3. **Milestone 3 — Skill Ecosystem Registration:**
   - Register `grapeot/video_export_skill` in public agent skill ecosystems and registries so coding agents can install the unified skill directly from GitHub.
