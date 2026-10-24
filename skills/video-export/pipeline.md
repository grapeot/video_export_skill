# Connected Resolve-to-Compressor Pipeline (`video-export pipeline`)

> **Scaffold Status (2026-10-24):** This document specifies the planned `video-export pipeline run` command and the verification gates that connect DaVinci Resolve Studio exports to Apple Compressor transcodes.

Use this focused skill when running an end-to-end workflow that exports a master timeline from DaVinci Resolve Studio, verifies the master file on disk, and submits it to Apple Compressor for one or more target transcodes. Also review [`./resolve.md`](resolve.md) and [`./compressor.md`](compressor.md) if you need backend-specific diagnostics.

## Done Means

1. **Dry-run plan verified first:** `video-export pipeline run` (without `--execute`) returned `ok: true`, showing the resolved Resolve project, timeline, preset, master output path, and all Compressor target settings and output paths with zero collisions.
2. **Stage 1 (Master Render or Provenance-Verified Reuse) succeeded:**
   - Either Resolve rendered the master timeline under `--execute` and reported positive job completion (`GetRenderJobStatus(job_id)` == `Complete`, `100%`), **or**
   - `--reuse-master` was passed and a prior per-run `manifest.json` proved provenance for the exact project, timeline, preset, and master output path, with matching on-disk file size and sha256.
3. **Stage 2 (Hand-Off Verification Gate) passed before Compressor submission:**
   - The master file had no open writer (`lsof`), maintained a stable non-zero byte size across the bounded stability window, and passed `ffprobe` validation (valid streams and expected duration/codec/resolution/color tags).
4. **Stage 3 (Compressor Batch & Target Verification) succeeded:**
   - Compressor `-monitor -format json -batchid <ID> -once` reached terminal status `Successful`, and every target output file defined in `[[compressor.targets]]` passed `lsof`, byte-size stability, and `ffprobe` verification (plus optional `ffmpeg -v error -i ... -f null -` full decode when `--verify-decode` was requested).
5. **Master retained and manifest finalized:** The master file remains on disk (`keep_master = true`), and the per-run `manifest.json` records all Resolve and Compressor identifiers, paths, and verification results.

## Pipeline Gating Rules

- **Strict failure gate between Resolve and Compressor:** Compressor must **never** be invoked if the Resolve render job fails, is cancelled, times out, or produces a file that fails the `lsof` open-writer check, bounded byte-size stability check, or `ffprobe` inspection.
- **Provenance required for master reuse:** Never trust an arbitrary file sitting at the master output path. If the master output path already exists on disk:
  - Without `--reuse-master`, `pipeline run` refuses with `output_collision`.
  - With `--reuse-master`, `pipeline run` checks the private run state directory for a prior `manifest.json` that positively verified that exact master file. If no matching manifest exists or the file's size/hash changed, `pipeline run` refuses with `unverified_master_provenance`.
- **No automatic deletion:** Neither source clips nor the rendered master file are ever deleted automatically after Compressor finishes.

## External TOML Profile Example

```toml
[resolve]
preset = "ProRes_Master"
output = "/path/to/exports/episode_master.mov"

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

With the profile above, a master exported to `/path/to/exports/episode_master.mov` produces Compressor targets `/path/to/exports/episode_master-1080p.mov` and `/path/to/exports/episode_master-hevc.mov`. Explicit CLI flags always override profile values.

## Planned Commands

```bash
# 1. Dry-run pipeline plan (validates TOML profile, CLI overrides, and output collisions)
video-export pipeline run \
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Main Edit"

# 2. Execute full pipeline (Resolve render -> stability + ffprobe gate -> Compressor transcode -> target verification)
video-export pipeline run \
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --execute

# 3. Override profile values on the CLI and enable optional full-decode verification
video-export pipeline run \
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Cut B" \
  --preset "Broadcast_ProRes" \
  --output /path/to/exports/cut_b_master.mov \
  --verify-decode \
  --execute

# 4. Reuse an already rendered master (only allowed when manifest proves provenance)
video-export pipeline run \
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Main Edit" \
  --reuse-master \
  --execute
```

## Pipeline Error Handling

| `error` | Stage | Meaning & Next Step |
|---|---|---|
| `config_invalid` | Preflight | Unknown key or invalid value in TOML profile (e.g., `keep_master = false`). Fix the TOML file. |
| `output_collision` | Preflight | Master or target output file already exists (and `--reuse-master` was not set). Choose new output paths or pass `--reuse-master` if retrying Compressor on a verified master. |
| `unverified_master_provenance` | Stage 1 | `--reuse-master` was passed, but no prior verified `manifest.json` matches the on-disk file's path, size, and hash. Render a fresh master to a new path instead. |
| `foreign_project_loaded` | Stage 1 | Attached GUI Resolve has a different non-`Untitled` project open. Ask the user to switch projects in Resolve. |
| `render_job_failed` / `source_unstable` / `ffprobe_failed` | Stage 1–2 | Resolve job did not complete cleanly or the rendered master failed `lsof`/stability/`ffprobe` checks. Compressor submission is skipped automatically; inspect `manifest.json`. |
| `compressor_batch_failed` / `target_verification_failed` | Stage 3–4 | Compressor batch ended in `Failed`/`Cancelled` or a target file failed post-transcode verification. Master remains intact; after fixing the preset or service issue, you can rerun with `--reuse-master` and non-colliding target paths. |
