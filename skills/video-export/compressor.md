# Apple Compressor Transcode (`video-export compressor`)

Use this focused skill when inspecting `.compressorsetting` XML presets, submitting standalone transcoding batches to Apple Compressor, or checking batch status via `video-export compressor`.

## Done Means

- `video-export compressor doctor` confirms the Compressor binary (`/Applications/Compressor.app/Contents/MacOS/Compressor` or `VIDEO_EXPORT_COMPRESSOR`) and required helpers (`ffprobe`, `lsof`, and `ffmpeg` when `--verify-decode` is used).
- A dry-run plan (without `--execute`) validated the `.compressorsetting` XML files, resolved target output paths, and confirmed zero output path collisions.
- Under `--execute`, the input file passed `lsof`, `--stability-window`, and `ffprobe` checks prior to submission; Compressor returned a `batchID`; `-monitor -format json -batchid <ID> -once` reached `Successful` for that `batchID`; and **every** target output file passed `lsof`, `--stability-window`, and `ffprobe` checks (including duration matching the input within `0.1`s, any `--expect-*` checks, and optional `--verify-decode`).
- The per-run `manifest.json` path returned in stdout recorded the batch ID, monitor payload, and verified target media properties.

## Verified Compressor Behavior & Constraints

1. **Submission & monitor flag order:**
   - Submits batches via `/Applications/Compressor.app/Contents/MacOS/Compressor -batchname video-export -priority medium -jobpath file:///path/to/input.mov -settingpath /path/to/preset.compressorsetting -locationpath /path/to/output.mov -outputformat json`.
   - `-locationpath` must be a complete file path whose extension matches the preset's `<file-extension>`.
   - Queries status via `Compressor -monitor -format json -batchid <ID> -once` (`-format json` must immediately follow `-monitor`).
   - Extracts JSON tolerantly (`noisy_json`) when Compressor prints diagnostic lines around the JSON payload.
2. **Scoped queue polling & shared `jobID`s:**
   - Submission only queues the batch. `batch_status()` matches the specific `batchID` and continues polling every `--poll` seconds while status is `Waiting` or `Processing`, never mistaking another batch's status or a child job status for batch completion.
   - Multi-target batches can share a single `jobID`, so `video-export` verifies every target output file on disk after the batch reaches `Successful`.
   - On `--timeout`, the active Compressor batch is not cancelled (`compressor_timeout`); its `batch_id` is retained in `manifest.json` and can be checked with `video-export compressor status --batch-id ID`.
3. **`.compressorsetting` XML parsing:**
   - Presets are custom `<setting>` XML files (not Apple plists).
   - Inside `<video-encode>`, `<bounds>` width or height set to `"-100"` means `resolution_mode: "follow_source"` rather than fixed dimensions. Always inspect presets with `video-export compressor presets` instead of inferring dimensions from preset filenames.
    - If `--setting` is omitted on `compressor presets`, `video-export` discovers `.compressorsetting` files under `~/Library/Group Containers/*.com.apple.videoProApps/Library/Application Support/Compressor/Settings/*.compressorsetting`.
    - Execution checks each target's recognized codec, positive fixed bounds, and fixed frame rate. Follow-source bounds are not enough to infer final dimensions when transforms are involved; use `--expect-resolution` when dimensions are required. Source duration must also satisfy `--expect-duration` before submission; outputs always match measured source duration.

## Commands

```bash
# Check Compressor executable and ffprobe/ffmpeg/lsof paths
video-export compressor doctor [--timeout 3600]

# Inspect explicit or auto-discovered .compressorsetting XML files
video-export compressor presets \
  [--setting /path/to/presets/web_1080p.compressorsetting] \
  [--setting /path/to/presets/archive_hevc.compressorsetting]

# Dry-run transcode plan (validates XML and output collisions; creates no manifest)
video-export compressor transcode \
  --input /path/to/input.mov \
  --setting /path/to/presets/web_1080p.compressorsetting \
  --output /path/to/exports/input-1080p.mov

# Execute single- or multi-target transcode and verify all outputs
video-export compressor transcode \
  [--profile /path/to/profile.toml] \
  --input /path/to/input.mov \
  [--setting /path/to/presets/web_1080p.compressorsetting] \
  [--output /path/to/exports/input-1080p.mov] \
  [--directory /path/to/exports] \
  [--state-dir /path/to/state] \
  [--stability-window 2] \
  [--poll 5] \
  [--expect-duration 120.0] \
  [--expect-codec hevc] \
  [--expect-resolution 1920x1080] \
  [--expect-color-primaries bt709] \
  [--expect-color-transfer bt709] \
  [--expect-color-space bt709] \
  [--verify-decode] \
  [--timeout 3600] \
  --execute

# Query status of a submitted Compressor batch
video-export compressor status --batch-id "BATCH_ID" [--timeout 3600]
```

## TOML Profile Keys & Target Resolution Rules

```toml
[outputs]
directory = "/path/to/exports"
keep_master = true

[[compressor.targets]]
setting = "/path/to/presets/web_1080p.compressorsetting"
suffix = "-1080p"

[[compressor.targets]]
setting = "/path/to/presets/archive_hevc.compressorsetting"
output = "/path/to/exports/custom_archive.mov"
```

- Repeating `--setting` on the CLI overrides `[[compressor.targets]]` from `--profile` with generated suffixes `-1`, `-2`, etc.
- `--output` on `compressor transcode` is valid only when there is a single target (`config_invalid` if multiple targets exist).
- Target path precedence: CLI `--output` (single target) -> `target.output` -> `<base>/<input_stem><suffix>.<preset_extension>`, where `<base>` is `--directory` -> `[outputs].directory` -> `input.parent`.
