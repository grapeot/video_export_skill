# video_export_skill

An agent skill suite (`skills/video-export/SKILL.md`) and planned Python command-line tool (`video-export`) for macOS video export and transcoding workflows. It provides two independently usable capabilities—exporting timelines from **DaVinci Resolve Studio** and transcoding media with **Apple Compressor**—plus an optional gated pipeline that connects them.

> **Project Status (2026-10-24): Scaffold Phase.** This repository currently defines the product requirements, technical architecture, CLI and configuration contracts, test strategy, and agent skill specifications. The runtime Python package (`src/video_export/`) and automated test suite (`tests/`) are planned for the implementation milestone and are not yet present in this checkout.

## Who it is for

Video creators, educators, and developers on macOS who edit in DaVinci Resolve Studio, transcode delivery variants in Apple Compressor, or use either tool standalone with the help of a coding agent (Codex, Claude Code, Cursor, OpenCode, and similar).

Driving Resolve and Compressor through ad-hoc shell commands is fragile: Resolve's external scripting API lacks readback methods for active render settings and unsaved project state, while Compressor's command-line interface requires strict flag ordering, returns a batch identifier as soon as a job is queued rather than finished, and can produce truncated outputs if handed a source file that is still being written. `video-export` wraps both tools behind a conservative, dry-run-first contract with machine-readable JSON output and media verification gates.

## Capabilities and boundaries

- **Two standalone backends, one optional pipeline:**
  - `video-export resolve ...` inspects projects, timelines, and render presets, and renders master outputs through DaVinci Resolve Studio's official Python scripting API.
  - `video-export compressor ...` inspects `.compressorsetting` XML presets, submits single- or multi-target transcode batches through the Apple Compressor CLI executable, and monitors batch completion.
  - `video-export pipeline run ...` renders a master file in Resolve, verifies that the file is completely written and valid via `ffprobe`, and only then submits it to Compressor for one or more delivery targets.
- **Dry-run by default:** `resolve render`, `compressor transcode`, and `pipeline run` print a structured execution plan and touch nothing unless `--execute` is passed explicitly.
- **One JSON object per command:** Every subcommand prints a single machine-readable JSON object to stdout (`--help` excepted) and records run state, job/batch identifiers, output paths, and verification results in a private per-run manifest.
- **Conservative toward running applications and files:**
  - Refuses output path collisions; never overwrites existing files silently.
  - Never deletes source clips or rendered master files automatically.
  - Attaches to an already running Resolve instance by default (headless `-nogui` launch is explicit opt-in), refuses to switch away from a different open non-`Untitled` project in the GUI, never calls `SaveProject()`, starts only the render job ID it created, and never deletes other render queue jobs.
  - Never submits a still-writing file to Compressor, and never resets Compressor background services or cancels pre-existing jobs.
  - Never uploads or publishes media anywhere.

Full architecture and empirical tool constraints are documented in [`docs/rfc.md`](docs/rfc.md).

## Planned installation

Requires macOS, Python 3.11 or newer, and [uv](https://github.com/astral-sh/uv). Runtime code uses only the Python standard library. `ffprobe` (and optionally `ffmpeg` for full-decode verification) is required when executing renders or transcodes. DaVinci Resolve Studio is required for `resolve` commands; Apple Compressor is required for `compressor` commands.

Once the runtime package is implemented:

```bash
git clone https://github.com/grapeot/video_export_skill
cd video_export_skill
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
python -m pytest -q
```

### Installing the skill into your coding agent

Give your coding agent this repository's GitHub URL (`https://github.com/grapeot/video_export_skill`) and ask it to install the skill.

The agent should:
1. Read your workspace's `AGENTS.md` or `CLAUDE.md` and follow any workspace routing table (such as `WORKSPACE.md` or `rules/WORKSPACE.md`).
2. Register **only the root router skill**—`skills/video-export/SKILL.md`—in your workspace's skill index (`rules/skills/INDEX.md` or `skills/INDEX.md` if one exists, otherwise a short pointer in `AGENTS.md` or `CLAUDE.md`).
3. Leave the focused skill files (`skills/video-export/resolve.md`, `skills/video-export/compressor.md`, and `skills/video-export/pipeline.md`) unindexed at the global workspace level so the agent loads them on demand through `SKILL.md`.

## Configuration: TOML profile and local overlay

Public code and skill files contain no personal defaults or machine-specific paths. Configuration is separated into two local layers outside this repository:

1. **Local private Markdown overlay (optional):** In your own workspace skill directory, you can keep a short private overlay note describing your personal workflow intent (for example, which profile file to use for different shows or export routines) and pointing to `skills/video-export/SKILL.md`.
2. **External TOML profile:** Store concrete directory paths, Resolve preset names, and Compressor target `.compressorsetting` paths in an external TOML file passed via `--profile /path/to/profile.toml`:

```toml
[resolve]
preset = "ProRes_Master"
output = "/path/to/exports/episode_master.mov"

[outputs]
directory = "/path/to/exports"
keep_master = true

[[compressor.targets]]
setting = "/path/to/presets/web_1080p.compressorsetting"
suffix = "-1080p"

[[compressor.targets]]
setting = "/path/to/presets/archive_hevc.compressorsetting"
suffix = "-hevc"
```

Explicit CLI arguments always override values from the TOML profile.

## Planned CLI quick start

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
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Main Edit"
video-export pipeline run \
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --execute
```

## Documentation map

- [`AGENTS.md`](AGENTS.md) — Contributor and coding-agent invariants, environment setup, and safety rules.
- [`docs/prd.md`](docs/prd.md) — Product requirements, user needs, command scope, and milestones.
- [`docs/rfc.md`](docs/rfc.md) — Technical architecture, TOML schema, verified Resolve/Compressor behavior, and verification gates.
- [`docs/test.md`](docs/test.md) — Offline unit/integration test plan, CI matrix, and opt-in macOS live test rules.
- [`docs/working.md`](docs/working.md) — Dated changelog and empirical lessons learned.
- [`skills/video-export/SKILL.md`](skills/video-export/SKILL.md) — Root router skill for coding agents.

## License

MIT — Copyright (c) grapeot.
