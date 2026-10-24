# DaVinci Resolve Studio Export (`video-export resolve`)

Use this focused skill when inspecting DaVinci Resolve Studio projects, timelines, or Deliver presets, or when rendering a master timeline via `video-export resolve`.

## Done Means

- `video-export resolve doctor` confirms a reachable Resolve Studio instance (or launches `--headless` cleanly) and reports product, version, and current database.
- For inspection (`projects` / `inspect`), the target project (in the current database folder), timeline name, and Deliver preset name are confirmed without switching away from a different open named project.
- For rendering (`render`), the dry-run plan was checked first, `--execute` started only the run's own `job_id` in single-clip full-timeline Deliver mode, `GetRenderJobStatus(job_id)` reached `Complete` with matching queue `OutputFilename`, the output file passed `lsof` + `--stability-window` + `ffprobe` duration/stream checks (plus optional `--expect-*` and `--verify-decode`), and the per-run `manifest.json` recorded the result.

## Verified Resolve Studio Behavior & Constraints

1. **Subprocess worker isolation & headless mode:**
   - `video-export` runs Resolve API calls in an isolated child worker (`video_export.resolve_worker`) using a temporary result file so native `fusionscript.so` stdout noise never corrupts the CLI's single-JSON output.
   - Environment defaults to `RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"` and `RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"` (overridable via `VIDEO_EXPORT_RESOLVE_API`, `VIDEO_EXPORT_RESOLVE_LIB`, `VIDEO_EXPORT_RESOLVE_APP`).
   - `--headless` launches `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve -nogui` when Resolve is not running, and calls `resolve.Quit()` on completion when no render is in progress.
2. **Project loading & folder scope:**
   - `resolve projects` lists projects and folders in the **current Resolve database folder only** (`GetProjectListInCurrentFolder`, `GetFolderListInCurrentFolder`); it does not recursively traverse database folders.
   - `resolve inspect [--project NAME]` and `resolve render` may call `LoadProject(NAME)` **only** when no project is open, when `"Untitled Project"` is open, or when running an owned `--headless` instance. If a different named project is open in an attached GUI session, `video-export` raises `foreign_project_loaded`.
3. **Render settings mutation & Live Save:**
   - Dry-run (`resolve render` without `--execute`) checks configuration and output path collisions locally without connecting to Resolve; it does not verify that the project, timeline, or preset exists in Resolve.
   - During `resolve render --execute`, the worker calls `SetCurrentTimeline`, `LoadRenderPreset`, `SetCurrentRenderMode(1)` (single clip), optional `SetCurrentRenderFormatAndCodec(format, codec)`, and `SetRenderSettings({"SelectAllFrames": True, "TargetDir": ..., "CustomName": ..., "ExportVideo": True, "ExportAudio": True})`.
   - Resolve's API provides **no** `GetRenderSettings()` or `GetCurrentRenderPreset()` method and **no** dirty-state query. Active render settings remain changed in memory and are **not** restored. `video-export` never calls `SaveProject()`, but if the user has Resolve **Live Save** enabled, Resolve may persist these render setting changes.
   - `format` and `codec` are optional explicit overrides and must be supplied together; the `--output` extension must match the active render format (`output_invalid` otherwise).
   - Resolve may coerce timeline dimensions (for example, minimum `256x256` on tiny scratch timelines); always rely on `resolve inspect` and `ffprobe` for actual dimensions rather than assuming input clip dimensions.
   - `Quick Export` is neither tested nor used; only standard Deliver queue presets are supported.

## Commands

```bash
# Check Resolve connection, product version, and current database
video-export resolve doctor [--timeout 3600] [--headless]

# List projects and folders in the current Resolve database folder
video-export resolve projects [--timeout 3600] [--headless]

# Inspect timelines (fps, frames, duration, width, height), Deliver presets, format/codec, and queue jobs
video-export resolve inspect [--project "Demo Project"] [--timeout 3600] [--headless]

# Dry-run render plan (local config + path collision check only; does not connect to Resolve)
video-export resolve render \
  [--profile /path/to/profile.toml] \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --preset "ProRes_Master" \
  --output /path/to/exports/episode_master.mov \
  [--format mov --codec ProRes422HQ]

# Execute render, write manifest + checkpoint, and verify output
video-export resolve render \
  [--profile /path/to/profile.toml] \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --preset "ProRes_Master" \
  --output /path/to/exports/episode_master.mov \
  [--format mov --codec ProRes422HQ] \
  [--headless] \
  [--state-dir /path/to/state] \
  [--stability-window 2] \
  [--expect-duration 120.0] \
  [--expect-codec prores] \
  [--expect-resolution 1920x1080] \
  [--expect-color-primaries bt709] \
  [--expect-color-transfer bt709] \
  [--expect-color-space bt709] \
  [--verify-decode] \
  [--timeout 3600] \
  --execute
```

## TOML Profile Keys Used by `resolve render`

```toml
[resolve]
project = "Demo Project"
timeline = "Main Edit"
preset = "ProRes_Master"
output = "/path/to/exports/episode_master.mov"
# Optional explicit overrides (must be provided together):
# format = "mov"
# codec = "ProRes422HQ"
```

Explicit CLI flags override `[resolve]` keys in the TOML profile.

## Error Codes and Recovery

| `error` | Meaning | Next Step |
|---|---|---|
| `resolve_not_running` / `resolve_not_ready` | Resolve is not running (without `--headless`), or is running with external scripting disabled/blocked. | Open Resolve and enable Local external scripting in Preferences, or pass `--headless` when Resolve is closed. |
| `foreign_project_loaded` | Attached GUI Resolve has a different non-`Untitled Project` open. | Ask the user to switch to the target project in Resolve first. |
| `project_not_found` / `timeline_not_found` / `preset_not_found` | Requested project (in current folder), unique timeline, or Deliver preset was not found. | Run `video-export resolve projects` or `video-export resolve inspect --project NAME` to check exact names. |
| `resolve_busy` | Resolve is already rendering a job. | Wait for the active render to finish before starting a new run. |
| `output_invalid` / `output_collision` / `output_name_mismatch` | Output extension does not match selected format, file already exists, or preset forced a different filename. | Fix the `--output` extension/path or inspect the preset's filename settings. |
| `resolve_render_timeout` / `resolve_ipc_timeout` | Render or worker exceeded `--timeout`; active render and Resolve application are left running. | Check `manifest.json` and `resolve-job.json` in the state directory to inspect the running `job_id`. |
| `render_job_failed` | `GetRenderJobStatus(job_id)` reported `Failed` or `Cancelled`. | Inspect `details` and `manifest` in the error JSON. |
