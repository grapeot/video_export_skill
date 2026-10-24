# Apple Compressor Transcode (`video-export compressor`)

Use this focused skill when inspecting `.compressorsetting` XML presets, submitting standalone transcoding batches to Apple Compressor, or checking batch status via `video-export compressor`.

## Done Means

- `video-export compressor doctor` confirms the Compressor binary (`/Applications/Compressor.app/Contents/MacOS/Compressor` or `VIDEO_EXPORT_COMPRESSOR`) and required helpers (`ffprobe`, `lsof`, and `ffmpeg` when `--verify-decode` is used).
- A dry-run plan (without `--execute`) validated the `.compressorsetting` XML files, recorded `max_frame_rate` if configured (without probing the source or creating derived preset files), resolved target output paths, and confirmed zero output path collisions.
- Under `--execute`, the input file passed `lsof`, `--stability-window`, and `ffprobe` checks prior to submission; any `--max-frame-rate` cap created private byte-preserving derived settings inside the run state directory (`prepared_targets`); Compressor returned a `batchID`; `-monitor -format json -batchid <ID> -once` reached `Successful` for that `batchID`; and **every** target output file passed `lsof`, `--stability-window`, and `ffprobe` checks (including duration matching the input within `0.1`s, preset/derived frame rate, any `--expect-*` checks including `--expect-frame-rate`, and optional `--verify-decode`).
- The per-run `manifest.json` path returned in stdout recorded `prepared_targets` (when applicable), the batch ID, monitor payload, and verified target media properties.

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
3. **`.compressorsetting` XML parsing & geometry:**
   - Presets are custom `<setting>` XML files (not Apple plists). `<frame-rate>` accepts decimal, rational, `R`-prefixed values such as `R60/1` and `R30000/1001` (where `float()` previously failed), and whitespace-padded follow-source sentinels.
   - `video-export compressor presets` reports `automatic_geometry` (`<automatic width="..." height="..."/>`) separately from `<bounds>`. A negative automatic width (such as `width="-1920"`) can encode automatic geometry (`resolution_mode: "automatic_geometry"`) even when `<bounds>` has `"-100"`. Never claim `follow_source` from `<bounds>` alone or infer actual dimensions from preset filenames.
   - If `--setting` is omitted on `compressor presets`, `video-export` discovers `.compressorsetting` files under `~/Library/Group Containers/*.com.apple.videoProApps/Library/Application Support/Compressor/Settings/*.compressorsetting`.
   - Execution checks each target's recognized codec, positive fixed bounds, and fixed frame rate (using `< 0.01` fps tolerance for rounded NTSC labels). Because `follow_source` or `automatic_geometry` presets may scale, crop, or pad, probe actual outputs with `ffprobe`; `--expect-resolution` is available when all targets share one known resolution, though a single shared `--expect-resolution` flag cannot assert distinct dimensions across mixed-resolution targets. Source duration must also satisfy `--expect-duration` before submission; outputs always match measured source duration.
4. **Cap-preserving frame-rate policy (`--max-frame-rate` / `[compressor] max_frame_rate`):**
   - Without `--max-frame-rate` (or `[compressor] max_frame_rate = 60`), presets behave exactly as before.
   - With `--max-frame-rate`, dry-run records `max_frame_rate` on each planned target and creates no derived presets or source probes.
   - Under `--execute`, `video-export` verifies the source first and treats `max_frame_rate` as a literal ceiling: it selects an explicit source-matched output rate when the source rate is at or below the cap, or repeatedly halves above-cap rates until they fit while preserving exact NTSC rationals (for cap `60`: `23.976`, `24`, `29.97`, `30`, `59.94`, and `60` remain themselves; `119.88` becomes `59.94` and `120` becomes `60`; a literal `59.94` cap on integer `60`/`120` selects `30` to preserve integer cadence while obeying the ceiling—do not equate `59.94` with `60`). This is a cap-preserving cadence policy, not forcing every output to `60` and not leaving `<frame-rate>` on blind `Automatic`.
   - `--execute` writes private `0o600` derived `.compressorsetting` files inside the run state directory (`delivery-<N>.compressorsetting`), changing **only** the single `<frame-rate>...</frame-rate>` text inside the sole `<video-encode>` element byte-for-byte (`R<num>/<den>`) and verifying the result via parsed XML readback, with no changes to `data-rate`, `auto-purpose`, `auto-bit-rate-purpose`, color, HDR, Dolby Vision, or geometry fields. Original presets are never overwritten. Derived setting paths and `delivery_frame_rate` are recorded in `prepared_targets` inside `manifest.json`. Do not equate raw XML `data-rate` values to measured output Mbps or claim that lowering frame rate halves bitrate.
5. **Handling `Failed: 2x job controller down` in long CLI batches:**
   - Long CLI-only Compressor batches can fail with `Failed: 2x job controller down` when `CompressorHelper` exits and its `JobControllerService` is terminated during active work (visible in macOS unified logs).
   - Keeping the `Compressor.app` GUI open and repeating the batch with the identical media, codecs, frame rate, and bitrate/Dolby Vision settings succeeded in live production testing (an observed recovery, not a proven universal root cause; `video-export` CLI does not auto-launch the GUI).
   - On this error, inspect the batch status and unified logs, preserve the verified master file, leave existing queues and preset files untouched, **never** run `-resetBackgroundProcessing` or mass-cancel jobs, optionally open or keep `Compressor.app` running, and retry only terminal failed jobs when their output destination files are still absent.

## Commands

```bash
# Check Compressor executable and ffprobe/ffmpeg/lsof paths
video-export compressor doctor [--timeout 3600]

# Inspect explicit or auto-discovered .compressorsetting XML files
video-export compressor presets \
  [--setting /path/to/presets/web_1080p.compressorsetting] \
  [--setting /path/to/presets/archive_hevc.compressorsetting]

# Dry-run transcode plan (validates XML and output collisions; creates no manifest or derived presets)
video-export compressor transcode \
  --input /path/to/input.mov \
  --setting /path/to/presets/web_1080p.compressorsetting \
  --output /path/to/exports/input-1080p.mov \
  [--max-frame-rate 60]

# Execute single- or multi-target transcode and verify all outputs
video-export compressor transcode \
  [--profile /path/to/profile.toml] \
  --input /path/to/input.mov \
  [--setting /path/to/presets/web_1080p.compressorsetting] \
  [--output /path/to/exports/input-1080p.mov] \
  [--directory /path/to/exports] \
  [--max-frame-rate 60] \
  [--state-dir /path/to/state] \
  [--stability-window 2] \
  [--poll 5] \
  [--expect-duration 120.0] \
  [--expect-frame-rate 59.94] \
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

[compressor]
# Optional cap-preserving cadence ceiling:
# max_frame_rate = 60

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
