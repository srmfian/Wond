import SwiftUI

struct CaptureTimelineView: View {
    @EnvironmentObject private var store: CaptureStore
    @State private var shareItem: ShareItem?
    @State private var query = ""
    @State private var timeFilter: TodayTimeFilter = .all
    @State private var isRefreshingMacStatus = false

    var body: some View {
        NavigationStack {
            List {
                statusSection
                filterSection
                timelineSection
                exportSection
            }
            .navigationTitle("Today")
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always))
            .refreshable {
                await refreshMacStatus()
            }
            .task {
                if store.syncService.lastMacStatus == nil {
                    await refreshMacStatus()
                }
            }
            .sheet(item: $shareItem) { item in
                ShareSheet(items: [item.url])
            }
        }
    }

    private var statusSection: some View {
        Section("Status") {
            HStack(spacing: 12) {
                TodayStatusTile(
                    title: "Mac",
                    value: macStatusTitle,
                    icon: "desktopcomputer",
                    tint: macStatusTint
                )
                TodayStatusTile(
                    title: "Unsynced",
                    value: "\(store.pendingUploadEventCount)",
                    icon: "arrow.up.circle",
                    tint: store.pendingUploadEventCount == 0 ? .green : .orange
                )
            }
            HStack(spacing: 12) {
                TodayStatusTile(
                    title: "Audio",
                    value: audioStatusTitle,
                    icon: "waveform",
                    tint: audioStatusTint
                )
                TodayStatusTile(
                    title: "Events",
                    value: "\(store.todayEventCount)",
                    icon: "calendar",
                    tint: .blue
                )
            }

            Button {
                Task { await refreshMacStatus() }
            } label: {
                Label(isRefreshingMacStatus ? "Refreshing Mac Status" : "Refresh Mac Status", systemImage: "arrow.clockwise")
            }
            .disabled(isRefreshingMacStatus)

            if let lastSyncAt = store.settings.lastSyncAt {
                LabeledContent("Last sync", value: "\(CaptureFormatters.day(lastSyncAt)) \(CaptureFormatters.clock(lastSyncAt))")
            }

            if let status = store.syncService.lastStatus ?? store.settings.lastSyncStatus {
                Text(status)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if let error = store.syncService.lastMacStatusError {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }

            ForEach(store.syncService.lastMacStatus?.failures.prefix(2).map { $0 } ?? []) { failure in
                VStack(alignment: .leading, spacing: 4) {
                    Label(failure.title ?? "Audio analysis failed", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                    Text(failure.error ?? "No failure reason")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
            }
        }
    }

    private var filterSection: some View {
        Section {
            Picker("Time", selection: $timeFilter) {
                ForEach(TodayTimeFilter.allCases) { filter in
                    Text(filter.title).tag(filter)
                }
            }
            .pickerStyle(.segmented)
        }
    }

    private var timelineSection: some View {
        Section("Today") {
            if filteredTimelineItems.isEmpty {
                ContentUnavailableView(
                    "No Events",
                    systemImage: "calendar.badge.clock",
                    description: Text("Try another time range or search term.")
                )
            } else {
                ForEach(filteredTimelineItems) { item in
                    TodayTimelineRow(item: item)
                }
            }
        }
    }

    private var exportSection: some View {
        Section {
            Button {
                exportArchive()
            } label: {
                Label("Export All Captures", systemImage: "square.and.arrow.up")
            }
        }
    }

    private var timelineItems: [TodayTimelineItem] {
        var items: [TodayTimelineItem] = []
        for segment in store.todaySegments {
            items.append(
                TodayTimelineItem(
                    id: segment.id,
                    date: segment.observedAt,
                    endDate: segment.endedAt,
                    category: "Audio",
                    title: segmentTime(segment),
                    subtitle: segment.mediaPath,
                    detail: segment.location?.label,
                    icon: "waveform",
                    tint: .blue
                )
            )
        }
        for bookmark in store.todayBookmarks {
            items.append(
                TodayTimelineItem(
                    id: bookmark.id,
                    date: bookmark.observedAt,
                    endDate: nil,
                    category: "Bookmark",
                    title: bookmark.title,
                    subtitle: bookmark.note,
                    detail: bookmark.location?.label,
                    icon: "bookmark.fill",
                    tint: .orange
                )
            )
        }
        for quickTag in store.todayQuickTags {
            items.append(
                TodayTimelineItem(
                    id: quickTag.id,
                    date: quickTag.observedAt,
                    endDate: nil,
                    category: "Tag",
                    title: quickTag.title,
                    subtitle: quickTag.note,
                    detail: quickTag.location?.label,
                    icon: QuickTagKind(rawValue: quickTag.tag)?.iconName ?? "tag.fill",
                    tint: quickTag.tag == QuickTagKind.ignore.rawValue ? .secondary : .purple
                )
            )
        }
        for location in store.todayLocations {
            items.append(
                TodayTimelineItem(
                    id: location.id,
                    date: location.observedAt,
                    endDate: nil,
                    category: "Location",
                    title: location.label,
                    subtitle: location.coordinateLabel,
                    detail: nil,
                    icon: "location",
                    tint: .green
                )
            )
        }
        return items.sorted { $0.date > $1.date }
    }

    private var filteredTimelineItems: [TodayTimelineItem] {
        timelineItems.filter { item in
            guard timeFilter.contains(item.date) else { return false }
            let needle = query.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !needle.isEmpty else { return true }
            return item.searchText.localizedCaseInsensitiveContains(needle)
        }
    }

    private var macStatusTitle: String {
        if store.settings.remoteSyncURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return "Not set"
        }
        if store.syncService.lastMacStatusError != nil {
            return "Issue"
        }
        if let status = store.syncService.lastMacStatus {
            return (status.macOnline ?? status.ok) ? "Online" : "Offline"
        }
        return "Unknown"
    }

    private var macStatusTint: Color {
        switch macStatusTitle {
        case "Online":
            return .green
        case "Issue", "Offline":
            return .red
        default:
            return .secondary
        }
    }

    private var audioStatusTitle: String {
        guard let audio = store.syncService.lastMacStatus?.audio else {
            return "Pending"
        }
        if audio.complete {
            return "Done"
        }
        if audio.errors > 0 {
            return "\(audio.errors) err"
        }
        return "\(audio.pending) left"
    }

    private var audioStatusTint: Color {
        guard let audio = store.syncService.lastMacStatus?.audio else {
            return .secondary
        }
        if audio.complete {
            return .green
        }
        return audio.errors > 0 ? .red : .orange
    }

    private func refreshMacStatus() async {
        guard !isRefreshingMacStatus else { return }
        isRefreshingMacStatus = true
        await store.syncService.refreshMacStatus()
        isRefreshingMacStatus = false
    }

    private func segmentTime(_ segment: AudioSegmentRecord) -> String {
        var text = CaptureFormatters.clock(segment.observedAt)
        if let endedAt = segment.endedAt {
            text += "-\(CaptureFormatters.clock(endedAt))"
        }
        if let duration = segment.durationSeconds {
            text += " \(CaptureFormatters.duration(duration))"
        }
        return text
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

private struct TodayTimelineItem: Identifiable {
    var id: String
    var date: Date
    var endDate: Date?
    var category: String
    var title: String
    var subtitle: String?
    var detail: String?
    var icon: String
    var tint: Color

    var searchText: String {
        [category, title, subtitle, detail].compactMap { $0 }.joined(separator: " ")
    }
}

private enum TodayTimeFilter: String, CaseIterable, Identifiable {
    case all
    case morning
    case afternoon
    case evening

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all:
            return "All"
        case .morning:
            return "AM"
        case .afternoon:
            return "PM"
        case .evening:
            return "Night"
        }
    }

    func contains(_ date: Date) -> Bool {
        guard self != .all else { return true }
        let hour = Calendar.current.component(.hour, from: date)
        switch self {
        case .all:
            return true
        case .morning:
            return (5..<12).contains(hour)
        case .afternoon:
            return (12..<18).contains(hour)
        case .evening:
            return hour >= 18 || hour < 5
        }
    }
}

private struct TodayTimelineRow: View {
    var item: TodayTimelineItem

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 4) {
                Text(CaptureFormatters.clock(item.date))
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                if let endDate = item.endDate {
                    Text(CaptureFormatters.clock(endDate))
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(.tertiary)
                }
            }
            .frame(width: 46, alignment: .leading)

            Image(systemName: item.icon)
                .foregroundStyle(item.tint)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(item.category)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(item.tint)
                    Text(item.title)
                        .font(.subheadline.weight(.semibold))
                        .lineLimit(2)
                }
                if let subtitle = item.subtitle, !subtitle.isEmpty {
                    Text(subtitle)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                if let detail = item.detail, !detail.isEmpty {
                    Label(detail, systemImage: "mappin.and.ellipse")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

private struct TodayStatusTile: View {
    var title: String
    var value: String
    var icon: String
    var tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: icon)
                .foregroundStyle(tint)
            Text(value)
                .font(.title3.weight(.semibold))
                .minimumScaleFactor(0.75)
                .lineLimit(1)
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }
}
