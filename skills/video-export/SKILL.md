---
name: video-export
description: Export timelines from DaVinci Resolve Studio, transcode media with Apple Compressor, or run a verified Resolve-to-Compressor pipeline on macOS using the video-export CLI.
---

# Video Export (`video-export`)

Use this root skill whenever a task involves exporting timelines from **DaVinci Resolve Studio**, inspecting or running **Apple Compressor** `.compressorsetting` transcodes, or running a connected **Resolve -> verification -> Compressor** delivery pipeline on macOS.

## Focused Skill Routing (Load on Demand)

This file is the **single root router skill** exposed to your workspace skill index. Do not index the focused files globally; read the appropriate focused file on demand based on the task:

| Task / Workflow | Focused Skill to Read | CLI Subcommands |
|---|---|---|
| Inspecting Resolve projects/timelines/presets or rendering a master export from DaVinci Resolve Studio | [`./resolve.md`](resolve.md) | `video-export resolve doctor \| projects \| inspect \| render` |
| Inspecting `.compressorsetting` XML presets, submitting transcode batches, or querying batch status in Apple Compressor | [`./compressor.md`](compressor.md) | `video-export compressor doctor \| presets \| transcode \| status` |
| Rendering a master in Resolve (or reusing a manifest-verified master), verifying completion with `lsof` + `ffprobe`, and transcoding targets in Compressor | [`./pipeline.md`](pipeline.md) | `video-export pipeline run` |

## Done Means (Acceptance Criteria)

A `video-export` task is complete only when all applicable criteria below are met:

1. **Dry-run plan reviewed first:** For `resolve render`, `compressor transcode`, or `pipeline run`, a dry-run invocation (without `--execute`) returned `ok: true` with `dry_run: true`, valid configuration/preset XML, and no output path collisions. Note that dry-run does not connect to Resolve or verify that the Resolve project/timeline/preset exists; run `resolve inspect` first if Resolve names are uncertain.
2. **Explicit execution and positive backend status:** Under `--execute`, Resolve reported `Complete` for the run's own `job_id` (and confirmed the actual queue `OutputFilename`) and/or Compressor `-monitor` reached terminal status `Successful` for the run's `batch_id`.
3. **Media verification passed:** Every produced master and target output file passed `lsof` open-writer checks, constant non-zero size/mtime across `--stability-window`, and `ffprobe` validation (positive duration matching the timeline/source within `0.1`s, plus any `--expect-*` stream checks and optional `--verify-decode`).
4. **Manifest recorded:** The `--execute` response returned the private per-run `manifest.json` path (`~/.local/state/video-export/<run-id>/manifest.json` or `--state-dir`) recording the plan, job/batch IDs, media metadata, and completion status.

## Configuration Model: Local Overlay & External TOML Profile

- **Local private overlay (optional):** If the user's workspace maintains a private skill overlay (for example in `rules/skills/`), read it first to learn which external TOML profile or naming convention applies to the current task.
- **External TOML profile (`--profile /path/to/profile.toml`):** Store paths and presets outside this repository (use absolute paths, as relative paths resolve against the invocation working directory):
  - `[resolve]`: `project`, `timeline`, `preset`, `output`, `format`, `codec` (`format` and `codec` are optional explicit overrides and must be supplied together)
  - `[outputs]`: `directory`, `keep_master` (`keep_master` must be `true`)
  - `[[compressor.targets]]`: `setting`, `suffix`, `output` (each target requires `setting` and at least `suffix` or `output`)
- **CLI precedence:** Explicit CLI flags (`--project`, `--timeline`, `--preset`, `--output`, `--format`, `--codec`, `--setting`, `--directory`) override values from `--profile`. In `pipeline run`, `--output` sets the master output path; in single-target `compressor transcode`, `--output` sets the target output path. Repeating `--setting` on the CLI overrides `[[compressor.targets]]` with suffixes `-1`, `-2`, etc.

## Hard Safety Boundaries

- **Dry-run default:** Never pass `--execute` before running and inspecting the dry-run plan.
- **One JSON object on stdout:** Parse the single JSON object printed to stdout (`--help` excepted). Never auto-publish local stdout metadata, media files, or private manifests/logs.
- **No collisions or deletions:** Refuse any run where an output file already exists (`output_collision`). Never overwrite existing files, and never delete source clips or rendered masters.
- **Conservative Resolve handling:** Attach to a running Resolve instance by default (`--headless` is opt-in). Never silently switch away from another open named project in GUI mode (`foreign_project_loaded`). Never call `SaveProject()`, though loading presets/settings mutates active Deliver settings in memory and Resolve Live Save may persist them. Start only the run's own `job_id`. On timeout, leave active renders running and use the saved checkpoint/manifest for recovery; quit an owned `--headless` Resolve via `resolve.Quit()` only when no render is in progress.
- **Conservative Compressor handling:** Never submit a file with an open writer. Never call `Compressor -resetBackgroundProcessing` or cancel existing batches automatically.
- **Measured tags vs visual grading:** `--expect-color-*` checks `ffprobe` stream tags only and does not prove subjective HDR or Dolby Vision appearance.
