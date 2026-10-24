# AGENTS.md

Instructions and repository invariants for coding agents working in `https://github.com/grapeot/video_export_skill`.

## Current status

The `video-export` runtime package (`src/video_export/`), offline test suite (`tests/`), and agent skill suite (`skills/video-export/`) are implemented and verified. Offline unit tests pass under `pytest`, and end-to-end macOS smoke verification has been completed against DaVinci Resolve Studio and Apple Compressor using synthetic scratch media.

## Environment and commands

- **Platform & Python:** macOS-first for live tool integration; Python `>=3.11` with **stdlib-only runtime dependencies**.
- **Virtual environment rule:** Always check for `.venv` at the repository root first. If it exists, activate it before running commands; if it does not exist, create it with `uv venv`. Always install dependencies with `uv pip install` (never raw `pip install` or `uv pip install --system`).

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[dev]'
ruff check .
python -m pytest -q
```

Automated tests in `pytest` are 100% offline by default, using synthetic fixtures and mocked subprocess/IPC boundaries. Live macOS checks against DaVinci Resolve Studio or Apple Compressor are strictly opt-in and must use generated scratch clips and a disposable scratch project only.

## Repository invariants

1. **English only.** All code, docstrings, comments, documentation, skill files, commit messages, and pull request descriptions in this repository must be written in English.
2. **Default branch is `master`.** Branch protection on `master` requires pull requests before merging, 0 required approving reviews, and `enforce_admins=true`. All changes must go through a feature branch, pass offline tests and linting, undergo review, and merge via pull request.
3. **User-authorized Git actions and scoped staging only.** Never run `git commit`, `git push`, `gh pr create`, `gh pr merge`, or branch-protection mutations unless the user has explicitly authorized that action. Never run `git add -A` or `git add .`; always stage specific task files by path and scan staged diffs for private data before pushing.
4. **Public repository hygiene.** Never commit real usernames, home directory paths, Group Container IDs, personal project or timeline names, personal preset names, unproved color/format claims, or machine-specific filenames in code, documentation, tests, or fixtures. Use generic placeholders such as `/path/to/input.mov`, `/path/to/profile.toml`, and `/path/to/presets/web_1080p.compressorsetting`. Generated media, local TOML profiles, private overlays, logs, and run manifests must stay outside tracked files.
5. **Single root skill exposure.** Expose only `skills/video-export/SKILL.md` to workspace-level skill indices (`rules/skills/INDEX.md`, `skills/INDEX.md`, `AGENTS.md`, or `CLAUDE.md`). The focused skill files (`resolve.md`, `compressor.md`, `pipeline.md`) are internal to `skills/video-export/` and loaded on demand.
6. **No private defaults in public code.** User-specific directory paths and preset mappings belong in an external TOML profile (`--profile /path/to/profile.toml`), and user-specific workflow intent belongs in a local private Markdown overlay outside this repository. Explicit CLI flags always override TOML profile values.
7. **Dry-run by default and non-destructive execution.**
   - `resolve render`, `compressor transcode`, and `pipeline run` output a dry-run plan by default (validating configuration, Compressor preset XML, and output path collisions without connecting to Resolve or creating run manifests) and perform no writes or job submissions unless `--execute` is passed.
   - Refuse output path collisions; never overwrite existing files, never auto-delete source media or master exports, and never upload or publish outputs.
   - **DaVinci Resolve Studio boundaries:** Attach to an already running Resolve instance by default (`--headless` launch via `Contents/MacOS/Resolve -nogui` is explicit opt-in). Never silently switch away from a different loaded non-`Untitled Project` in GUI mode (`inspect` and `render` may load a requested project only from an empty/`Untitled Project` session or an owned headless instance). Never call `SaveProject()`. Never claim to snapshot/restore active render settings (Resolve mutates active render settings in memory and Live Save may persist them) or claim `Quick Export` is used or tested. Start only the job ID created by the current run and never delete other render jobs. Run Resolve IPC via `video_export.resolve_worker` in a child subprocess with a bounded timeout; never auto-kill a running Resolve or cancel an active render on timeout, and quit an owned headless Resolve via `resolve.Quit()` only when no render is in progress.
   - **Apple Compressor boundaries:** Never submit a source file that is still being written; require `lsof` writer checks, bounded file-size/mtime stability, and `ffprobe` validation on `--execute`. Never run `-resetBackgroundProcessing` or cancel existing batches automatically.
8. **Update `docs/working.md`.** Whenever you complete a milestone, change behavior, or record verification results, add a flat dated entry under `## Changelog` and any reusable operational lessons under `## Lessons Learned`.

## Repository layout

```text
video_export_skill/
├── README.md
├── AGENTS.md
├── LICENSE                           # MIT
├── pyproject.toml                    # Python >=3.11, stdlib runtime, ruff + pytest dev deps
├── .gitignore                        # Blocks .venv, caches, private logs, local manifests, media
├── .github/
│   └── workflows/
│       └── ci.yml                    # Ubuntu Python 3.11, 3.12, 3.13 (uv venv + ruff + pytest)
├── docs/
│   ├── prd.md                        # Product requirements and milestones
│   ├── rfc.md                        # Architecture, CLI/TOML schemas, and empirical backend rules
│   ├── test.md                       # Offline test suite, CI matrix, and opt-in macOS live smoke
│   └── working.md                    # Changelog and lessons learned
├── skills/
│   └── video-export/
│       ├── SKILL.md                  # Root router skill indexed by coding agents
│       ├── resolve.md                # Focused skill: DaVinci Resolve Studio export
│       ├── compressor.md             # Focused skill: Apple Compressor transcoding
│       └── pipeline.md               # Focused skill: Resolve -> verification -> Compressor pipeline
├── src/
│   └── video_export/                 # Runtime package (stdlib only)
│       ├── __init__.py
│       ├── py.typed
│       ├── cli.py                    # Subcommand parser and single-JSON stdout envelope
│       ├── common.py                 # Shared subprocess, JSON extraction, and path collision helpers
│       ├── config.py                 # TOML profile loader, validation, and CLI override merging
│       ├── resolve.py                # Subprocess-isolated IPC wrapper for Resolve scripting
│       ├── resolve_worker.py         # Child worker isolating native fusionscript stdout noise
│       ├── compressor.py             # Compressor CLI adapter and .compressorsetting XML parser
│       ├── pipeline.py               # Gated Resolve -> verification -> Compressor orchestrator
│       ├── verification.py           # lsof writer check, file stability, ffprobe, opt-in ffmpeg decode
│       └── state.py                  # Private per-run manifest persistence and master reuse check
└── tests/                            # Offline unit/integration suite + synthetic fixtures
    ├── conftest.py
    ├── test_scaffold.py
    ├── test_config_cli.py
    ├── test_resolve.py
    ├── test_compressor.py
    └── test_pipeline_verification.py
```
