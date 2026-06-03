# Mobile Capture App Design

## Goal

Build the Wond app for iPhone and Apple Watch so iPhone can record ambient audio, record location, and expose fast bookmark controls.

The Mac-side `wond` project remains the long-term memory store. The mobile app exports short audio segments and metadata that can be imported with:

```bash
python3 -m wond ingest-mobile mobile-export.json --report-date today
```

## Product Principles

- Recording must be visible and controllable at all times.
- The iPhone is the source of truth for audio, location, storage, and sync.
- The Watch should never need to carry large files for the normal workflow.
- Audio should be split into short segments so crashes, battery loss, and sync failures lose only a small window.
- Raw audio, transcript, and location are sensitive; keep local-first by default.

## iPhone App

### Primary Screen: Capture

Show the current capture state as the first screen:

- Current state: Recording, Paused, Stopped, Permission Needed, Storage Full, Interrupted
- Elapsed time for the current session
- Current segment timer
- Last known location freshness
- Battery/storage warning if relevant
- Large Pause/Resume control
- Add Bookmark control
- Stop Session control

### Timeline Screen

Show today by default:

- Audio segments grouped by session
- Bookmarks inline at their timestamps
- Location hints attached to nearby segments
- Transcript snippets when available
- Export status for each segment

### Settings Screen

Minimum useful settings:

- Segment length: 1, 5, 10, or 15 minutes
- Audio quality: Speech, Balanced, High
- Location mode: Off, Significant Change, Periodic, Continuous
- Keep raw audio for: 1 day, 7 days, 30 days, Forever
- Export target: Files/iCloud folder first; later local network or CloudKit
- Auto-start recording after app launch: off by default
- Privacy controls: delete today, delete session, delete all local data

## Apple Watch App

The Watch app is a controller, not the recorder.

### Main Screen

- Recording status mirrored from iPhone
- Elapsed session time
- Pause/Resume button
- Bookmark button
- Small warning when iPhone is unreachable

### Complication / Smart Stack Widget

- Show recording indicator
- Tap opens the Watch app
- Optional: one-tap bookmark if Apple allows the interaction path for the chosen widget type

### Watch-To-iPhone Commands

Use WatchConnectivity:

- `startRecording`
- `pauseRecording`
- `resumeRecording`
- `stopRecording`
- `addBookmark`
- `requestStatus`

The iPhone responds with:

- `state`
- `sessionId`
- `elapsedSeconds`
- `currentSegmentStartedAt`
- `lastBookmarkAt`
- `lastError`

## Capture Engine

### Audio

The iPhone uses `AVAudioSession` and either `AVAudioRecorder` or `AVAudioEngine`.

Recommended MVP:

- Use `AVAudioRecorder` for simpler file writing.
- Use `.record` or `.playAndRecord` depending on whether monitoring/playback is needed.
- Enable the audio background mode.
- Split files by timer, not by one unbounded file.
- Prefer `.m4a` AAC for size.

Recommended segment defaults:

- Segment duration: 5 minutes
- Filename: `recordings/YYYY-MM-DD/session-id/YYYY-MM-DD-HHMMSS.m4a`
- Metadata row written immediately when segment starts
- Metadata row updated when segment ends

### Location

The iPhone owns location capture.

Recommended MVP:

- Use significant-change or periodic location for lower battery cost.
- Attach nearest location sample to each audio segment.
- Allow continuous location only as an explicit setting.

### Interruptions

Handle:

- Phone calls
- Siri
- Bluetooth microphone route changes
- AirPods disconnect
- Low battery
- Storage pressure
- Permission revoked

Every interruption should write a `bookmark` or `system_event` record so the timeline explains gaps.

## Data Model

### Session

```json
{
  "id": "session-20260530-142000",
  "started_at": "2026-05-30T14:20:00+09:00",
  "ended_at": null,
  "state": "recording",
  "device": "iPhone",
  "settings": {
    "segment_seconds": 300,
    "audio_quality": "balanced",
    "location_mode": "periodic"
  }
}
```

### Audio Segment

```json
{
  "id": "ios-audio-2026-05-30T14:20:00+09:00",
  "kind": "audio_segment",
  "recording_session_id": "session-20260530-142000",
  "observed_at": "2026-05-30T14:20:00+09:00",
  "ended_at": "2026-05-30T14:25:00+09:00",
  "duration_seconds": 300,
  "device": "iPhone",
  "media_path": "recordings/2026-05-30/session-20260530-142000/2026-05-30-142000.m4a",
  "transcript": null,
  "location": {
    "latitude": 35.6812,
    "longitude": 139.7671,
    "horizontal_accuracy": 12
  }
}
```

### Bookmark

```json
{
  "id": "bookmark-20260530-142315",
  "kind": "bookmark",
  "recording_session_id": "session-20260530-142000",
  "observed_at": "2026-05-30T14:23:15+09:00",
  "title": "Important moment",
  "note": "Marked from Apple Watch"
}
```

## Sync And Export

### MVP Export

Use Files/iCloud Drive:

- Export `mobile-export.json`
- Export referenced `.m4a` files in the same folder tree
- Mac imports JSON with `ingest-mobile`

### Later Sync Options

- Local network upload to the Mac Wond sync server
- CloudKit private database
- iCloud Drive folder watcher
- Manual AirDrop/Files export

Start with Files/iCloud Drive because it is easiest to debug and keeps the mobile app independent from the Mac daemon.

## Permissions

Required iPhone permissions:

- Microphone usage description
- Location when in use, or always if background location is enabled
- Background mode: audio
- Background mode: location only if continuous background location is enabled

User-visible behavior:

- Show a persistent in-app recording state.
- Explain exactly what is stored locally.
- Make pause/stop/delete obvious.
- Provide a clear data retention setting.

## MVP Build Plan

1. iPhone-only local recorder
   - Record, pause, resume, stop
   - Segment files every 5 minutes
   - Write JSON metadata

2. iPhone location attachment
   - Capture location samples
   - Attach nearest sample to segment metadata

3. Export to Mac Wond sync server
   - Export folder with JSON plus audio files
   - Verify `ingest-mobile` and daily report

4. Watch remote
   - Mirror state
   - Pause/resume
   - Add bookmark

5. Reliability pass
   - Interruptions
   - route changes
   - low storage
   - background behavior on real devices

6. Optional transcription
   - On-device when feasible
   - Or Mac-side transcription after import

## Main Risks

- Always-on audio has battery and heat costs.
- iOS audio interruptions are normal; the app needs gap records.
- WatchConnectivity is not instant in all states; Watch commands need queued/fallback behavior.
- App Store review may require very clear privacy wording and visible recording controls.
- Testing must happen on physical iPhone and Apple Watch, not only simulator.
