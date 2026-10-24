# Connected Resolve-to-Compressor Pipeline (`video-export pipeline`)

Use this focused skill when running an end-to-end workflow that renders a master timeline in DaVinci Resolve Studio (or reuses a manifest-verified master), verifies the master file on disk, and submits it to Apple Compressor for one or more target transcodes. See [`./resolve.md`](resolve.md) and [`./compressor.md`](compressor.md) for backend details.

## Done Means

1. **Dry-run plan verified first:** `video-export pipeline run` (without `--execute`) returned `ok: true` and `dry_run: true`, showing the resolved Resolve configuration, all Compressor targets, and zero output path collisions (note: dry-run does not connect to Resolve or write a manifest).
2. **Master stage succeeded:**
   - Either Resolve rendered the master timeline under `--execute`, reached `JobStatus == "Complete"`, and passed `lsof`, `--stability-window`, and `ffprobe` verification (including duration matching the Resolve timeline duration within `0.1`s), **or**
   - `--reuse-master /path/to/prior/manifest.json` was passed, matching the full Resolve configuration identity and the master file's on-disk metadata fingerprint (`path`, `size`, `mtime_ns`), and the master file passed a fresh `verify()` check on disk.
3. **Compressor stage succeeded:**
   - Compressor re-verified the master as a stable input source, submitted the batch, reached terminal status `Successful` for the batch ID, and verified every target output file via `lsof`, `--stability-window`, and `ffprobe` (duration matching the master within `0.1`s, plus any `--expect-*` delivery checks and optional `--verify-decode`).
4. **Master retained and manifest saved:** Both the master file and all target files remain on disk, and the new run's `manifest.json` path is returned in stdout.

## Pipeline Rules & Caveats

- **Preflight collision check:** Before rendering or transcoding, `pipeline run` verifies that all target output paths (and the master output path, unless `--reuse-master MANIFEST` is used) do not exist and do not collide with each other or the master path.
- **Strict failure gate:** If the Resolve render fails, times out, or fails `lsof` / stability / `ffprobe` verification, Compressor is never invoked.
- **`--reuse-master MANIFEST` provenance is metadata-based:**
  - `--reuse-master` requires an **explicit path** to a prior `manifest.json` (not a boolean flag).
  - It checks that the prior manifest has `master.verified == true`, the exact same Resolve config `identity` (`project`, `timeline`, `preset`, `output`, and optional `format`/`codec`), and the same file metadata `fingerprint` (`path`, `size`, `mtime_ns`).
  - This metadata check avoids hashing multi-gigabyte masters on retry, but it is **not** a SHA-256 content hash and **cannot** detect whether you edited the timeline inside DaVinci Resolve. Always run a fresh render (without `--reuse-master`) after editing your Resolve project.
- **Meaning of `--output` and `--expect-*` in `pipeline run`:**
  - In `pipeline run`, `--output` overrides `[resolve].output` (the **master** file path). Target paths come from `[[compressor.targets]]` (`output` or `suffix` + `--directory` / `[outputs].directory`), or from repeating `--setting` on the CLI.
  - In `pipeline run`, `--expect-*` flags validate the **Compressor delivery targets** (the master is automatically checked against the Resolve timeline duration). To check `--expect-*` on a master directly, run `video-export resolve render`.

## External TOML Profile Example

```toml
[resolve]
project = "Demo Project"
timeline = "Main Edit"
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

## Commands

```bash
# 1. Dry-run pipeline plan (validates TOML, preset XML, and output collisions; no Resolve connection)
video-export pipeline run \
  --profile /path/to/profile.toml

# 2. Execute full pipeline (Resolve master render -> verification gate -> Compressor targets)
video-export pipeline run \
  --profile /path/to/profile.toml \
  [--headless] \
  [--verify-decode] \
  --execute

# 3. Override Resolve settings and delivery expectations on the CLI
video-export pipeline run \
  --profile /path/to/profile.toml \
  --project "Demo Project" \
  --timeline "Cut B" \
  --preset "Broadcast_ProRes" \
  --output /path/to/exports/cut_b_master.mov \
  --expect-codec hevc \
  --expect-resolution 1920x1080 \
  --verify-decode \
  --execute

# 4. Reuse a previously verified master by passing its explicit prior manifest.json path
video-export pipeline run \
  --profile /path/to/profile.toml \
  --reuse-master /path/to/state/video-export/PRIOR_RUN_ID/manifest.json \
  --execute
```

## Pipeline Error Handling

| `error` | Stage | Meaning & Next Step |
|---|---|---|
| `config_invalid` | Preflight | Invalid/missing TOML key, `keep_master = false`, or `format`/`codec` not supplied together. |
| `output_collision` | Preflight | Master or target output path already exists on disk (or duplicates another path). Choose unused output paths, or pass `--reuse-master /path/to/manifest.json` if reusing an existing master with new target paths. |
| `unverified_master_provenance` | Master reuse | Prior `manifest.json` is missing/invalid, Resolve config options changed, or the master file's `path`/`size`/`mtime_ns` changed. Render a fresh master. |
| `foreign_project_loaded` | Resolve | Attached GUI Resolve has another named project open. Switch projects in Resolve first. |
| `render_job_failed` / `source_unstable` / `media_invalid` / `media_mismatch` | Master / Gate | Resolve job failed or master failed `lsof`/stability/`ffprobe` verification. Compressor was not called; inspect `manifest.json`. |
| `compressor_batch_failed` / `compressor_timeout` | Compressor | Compressor batch failed or timed out. The verified master remains on disk and its `manifest.json` can be passed to `--reuse-master` once target paths/settings are adjusted. |
