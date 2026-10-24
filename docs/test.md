# Test Strategy and Verification: `video_export_skill`

- **Repository:** `https://github.com/grapeot/video_export_skill`
- **Date:** 2026-10-24
- **Status:** Implemented (Offline Suite + Opt-In macOS Smoke Verified)

## 1. Testing Principles

1. **Offline by default:** Running `python -m pytest -q` requires no DaVinci Resolve installation, no Apple Compressor installation, no `ffprobe`/`ffmpeg` binaries on the runner, and no network access.
2. **Behavior and boundary coverage:** Offline tests exercise real TOML parsing, precedence merging, `.compressorsetting` XML inspection, noisy JSON extraction, foreign-project guards, queue polling, verification failure gates, and manifest provenance checks.
3. **Synthetic fixtures and public hygiene:** All fixtures in `tests/` use synthetic project names (`"Demo"`), generic paths, and synthetic `.compressorsetting` XML snippets with no personal paths or identifiers.

## 2. Offline Test Suite (`tests/`)

### 2.1 Skill structure (`tests/test_scaffold.py`)
- Verifies that `skills/video-export/SKILL.md`, `resolve.md`, `compressor.md`, and `pipeline.md` exist in the repository layout.

### 2.2 Configuration, CLI, and dry-run boundaries (`tests/test_config_cli.py`)
- **Profile validation:** Rejects unknown tables/keys, invalid types, `keep_master=false`, path-traversal target suffixes (`../escape`), and malformed target entries with `config_invalid`.
- **CLI override precedence:** Confirms explicit CLI flags override `[resolve]` profile values without mutating the loaded dictionary.
- **Output collision checks:** Rejects duplicate target paths, output paths matching input paths, and pre-existing output files with `output_collision`.
- **Dry-run isolation:** Verifies that running `resolve render` without `--execute` returns `dry_run: true`, never calls the Resolve backend, and never creates a `--state-dir` manifest directory.
- **Single-JSON error contract:** Confirms invalid CLI arguments (missing required flags, `nan` or negative timeouts, unknown subcommands) return exit code 1 and a single JSON object with `error: "invalid_arguments"`.
- **Target extension derivation:** Confirms Compressor target filenames use the `<file-extension>` from the `.compressorsetting` XML rather than the input container extension.

### 2.3 DaVinci Resolve Studio worker guards (`tests/test_resolve.py`)
- **Foreign GUI project refusal:** Verifies `choose_project()` raises `foreign_project_loaded` and never calls `LoadProject()` when an attached GUI session has a different named project open.
- **Permitted project loads:** Confirms `LoadProject()` is allowed when the current project is `"Untitled Project"` or when the worker owns a `--headless` Resolve instance.
- **Scoped render job execution:** Confirms `operate()` configures `SelectAllFrames: True`, starts only its own `[job_id]`, checks `OutputFilename` from the render queue, and raises `render_job_failed` when `JobStatus` is `"Failed"`.

### 2.4 Apple Compressor XML and queue handling (`tests/test_compressor.py`)
- **`.compressorsetting` XML parsing:** Verifies `follow_source` detection for `-100` bounds, explicit width/height extraction, and `preset_invalid` errors on non-XML input.
- **Tolerant JSON extraction:** Verifies `noisy_json()` extracts JSON objects surrounded by bracketed diagnostic lines.
- **Exact flag ordering:** Confirms `submit_command()` encodes input paths as `file://` URIs with `-outputformat json` at the tail, and `status()` places `-format json` immediately after `-monitor` (`-monitor -format json -batchid <id> -once`).
- **Scoped batch status:** Verifies `batch_status()` ignores `Successful` statuses belonging to other batch IDs or child job entries while the target batch is still `Waiting`.
- **Queue polling and target verification:** Confirms `transcode()` waits through `Waiting` and `Processing` states, verifies all target outputs on `Successful`, raises `compressor_batch_failed` on `Failed`/`Cancelled`, and blocks submission if source verification fails.

### 2.5 Pipeline gating, verification, and master reuse (`tests/test_pipeline_verification.py`)
- **Failure gates:** Confirms that either a Resolve render failure or a master media verification failure prevents `compressor.transcode()` from being called.
- **Master reuse provenance:** Confirms `reuse_master()` succeeds when the manifest's `identity(config)` and on-disk `fingerprint(file)` (`path`, `size`, `mtime_ns`) match, and fails with `unverified_master_provenance` if either the Resolve configuration or the master file on disk changes.
- **Stability and stream verification:** Confirms `stable_file()` rejects files with open `lsof` writers (`aw`) or changing byte sizes across the stability window, `inspect_media()` rejects non-positive or non-finite durations, and `verify()` enforces expected stream attributes and passes `-xerror` to `ffmpeg` when `decode=True`.

## 3. Continuous Integration (GitHub Actions)

The suite currently contains 52 passing cases, including regression coverage for per-target codec/dimension mismatches, duration expectations that would permit truncation, short Resolve timeouts, late headless readiness, structured writer/decode timeouts, and late Compressor success beyond the monitoring deadline.

Workflow `.github/workflows/ci.yml` runs on `ubuntu-latest` across Python `3.11`, `3.12`, and `3.13`:

```bash
uv venv
uv pip install -e '.[dev]'
uv run ruff check .
uv run python -m pytest -q
```

## 4. macOS Live Smoke Verification Summary

End-to-end live smoke verification was executed on macOS against DaVinci Resolve Studio and Apple Compressor:
- **Synthetic input:** Generated a 2-second (`48` frames at `24` fps) synthetic test-pattern video with audio in a temporary directory.
- **Disposable Resolve project & headless lifecycle:** Launched Resolve Studio in headless mode (`-nogui`), attached via `DaVinciResolveScript`, created a disposable scratch project and timeline, exported a ProRes 422 HQ `.mov` master via the Deliver queue, and verified that `resolve.Quit()` exited cleanly with exit code `0`.
- **Resolution coercion observation:** Resolve coerced tiny requested scratch timeline dimensions to its `256x256` minimum, so the scratch timeline, rendered ProRes master, and transcoded Compressor target all measured `256x256` (confirming why output verification must compare against actual timeline/source metadata rather than input clip dimensions).
- **Pipeline & Compressor verification:** Ran `pipeline run --execute` (and `--reuse-master <manifest.json>`), transcoding the ProRes master to an HEVC `.mov` delivery file via Apple Compressor. Both the master and delivery output measured `duration = 2.0` seconds and passed full decode verification (`ffmpeg -v error -xerror -i ... -f null -`).
- **Scope boundary:** Large multi-gigabyte exports, HDR/Dolby Vision workflows, 8K timelines, and Resolve Quick Export were not live-tested.

The reproducible opt-in harness also passed with a fresh 1280x720 timeline and matching ProRes/HEVC outputs. Close Resolve before running it, provide an existing Compressor preset, and choose a new private scratch directory. The small scratch project remains in the local library for inspection; no production project is opened or saved.

```bash
source .venv/bin/activate
python scripts/live_smoke.py --execute \
  --work-dir /path/to/new/private/smoke-run \
  --setting /path/to/presets/delivery.compressorsetting \
  --resolve-preset "ProRes 422 HQ"
```
