# AGENTS.md

Instructions and repository invariants for coding agents working in `https://github.com/grapeot/video_export_skill`.

## Current phase

As of `2026-10-24`, this repository is in the **scaffold phase**. The documentation (`README.md`, `docs/*.md`) and agent skills (`skills/video-export/*.md`) define the planned CLI contract and verified backend constraints. Do not claim that the `video-export` CLI executable, `src/video_export/` modules, or `tests/` exist at runtime until they have been implemented and verified on a feature branch.

## Environment and commands

- **Platform & Python:** macOS-first for live tool integration; Python `>=3.11` with **stdlib-only runtime dependencies**.
- **Virtual environment rule:** Always check for `.venv` at the repository root first. If it exists, activate it before running commands; if it does not exist, create it with `uv venv`. Always install dependencies with `uv pip install` (never raw `pip install` or `uv pip install --system`).

When the package and test suite are present:

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
ruff check .
python -m pytest -q
```

Automated tests in `pytest` must remain 100% offline by default, using synthetic fixtures and mocked subprocess/IPC boundaries. Live macOS tests against DaVinci Resolve Studio or Apple Compressor are strictly opt-in and must use generated scratch clips and a disposable scratch project only.

## Repository invariants

1. **English only.** All code, docstrings, comments, documentation, skill files, commit messages, and pull request descriptions in this repository must be written in English.
2. **Default branch is `master`.** After the initial scaffold is published to `master`, branch protection on `master` requires pull requests before merging, 0 required approving reviews, and `enforce_admins=true`. All subsequent implementation and documentation changes must go through a feature branch, pass offline tests and linting, undergo review, and merge via pull request.
3. **User-authorized Git actions and scoped staging only.** Never run `git commit`, `git push`, `gh pr create`, `gh pr merge`, or branch-protection mutations unless the user has explicitly authorized that action. Never run `git add -A` or `git add .`; always stage specific task files by path and scan staged diffs for private data before pushing.
4. **Public repository hygiene.** Never commit real usernames, home directory paths, Group Container IDs, personal project or timeline names, personal preset names, unproved color/format claims, or machine-specific filenames in code, documentation, tests, or fixtures. Use generic placeholders such as `/path/to/input.mov`, `/path/to/profile.toml`, and `/path/to/presets/web_1080p.compressorsetting`. CLI runtime error metadata may point to private local log paths on the user's machine, but stdout outputs containing local data must never be auto-published, and any evidence pasted into commits or PR descriptions must be sanitized.
5. **Single root skill exposure.** Expose only `skills/video-export/SKILL.md` to workspace-level skill indices (`rules/skills/INDEX.md`, `skills/INDEX.md`, `AGENTS.md`, or `CLAUDE.md`). The focused skill files (`resolve.md`, `compressor.md`, `pipeline.md`) are internal to `skills/video-export/` and loaded on demand.
6. **No private defaults in public code.** User-specific directory paths and preset mappings belong in an external TOML profile (`--profile /path/to/profile.toml`), and user-specific workflow intent belongs in a local private Markdown overlay outside this repository. Explicit CLI flags always override TOML profile values.
7. **Dry-run by default and non-destructive execution.**
   - `resolve render`, `compressor transcode`, and `pipeline run` must output a dry-run plan and perform no writes or job submissions unless `--execute` is passed.
   - Refuse output path collisions; never overwrite existing files, never auto-delete source media or master exports, and never upload or publish outputs.
   - **DaVinci Resolve Studio boundaries:** Attach to an already running Resolve instance by default (`--headless` launch via `Contents/MacOS/Resolve -nogui` is explicit opt-in). Never silently switch away from a different loaded non-`Untitled` project in GUI mode. Never call `SaveProject()`. Never claim to snapshot/restore all render settings (Resolve's API has no `GetRenderSettings` or `GetCurrentRenderPreset`) or claim `Quick Export` is safe. Start only the job ID created by the current run and never delete other render jobs. Run all Resolve IPC in a child subprocess with a bounded timeout; never auto-kill a user's running Resolve on timeout, and quit an owned headless Resolve via the scripting API (`Quit()`) rather than `SIGTERM` (which triggers macOS Crash Reporter).
   - **Apple Compressor boundaries:** Never submit a source file that is still being written; require bounded file-stability and `ffprobe` checks on `--execute`. Never run `-resetBackgroundProcessing` or cancel existing jobs automatically.
8. **Update `docs/working.md`.** Whenever you complete a milestone, change behavior, or record verification results, add a flat dated entry under `## Changelog` and any reusable operational lessons under `## Lessons Learned`.

## Planned repository layout

```text
video_export_skill/
├── README.md
├── AGENTS.md
├── LICENSE                           # MIT (planned with implementation/repo init)
├── pyproject.toml                    # Planned: Python >=3.11, stdlib runtime, ruff + pytest dev deps
├── .gitignore                        # Planned: blocks .venv, caches, private logs, local manifests
├── .github/
│   └── workflows/
│       └── ci.yml                    # Planned: Ubuntu Python 3.11, 3.12, 3.13 (uv venv + ruff + pytest)
├── docs/
│   ├── prd.md                        # Product requirements and milestones
│   ├── rfc.md                        # Architecture, CLI/TOML schemas, and empirical backend rules
│   ├── test.md                       # Offline test strategy, CI matrix, and opt-in macOS live tests
│   └── working.md                    # Changelog and lessons learned
├── skills/
│   └── video-export/
│       ├── SKILL.md                  # Root router skill indexed by coding agents
│       ├── resolve.md                # Focused skill: DaVinci Resolve Studio export
│       ├── compressor.md             # Focused skill: Apple Compressor transcoding
│       └── pipeline.md               # Focused skill: Resolve -> verification -> Compressor pipeline
├── src/
│   └── video_export/                 # Planned runtime package (stdlib only)
│       ├── __init__.py
│       ├── cli.py                    # Subcommand parser and single-JSON stdout envelope
│       ├── config.py                 # TOML profile loader, validation, and CLI override merging
│       ├── resolve.py                # Subprocess-isolated Resolve Studio scripting backend
│       ├── compressor.py             # Compressor CLI wrapper and .compressorsetting XML parser
│       ├── pipeline.py               # Gated Resolve -> verification -> Compressor orchestrator
│       ├── verification.py           # lsof writer check, file size stability, ffprobe, opt-in ffmpeg decode
│       └── state.py                  # Private per-run manifest persistence and master provenance check
└── tests/                            # Planned offline unit/integration suite + synthetic fixtures
```
