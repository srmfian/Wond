# Wond iOS

This Xcode project contains the iPhone capture app for Wond.

The app is designed for local-first capture:

- Record segmented audio on iPhone.
- Add bookmarks while recording.
- Capture location samples and reverse-geocoded address fields.
- Encrypt and sync pending events to the Mac sync server.
- Ask questions against the Mac local memory index through the sync server.
- Keep per-event upload fingerprints so unchanged events are not uploaded again.

## Project

- Xcode project: `ios/Wond/Wond.xcodeproj`
- iPhone display name: `Wond`
- Bundle IDs and Apple Team ID: loaded from `Config/Signing.xcconfig`; put personal values in ignored `Config/Signing.local.xcconfig`
- Mac sync server: `python3 -m wond sync-server`

## iPhone Features

- Segmented audio recording with configurable segment length and quality.
- Background audio mode for continued recording.
- Location modes: off, significant-change, periodic, continuous.
- Reverse geocoding for human-readable addresses.
- Bookmarks attached to the nearest current segment and location.
- Background URLSession sync.
- Encrypted `.pcsync` upload packages.
- Mac-backed local memory Q&A with answer citations.
- Optional raw-audio retention cleanup after sync/import.

Location export includes both coordinates and address fields:

- `address`
- `placeName`
- `country`
- `isoCountryCode`
- `administrativeArea`
- `subAdministrativeArea`
- `locality`
- `subLocality`
- `thoroughfare`
- `subThoroughfare`
- latitude, longitude, altitude, accuracy, speed, course

If Location shows `kCLErrorDomain error 1`, iOS has denied location access. Open iOS Settings for Wond and allow location access. For background or continuous capture, use the strongest permission level iOS offers for this app.

## Apple Watch

Apple Watch recording support has been removed. The watchOS target is kept as a small companion placeholder so existing paired installs can be updated without exposing recording controls, microphone access, background audio, WatchConnectivity transfer, or iPhone fallback behavior.

## Permissions

iPhone:

- Microphone
- Location, if location capture is enabled
- Local network access may be requested by iOS when syncing to the Mac on LAN. Tailscale private VPN is the recommended sync path.

## Installing

Normal development flow:

1. Open `Wond.xcodeproj` in Xcode.
2. Select the `Wond` iPhone scheme.
3. Choose the connected iPhone as the run destination.
4. Build and run.

The paired Watch app, if present, now shows only that Watch recording has been removed.

## Local Signing

The checked-in project uses placeholder signing values so GitHub does not expose a personal Apple Team ID or bundle identifier. For device builds, create:

```xcconfig
// ios/Wond/Config/Signing.local.xcconfig
WOND_DEVELOPMENT_TEAM = YOURTEAMID
WOND_IOS_BUNDLE_ID = your.private.bundle.id
WOND_WATCH_BUNDLE_ID = $(WOND_IOS_BUNDLE_ID).watchkitapp
```

`Signing.local.xcconfig` is ignored by Git. If you need to update an already-installed private app, use that app's existing bundle IDs in this local file; changing bundle IDs creates a fresh install.

## Sync

Start the Mac sync server:

```bash
python3 -m wond sync-server
```

In the iPhone app settings, configure:

- Mac sync URL, preferably through Tailscale: `http://<mac-tailscale-ip-or-magicdns-name>:8765/upload`
- Sync token
- Wi-Fi-only sync preference. Turn this off if you want Tailscale sync to work over cellular data.
- Auto sync

Examples:

```text
http://100.x.y.z:8765/upload
http://macbook-name.tailnet-name.ts.net:8765/upload
```

Use `http://<mac-lan-ip>:8765/upload` only as a same-Wi-Fi fallback. Do not expose the Mac sync server to the public internet or configure router port forwarding for `8765`.

The app creates encrypted `.pcsync` packages. The Mac server decrypts and imports them into Wond's local SQLite database, normally `data/wond.sqlite3`, then can write reports under `data/reports/`.

The Ask tab uses the same Mac sync URL and token. It posts signed JSON to `/ask`; the Mac performs retrieval and local-model answering, then returns the answer plus citations.

The sync path uses event fingerprints. If the Mac has already accepted an event, the iPhone does not need to upload that event again; new audio, bookmarks and location samples still sync normally.

## Troubleshooting

- iPhone Location error `kCLErrorDomain error 1`: location permission is denied.
- Upload succeeds but nothing new appears: the events may already be accepted fingerprints; record a new segment or bookmark and sync again.
- Mac receives sync but audio is not analyzed immediately: check `mobile_sync.analyze_after_import`, audio queue, local model availability and `python3 -m wond doctor`.
