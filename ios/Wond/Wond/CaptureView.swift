import SwiftUI

struct CaptureView: View {
    @EnvironmentObject private var store: CaptureStore
    @State private var shareItem: ShareItem?
    @State private var bookmarkNote = ""
    @State private var quickTagNote = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    captureStatusPanel
                }
                .listRowInsets(EdgeInsets(top: 16, leading: 16, bottom: 16, trailing: 16))

                Section("Controls") {
                    primaryRecordingButton
                        .buttonStyle(.borderedProminent)
                        .controlSize(.large)
                    if store.state == .recording || store.state == .paused {
                        Button(role: .destructive) {
                            store.stopRecording()
                        } label: {
                            Label("Stop Session", systemImage: "stop.fill")
                        }
                    }
                    Button {
                        store.addBookmark(note: bookmarkNote.isEmpty ? "Marked on iPhone" : bookmarkNote)
                        bookmarkNote = ""
                    } label: {
                        Label("Add Bookmark", systemImage: "bookmark.fill")
                    }
                    TextField("Bookmark note", text: $bookmarkNote, axis: .vertical)
                        .lineLimit(1...3)
                }

                Section("Quick Tags") {
                    VStack(alignment: .leading, spacing: 10) {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 118), spacing: 8)], spacing: 8) {
                            ForEach(QuickTagKind.allCases) { tag in
                                Button {
                                    store.addQuickTag(tag, note: quickTagNote.isEmpty ? nil : quickTagNote)
                                    quickTagNote = ""
                                } label: {
                                    Label(tag.title, systemImage: tag.iconName)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                        TextField("Optional tag note", text: $quickTagNote, axis: .vertical)
                            .lineLimit(1...2)
                    }
                }

                Section("Today") {
                    VStack(spacing: 10) {
                        HStack(spacing: 12) {
                            CaptureMetricTile(
                                title: "Events",
                                value: "\(store.todayEventCount)",
                                icon: "calendar"
                            )
                            CaptureMetricTile(
                                title: "Unsynced",
                                value: "\(store.pendingUploadEventCount)",
                                icon: "arrow.up.circle"
                            )
                        }
                        HStack(spacing: 12) {
                            CaptureMetricTile(
                                title: "Segments",
                                value: "\(store.todaySegments.count)",
                                icon: "waveform"
                            )
                            CaptureMetricTile(
                                title: "Places",
                                value: "\(store.todayLocations.count)",
                                icon: "location"
                            )
                            CaptureMetricTile(
                                title: "Tags",
                                value: "\(store.todayQuickTags.count)",
                                icon: "tag"
                            )
                        }
                    }
                    .padding(.vertical, 4)
                    if let segment = store.currentSegment {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Current file")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                            Text(segment.mediaPath)
                                .font(.footnote.monospaced())
                                .lineLimit(2)
                        }
                    }
                }

                Section("Mac Sync") {
                    Button {
                        store.syncTodayNow()
                    } label: {
                        Label(syncButtonTitle, systemImage: "arrow.triangle.2.circlepath")
                    }
                    .disabled(store.syncService.isUploading)

                    if let lastSyncAt = store.settings.lastSyncAt {
                        LabeledContent("Last sync", value: "\(CaptureFormatters.day(lastSyncAt)) \(CaptureFormatters.clock(lastSyncAt))")
                    }
                    if let status = store.settings.lastSyncStatus ?? store.syncService.lastStatus {
                        Text(status)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    if let response = store.syncService.lastUploadResponse, !response.summaryText.isEmpty {
                        LabeledContent("Server", value: response.summaryText)
                    }
                }

                Section {
                    Button {
                        exportArchive()
                    } label: {
                        Label("Export JSON + Audio", systemImage: "square.and.arrow.up")
                    }
                } footer: {
                    Text("The export is a zip file containing mobile-export.json and recorded audio files. Unzip it on your Mac, then import the JSON into Wond.")
                }

                if let error = store.lastError {
                    Section("Last Error") {
                        Text(error)
                            .foregroundStyle(.red)
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Wond")
            .sheet(item: $shareItem) { item in
                ShareSheet(items: [item.url])
            }
        }
    }

    private var primaryRecordingButton: some View {
        Group {
            if store.state == .recording {
                Button {
                    store.pauseRecording()
                } label: {
                    Label("Pause Recording", systemImage: "pause.fill")
                }
            } else if store.state == .paused || store.state == .interrupted {
                Button {
                    Task { await store.resumeRecording() }
                } label: {
                    Label("Resume Recording", systemImage: "record.circle")
                }
            } else {
                Button {
                    Task { await store.startRecording() }
                } label: {
                    Label("Start Recording", systemImage: "record.circle")
                }
            }
        }
    }

    private var captureStatusPanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .center) {
                Label(store.state.title, systemImage: statusIcon)
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(statusColor)
                Spacer()
                Text(statusPillTitle)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(statusColor)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 5)
                    .background(statusColor.opacity(0.12), in: Capsule())
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(CaptureFormatters.duration(store.elapsedSeconds))
                    .font(.system(size: 44, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .minimumScaleFactor(0.75)
                Text(sessionSubtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Current segment")
                        .font(.subheadline.weight(.medium))
                    Spacer()
                    Text("\(CaptureFormatters.duration(store.currentSegmentSeconds)) / \(CaptureFormatters.duration(TimeInterval(store.settings.segmentSeconds)))")
                        .font(.footnote.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                ProgressView(value: segmentProgress)
                    .tint(statusColor)
            }

            StatusSummaryRow(
                icon: "location",
                title: locationTitle,
                subtitle: locationSubtitle,
                tint: store.settings.locationMode == .off ? .secondary : .blue
            )

        }
        .padding(.vertical, 4)
    }

    private var statusColor: Color {
        switch store.state {
        case .recording:
            return .red
        case .paused:
            return .orange
        case .idle:
            return .secondary
        case .interrupted, .permissionNeeded, .failed:
            return .yellow
        }
    }

    private var statusIcon: String {
        switch store.state {
        case .recording:
            return "record.circle.fill"
        case .paused:
            return "pause.circle.fill"
        case .idle:
            return "stop.circle"
        case .interrupted:
            return "exclamationmark.triangle.fill"
        case .permissionNeeded:
            return "mic.badge.xmark"
        case .failed:
            return "xmark.octagon.fill"
        }
    }

    private var statusPillTitle: String {
        switch store.state {
        case .recording:
            return "Live"
        case .paused:
            return "Paused"
        case .idle:
            return "Ready"
        case .interrupted:
            return "Interrupted"
        case .permissionNeeded:
            return "Permission"
        case .failed:
            return "Error"
        }
    }

    private var sessionSubtitle: String {
        guard let session = store.currentSession else {
            return "Ready to start a new session"
        }
        return "Started \(CaptureFormatters.clock(session.startedAt))"
    }

    private var segmentProgress: Double {
        guard store.settings.segmentSeconds > 0 else { return 0 }
        return min(1, store.currentSegmentSeconds / TimeInterval(store.settings.segmentSeconds))
    }

    private var syncButtonTitle: String {
        store.syncService.isUploading ? "Syncing to Mac" : "Sync to Mac Now"
    }

    private var locationTitle: String {
        guard store.settings.locationMode != .off else {
            return "Location off"
        }
        if let location = store.latestLocation {
            return location.address ?? location.placeName ?? store.locationStatusMessage ?? "Resolving address"
        }
        return store.locationStatusMessage ?? "Waiting for location"
    }

    private var locationSubtitle: String {
        guard store.settings.locationMode != .off else {
            return "No place attached"
        }
        if let location = store.latestLocation {
            return "\(store.settings.locationMode.title) - \(CaptureFormatters.clock(location.observedAt))"
        }
        return store.settings.locationMode.title
    }

    private func exportArchive() {
        do {
            let url = try store.makeExportArchive()
            shareItem = ShareItem(url: url)
        } catch {
            store.lastError = error.localizedDescription
        }
    }
}

private struct CaptureMetricTile: View {
    var title: String
    var value: String
    var icon: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: icon)
                .font(.headline)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title2.weight(.semibold))
                .monospacedDigit()
            Text(title)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }
}

private struct StatusSummaryRow: View {
    var icon: String
    var title: String
    var subtitle: String
    var tint: Color

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .lineLimit(2)
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        } icon: {
            Image(systemName: icon)
                .foregroundStyle(tint)
        }
    }
}
