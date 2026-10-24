# Technical RFC: `video-export` Architecture and Backend Contracts

- **Repository:** `https://github.com/grapeot/video_export_skill`
- **Date:** 2026-10-24
- **Status:** Scaffold Phase (Proposed Specification; Runtime Not Yet Implemented)

## 1. Architecture Overview

`video-export` is designed as a compact, single-package Python CLI (`src/video_export/`) targeting macOS and Python `>=3.11`. At runtime it depends only on the Python standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `os`, `pathlib`, `subprocess`, `sys`, `time`, `tomllib`, ` urllib.parse`, `xml.etree.ElementTree`). There is no background daemon, no plugin framework, and no speculative multi-layer sandbox.

### Planned module layout

| Module | Responsibility |
|---|---|
| `src/video_export/cli.py` | Argument parsing, subcommand routing, single-JSON stdout envelope formatting, and deterministic exit codes. |
| `src/video_export/config.py` | TOML profile parsing (`tomllib`), strict key validation (rejecting unknown keys), CLI-over-TOML precedence resolution, output path derivation, and collision checks. |
| `src/video_export/resolve.py` | Subprocess-isolated IPC client for DaVinci Resolve Studio's Python scripting API, environment resolution, conservative GUI project guard, render job submission/polling, and clean headless shutdown. |
| `src/video_export/compressor.py` | Wrapper around `/Applications/Compressor.app/Contents/MacOS/Compressor`, `.compressorsetting` XML parser, tolerant JSON extraction across noisy stdout/stderr, and `-monitor` polling. |
| `src/video_export/pipeline.py` | Sequential orchestrator connecting Resolve render (or provenance-checked master reuse), media stability + `ffprobe` gating, and Compressor multi-target transcoding. |
| `src/video_export/verification.py` | Open-writer checks (`lsof`), bounded file-size/mtime stability polling, `ffprobe` stream/duration/codec/resolution/color-tag validation, and opt-in full stream decode via `ffmpeg`. |
| `src/video_export/state.py` | Private per-run manifest (`manifest.json`) creation, atomic updates, and provenance verification for master reuse. |

## 2. Configuration Schema and Precedence

### 2.1 External TOML profile schema

User-specific paths and preferred presets live in an external TOML file passed via `--profile /path/to/profile.toml`:

```toml
[resolve]
preset = "ProRes_Master"
output = "/path/to/exports/master.mov"

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

### 2.2 Validation and precedence rules
1. **Strict schema:** Only `[resolve]` (`preset`, `output`), `[outputs]` (`directory`, `keep_master`), and `[[compressor.targets]]` (`setting`, `suffix`) are recognized. Any unknown table or key raises a `config_invalid` error before any backend is contacted.
2. **Precedence:** Explicit CLI arguments always override TOML profile values. For example, passing `--preset "Broadcast_ProRes"` or `--output /path/to/custom_master.mov` on the command line overrides `[resolve].preset` or `[resolve].output` from `--profile`.
3. **Target output derivation:** When `[[compressor.targets]]` entries specify `suffix` (such as `"-1080p"`), the target output path defaults to `<outputs.directory>/<master_stem><suffix><ext>`, where `<outputs.directory>` defaults to the master file's parent directory if omitted. In standalone `compressor transcode`, `--output /path/to/output.mov` can also be passed directly for a single target.
4. **Master retention and collision refusal:**
   - Automatic deletion of source clips or rendered masters is forbidden. If `keep_master = false` is set in TOML, validation refuses the configuration rather than deleting the master after transcoding.
   - If any planned master output path or target output path already exists on disk, or if two targets resolve to the same output path, planning and execution fail with `output_collision`.

## 3. CLI Surface and JSON Envelope Contract

### 3.1 Subcommands

```text
video-export resolve doctor [--headless]
video-export resolve projects [--headless]
video-export resolve inspect [--project NAME] [--timeline NAME] [--headless]
video-export resolve render [--profile PATH] --project NAME --timeline NAME [--preset NAME] [--output PATH] [--headless] [--verify-decode] [--execute]

video-export compressor doctor
video-export compressor presets --setting PATH [--setting PATH ...]
video-export compressor transcode [--profile PATH] --input PATH [--setting PATH --output PATH | --directory PATH] [--expect-duration SEC] [--expect-codec CODEC] [--expect-resolution WxH] [--expect-color-primaries TAG] [--verify-decode] [--execute]
video-export compressor status --batch-id ID

video-export pipeline run [--profile PATH] --project NAME --timeline NAME [--preset NAME] [--output PATH] [--reuse-master] [--headless] [--verify-decode] [--execute]
```

### 3.2 Machine-readable stdout contract
Every subcommand prints exactly one JSON object to stdout (`--help` excepted):

```json
{
  "ok": true,
  "command": "pipeline.run",
  "mode": "plan",
  "manifest_path": "/path/to/state/runs/20261024T180000Z_a1b2c3/manifest.json",
  "data": {
    "execute": false,
    "resolve": {
      "project": "Demo Project",
      "timeline": "Main Edit",
      "preset": "ProRes_Master",
      "output": "/path/to/exports/master.mov",
      "reuse_master": false
    },
    "compressor": {
      "targets": [
        {
          "setting": "/path/to/presets/web_1080p.compressorsetting",
          "suffix": "-1080p",
          "output": "/path/to/exports/master-1080p.mov"
        }
      ]
    }
  }
}
```

On error, `ok` is `false` and the payload includes `error` (machine code), `message`, and optional `details` (which may reference a private local log path, never auto-published).

## 4. DaVinci Resolve Studio Backend

### 4.1 Empirically verified Resolve Studio 21 facts
Local verification against DaVinci Resolve Studio 21 established the following ground truth:
- **External Python attach:** Works reliably when a child Python process sets:
  - `RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"`
  - `RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"`
  - `PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"`
  and imports `DaVinciResolveScript as dvr_script; resolve = dvr_script.scriptapp("Resolve")`.
- **Headless launch:** `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve -nogui` starts a headless Resolve Studio instance that accepts external Python scripting connections.
- **Verified read/inspection methods:**
  - `resolve.GetProjectManager()`
  - `project_manager.GetProjectListInCurrentFolder()`
  - `project_manager.GetCurrentProject()` and `project_manager.LoadProject(name)`
  - `project.GetTimelineCount()`, `project.GetTimelineByIndex(index)` (1-based indexing), `project.GetCurrentTimeline()`, `project.SetCurrentTimeline(timeline)`
  - `project.GetCurrentRenderFormatAndCodec()`
  - `project.GetRenderPresetList()`
- **Verified missing methods:**
  - `Project` objects have **no** `GetRenderSettings()` method and **no** `GetCurrentRenderPreset()` method. Consequently, once a script calls `LoadRenderPreset(name)` or `SetRenderSettings({...})`, it **cannot** read back and restore the full prior render configuration. Documentation and code must never claim to snapshot/restore all render settings.
  - There is **no proven dirty-state query** on an open project.
- **Documented render queue methods (planned for implementation & live verification):**
  - `project.LoadRenderPreset(preset_name)`
  - `project.SetRenderSettings({"SelectAllFrames": 1, "TargetDir": parent_dir, "CustomName": filename_stem})`
  - `job_id = project.AddRenderJob()`
  - `project.StartRendering([job_id])` (or `StartRendering(job_id)`)
  - `project.GetRenderJobStatus(job_id)` and `project.IsRenderingInProgress()`
- **Quick Export exclusion:** `Quick Export` presets appear in Resolve, but their mutability, blocking behavior, and metadata semantics under scripting are unverified. `video-export` must not claim Quick Export is safe and must use standard Deliver render presets only.
- **Headless shutdown hazard:** Sending `SIGTERM` to a running `Resolve -nogui` process triggers the macOS Crash Reporter dialog. Calling `resolve.Quit()` through the scripting API exits cleanly.

### 4.2 Conservative Resolve execution policy
1. **Attach by default, headless opt-in:** By default, `resolve` commands connect to an already running Resolve instance. If none is running, they return `resolve_not_running` unless `--headless` was explicitly passed.
2. **No silent GUI project switching:** When attached to a running GUI Resolve instance, `video-export` inspects `project_manager.GetCurrentProject().GetName()`. If a different project is currently loaded and its name is not `"Untitled Project"`, `video-export` refuses to call `LoadProject(requested_project)` and exits with `foreign_project_loaded`. The user must either open the target project in Resolve first or run in an isolated environment.
3. **No `SaveProject()`:** `video-export` never calls `SaveProject()` so temporary render preset/target changes are not silently persisted over the user's project state.
4. **Scoped render job ownership:** `resolve render --execute` captures the single `job_id` returned by `AddRenderJob()`, passes only that `job_id` to `StartRendering([job_id])`, polls `GetRenderJobStatus(job_id)`, and never calls `DeleteAllRenderJobs()` or `DeleteRenderJob()` on pre-existing jobs.
5. **Subprocess IPC with timeout:** Every Resolve scripting interaction runs inside a short-lived Python subprocess with a bounded timeout. If a call times out against an attached GUI Resolve, `video-export` kills only its own helper subprocess—**never** the Resolve application—and reports `resolve_ipc_timeout`. If `video-export` launched its own `--headless` Resolve instance, it shuts it down via `resolve.Quit()` and waits for clean process termination rather than sending `SIGTERM`.

## 5. Apple Compressor Backend

### 5.1 Empirically verified Compressor CLI facts
- **Executable:** `/Applications/Compressor.app/Contents/MacOS/Compressor`.
- **Batch submission command shape:**
  ```bash
  /Applications/Compressor.app/Contents/MacOS/Compressor \
    -batchname "video-export batch" \
    -priority medium \
    -jobpath "file:///path/to/input.mov" \
    -settingpath "/path/to/presets/web_1080p.compressorsetting" \
    -locationpath "/path/to/exports/input-1080p.mov" \
    -outputformat json
  ```
- **Critical Compressor behaviors:**
  1. **`-locationpath` requires a full filename:** Passing a directory fails with `Parameter error: Destination is a directory; Expected complete output file path with file name.`
  2. **Diagnostic text around JSON:** Compressor may emit non-JSON diagnostic lines (such as `fileURL is NOT a directory`) to stdout or stderr alongside `-outputformat json` or `-monitor -format json`. The parser must locate and parse the JSON object tolerantly while capturing raw output for error reporting.
  3. **Parameter order for `-monitor`:** `-format json` **must** immediately follow `-monitor`:
     ```bash
     /Applications/Compressor.app/Contents/MacOS/Compressor \
       -monitor \
       -format json \
       -batchid "BATCH_ID" \
       -once
     ```
     Placing `-format json` after `-once` fails with `Invalid parameter: -format`.
  4. **`batchID` means queued only:** A submission response containing `batchID` and `jobID` only confirms that the batch entered Compressor's queue.
  5. **Status semantics (`Waiting` vs terminal states):** `-monitor` reports statuses including `Waiting`, `Processing`, `Successful`, `Failed`, and `Cancelled`. `Waiting` (or `Processing` at `0%` while waiting for an available transcode service) is **not** a failure; polling must continue until a terminal status (`Successful`, `Failed`, or `Cancelled`) or explicit user timeout is reached.
  6. **Multiple targets sharing a single `jobID`:** When multiple `-jobpath` / `-settingpath` / `-locationpath` triples for the same source file are submitted in one batch, Compressor may return a single `jobID` that encompasses multiple targets. Completion verification must check every planned target output file rather than assuming one `jobID` per target.
  7. **`.compressorsetting` is custom XML, not plist:** Preset files use a custom `<setting>` XML root element (`plutil` rejects them). Furthermore, a preset's filename does not guarantee its output resolution: in `<video-encode>`, `bounds` attributes with width/height `-100` (or automatic flags) mean **follow source dimensions**. `compressor presets` parses the XML via `xml.etree.ElementTree` to report actual settings and whether resolution follows the source.
  8. **Non-disruptive operation:** `video-export` never runs `-resetBackgroundProcessing` and never cancels or pauses pre-existing batches.

## 6. Media Verification and Pipeline Gating

### 6.1 Pre-submission source validation (`compressor transcode --execute` and `pipeline run --execute`)
Before any file is submitted to Compressor:
1. **Positive Resolve status (pipeline mode):** If Resolve rendered the master in Stage 1, `GetRenderJobStatus(job_id)` must report completion (`JobStatus == "Complete"`, `CompletionPercentage == 100`). Any failed, cancelled, or incomplete status aborts the pipeline immediately.
2. **Open-writer check:** Run `lsof -- /path/to/source.mov` and verify that no process holds the file open for writing.
3. **Bounded file-stability check:** Sample `stat` (byte size > 0 and mtime) across a bounded interval (default e.g. two checks separated by a configurable stability window; injectable clock/sleeper in tests) and require identical non-zero byte size and mtime.
4. **Stream validation via `ffprobe`:** Run `ffprobe -v error -show_format -show_streams -of json /path/to/source.mov` and verify:
   - Valid container with at least one video stream and positive duration.
   - Expected duration (within tolerance), video codec, resolution (`width`x`height`), and color tags (`color_primaries`, `color_transfer`, `color_space`) whenever specified by the command or preset metadata.

### 6.2 Post-transcode output verification
After Compressor `-monitor` reports `Successful` for the batch:
1. Verify every target output path exists, has no open writer (`lsof`), and has a stable non-zero byte size (and no leftover `.sb-*` segment files).
2. Run `ffprobe` on each target output to confirm stream presence, duration agreement with the source file, and any expected codec/resolution/color tags.
3. **Optional full decode (`--verify-decode`):** When explicitly requested, run `ffmpeg -v error -i /path/to/target.mov -f null -` and require exit code 0 with empty stderr. Full decode is opt-in because decoding long high-resolution masters and targets is CPU/GPU-intensive.

## 7. Private Per-Run Manifest and Master Provenance

Each command execution writes a private manifest outside tracked git repositories (default `/path/to/state/video-export/runs/<run_id>/manifest.json` or `--state-dir`):

```json
{
  "run_id": "20261024T180000Z_a1b2c3",
  "created_at": "2026-10-24T18:00:00Z",
  "command": "pipeline.run",
  "execute": true,
  "config": {
    "profile_path": "/path/to/profile.toml",
    "project": "Demo Project",
    "timeline": "Main Edit",
    "resolve_preset": "ProRes_Master",
    "master_output": "/path/to/exports/master.mov",
    "keep_master": true
  },
  "resolve_job": {
    "job_id": "job_001",
    "status": "Complete",
    "verified": true,
    "size_bytes": 104857600,
    "mtime_ns": 1792864800000000000,
    "sha256": "0123456789abcdef..."
  },
  "compressor_batch": {
    "batch_id": "11111111-2222-3333-4444-555555555555",
    "job_ids": ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
    "status": "Successful",
    "targets": [
      {
        "setting": "/path/to/presets/web_1080p.compressorsetting",
        "output": "/path/to/exports/master-1080p.mov",
        "verified": true,
        "full_decode_verified": false
      }
    ]
  }
}
```

### Master reuse rule (`--reuse-master`)
In `pipeline run --reuse-master`, `video-export` skips the Resolve render stage **only** if a prior run manifest in the state directory records a completed, verified Resolve render for the exact same `project`, `timeline`, `resolve_preset`, and `master_output` path, and the file currently on disk matches the manifest's `size_bytes` and `sha256` (or `mtime_ns` + `size_bytes` when configured). If no matching manifest exists or the file on disk differs, `pipeline run` refuses reuse with `unverified_master_provenance`.
