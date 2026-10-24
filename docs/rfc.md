# Technical RFC: `video-export` Architecture and Backend Contracts

- **Repository:** `https://github.com/grapeot/video_export_skill`
- **Date:** 2026-10-24
- **Status:** Implemented (`src/video_export/`)

## 1. Architecture Overview

`video-export` is a single-package Python CLI (`src/video_export/`) targeting macOS and Python `>=3.11` with stdlib-only runtime dependencies (`argparse`, `datetime`, `hashlib`, `json`, `math`, `os`, `pathlib`, `shutil`, `subprocess`, `sys`, `tempfile`, `time`, `tomllib`, `uuid`, `xml.etree.ElementTree`). There is no background daemon and no plugin framework.

### Module layout

| Module | Responsibility |
|---|---|
| `src/video_export/cli.py` | Argument parsing (`Parser`), subcommand routing, dry-run vs `--execute` gating, single-JSON stdout envelope, and `0o077` umask enforcement. |
| `src/video_export/common.py` | `ExportError` exception hierarchy, subprocess execution (`run`), tolerant JSON extraction (`noisy_json`), path resolution, and output collision checks (`outputs_available`). |
| `src/video_export/config.py` | TOML profile validation (`load_profile`), strict key checking, and Resolve option merging (`resolve_options`). |
| `src/video_export/resolve.py` | Subprocess-isolated IPC wrapper (`call`) invoking `video_export.resolve_worker` with Resolve scripting environment variables and a temporary result file. |
| `src/video_export/resolve_worker.py` | Child worker connecting to `DaVinciResolveScript`, enforcing foreign-project guards, configuring single-clip Deliver renders, writing job checkpoints, confirming queue output filenames, and calling `resolve.Quit()` on owned idle headless sessions. |
| `src/video_export/compressor.py` | Wrapper around `/Applications/Compressor.app/Contents/MacOS/Compressor`, `.compressorsetting` XML parser (`preset`), target path planner (`plan_targets`), batch submission, and scoped `-monitor` status polling (`batch_status`). |
| `src/video_export/pipeline.py` | Sequential orchestrator (`render_master`, `execute`) connecting Resolve master rendering or manifest-based reuse with Compressor transcoding. |
| `src/video_export/verification.py` | Open-writer checks (`lsof -Ffa`), bounded size/mtime stability (`stable_file`), `ffprobe` stream and expectation validation (`inspect_media`, `verify`), and opt-in `ffmpeg -v error -xerror` full decode. |
| `src/video_export/state.py` | Atomic private per-run manifest persistence (`RunState`) and metadata-based master reuse verification (`reuse_master`, `fingerprint`, `identity`). |

## 2. Configuration Schema and Precedence

### 2.1 External TOML profile schema

User-specific paths and presets live in an external TOML file passed via `--profile /path/to/profile.toml`:

```toml
[resolve]
project = "Demo Project"
timeline = "Main Edit"
preset = "ProRes_Master"
output = "/path/to/exports/master.mov"
# Optional explicit override; format and codec must be supplied together:
# format = "mov"
# codec = "ProRes422HQ"

[outputs]
directory = "/path/to/exports"
keep_master = true

[[compressor.targets]]
setting = "/path/to/presets/web_1080p.compressorsetting"
suffix = "-1080p"

[[compressor.targets]]
setting = "/path/to/presets/archive_hevc.compressorsetting"
output = "/path/to/exports/master-archive.mov"
```

### 2.2 Validation and precedence rules
1. **Strict schema:**
   - Top-level tables allowed: `resolve`, `outputs`, `compressor`.
   - `[resolve]` keys allowed: `project`, `timeline`, `preset`, `output`, `format`, `codec` (all non-empty strings when present).
   - `[outputs]` keys allowed: `directory` (non-empty string), `keep_master` (must be `true` if present; `false` raises `config_invalid`).
   - `[compressor]` keys allowed: `targets` (must be a list of tables).
   - `[[compressor.targets]]` keys allowed: `setting` (required non-empty string), `suffix` (string without `/` or `\`), `output` (non-empty string). Each target requires at least `suffix` or `output`.
2. **CLI precedence:**
   - On `resolve render` and `pipeline run`, CLI flags `--project`, `--timeline`, `--preset`, `--output`, `--format`, and `--codec` override `[resolve]` keys. After merging, `project`, `timeline`, `preset`, and `output` are required, and `format` and `codec` must be provided together if either is set.
   - Note that in `pipeline run`, `--output` specifies the **master** output path (`[resolve].output`), whereas in `compressor transcode`, `--output` specifies the single target output path (and fails with `config_invalid` if more than one target is planned).
   - Passing one or more `--setting PATH` flags on `compressor transcode` or `pipeline run` overrides `[[compressor.targets]]` from the profile with generated suffixes `-1`, `-2`, etc.
3. **Target path derivation and relative paths:**
   - For each target, output path resolution selects: CLI `--output` (only in single-target `compressor transcode`) -> `target.output` -> `<base>/<source_stem><suffix>.<preset_extension>`, where `<base>` is `--directory` -> `[outputs].directory` -> `source.parent`.
   - The target filename extension must match the `<file-extension>` parsed from the `.compressorsetting` XML (`output_invalid` otherwise).
   - All paths are resolved via `Path(value).expanduser().resolve()` against the current working directory; absolute paths are recommended in TOML profiles.
4. **Collision refusal (`outputs_available`):**
   - All planned output paths must have a filename extension, must be distinct from each other and from input/master paths, and must not already exist (including broken symlinks) on disk (`output_collision`).

## 3. CLI Surface and JSON Envelope Contract

### 3.1 Exact subcommands and flags

```text
video-export resolve doctor [--timeout SEC] [--headless]
video-export resolve projects [--timeout SEC] [--headless]
video-export resolve inspect [--project NAME] [--timeout SEC] [--headless]
video-export resolve render [--profile PATH] [--project NAME] [--timeline NAME] [--preset NAME] [--output PATH] [--format FORMAT --codec CODEC] [--headless] [--state-dir DIR] [--directory DIR] [--verify-decode] [--stability-window SEC] [--poll SEC] [--expect-duration SEC] [--expect-codec CODEC] [--expect-resolution WIDTHxHEIGHT] [--expect-color-primaries TAG] [--expect-color-transfer TAG] [--expect-color-space TAG] [--timeout SEC] [--execute]

video-export compressor doctor [--timeout SEC]
video-export compressor presets [--setting PATH ...] [--timeout SEC]
video-export compressor status --batch-id ID [--timeout SEC]
video-export compressor transcode --input PATH [--profile PATH] [--setting PATH ...] [--output PATH] [--directory DIR] [--state-dir DIR] [--verify-decode] [--stability-window SEC] [--poll SEC] [--expect-duration SEC] [--expect-codec CODEC] [--expect-resolution WIDTHxHEIGHT] [--expect-color-primaries TAG] [--expect-color-transfer TAG] [--expect-color-space TAG] [--timeout SEC] [--execute]

video-export pipeline run [--profile PATH] [--project NAME] [--timeline NAME] [--preset NAME] [--output PATH] [--format FORMAT --codec CODEC] [--setting PATH ...] [--directory DIR] [--reuse-master MANIFEST] [--headless] [--state-dir DIR] [--verify-decode] [--stability-window SEC] [--poll SEC] [--expect-duration SEC] [--expect-codec CODEC] [--expect-resolution WIDTHxHEIGHT] [--expect-color-primaries TAG] [--expect-color-transfer TAG] [--expect-color-space TAG] [--timeout SEC] [--execute]
```

### 3.2 Stdout JSON envelope
Every invocation (`--help` excepted) prints a single JSON object to stdout:
- Success (`exit 0`): `{"ok": true, "data": ...}`
  - For dry-runs (`render`, `transcode`, `pipeline run` without `--execute`):
    `{"ok": true, "data": {"dry_run": true, "plan": {"resolve": ..., "targets": ..., "input": ..., "expected": ..., "backend_validation": "performed on execute; dry-run does not connect to Resolve"}}}`
  - For `--execute` runs:
    `{"ok": true, "data": {"result": ..., "manifest": "/path/to/manifest.json"}}`
- Error (`exit 1`): `{"ok": false, "error": "<code>", "message": "<text>", "details": {...}}` (when an `--execute` run fails after creating a state directory, `details.manifest` points to the saved `manifest.json`).

## 4. DaVinci Resolve Studio Backend (`resolve.py` & `resolve_worker.py`)

### 4.1 Worker isolation and environment
Native `fusionscript.so` initialization can write text directly to file descriptor 1. To guarantee clean JSON on stdout, `resolve.call()` spawns `sys.executable -m video_export.resolve_worker <temp_result.json>` with `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH` (overridable via `VIDEO_EXPORT_RESOLVE_API`, `VIDEO_EXPORT_RESOLVE_LIB`, `VIDEO_EXPORT_RESOLVE_APP`). The worker writes its JSON payload to `<temp_result.json>`.

### 4.2 Empirically verified behavior and execution rules
1. **Attach by default, headless opt-in:** `dvr.scriptapp("Resolve")` connects to a running instance. If none is reachable and `--headless` is set, the worker first checks `pgrep -x Resolve` (returning `resolve_not_ready` if Resolve is running without external scripting enabled) and otherwise launches `Resolve -nogui`, polling up to `min(120, timeout)` seconds.
2. **Project loading guard (`choose_project`):**
   - If no `--project` is passed or the active project already matches `--project`, the active project is used.
   - If a different project is open and its name is not `"Untitled Project"` (and the session is not an owned `--headless` instance), the worker raises `foreign_project_loaded` without calling `LoadProject()`.
   - When no project or `"Untitled Project"` is open (or in an owned headless session), `inspect` and `render` may call `manager.LoadProject(name)` for a project in the current database folder (`resolve projects` lists current-folder projects and folders only).
3. **Render settings mutation and Deliver queue:**
   - Dry-run does not contact Resolve, so preset and timeline existence are verified on `inspect` or `--execute`.
   - `render --execute` refuses if `project.IsRenderingInProgress()` (`resolve_busy`), locates the unique timeline by name (`timeline_not_found`), verifies the preset is in `project.GetRenderPresetList()` (`preset_not_found`), and calls `SetCurrentTimeline`, `LoadRenderPreset`, and `SetCurrentRenderMode(1)` (Individual/Single Clip mode).
   - If `format` and `codec` overrides were supplied, it calls `SetCurrentRenderFormatAndCodec(format, codec)`. It then checks `GetCurrentRenderFormatAndCodec()` and requires the output file extension to match `.` + `selected["format"]` (`output_invalid`).
   - It calls `SetRenderSettings({"SelectAllFrames": True, "TargetDir": str(output.parent), "CustomName": output.stem, "ExportVideo": True, "ExportAudio": True})`, adds a job via `AddRenderJob()`, writes checkpoints to `resolve-job.json`, starts only `[job_id]` via `StartRendering([job_id])`, and polls `GetRenderJobStatus(job_id)`.
   - Active render settings remain mutated in memory (`Project` has no `GetRenderSettings()` or `GetCurrentRenderPreset()`). `video-export` never calls `SaveProject()`, though Resolve's Live Save may persist changes.
   - Upon `JobStatus == "Complete"`, the worker checks `GetRenderJobList()` for `job_id`'s `OutputFilename` and raises `output_name_mismatch` if Resolve wrote a filename different from `output.name`.
4. **Timeout and clean headless shutdown:**
   - On an owned `--headless` instance, the `finally` block calls `resolve.Quit()` (verified to exit with code 0 without triggering macOS Crash Reporter) **only** when `not project or not project.IsRenderingInProgress()`.
   - If a render times out (`resolve_render_timeout` or `resolve_ipc_timeout`), `video-export` neither cancels the render job nor kills Resolve; the checkpoint path and manifest are retained for recovery.

## 5. Apple Compressor Backend (`compressor.py`)

1. **XML preset inspection (`preset`):** Parses `<setting>` XML via `xml.etree.ElementTree`, requiring a valid alphanumeric `<file-extension>`. Reports `resolution_mode: "follow_source"` when `<bounds>` width or height is `"-100"`. If `--setting` is omitted on `compressor presets`, `discover_presets()` globs `~/Library/Group Containers/*.com.apple.videoProApps/Library/Application Support/Compressor/Settings/*.compressorsetting`.
2. **Batch submission and monitoring:**
   - Submits `-batchname video-export -priority medium` followed by `-jobpath file:///... -settingpath ... -locationpath ...` triples and `-outputformat json`.
   - Polls `Compressor -monitor -format json -batchid <batch_id> -once` (`-format json` immediately after `-monitor`) and extracts JSON via `noisy_json()`.
   - `batch_status()` matches only the requested `batch_id` (or a single-batch wrapper omitted ID) and never mistakes a child job status or another batch's `Successful` status for batch completion.
   - Continues polling while status is `Waiting` or `Processing` (or `None` while initializing), fails on `Failed`/`Cancelled`/`Canceled` (`compressor_batch_failed`), and leaves the batch running on timeout (`compressor_timeout`).

## 6. Verification and Master Reuse (`verification.py`, `pipeline.py`, `state.py`)

1. **File stability and stream checks (`verify`):**
   - `stable_file()` runs `lsof -Ffa -- <file>` to reject open writers (`aw` or `au`) and samples `stat()` across `--stability-window` seconds (default `2`) to require constant positive `st_size` and `st_mtime_ns`.
   - `inspect_media()` runs `ffprobe -v error -show_format -show_streams -of json`, requiring a video stream and positive finite `format.duration`.
   - Duration is checked within `0.1` seconds tolerance: `render_master()` checks the master against the Resolve timeline's `frames / fps` duration, and `compressor.transcode()` checks every target output against the verified source/master duration.
    - Optional `--expect-*` flags check `duration`, `codec_name`, `width`/`height`, `color_primaries`, `color_transfer`, and `color_space` on the first video stream. Expected duration is also checked against the source before Compressor submission and cannot replace source/output duration consistency. Each target additionally checks recognized preset codec mappings, positive fixed bounds and fixed frame rate; `-100` dimensions remain descriptive because cropping/padding may change the result, so use `--expect-resolution` for an explicit requirement. Conflicting preset and CLI expectations fail. In `pipeline run`, stream expectations apply to Compressor delivery targets; master expectations can be checked via standalone `resolve render`. Measured `ffprobe` tags do not prove subjective HDR/Dolby Vision grading appearance.
    - Optional `--verify-decode` runs `ffmpeg -v error -xerror -i <file> -f null -` and requires exit code 0 and empty stderr.
    - `--timeout` bounds the Resolve worker operation and each Compressor monitor phase, not the entire multi-stage pipeline. Subprocess writer/decode timeouts return structured errors. Monitor subprocesses and polling sleeps use remaining time; timeouts do not cancel backend jobs.
2. **Manifest provenance for `--reuse-master MANIFEST`:**
   - `reuse_master(manifest, config)` reads the explicit manifest path and requires `master["verified"] is True`, `master["identity"] == identity(config)` (SHA-256 of the sorted Resolve config JSON), and `master["fingerprint"] == fingerprint(config["output"])` (`path`, `size`, `mtime_ns`).
   - If matched, `pipeline.execute()` also re-verifies the master file on disk (`verify()` with the recorded master duration) before invoking Compressor. Because the fingerprint is file metadata (not a content hash or Resolve project state check), users must run a fresh render whenever the Resolve project is edited.
