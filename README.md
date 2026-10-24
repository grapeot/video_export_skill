# video_export_skill

An agent skill suite (`skills/video-export/SKILL.md`) and Python command-line tool (`video-export`) for macOS video export and transcoding workflows. It provides two independently usable capabilities—rendering timelines from **DaVinci Resolve Studio** and transcoding media with **Apple Compressor**—plus an optional gated pipeline that connects them.

## Who it is for

Video creators, educators, and developers on macOS who edit in DaVinci Resolve Studio, transcode delivery variants in Apple Compressor, or use either application standalone with a coding agent (Codex, Claude Code, Cursor, OpenCode, and similar).

Driving Resolve and Compressor through ad-hoc shell commands is fragile: Resolve's external scripting API mutates active render settings in memory without full readback methods, while Compressor's command-line interface requires strict flag ordering, returns a batch identifier as soon as a job is queued rather than finished, and can produce truncated outputs if handed a source file that is still being written. `video-export` wraps both tools behind a dry-run-first contract with machine-readable JSON output and media verification gates.

## Capabilities and boundaries

- **Two standalone backends, one optional pipeline:**
  - `video-export resolve ...` checks scripting availability, lists current-folder projects, inspects timelines and Deliver presets, and renders master outputs through DaVinci Resolve Studio's official Python scripting API (with optional post-preset render overrides for resolution, frame rate, and audio codec/bit-depth/sample-rate).
  - `video-export compressor ...` checks tool availability, parses `.compressorsetting` XML presets (including `R`-prefixed rational frame rates and `automatic_geometry` metadata), submits single- or multi-target transcode batches through the Apple Compressor CLI executable (with optional `--max-frame-rate` cap-preserving cadence derivation), and queries batch status.
  - `video-export pipeline run ...` renders a master file in Resolve (or reuses a manifest-verified master), checks writer closure and stream metadata via `lsof` and `ffprobe`, and submits the verified master to Compressor for one or more delivery targets.
- **Dry-run by default:** `resolve render`, `compressor transcode`, and `pipeline run` validate configuration, Compressor preset XML, and output path collisions without connecting to Resolve, probing media sources, creating derived presets, queueing jobs, or writing run manifests unless `--execute` is passed.
- **One JSON object per command:** Every subcommand prints a single JSON object to stdout (`--help` excepted). Every `--execute` run records its resolved plan, backend job/batch IDs, media metadata, and status in a private per-run manifest (`~/.local/state/video-export/<run-id>/manifest.json` or `--state-dir`).
- **Conservative toward running applications and files:**
  - Refuses output path collisions and never overwrites or auto-deletes source clips or rendered masters.
  - Attaches to a running Resolve instance by default (`--headless` launch via `-nogui` is opt-in), never switches away from a different open named project in GUI mode, starts only the render job ID it created, and never deletes other render queue jobs.
  - Never calls `SaveProject()`, though users should note that Resolve changes active render settings in memory and Resolve's own Live Save (if enabled) can persist those changes.
  - Never submits a file with an open writer to Compressor, and never resets Compressor services or cancels existing jobs on timeout.

Full architecture and backend contracts are documented in [`docs/rfc.md`](docs/rfc.md).

## Installation

Requires macOS, Python 3.11 or newer, and [uv](https://github.com/astral-sh/uv). Runtime code uses only the Python standard library. Executing renders or transcodes requires `ffprobe` and `lsof` on `PATH` (plus `ffmpeg` when `--verify-decode` is used), DaVinci Resolve Studio for `resolve` commands, and Apple Compressor for `compressor` commands.

Install as a standalone CLI tool with `uv`:

```bash
uv tool install git+https://github.com/grapeot/video_export_skill
```

Or install from a local clone inside a virtual environment:

```bash
git clone https://github.com/grapeot/video_export_skill
cd video_export_skill
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Installing the skill into your coding agent

Give your coding agent this repository's GitHub URL (`https://github.com/grapeot/video_export_skill`) and ask it to install the skill.

The agent should:
1. Read your workspace's `AGENTS.md` or `CLAUDE.md` and follow any workspace routing table (such as `WORKSPACE.md` or `rules/WORKSPACE.md`).
2. Register **only the root router skill**—`skills/video-export/SKILL.md`—in your workspace's skill index (`rules/skills/INDEX.md` or `skills/INDEX.md` if one exists, otherwise a short pointer in `AGENTS.md` or `CLAUDE.md`).
3. Leave the focused skill files (`skills/video-export/resolve.md`, `skills/video-export/compressor.md`, and `skills/video-export/pipeline.md`) unindexed at the global workspace level so the agent loads them on demand through `SKILL.md`.

## Configuration: TOML profile and local overlay

Store directory paths, Resolve defaults, and Compressor targets in an external TOML file passed via `--profile /path/to/profile.toml` (use absolute paths, as relative paths resolve against the current working directory):

```toml
[resolve]
project = "Demo Project"
timeline = "Main Edit"
preset = "ProRes_Master"
output = "/path/to/exports/episode_master.mov"
# Optional explicit format/codec override (must be supplied together):
# format = "mov"
# codec = "ProRes422HQ"
# Optional post-preset render setting overrides (profile values are strings):
# resolution = "3840x2160"
# frame_rate = "59.94"
# audio_codec = "lpcm"
# audio_bit_depth = "24"
# audio_sample_rate = "48000"

[outputs]
directory = "/path/to/exports"
keep_master = true

[compressor]
# Optional cap-preserving cadence ceiling (preserves <= cap, halves above cap):
# max_frame_rate = 60

[[compressor.targets]]
setting = "/path/to/presets/web_1080p.compressorsetting"
suffix = "-1080p"

[[compressor.targets]]
setting = "/path/to/presets/archive_hevc.compressorsetting"
output = "/path/to/exports/custom_archive.mov"
```

Explicit CLI flags override values from the TOML profile. In your own workspace, you can also keep an optional private Markdown overlay noting which TOML profile applies to each project.

## CLI quick start

```bash
# 1. Standalone DaVinci Resolve Studio workflow
video-export resolve doctor
video-export resolve projects
video-export resolve inspect --project "Demo Project"
video-export resolve render \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --preset "ProRes_Master" \
  --output /path/to/exports/episode_master.mov
video-export resolve render \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --preset "ProRes_Master" \
  --output /path/to/exports/episode_master.mov \
  --execute

# 2. Standalone Apple Compressor workflow
video-export compressor doctor
video-export compressor presets --setting /path/to/presets/web_1080p.compressorsetting
video-export compressor transcode \
  --input /path/to/input.mov \
  --setting /path/to/presets/web_1080p.compressorsetting \
  --output /path/to/exports/input-1080p.mov
video-export compressor transcode \
  --input /path/to/input.mov \
  --setting /path/to/presets/web_1080p.compressorsetting \
  --output /path/to/exports/input-1080p.mov \
  --execute
video-export compressor status --batch-id "BATCH_ID"

# 3. Connected Resolve -> Compressor pipeline
video-export pipeline run \
  --profile /path/to/profile.toml
video-export pipeline run \
  --profile /path/to/profile.toml \
  --execute

# Reuse a previously rendered master via its explicit manifest path
video-export pipeline run \
  --profile /path/to/profile.toml \
  --reuse-master /path/to/state/video-export/RUN_ID/manifest.json \
  --execute
```

## Documentation map

- [`AGENTS.md`](AGENTS.md) — Contributor and coding-agent invariants, environment setup, and safety rules.
- [`docs/prd.md`](docs/prd.md) — Product requirements, user needs, command scope, and milestones.
- [`docs/rfc.md`](docs/rfc.md) — Technical architecture, TOML schema, Resolve/Compressor contracts, and verification gates.
- [`docs/test.md`](docs/test.md) — Offline unit/integration test suite, CI matrix, and macOS live smoke verification.
- [`docs/working.md`](docs/working.md) — Dated changelog and empirical lessons learned.
- [`skills/video-export/SKILL.md`](skills/video-export/SKILL.md) — Root router skill for coding agents.

## License

MIT — Copyright (c) grapeot.
