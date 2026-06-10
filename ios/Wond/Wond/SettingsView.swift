import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: CaptureStore
    @State private var showingDeleteConfirmation = false

    private let segmentOptions = [60, 300, 600, 900]
    private let retentionOptions = [1, 7, 30, 0]

    var body: some View {
        NavigationStack {
            Form {
                Section("Capture") {
                    Picker("Capture mode", selection: captureModeBinding) {
                        ForEach(CaptureMode.allCases) { mode in
                            Text(mode.title).tag(mode)
                        }
                    }

                    if store.settings.captureMode.recordsAudio {
                        Picker("Segment length", selection: segmentBinding) {
                            ForEach(segmentOptions, id: \.self) { value in
                                Text(CaptureFormatters.duration(TimeInterval(value))).tag(value)
                            }
                        }

                        Picker("Audio quality", selection: qualityBinding) {
                            ForEach(AudioQuality.allCases) { quality in
                                Text(quality.title).tag(quality)
                            }
                        }

                        Toggle("Stop recording during quiet hours", isOn: sleepQuietHoursBinding)

                        NavigationLink {
                            QuietScheduleView()
                        } label: {
                            SettingsSummaryRow(
                                icon: "moon.zzz",
                                title: "Quiet Schedule",
                                subtitle: quietScheduleOverview
                            )
                        }
                    } else {
                        SettingsSummaryRow(
                            icon: "mic.slash",
                            title: "Audio recording disabled",
                            subtitle: "Location-only mode will not request microphone permission."
                        )
                    }
                }

                Section {
                    if store.settings.captureMode.recordsLocation {
                        Picker("Location mode", selection: locationModeBinding) {
                            ForEach(locationModeOptions) { mode in
                                Text(mode.title).tag(mode)
                            }
                        }

                        if let location = store.latestLocation {
                            LabeledContent("Last place", value: location.label)
                            LabeledContent("Updated", value: "\(CaptureFormatters.day(location.observedAt)) \(CaptureFormatters.clock(location.observedAt))")
                        }
                        if let status = store.locationStatusMessage {
                            Text(WondL10n.t(status))
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        if store.canOpenLocationSettings {
                            Button {
                                store.openAppSettings()
                            } label: {
                                Label("Open Settings", systemImage: "gear")
                            }
                        }
                    } else {
                        SettingsSummaryRow(
                            icon: "location.slash",
                            title: "Location recording disabled",
                            subtitle: "Audio-only mode will not write location samples."
                        )
                    }
                } header: {
                    Text("Location")
                } footer: {
                    if store.settings.captureMode.recordsLocation {
                        Text("Location samples are recorded only while a capture session is active.")
                    } else {
                        Text("Switch Capture mode to Location Only or Audio + Location to record places.")
                    }
                }

                Section("Retention") {
                    Picker("Keep raw audio", selection: retentionBinding) {
                        ForEach(retentionOptions, id: \.self) { value in
                            Text(retentionTitle(value)).tag(value)
                        }
                    }
                }

                Section {
                    NavigationLink {
                        MacSyncSettingsView()
                    } label: {
                        SettingsSummaryRow(
                            icon: "desktopcomputer",
                            title: "Connection",
                            subtitle: macSyncOverview
                        )
                    }
                    Button {
                        store.syncTodayNow()
                    } label: {
                        Label("Sync to Mac Now", systemImage: "arrow.triangle.2.circlepath")
                    }
                    if let lastSyncAt = store.settings.lastSyncAt {
                        LabeledContent("Last sync", value: "\(CaptureFormatters.day(lastSyncAt)) \(CaptureFormatters.clock(lastSyncAt))")
                    }
                    if let status = store.settings.lastSyncStatus ?? store.syncService.lastStatus {
                        Text(WondL10n.t(status))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Mac Sync")
                } footer: {
                    Text("Remote sync URL should point to the Mac `/upload` endpoint through Tailscale or another HTTPS route. Wi-Fi only limits automatic sync; manual sync can use any network.")
                }

                Section("Local Data") {
                    LabeledContent("Sessions", value: "\(store.sessions.count)")
                    LabeledContent("Audio segments", value: "\(store.segments.count)")
                    LabeledContent("Bookmarks", value: "\(store.bookmarks.count)")
                    LabeledContent("Locations", value: "\(store.locations.count)")
                    Button(role: .destructive) {
                        showingDeleteConfirmation = true
                    } label: {
                        Label("Delete All Local Data", systemImage: "trash")
                    }
                }
            }
            .navigationTitle("Settings")
            .confirmationDialog(
                "Delete all local data?",
                isPresented: $showingDeleteConfirmation,
                titleVisibility: .visible
            ) {
                Button("Delete Everything", role: .destructive) {
                    store.deleteAllLocalData()
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This removes recordings, bookmarks, and metadata stored by this app.")
            }
        }
    }

    private var segmentBinding: Binding<Int> {
        Binding(
            get: { store.settings.segmentSeconds },
            set: { store.setSegmentSeconds($0) }
        )
    }

    private var qualityBinding: Binding<AudioQuality> {
        Binding(
            get: { store.settings.audioQuality },
            set: { store.setAudioQuality($0) }
        )
    }

    private var captureModeBinding: Binding<CaptureMode> {
        Binding(
            get: { store.settings.captureMode },
            set: { store.setCaptureMode($0) }
        )
    }

    private var locationModeBinding: Binding<LocationMode> {
        Binding(
            get: { store.settings.locationMode },
            set: { store.setLocationMode($0) }
        )
    }

    private var locationModeOptions: [LocationMode] {
        store.settings.captureMode.recordsLocation ? LocationMode.allCases.filter { $0 != .off } : [.off]
    }

    private var retentionBinding: Binding<Int> {
        Binding(
            get: { store.settings.retentionDays },
            set: { store.setRetentionDays($0) }
        )
    }

    private var autoSyncBinding: Binding<Bool> {
        Binding(
            get: { store.settings.autoSyncEnabled },
            set: { store.setAutoSyncEnabled($0) }
        )
    }

    private var syncTokenBinding: Binding<String> {
        Binding(
            get: { store.settings.syncToken },
            set: { store.setSyncToken($0) }
        )
    }

    private var remoteSyncURLBinding: Binding<String> {
        Binding(
            get: { store.settings.remoteSyncURL },
            set: { store.setRemoteSyncURL($0) }
        )
    }

    private var wifiOnlyAutoSyncBinding: Binding<Bool> {
        Binding(
            get: { store.settings.wifiOnlyAutoSync },
            set: { store.setWifiOnlyAutoSync($0) }
        )
    }

    private var sleepQuietHoursBinding: Binding<Bool> {
        Binding(
            get: { store.settings.sleepQuietHoursEnabled },
            set: { store.setSleepQuietHoursEnabled($0) }
        )
    }

    private func retentionTitle(_ value: Int) -> String {
        if value == 0 {
            return WondL10n.t("Forever")
        }
        if value == 1 {
            return WondL10n.t("1 day")
        }
        return WondL10n.format("%d days", value)
    }

    private var quietScheduleOverview: String {
        guard store.settings.sleepQuietHoursEnabled else { return WondL10n.t("Off") }
        let enabledCount = store.settings.sleepQuietSchedule.filter(\.enabled).count
        if enabledCount == 0 { return WondL10n.t("No active days") }
        if enabledCount == 7 { return WondL10n.t("Every day") }
        return WondL10n.format("%d active days", enabledCount)
    }

    private var macSyncOverview: String {
        if store.settings.autoSyncEnabled {
            return store.settings.wifiOnlyAutoSync ? WondL10n.t("Auto-sync, Wi-Fi only") : WondL10n.t("Auto-sync on any network")
        }
        return WondL10n.t("Manual sync")
    }
}

private struct SettingsSummaryRow: View {
    var icon: String
    var title: String
    var subtitle: String

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 3) {
                Text(WondL10n.t(title))
                Text(WondL10n.t(subtitle))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        } icon: {
            Image(systemName: icon)
                .foregroundStyle(.secondary)
        }
    }
}

private struct QuietScheduleView: View {
    @EnvironmentObject private var store: CaptureStore
    @State private var selectedWeekdays = Set(QuietWeekday.settingsOrder)
    @State private var batchStartDate = QuietScheduleFormatter.date(for: 23 * 60)
    @State private var batchEndDate = QuietScheduleFormatter.date(for: 7 * 60)
    @State private var didSeedBatchControls = false

    var body: some View {
        Form {
            Section {
                DatePicker("Start", selection: $batchStartDate, displayedComponents: .hourAndMinute)
                DatePicker("End", selection: $batchEndDate, displayedComponents: .hourAndMinute)
                ForEach(QuietWeekday.settingsOrder) { weekday in
                    Toggle(weekday.title, isOn: weekdaySelectionBinding(for: weekday))
                }
                Button {
                    applyBatchSchedule()
                } label: {
                    Label("Apply to Selected Days", systemImage: "calendar.badge.clock")
                }
                .disabled(selectedWeekdays.isEmpty)
            } header: {
                Text("Apply Time to Days")
            } footer: {
                Text("Use a start time later than the end time for an overnight window. The main Settings page controls whether quiet hours are active.")
            }

            Section("Weekly Schedule") {
                ForEach(QuietWeekday.settingsOrder) { weekday in
                    NavigationLink {
                        QuietDayScheduleView(weekday: weekday)
                    } label: {
                        QuietScheduleRow(weekday: weekday)
                    }
                }
            }
        }
        .navigationTitle("Quiet Schedule")
        .onAppear(perform: seedBatchControlsIfNeeded)
    }

    private func weekdaySelectionBinding(for weekday: QuietWeekday) -> Binding<Bool> {
        Binding(
            get: { selectedWeekdays.contains(weekday) },
            set: { isSelected in
                if isSelected {
                    selectedWeekdays.insert(weekday)
                } else {
                    selectedWeekdays.remove(weekday)
                }
            }
        )
    }

    private func seedBatchControlsIfNeeded() {
        guard !didSeedBatchControls else { return }
        let enabledIntervals = store.settings.sleepQuietSchedule.filter(\.enabled)
        let seedInterval = enabledIntervals.first ?? store.sleepQuietInterval(for: .monday)
        let seedWeekdays = enabledIntervals.map(\.weekday)
        batchStartDate = QuietScheduleFormatter.date(for: seedInterval.startMinute)
        batchEndDate = QuietScheduleFormatter.date(for: seedInterval.endMinute)
        selectedWeekdays = seedWeekdays.isEmpty ? Set(QuietWeekday.settingsOrder) : Set(seedWeekdays)
        didSeedBatchControls = true
    }

    private func applyBatchSchedule() {
        store.setSleepQuietIntervals(
            for: selectedWeekdays,
            startMinute: QuietScheduleFormatter.minuteOfDay(from: batchStartDate),
            endMinute: QuietScheduleFormatter.minuteOfDay(from: batchEndDate)
        )
    }
}

private struct QuietScheduleRow: View {
    @EnvironmentObject private var store: CaptureStore
    var weekday: QuietWeekday

    var body: some View {
        let interval = store.sleepQuietInterval(for: weekday)

        VStack(alignment: .leading, spacing: 3) {
            Text(weekday.title)
            Text(QuietScheduleFormatter.summary(for: interval))
                .font(.footnote)
                .foregroundStyle(interval.enabled ? .secondary : .tertiary)
        }
    }
}

private struct QuietDayScheduleView: View {
    @EnvironmentObject private var store: CaptureStore
    var weekday: QuietWeekday

    var body: some View {
        Form {
            Section {
                Toggle("Enabled", isOn: dayEnabledBinding)
                if interval.enabled {
                    DatePicker("Start", selection: startBinding, displayedComponents: .hourAndMinute)
                    DatePicker("End", selection: endBinding, displayedComponents: .hourAndMinute)
                    LabeledContent("Summary", value: QuietScheduleFormatter.summary(for: interval))
                }
            } footer: {
                Text("Use a start time later than the end time for an overnight window.")
            }
        }
        .navigationTitle(weekday.title)
    }

    private var interval: SleepQuietInterval {
        store.sleepQuietInterval(for: weekday)
    }

    private var dayEnabledBinding: Binding<Bool> {
        Binding(
            get: { interval.enabled },
            set: { value in
                var updated = interval
                updated.enabled = value
                store.setSleepQuietInterval(updated)
            }
        )
    }

    private var startBinding: Binding<Date> {
        Binding(
            get: { QuietScheduleFormatter.date(for: interval.startMinute) },
            set: { date in
                var updated = interval
                updated.startMinute = QuietScheduleFormatter.minuteOfDay(from: date)
                store.setSleepQuietInterval(updated)
            }
        )
    }

    private var endBinding: Binding<Date> {
        Binding(
            get: { QuietScheduleFormatter.date(for: interval.endMinute) },
            set: { date in
                var updated = interval
                updated.endMinute = QuietScheduleFormatter.minuteOfDay(from: date)
                store.setSleepQuietInterval(updated)
            }
        )
    }
}

private struct MacSyncSettingsView: View {
    @EnvironmentObject private var store: CaptureStore

    var body: some View {
        Form {
            Section {
                Toggle("Auto-sync to Mac", isOn: autoSyncBinding)
                Toggle("Wi-Fi only automatic sync", isOn: wifiOnlyAutoSyncBinding)
            }

            Section("Connection") {
                TextField("Sync token", text: syncTokenBinding)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                TextField("Remote sync URL", text: remoteSyncURLBinding)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
            }

            Section {
                Button {
                    store.syncTodayNow()
                } label: {
                    Label("Sync to Mac Now", systemImage: "arrow.triangle.2.circlepath")
                }
                .disabled(store.syncService.isUploading)
                if let lastSyncAt = store.settings.lastSyncAt {
                    LabeledContent("Last sync", value: "\(CaptureFormatters.day(lastSyncAt)) \(CaptureFormatters.clock(lastSyncAt))")
                }
                if let status = store.settings.lastSyncStatus ?? store.syncService.lastStatus {
                    Text(WondL10n.t(status))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("Mac Sync")
    }

    private var autoSyncBinding: Binding<Bool> {
        Binding(
            get: { store.settings.autoSyncEnabled },
            set: { store.setAutoSyncEnabled($0) }
        )
    }

    private var syncTokenBinding: Binding<String> {
        Binding(
            get: { store.settings.syncToken },
            set: { store.setSyncToken($0) }
        )
    }

    private var remoteSyncURLBinding: Binding<String> {
        Binding(
            get: { store.settings.remoteSyncURL },
            set: { store.setRemoteSyncURL($0) }
        )
    }

    private var wifiOnlyAutoSyncBinding: Binding<Bool> {
        Binding(
            get: { store.settings.wifiOnlyAutoSync },
            set: { store.setWifiOnlyAutoSync($0) }
        )
    }
}

private enum QuietScheduleFormatter {
    static func summary(for interval: SleepQuietInterval) -> String {
        if !interval.enabled {
            return WondL10n.t("Disabled")
        }
        let startDayOffset = quietDayOffset(for: interval.startMinute)
        let endDayOffset = quietDayOffset(for: interval.endMinute)
        if interval.startMinute == interval.endMinute {
            return "\(dayPrefix(for: startDayOffset))\(WondL10n.t("all day"))"
        }
        if startDayOffset == endDayOffset {
            return "\(dayPrefix(for: startDayOffset))\(formattedMinute(interval.startMinute)) - \(formattedMinute(interval.endMinute))"
        }
        return "\(dayPrefix(for: startDayOffset))\(formattedMinute(interval.startMinute)) - \(dayPrefix(for: endDayOffset))\(formattedMinute(interval.endMinute))"
    }

    static func date(for minute: Int) -> Date {
        let calendar = Calendar.current
        let startOfDay = calendar.startOfDay(for: Date())
        return calendar.date(
            byAdding: .minute,
            value: max(0, min(23 * 60 + 59, minute)),
            to: startOfDay
        ) ?? startOfDay
    }

    static func minuteOfDay(from date: Date) -> Int {
        let calendar = Calendar.current
        return calendar.component(.hour, from: date) * 60 + calendar.component(.minute, from: date)
    }

    private static func formattedMinute(_ minute: Int) -> String {
        timeFormatter.string(from: date(for: minute))
    }

    private static func quietDayOffset(for minute: Int) -> Int {
        minute < sleepDayRolloverMinute ? 1 : 0
    }

    private static func dayPrefix(for offset: Int) -> String {
        offset == 1 ? WondL10n.t("next day ") : ""
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        formatter.dateStyle = .none
        return formatter
    }()

    private static let sleepDayRolloverMinute = 12 * 60
}
