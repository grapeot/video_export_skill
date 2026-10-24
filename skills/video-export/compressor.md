# Apple Compressor Transcode (`video-export compressor`)

> **Scaffold Status (2026-10-24):** This document specifies the planned `video-export compressor` subcommands and empirically verified Apple Compressor CLI behaviors.

Use this focused skill when inspecting `.compressorsetting` preset files, submitting standalone transcoding batches to Apple Compressor, or monitoring batch progress via `video-export compressor`.

## Done Means

- Source media was verified before submission: no process held the source file open for writing (`lsof`), byte size remained constant across the bounded stability window, and `ffprobe` confirmed valid streams.
- A dry-run plan was checked first (without `--execute`), confirming complete output file paths for all targets and zero file collisions.
- Under `--execute`, Compressor returned a `batchID`, `-monitor -format json -batchid <ID> -once` reached terminal status `Successful` (distinguished from queued `Waiting`/`Processing` and terminal `Failed`/`Cancelled`), and **every** planned target output file was verified on disk via `lsof`, byte-size stability, and `ffprobe` (duration, codec, resolution, and color tags when specified, plus optional `ffmpeg` full decode via `--verify-decode`).
- The per-run `manifest.json` recorded the `batchID`, `jobID`s, target paths, and verification outcomes.

## Empirically Verified Compressor Facts & Pitfalls

1. **CLI executable and submission flags:**
   - Binary: `/Applications/Compressor.app/Contents/MacOS/Compressor`
   - Submission shape:
     ```bash
     /Applications/Compressor.app/Contents/MacOS/Compressor \
       -batchname "video-export batch" \
       -priority medium \
       -jobpath "file:///path/to/input.mov" \
       -settingpath "/path/to/presets/web_1080p.compressorsetting" \
       -locationpath "/path/to/exports/input-1080p.mov" \
       -outputformat json
     ```
   - **`-locationpath` must be a full filename:** Passing a directory path fails with `Parameter error: Destination is a directory; Expected complete output file path with file name.` Always pass the complete output file path including filename and extension.
2. **Strict `-monitor` flag order:**
   - `-format json` **must** immediately follow `-monitor`:
     ```bash
     /Applications/Compressor.app/Contents/MacOS/Compressor \
       -monitor \
       -format json \
       -batchid "BATCH_ID" \
       -once
     ```
   - Placing `-format json` at the end (after `-once`) fails with `Invalid parameter: -format`.
3. **Diagnostic text around JSON output:**
   - Compressor frequently prints diagnostic lines (for example `fileURL is NOT a directory`) alongside JSON output on stdout/stderr even when submission succeeds. Never treat that line alone as a failure; extract the JSON object tolerantly and validate `batchID` and target completion.
4. **Queue semantics (`batchID` and `Waiting` vs terminal states):**
   - Receiving a `batchID` and `jobID` on submission means only that the batch was **queued**, not that transcoding has started or finished.
   - Monitor statuses include `Waiting`, `Processing`, `Successful`, `Failed`, and `Cancelled`. `Waiting` (or `Processing` at `0%` while waiting for an idle transcode service) is **not** a failure. Wait until the batch reaches `Successful` (or fails with `Failed`/`Cancelled`).
5. **Multiple targets can share a single `jobID`:**
   - When multiple `-jobpath` / `-settingpath` / `-locationpath` triples for the same source file are submitted in one batch, Compressor can merge them under a single `jobID`. Never assume one `jobID` per target; always verify each expected target output file on disk.
6. **`.compressorsetting` presets are custom XML, not plists:**
   - Preset files use a custom `<setting>` XML schema (`plutil` will fail on them).
   - **Preset names do not guarantee output resolution:** Inside `<video-encode>`, a `bounds` width/height value of `-100` (or automatic sizing) means **follow source dimensions**. Always inspect the XML via `video-export compressor presets` rather than guessing resolution from the filename.

## Mandatory Safety Rules

- **Never submit a still-writing source file:** Submitting a file while Resolve or another process is still writing it produces truncated outputs. `compressor transcode --execute` enforces `lsof` open-writer checks, bounded file-size stability, and `ffprobe` validation before calling Compressor.
- **Refuse output collisions and never delete sources:** If any target output path already exists, refuse the run. Never delete source media automatically.
- **Never reset services or cancel other jobs:** Do not run `Compressor -resetBackgroundProcessing` or `-kill` on existing batches without explicit user instruction.

## Planned Commands

```bash
# Check Compressor binary and ffprobe/ffmpeg availability
video-export compressor doctor

# Parse .compressorsetting XML (codec, frame rate, fixed vs -100 follow-source bounds)
video-export compressor presets \
  --setting /path/to/presets/web_1080p.compressorsetting \
  --setting /path/to/presets/archive_hevc.compressorsetting

# Dry-run transcode plan (single target via CLI flags, or multi-target via --profile)
video-export compressor transcode \
  --input /path/to/input.mov \
  --setting /path/to/presets/web_1080p.compressorsetting \
  --output /path/to/exports/input-1080p.mov

# Execute transcode after source stability + ffprobe checks, then monitor and verify outputs
video-export compressor transcode \
  [--profile /path/to/profile.toml] \
  --input /path/to/input.mov \
  [--expect-duration 120.5] \
  [--expect-codec hevc] \
  [--expect-resolution 1920x1080] \
  [--expect-color-primaries bt709] \
  [--verify-decode] \
  --execute

# Check status of an existing Compressor batch ID
video-export compressor status --batch-id "BATCH_ID"
```

## TOML Profile Keys Used by `compressor transcode`

```toml
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

Explicit CLI flags (`--setting`, `--output`, `--directory`) override TOML profile values.
