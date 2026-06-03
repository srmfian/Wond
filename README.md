# Wond

Wond is a local-first personal context system. It writes daily Mac activity, file content, mobile recordings, locations, and photo/media analysis into a local SQLite database, then produces daily reports, long-term summaries, email digests, and operational views through the dashboard, doctor, and sync service.

Wond defaults to local AI. Text and vision models run through Ollama, and speech transcription runs through MLX Audio. OpenAI configuration is still available as an optional backend, but the primary path does not depend on OpenAI.

## Main Capabilities

- Mac context capture: calendars, reminders, browser history, recent files, foreground apps, mail metadata, photo/media clues, and related signals.
- File and media analysis: scans new files in configured directories, analyzes documents, images, audio, and video, and writes results back into the database.
- Audio processing: transcribes recordings with local ASR, produces summaries, speaker clues, and `no_speech` markers, and can delete source audio after successful processing.
- Mobile capture: iPhone can record audio, add bookmarks, create quick tags, record location, and upload encrypted sync packages to the Mac. Apple Watch recording support has been removed; the watchOS target now keeps only a placeholder companion.
- Mobile Q&A: iPhone can call the Wond sync server for local search and question answering. Answers and citations are still generated from the Mac's local index and models.
- Address-level location: mobile capture stores reverse-geocoded address fields, not just latitude and longitude.
- Reports and search: daily reports, long-term summaries, email summaries, full-text search indexes, and a local dashboard.
- Operational diagnostics: `doctor`, `status`, `dashboard`, and the sync server `/health` endpoint help inspect the current runtime state.

## Quick Start

### Installer Package

Download `Wond-0.3.0-macos.zip` from the GitHub release, unzip it, and double-click `install.command`.

The installer prefers `/Applications/Wond`, creates a private Python virtual environment, initializes `config.json`, and can optionally load LaunchAgents for the dashboard, sync server, and background monitor. If this Mac already has an older `~/Applications/Wond` install, the installer reuses that directory and tries to create an entry point at `/Applications/Wond`. If the current user cannot write to `/Applications/Wond`, it falls back to `~/Applications/Wond`. Reinstalling preserves the existing `config.json`, `.venv/`, and `data/`.

To choose a custom install directory:

```bash
WOND_INSTALL_DIR=/path/to/Wond ./install.command
```

Common commands after installation:

- `/Applications/Wond/Start Wond Dashboard.command`
- `/Applications/Wond/Install Wond Services.command`
- `/Applications/Wond/Run Wond Doctor.command`

If the installer reports that it used a legacy or fallback directory, these commands will be under `~/Applications/Wond/` instead.

### Update Package

Existing Wond users do not need to run the full installer again. Download `Wond-0.3.0-macos-update.zip` from the GitHub release, unzip it, and double-click `Update Wond.command`.

The update package replaces only Wond-managed application files and command entry points, while reusing the current install directory. It does not replace `config.json`, `data/`, local databases, reports, mobile sync imports, speaker samples, or model caches. The existing `.venv` is reused; if dependencies changed, the updater may refresh dependency metadata in that virtual environment.

The updater automatically checks `/Applications/Wond` and the older `~/Applications/Wond` location. If Wond is installed somewhere else:

```bash
WOND_INSTALL_DIR=/path/to/Wond "./Update Wond.command"
```

After the update finishes, any previously installed dashboard, sync server, or monitor LaunchAgents are automatically reloaded.

### Run From Source

```bash
python3 -m wond init
python3 -m wond collect
python3 -m wond summarize
```

The base install declares the Python dependencies needed for the dashboard, sync encryption, and SQLite workflows. Local audio models and speaker tooling are optional extras:

```bash
python3 -m pip install -e ".[local-audio,speaker]"
python3 -m pip install -e ".[eval]"  # only for tools/evaluate_wespeaker_resnet34.py
```

Common health checks:

```bash
python3 -m wond status
python3 -m wond doctor
python3 -m wond dashboard --open
```

`python3 -m wond` is the current entry point. Python modules, LaunchAgent labels, and mobile sync identifiers under the old project name have been removed.

Common background service commands:

```bash
python3 -m wond install-agent --load
python3 -m wond install-sync-agent --load
python3 -m wond install-dashboard-agent --load
python3 -m wond monitor --once
```

The sync server can also be started manually:

```bash
python3 -m wond sync-server
```

The default dashboard URL is `http://127.0.0.1:8787`, and the mobile sync service listens on `0.0.0.0:8765` by default. It is best to keep iPhone-to-Mac sync traffic inside a private Tailscale VPN instead of exposing `8765` to the public internet or forwarding it through a router.

Recommended iPhone sync URL:

```text
http://<mac-tailscale-ip-or-magicdns-name>:8765/upload
```

Examples:

```text
http://100.x.y.z:8765/upload
http://macbook-name.tailnet-name.ts.net:8765/upload
```

On the same Wi-Fi/LAN, `http://<mac-lan-ip>:8765/upload` can be used temporarily, but Tailscale is recommended for long-term use. Binding to `0.0.0.0` lets the sync server accept connections on the Tailscale interface. To allow only Tailscale access, set `mobile_sync.host` to the Mac's Tailscale IP.

## Data Directory

By default, Wond stores runtime data under `data/`:

- `data/wond.sqlite3`: main database.
- `data/reports/`: daily reports and mobile import reports.
- `data/summaries/`: long-term summaries and compact outputs.
- `data/mobile_sync/inbox/`: landing directory for mobile sync packages.
- `data/mobile_sync/imports/`: unpacked mobile media and imported content.
- `data/file_analysis_workspace/`: working copies for user-directory file analysis; source files are not moved.
- `data/recycle_bin/`: mobile cleanup files and file-analysis working copies go here before purge.
- `data/speaker_samples/`: samples saved for speaker review.
- `data/search_index/`: full-text search index.

`config.json` is the real configuration for the current machine, while `config.example.json` is a template. Before committing or sharing configuration, check for tokens, email addresses, model paths, and local directories.

## Configuration Highlights

Core fields:

```json
{
  "data_dir": "data",
  "timezone": "Asia/Tokyo",
  "watch_paths": ["~/Desktop", "~/Documents", "~/Downloads"],
  "collectors": {
    "foreground_app": true,
    "calendar": true,
    "reminders": true,
    "browsers": true,
    "recent_files": true,
    "messages": true,
    "apple_mail": true,
    "photo_locations": true
  },
  "ai_backend": {
    "provider": "local"
  }
}
```

Common local AI fields:

```json
{
  "local_ai": {
    "ollama_base_url": "http://127.0.0.1:11434",
    "text_model": "qwen3.5:35b",
    "vision_model": "qwen3.5:35b",
    "search_embedding_candidates": [
      "bge-m3:latest",
      "bge-m3",
      "qwen3-embedding:4b"
    ],
    "transcription_backend": "mlx_audio",
    "transcription_model": "mlx-community/Qwen3-ASR-1.7B-8bit",
    "speaker_diarization_enabled": true,
    "speaker_diarization_backend": "vibevoice_mlx",
    "speaker_diarization_model": "mlx-community/VibeVoice-ASR-4bit",
    "vad_presegment": true,
    "vad_presegment_diarization": true,
    "diarization_vad_max_chunk_seconds": 120,
    "diarization_vad_max_chunks": 32
  }
}
```

Common audio preprocessing fields:

```json
{
  "audio_preprocessing": {
    "enabled": true,
    "asr_enabled": true,
    "diarization_enabled": true,
    "speaker_samples_enabled": true,
    "speech_filter": "highpass=f=80,lowpass=f=7800,afftdn=nf=-25,dynaudnorm=f=150:g=15,loudnorm=I=-18:TP=-1.5:LRA=11",
    "overlap_separation_enabled": true,
    "overlap_separation_backend": "speechbrain_sepformer",
    "overlap_separation_fallback_enabled": true,
    "overlap_separation_fallback_backend": "ffmpeg_bandpass",
    "overlap_sepformer_model": "speechbrain/sepformer-whamr16k",
    "overlap_sepformer_model_dir": "models/speechbrain_sepformer",
    "overlap_create_new_speakers": false
  }
}
```

If Hugging Face or MLX model directories are moved to an external drive or redirected, make sure the background LaunchAgents can see the same paths. If the external drive is not mounted, `HF_HOME` differs, or a symlink is broken, audio analysis may slow down, fail, or download models again.

Main transcription defaults to the faster `mlx_audio` / Qwen3 ASR path. Speaker labeling is a separate helper stage that prefers `vibevoice_mlx` / `mlx-community/VibeVoice-ASR-4bit` to assign Speaker 1 / Speaker 2 labels to speech windows only. If VibeVoice fails or times out, the main transcript is preserved and the audio remains in a repairable speaker state.

ASR, diarization, and speaker samples prefer enhanced temporary audio. Original audio is kept for repair windows and audit. Overlapping speech is marked as overlap; Wond first tries SpeechBrain SepFormer to generate candidate stems, then accepts them only after volume, duration, clipping, and other quality gates. If SepFormer is unavailable, Wond falls back to `ffmpeg_bandpass`. By default, overlap candidates do not create brand-new speakers by themselves, which avoids polluting the voice library. If you integrate another external separator, you can enable `overlap_create_new_speakers` or configure `overlap_separation_command`.

## Dashboard And Doctor

The dashboard is the daily operating surface:

```bash
python3 -m wond dashboard --open
python3 -m wond install-dashboard-agent --load
```

It is organized around the main workspaces: Today, Daily Workbench, Projects, Audio, Sources, Search, and Setup. Action Inbox, project memory, Meeting Mode, Speaker Training, Privacy & Retention, mobile sync, Doctor, and record maintenance remain as subpages under the relevant workspaces. Old hash links still open directly.

Doctor is the command-line diagnostic entry point:

```bash
python3 -m wond doctor
```

It checks collectors, sync server, local AI, audio tools, chat sources, and data directories. If background tasks behave unexpectedly, start with:

```bash
python3 -m wond status
python3 -m wond doctor
```

## File, Media, And Audio Analysis

Scan new files:

```bash
python3 -m wond analyze-new-files
```

Process imported mobile audio:

```bash
python3 -m wond analyze-audio
python3 -m wond analyze-audio --date today --limit 20
python3 -m wond analyze-audio --force
```

Analyze an image, video, or other media file:

```bash
python3 -m wond analyze-media /path/to/file
```

Automatic new-file analysis does not move source files from user directories such as `Desktop`, `Documents`, or `Downloads`. It first copies a working file to `data/file_analysis_workspace/`, analyzes that copy, and later recycles only the copy. Imported media under `data/mobile_sync/` can delete the source file only when `mobile_sync.delete_audio_after_analysis` is enabled.

Mobile audio is transcribed and processed for speaker labels before the source file is deleted. If transcription finds speech segments but no speaker labels, Wond records `speaker_processing.status=skipped_no_speaker_labels` and keeps the original audio for `mobile_sync.delete_audio_after_analysis_repair_window_hours`, so it can later be rerun with a better diarization model or used to repair samples.

Recycle bin commands:

```bash
python3 -m wond recycle-bin list
python3 -m wond recycle-bin restore <trash-path>
python3 -m wond recycle-bin purge
```

Short recordings, silent clips, and clips without useful speech are marked as `no_speech`. This is not an error; it means ASR did not detect usable text.

## iPhone Capture And Watch Placeholder

The iOS project is at `ios/Wond/Wond.xcodeproj`.

The current capture entry point is the iPhone app:

- iPhone can record continuous segmented audio, add bookmarks, create quick tags, record location, show sync status, and upload encrypted packages with background URLSession.
- iPhone can ask the Mac local search/Q&A service from the Ask page, using the same sync URL and token.
- Quiet Hours / schedule can automatically stop iPhone recording at night or during configured times, avoiding capture during quiet periods.
- The Watch app currently shows only "Watch recording removed". It no longer exposes recording, microphone permission, background audio, WatchConnectivity transfer, or iPhone fallback controls.

Mobile export contains these event types:

- `audio_segment`: recorded audio segment.
- `bookmark`: user bookmark.
- `quick_tag`: quick labels such as important, to-do, idea, meeting, and ignore.
- `location_sample`: location sample.

### Location And Address

Location capture is no longer just latitude and longitude. iPhone uses Core Location for coordinates and reverse geocoding for approximate address fields:

- `address`: system-formatted address.
- `placeName`: place name.
- `country` / `isoCountryCode`: country.
- `administrativeArea` / `subAdministrativeArea`: state, prefecture, province, city, or similar administrative area.
- `locality` / `subLocality`: city, ward, neighborhood, district, or similar local area.
- `thoroughfare` / `subThoroughfare`: street name and street number.
- Latitude, longitude, altitude, accuracy, speed, and course are still preserved for troubleshooting or later reprocessing.

For example, in Japan this may capture neighborhood and block-level information such as Roppongi 1-chome, while in other countries it may capture city, district, street, and street number fields. Actual granularity depends on iOS location permission, network access, map data, and the current position.

If the iPhone Location area shows `kCLErrorDomain error 1`, location permission is usually denied. Allow Wond to use location in iOS Settings. For background or continuous recording, grant a higher level of location permission.

## Encrypted Mobile Sync

Start the sync service on the Mac:

```bash
python3 -m wond sync-server
```

Install Tailscale on both Mac and iPhone first, and join them to the same tailnet. Then enter the Mac's Tailscale address in the iPhone app settings:

```text
http://<mac-tailscale-ip-or-magicdns-name>:8765/upload
```

Use a LAN address such as `http://<mac-lan-ip>:8765/upload` only as a same-Wi-Fi fallback. Do not expose port `8765` directly to the public internet. Even though sync packages use AES-GCM encryption and HMAC tokens, public exposure still increases the attack surface. To sync over cellular, make sure Tailscale is connected and turn off Wi-Fi-only sync in the iPhone app.

Mobile sync uses:

- AES-GCM encrypted `.pcsync` packages.
- PBKDF2-HMAC-SHA256 key derivation.
- HMAC request authentication.
- The `/ask` Q&A endpoint reuses the same HMAC token; retrieval and local model answering happen on the Mac.
- Per-event fingerprint deduplication.
- Background URLSession, so the iPhone app can finish uploads after moving to the background.

Mac import command:

```bash
python3 -m wond ingest-mobile data/mobile_sync/imports/<id>/mobile-export.json
```

The sync server can also import automatically. `skip_existing_uploads` and event fingerprints prevent accepted events from being imported twice. If only a few new recordings or location samples were added, those new events are still uploaded and imported.

Clean mobile sync cache:

```bash
python3 -m wond mobile-sync-cleanup
```

## Apple Watch Status

Apple Watch recording support has been removed. The repository still includes the watchOS target so existing paired installs can update to a safe placeholder companion. It no longer asks for microphone permission or handles background recording, WatchConnectivity audio transfer, or iPhone fallback.

If the Watch app is already installed, reinstalling the iPhone app should leave the paired Watch showing only the recording-removed message. Use the iPhone app when audio capture is needed.

## Speaker Review

List speakers:

```bash
python3 -m wond speakers list
```

Review, rename, merge, and inspect samples:

```bash
python3 -m wond speakers review
python3 -m wond speakers rename <speaker-id> <name>
python3 -m wond speakers merge <source-id> <target-id>
python3 -m wond speakers merge-many <target-id> <source-id> [<source-id> ...]
python3 -m wond speakers samples <speaker-id>
python3 -m wond speakers matches <speaker-id>
python3 -m wond speakers profile <speaker-id>
```

Organize and repair speaker samples:

```bash
python3 -m wond speakers auto-organize --apply --threshold 0.68
python3 -m wond speakers confirm <speaker-id> [<speaker-id> ...]
python3 -m wond speakers unhide <speaker-id> [<speaker-id> ...]
python3 -m wond speakers delete-many --apply <speaker-id> [<speaker-id> ...]
python3 -m wond speakers detach-sample <sample-id>
python3 -m wond speakers repair-samples
python3 -m wond speakers repair-sample-text --apply
python3 -m wond speakers repair-sample-clips --apply
python3 -m wond speakers reset-regroup-samples --apply --threshold 0.68 --max-merges 500
```

Speaker results come from local audio analysis and sample matching. They are useful for human correction, not absolute identity decisions. `reset-regroup-samples` resets sample grouping and is intended for large reorganizations after a database backup.

## Reports, Long-Term Summaries, And Email

Generate a daily report:

```bash
python3 -m wond summarize
```

Compact long-term context:

```bash
python3 -m wond compact
```

Apply retention policy:

```bash
python3 -m wond retention
```

Email summaries:

```bash
python3 -m wond email-summary
python3 -m wond email-due
```

## Search Index

Build or refresh the full-text search index:

```bash
python3 -m wond search-index
```

Afterwards, the dashboard Search page can find imported and analyzed content.

## Troubleshooting

- `status` says the agent is not running: run `install-agent --load` again or check LaunchAgent logs.
- Sync server is unreachable: first open `http://127.0.0.1:8765/health` on the Mac or run `python3 -m wond status`; then check that Tailscale is online on the iPhone and confirm the sync URL is `http://<mac-tailscale-ip-or-magicdns-name>:8765/upload`.
- Dashboard is unreachable: run `install-dashboard-agent --load` again, then open `http://127.0.0.1:8787`.
- Audio analysis fails: check the external model drive, `HF_HOME`, `ffmpeg`, MLX Audio, Ollama, and the LaunchAgent PATH.
- Location reports `kCLErrorDomain error 1`: iOS location permission was denied or is not sufficient.
- Watch still shows the old recording UI: reinstall or update the iPhone app and paired Watch app. The current Watch target should show only the recording-removed message.
- New-file analysis is stuck: check for temporary lock files such as Office `~$...pptx` files, which are often incomplete documents. Normal files are copied to `data/file_analysis_workspace/` before analysis.

## License

Wond is released under the MIT License. See [LICENSE](LICENSE) for details.
