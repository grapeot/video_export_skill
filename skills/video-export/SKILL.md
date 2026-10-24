---
name: video-export
description: Export timelines from DaVinci Resolve Studio, transcode media with Apple Compressor, or run a verified Resolve-to-Compressor pipeline on macOS using the planned video-export CLI.
---

# Video Export (`video-export`)

> **Scaffold Status (2026-10-24):** This repository is currently in the scaffold phase. The CLI contract (`video-export`), TOML profile schema, and backend safety rules below specify the planned runtime implementation. Before invoking `video-export`, check whether the package is installed in `.venv`; if the repository is still at the scaffold commit, treat these files as the authoritative design specification.

Use this root skill whenever a task involves exporting timelines from **DaVinci Resolve Studio**, inspecting or running **Apple Compressor** `.compressorsetting` transcodes, or running a connected **Resolve -> verification -> Compressor** delivery pipeline on macOS.

## Focused Skill Routing (Load on Demand)

This file is the **single root router skill** exposed to your workspace skill index. Do not index the focused files globally; read the appropriate focused file on demand based on the task:

| Task / Workflow | Focused Skill to Read | CLI Subcommands |
|---|---|---|
| Inspecting Resolve projects/timelines/presets or rendering a master export from DaVinci Resolve Studio | [`./resolve.md`](resolve.md) | `video-export resolve doctor \| projects \| inspect \| render` |
| Inspecting `.compressorsetting` XML presets, submitting transcode batches, or monitoring batch status in Apple Compressor | [`./compressor.md`](compressor.md) | `video-export compressor doctor \| presets \| transcode \| status` |
| Rendering a master in Resolve, verifying completion with `lsof` + `ffprobe`, and transcoding one or more targets in Compressor | [`./pipeline.md`](pipeline.md) | `video-export pipeline run` |

## Done Means (Acceptance Criteria)

A `video-export` task is complete only when all applicable criteria below are met:

1. **Dry-run plan reviewed first:** For `resolve render`, `compressor transcode`, or `pipeline run`, a dry-run invocation (without `--execute`) was run first and returned `ok: true` with no output path collisions and the expected resolved parameters.
2. **Explicit execution and positive backend status:** When run with `--execute`, Resolve reported positive completion for the run's own `job_id` (when Resolve was used) and/or Compressor `-monitor` reached terminal status `Successful` (not merely queued with a `batchID` or still in `Waiting`/`Processing`).
3. **Media verification passed:** Every produced master and target output file has no open writer (`lsof`), stable non-zero byte size across a bounded stability window, and valid `ffprobe` stream metadata matching expected duration, codec, resolution, and color tags when specified (plus clean `ffmpeg -v error -i ... -f null -` exit if `--verify-decode` was requested).
4. **Manifest recorded:** The private per-run `manifest.json` path returned in the stdout JSON envelope records all resolved settings, job/batch IDs, output paths, and verification results.

## Configuration Model: Public Skill vs Local Intent & TOML Profile

- **No private defaults in public files:** Never hardcode personal directory paths, project names, or preset paths into this repository.
- **Local private overlay (optional):** If the user's workspace maintains a private skill overlay (for example in `rules/skills/`), read it first to learn which external TOML profile or naming convention applies to the user's current project.
- **External TOML profile (`--profile /path/to/profile.toml`):** Holds concrete paths and presets:
  - `[resolve]`: `preset`, `output`
  - `[outputs]`: `directory`, `keep_master`
  - `[[compressor.targets]]`: `setting`, `suffix`
- **CLI precedence:** Explicit CLI flags (`--project`, `--timeline`, `--preset`, `--output`, `--setting`, `--directory`) always override values from `--profile`. Unknown keys in TOML are rejected.

## Hard Safety Boundaries

- **Dry-run default:** Never pass `--execute` before running and inspecting the dry-run plan.
- **One JSON object on stdout:** Parse the single JSON object printed to stdout by each `video-export` subcommand. Never auto-publish local stdout metadata or private log paths externally.
- **No collisions or deletions:** Refuse any run where an output file already exists. Never overwrite existing media files, and never automatically delete source clips or rendered master files (`keep_master` must remain `true`).
- **Conservative Resolve handling:** Attach to a running Resolve instance by default (`--headless` is explicit opt-in). Never silently switch away from a different open non-`Untitled` project in GUI mode, never call `SaveProject()`, never claim to restore all prior render settings, never use `Quick Export`, start only the run's own `job_id`, and never delete other render queue jobs. Never `SIGTERM` a GUI Resolve on timeout; quit an owned headless Resolve via the scripting API (`Quit()`).
- **Conservative Compressor handling:** Never submit a source file that is still being written. Never call `Compressor -resetBackgroundProcessing` or cancel existing jobs without explicit user authorization.
- **No uploading or publishing:** `video-export` only produces and verifies local media files.
