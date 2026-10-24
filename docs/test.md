# Test Strategy: `video_export_skill`

- **Repository:** `https://github.com/grapeot/video_export_skill`
- **Date:** 2026-10-24
- **Status:** Scaffold Phase (Test Plan Defined; Test Suite Planned for Implementation Milestone)

## 1. Testing Principles

1. **Offline by default:** Running `python -m pytest -q` must require no DaVinci Resolve installation, no Apple Compressor installation, no `ffprobe`/`ffmpeg` binaries on the runner, and no network access. All subprocess and IPC boundaries are exercised through deterministic fakes and synthetic fixtures.
2. **Behavior and boundary coverage over shallow mocks:** Offline tests must verify real configuration parsing, precedence merging, XML inspection, noisy JSON extraction, state machine transitions, and failure gating rather than asserting that a mocked function was called.
3. **Synthetic fixtures and public hygiene:** Every fixture in `tests/` must use synthetic project names (`"Demo Project"`), generic paths (`/path/to/input.mov`), and synthetic `.compressorsetting` XML snippets. No real usernames, home directories, Group Container IDs, or personal filenames may appear anywhere in the test suite.

## 2. Planned Offline Test Suite (`tests/`)

### 2.1 Configuration precedence and validation (`tests/test_config.py`)
- **Precedence:** Verify that explicit CLI flags (`--preset`, `--output`, `--directory`, `--setting`) override corresponding values in `[resolve]`, `[outputs]`, and `[[compressor.targets]]` loaded from a TOML profile, while unspecified CLI flags fall back to the TOML profile.
- **Unknown keys rejected:** Verify that unknown tables or keys in TOML (for example `[resolve].unknown_key` or `[publish]`) fail immediately with `config_invalid`.
- **Non-destructive master policy:** Verify that `keep_master = false` in `[outputs]` is rejected so master files are never automatically deleted.

### 2.2 Path collisions and output derivation (`tests/test_collisions.py`)
- **Existing file collision:** Verify that `resolve render`, `compressor transcode`, and `pipeline run` refuse to proceed (in both dry-run and `--execute` modes) when the planned master output or any planned Compressor target output already exists on disk.
- **Duplicate target collision:** Verify refusal when two `[[compressor.targets]]` entries resolve to the same output path (e.g., identical `suffix` values).
- **Directory vs filename check:** Verify refusal when `-locationpath` / `--output` points to an existing directory or lacks a filename.

### 2.3 DaVinci Resolve Studio backend guards (`tests/test_resolve.py`)
- **Foreign GUI project refusal:** Simulate an attached GUI Resolve session where `GetCurrentProject().GetName()` returns `"Client_Edit"` while the user requested `--project "Demo Project"`; verify that `video-export` refuses with `foreign_project_loaded` and never calls `LoadProject("Demo Project")`.
- **Allowed project load cases:** Verify that `LoadProject("Demo Project")` is permitted when `"Demo Project"` is already the active project, when the active project is `"Untitled Project"`, or when running an owned `--headless` instance.
- **Scoped job control and no forbidden calls:** Verify that `resolve render --execute` calls `AddRenderJob()`, passes only the returned `[job_id]` to `StartRendering([job_id])`, and never invokes `SaveProject()`, `DeleteAllRenderJobs()`, or `DeleteRenderJob()`.
- **Quick Export rejection:** Verify that attempting to render with a Quick Export preset or claiming settings restoration is rejected.
- **Subprocess timeout and clean headless quit:**
  - Simulate a hung Resolve IPC subprocess in attached GUI mode; verify that `video-export` terminates only its own helper subprocess and never sends `SIGTERM` or `SIGKILL` to the Resolve PID.
  - Simulate an owned `--headless` session shutdown; verify that `resolve.Quit()` is invoked over IPC instead of `SIGTERM`.

### 2.4 Apple Compressor XML and CLI handling (`tests/test_compressor.py`)
- **`.compressorsetting` XML parsing:**
  - Parse synthetic `<setting>` XML fixtures with fixed output dimensions (e.g., `1920x1080`) vs `bounds` width/height set to `-100` (follow-source dimensions). Verify that `compressor presets` reports `resolution_mode: "follow_source"` when `-100` is present and does not infer resolution from the preset filename.
  - Verify clear error reporting when handed a binary plist or malformed XML file.
- **Exact CLI flag order:**
  - Verify batch submission builds `-batchname ... -jobpath file:///path/to/input.mov -settingpath /path/to/preset.compressorsetting -locationpath /path/to/output.mov -outputformat json`.
  - Verify status monitoring builds `-monitor -format json -batchid <ID> -once` with `-format json` immediately after `-monitor`.
- **Tolerant JSON extraction:** Feed stdout/stderr containing diagnostic text before and after the JSON payload (such as `2026-10-24 ... fileURL is NOT a directory\n{"batch": ...}`) and verify that the JSON object is parsed cleanly.
- **Queue status semantics and shared `jobID`:**
  - Verify that receiving a `batchID` transitions the run state to `queued` rather than `completed`.
  - Verify that `-monitor` status `Waiting` (and `Processing` at `0%`) is treated as an active non-failure state, whereas `Failed` and `Cancelled` fail the run and only `Successful` triggers post-transcode verification.
  - Verify that a batch with two `[[compressor.targets]]` that returns a single shared `jobID` checks both target output files on disk before reporting success.
- **No service reset or job cancellation:** Verify that no code path under `src/video_export/` invokes `-resetBackgroundProcessing` or `-kill`.

### 2.5 Verification, failure gating, and master provenance (`tests/test_pipeline_and_verification.py`)
- **Still-writing source refusal:** Simulate `lsof` reporting an active writer on `/path/to/input.mov` or byte size changing across the stability window; verify that `compressor transcode --execute` and `pipeline run --execute` abort before invoking Compressor.
- **Pipeline Resolve failure gating:** Simulate Resolve `GetRenderJobStatus(job_id)` returning `Failed`, `Cancelled`, or incomplete status, or `ffprobe` reporting a corrupt/mismatched master file; verify that Compressor is never called.
- **Expected media attribute checks:** Verify `ffprobe` validation against expected duration, codec, resolution, and color tags, plus opt-in `--verify-decode` (`ffmpeg -v error -i ... -f null -`) execution when requested and skip when omitted.
- **Master reuse provenance (`--reuse-master`):**
  - Verify that `pipeline run --reuse-master --execute` reuses `/path/to/exports/master.mov` only when a matching, verified `manifest.json` exists and the file's size and sha256 match the manifest.
  - Verify that an untracked file at `/path/to/exports/master.mov`, or a file whose bytes/size changed after the manifest was written, is refused with `unverified_master_provenance`.

### 2.6 CLI contract and source hygiene scan (`tests/test_cli_and_hygiene.py`)
- **Single-JSON stdout contract:** Verify that every subcommand prints exactly one valid JSON object to stdout on both success and error (`--help` excepted).
- **Repository hygiene scan:** Scan all tracked files under `README.md`, `AGENTS.md`, `docs/`, `skills/`, `src/`, and `tests/` to assert the absence of real home directory paths, Group Container IDs, personal email addresses, and forbidden API/CLI tokens (`SaveProject`, `DeleteAllRenderJobs`, `-resetBackgroundProcessing`).

## 3. Continuous Integration (GitHub Actions)

Planned workflow `.github/workflows/ci.yml`:
- **OS:** `ubuntu-latest`
- **Python matrix:** `["3.11", "3.12", "3.13"]`
- **Install & test commands:**
  ```bash
  uv venv
  uv pip install -e '.[dev]'
  uv run ruff check .
  uv run python -m pytest -q
  ```
  (Never use `uv pip install --system` on GitHub Actions runners.)

## 4. Opt-In macOS Live Verification

Live integration tests require a macOS machine with DaVinci Resolve Studio, Apple Compressor, and `ffmpeg`/`ffprobe` installed. They are skipped by default and enabled only via an explicit opt-in flag or environment variable (`VIDEO_EXPORT_LIVE_TESTS=1`).

Rules for live tests:
1. **Generated scratch clips only:** Generate a short (e.g., 2-second) synthetic test pattern clip in a temporary directory using `ffmpeg -f lavfi -i testsrc=size=1280x720:rate=24 -t 2 ...`.
2. **Scratch project only:** Never run live tests against a user's personal or production Resolve project. Use a disposable scratch project (`"video_export_scratch_test"`).
3. **Sanitized evidence:** When recording live verification outcomes in `docs/working.md` or pull request descriptions, replace any local temporary paths or machine-specific details with generic placeholders.
