# DaVinci Resolve Studio Export (`video-export resolve`)

> **Scaffold Status (2026-10-24):** This document specifies the planned `video-export resolve` subcommands and empirically verified DaVinci Resolve Studio 21 scripting rules.

Use this focused skill when inspecting DaVinci Resolve Studio projects, timelines, or render presets, or when exporting a master timeline via `video-export resolve`.

## Done Means

- `video-export resolve doctor` confirms Resolve Studio scripting modules (`RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`) and a reachable Resolve instance (or `--headless` capability).
- For inspection (`projects` / `inspect`), the target project and timeline names and available render presets are confirmed without silently switching away from a different open GUI project.
- For rendering (`render`), the dry-run plan was checked first, `--execute` started only the run's own `job_id`, `GetRenderJobStatus(job_id)` reached positive completion (`Complete`, `100%`), the output file passed bounded file-stability (`lsof` + stable non-zero size) and `ffprobe` checks (plus optional `--verify-decode`), and the per-run `manifest.json` recorded the result.

## Empirically Verified Resolve Studio 21 Facts & Constraints

1. **External scripting attach & headless mode:**
   - External Python scripts attach via `RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"`, `RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"`, and `PYTHONPATH="$RESOLVE_SCRIPT_API/Modules"`.
   - Headless mode launches via `/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve -nogui`.
2. **Available vs missing API methods:**
   - Verified working: `GetProjectManager()`, `GetProjectListInCurrentFolder()`, `LoadProject(name)`, `GetTimelineCount()`, `GetTimelineByIndex(idx)` (1-based), `GetCurrentRenderFormatAndCodec()`, `GetRenderPresetList()`.
   - Render queue methods: `AddRenderJob()`, `StartRendering([job_id])`, `GetRenderJobStatus(job_id)`.
   - **No settings readback:** Resolve's `Project` object has **no** `GetRenderSettings()` method and **no** `GetCurrentRenderPreset()` method. Loading a preset or setting a target directory/filename mutates the active render configuration in memory, and the tool **cannot** snapshot and restore all previous render settings. Never claim that prior render settings are restored.
   - **No dirty-state query:** Resolve provides no proven API method to check whether the currently open GUI project has unsaved changes.
   - **No Quick Export:** Although `Quick Export` presets appear in listings, their mutability, blocking behavior, and metadata semantics under scripting are unverified. Do not use `Quick Export` or claim it is safe; use standard Deliver render presets only.

## Mandatory Safety Rules

- **Attach by default; headless is opt-in:** Connect to an already running Resolve instance by default. Pass `--headless` only when Resolve is not running and headless execution is desired.
- **Refuse silent GUI project switches:** If attached to a running Resolve instance where a different project (other than `"Untitled Project"`) is currently open, `video-export` refuses to switch projects (`error: "foreign_project_loaded"`). Ask the user to switch projects in Resolve or authorize headless execution after closing Resolve.
- **Never call `SaveProject()`:** Do not persist temporary render target mutations into the user's project database.
- **Own-job isolation:** Start only the specific `job_id` returned by `AddRenderJob()` (`StartRendering([job_id])`). Never start or delete other jobs in the render queue.
- **Subprocess IPC timeout & clean headless shutdown:** Keep all Resolve scripting calls inside a child subprocess with a bounded timeout. Never auto-kill a user's running GUI Resolve on timeout. When shutting down an owned `--headless` Resolve instance, call `resolve.Quit()` via the scripting API rather than sending `SIGTERM` (sending `SIGTERM` triggers the macOS Crash Reporter dialog).
- **Refuse output collisions:** If `--output` (or `[resolve].output` from `--profile`) already exists, abort before adding a render job.

## Planned Commands

```bash
# Check Resolve scripting paths and running instance
video-export resolve doctor [--headless]

# List projects in current Resolve database folder and active project name
video-export resolve projects [--headless]

# Inspect timelines, current format/codec, and Deliver render presets
video-export resolve inspect --project "Demo Project" [--timeline "Main Edit"] [--headless]

# Dry-run render plan (no project mutation, no job queued)
video-export resolve render \
  [--profile /path/to/profile.toml] \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --preset "ProRes_Master" \
  --output /path/to/exports/episode_master.mov

# Execute render and verify output with lsof + stat stability + ffprobe
video-export resolve render \
  [--profile /path/to/profile.toml] \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --preset "ProRes_Master" \
  --output /path/to/exports/episode_master.mov \
  [--verify-decode] \
  --execute
```

## TOML Profile Keys Used by `resolve render`

```toml
[resolve]
preset = "ProRes_Master"
output = "/path/to/exports/episode_master.mov"

[outputs]
directory = "/path/to/exports"
keep_master = true
```

Explicit CLI flags (`--preset`, `--output`) always override the TOML profile values.

## Error Codes and Recovery

| `error` | Meaning | Next Step |
|---|---|---|
| `resolve_not_running` | No running Resolve instance found and `--headless` was not set. | Ask the user to open DaVinci Resolve Studio with the target project, or rerun with `--headless`. |
| `foreign_project_loaded` | Running Resolve has a different non-`Untitled` project open. | Do not force a switch. Ask the user to open the target project in Resolve first. |
| `timeline_not_found` / `preset_not_found` | Requested timeline or Deliver preset does not exist in the project. | Run `video-export resolve inspect --project NAME` and report the available timelines/presets. |
| `output_collision` | Planned output file already exists on disk. | Choose a new `--output` path; never delete or overwrite existing exports automatically. |
| `resolve_ipc_timeout` | Scripting call timed out inside the helper subprocess. | Do not kill GUI Resolve. Check whether Resolve is blocked by a modal dialog. |
| `render_job_failed` | `GetRenderJobStatus(job_id)` reported failure or cancellation, or verification failed. | Inspect the error details in `manifest.json` and do not proceed to downstream transcoding. |
