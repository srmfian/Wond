import AVFoundation
import Combine
import CoreLocation
import CryptoKit
import Foundation
import UIKit
@preconcurrency import UserNotifications

@MainActor
final class CaptureStore: NSObject, ObservableObject, AVAudioRecorderDelegate, CLLocationManagerDelegate, UNUserNotificationCenterDelegate {
    @Published private(set) var state: CaptureState = .idle
    @Published private(set) var currentSession: CaptureSessionRecord?
    @Published private(set) var sessions: [CaptureSessionRecord] = []
    @Published private(set) var segments: [AudioSegmentRecord] = []
    @Published private(set) var bookmarks: [BookmarkRecord] = []
    @Published private(set) var quickTags: [QuickTagRecord] = []
    @Published private(set) var locations: [LocationPoint] = []
    @Published var settings: CaptureSettings = CaptureSettings()
    @Published private(set) var elapsedSeconds: TimeInterval = 0
    @Published private(set) var currentSegmentSeconds: TimeInterval = 0
    @Published private(set) var locationStatusMessage: String?
    @Published var lastError: String?

    let syncService = SyncService()

    private let fileManager = FileManager.default
    private let persistence = CaptureStorePersistence()
    private let locationManager = CLLocationManager()
    private let geocoder = CLGeocoder()
    private var recorder: AVAudioRecorder?
    private var activeSegmentID: String?
    private var uiTimer: Timer?
    private var locationTimer: Timer?
    private var reverseGeocodeRetryTask: Task<Void, Never>?
    private var interruptionRecoveryTask: Task<Void, Never>?
    private var isRequestingOneShotLocation = false
    private var lastReverseGeocodeLocation: CLLocation?
    private var lastReverseGeocodeAt: Date?
    private var shouldResumeAfterInterruption = false
    private var interruptionRecoveryAttempts = 0
    private var didFailLoadingDatabase = false
    private var documentsURL: URL {
        persistence.documentsURL
    }

    override init() {
        super.init()
        repairDocumentsDirectoryIfNeeded()
        load()
        pruneExpiredData()
        UNUserNotificationCenter.current().delegate = self
        locationManager.delegate = self
        locationManager.activityType = .other
        registerAudioNotifications()
        syncService.uploadPackageProvider = { [weak self] in
            guard let self else { throw SyncError.invalidResponse }
            return try self.makePendingSyncPackage(onlyToday: true)
        }
        syncService.tokenProvider = { [weak self] in
            self?.settings.syncToken ?? ""
        }
        syncService.remoteURLProvider = { [weak self] in
            self?.settings.remoteSyncURL ?? ""
        }
        syncService.wifiOnlyProvider = { [weak self] in
            self?.settings.wifiOnlyAutoSync ?? true
        }
        syncService.onStatus = { [weak self] message, date in
            Task { @MainActor in
                self?.recordSyncStatus(message, at: date)
            }
        }
        syncService.onUploadAccepted = { [weak self] snapshot in
            Task { @MainActor in
                self?.markUploadAccepted(snapshot)
            }
        }
        configureLocationTracking()
        if let openSession = sessions.last(where: { $0.endedAt == nil }) {
            currentSession = openSession
            state = openSession.state == .recording ? .paused : openSession.state
            if openSession.state == .interrupted {
                shouldResumeAfterInterruption = true
                scheduleInterruptionRecovery(reason: WondL10n.t("Recovered an interrupted session after app launch"), delay: 1.0)
            }
        }
        if settings.autoSyncEnabled {
            syncService.start()
        }
    }

    deinit {
        uiTimer?.invalidate()
        locationTimer?.invalidate()
        reverseGeocodeRetryTask?.cancel()
        interruptionRecoveryTask?.cancel()
        locationManager.stopUpdatingLocation()
        locationManager.stopMonitoringSignificantLocationChanges()
        NotificationCenter.default.removeObserver(self)
    }

    var currentSegment: AudioSegmentRecord? {
        guard let activeSegmentID else { return nil }
        return segments.first(where: { $0.id == activeSegmentID })
    }

    var todaySegments: [AudioSegmentRecord] {
        filterToday(segments, date: \.observedAt)
            .sorted { $0.observedAt > $1.observedAt }
    }

    var todayBookmarks: [BookmarkRecord] {
        filterToday(bookmarks, date: \.observedAt)
            .sorted { $0.observedAt > $1.observedAt }
    }

    var todayQuickTags: [QuickTagRecord] {
        filterToday(quickTags, date: \.observedAt)
            .sorted { $0.observedAt > $1.observedAt }
    }

    var todayLocations: [LocationPoint] {
        filterToday(locations, date: \.observedAt)
            .sorted { $0.observedAt > $1.observedAt }
    }

    var latestLocation: LocationPoint? {
        locations.max { $0.observedAt < $1.observedAt }
    }

    var todayEventCount: Int {
        todaySegments.count + todayBookmarks.count + todayQuickTags.count + todayLocations.count
    }

    var pendingUploadEventCount: Int {
        countPendingUploadEvents(onlyToday: true)
    }

    var canOpenLocationSettings: Bool {
        guard settings.locationMode != .off else { return false }
        if !CLLocationManager.locationServicesEnabled() { return true }
        switch locationManager.authorizationStatus {
        case .restricted, .denied:
            return true
        default:
            return false
        }
    }

    func startRecording() async {
        lastError = nil
        guard !isInSleepQuietHours() else {
            stopRecordingForSleepQuietHours()
            lastError = WondL10n.t("Recording is stopped during quiet hours.")
            return
        }
        do {
            guard await requestMicrophonePermission() else {
                state = .permissionNeeded
                lastError = WondL10n.t("Microphone permission is required.")
                return
            }
            Self.requestPassiveStopNotificationPermission()
            if currentSession == nil || currentSession?.endedAt != nil {
                createSession()
            }
            try configureAudioSession()
            state = .recording
            updateCurrentSessionState(.recording)
            try startNewSegment()
            startUITimer()
            shouldResumeAfterInterruption = false
            interruptionRecoveryAttempts = 0
            save()
        } catch {
            state = .failed
            lastError = error.localizedDescription
            save()
        }
    }

    func pauseRecording() {
        guard state == .recording else { return }
        state = .paused
        updateCurrentSessionState(.paused)
        recorder?.stop()
        recorder = nil
        stopUITimer()
        save()
    }

    func resumeRecording() async {
        guard state == .paused || state == .interrupted else {
            await startRecording()
            return
        }
        await startRecording()
    }

    func stopRecording() {
        guard currentSession != nil else { return }
        shouldResumeAfterInterruption = false
        interruptionRecoveryAttempts = 0
        interruptionRecoveryTask?.cancel()
        state = .idle
        recorder?.stop()
        recorder = nil
        stopUITimer()
        finalizeCurrentSession()
        do {
            try AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        } catch {
            lastError = error.localizedDescription
        }
        save()
    }

    func addBookmark(title: String = WondL10n.t("Important moment"), note: String? = WondL10n.t("Marked on iPhone")) {
        let observedAt = Date()
        let bookmark = BookmarkRecord(
            id: "bookmark-\(filenameTimestamp(observedAt))",
            recordingSessionID: currentSession?.id,
            observedAt: observedAt,
            title: title,
            note: note,
            location: nearestLocation(to: observedAt)
        )
        bookmarks.append(bookmark)
        save()
    }

    func addQuickTag(_ tag: QuickTagKind, note: String? = nil, sourceRef: String? = nil, device: String? = nil) {
        let observedAt = Date()
        let quickTag = QuickTagRecord(
            id: "quick-tag-\(filenameTimestamp(observedAt))-\(UUID().uuidString.prefix(6))",
            recordingSessionID: currentSession?.id,
            observedAt: observedAt,
            tag: tag.rawValue,
            title: tag.title,
            note: note ?? tag.defaultNote,
            device: device ?? UIDevice.current.name,
            sourceRef: sourceRef ?? activeSegmentID,
            location: nearestLocation(to: observedAt)
        )
        quickTags.append(quickTag)
        save()
    }

    func setSegmentSeconds(_ value: Int) {
        settings.segmentSeconds = value
        save()
    }

    func setAudioQuality(_ value: AudioQuality) {
        settings.audioQuality = value
        save()
    }

    func setLocationMode(_ value: LocationMode) {
        settings.locationMode = value
        if var session = currentSession,
           let index = sessions.firstIndex(where: { $0.id == session.id }) {
            session.locationMode = value
            currentSession = session
            sessions[index] = session
        }
        configureLocationTracking()
        save()
    }

    func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    func setRetentionDays(_ value: Int) {
        settings.retentionDays = value
        pruneExpiredData()
        save()
    }

    func setAutoSyncEnabled(_ value: Bool) {
        settings.autoSyncEnabled = value
        if value {
            syncService.start()
        } else {
            syncService.stop()
        }
        save()
    }

    func setSyncToken(_ value: String) {
        settings.syncToken = value.trimmingCharacters(in: .whitespacesAndNewlines)
        save()
    }

    func setRemoteSyncURL(_ value: String) {
        settings.remoteSyncURL = value.trimmingCharacters(in: .whitespacesAndNewlines)
        save()
    }

    func setWifiOnlyAutoSync(_ value: Bool) {
        settings.wifiOnlyAutoSync = value
        save()
    }

    func setSleepQuietHoursEnabled(_ value: Bool) {
        settings.sleepQuietHoursEnabled = value
        if value {
            enforceSleepQuietRecordingPolicy()
        }
        save()
    }

    func sleepQuietInterval(for weekday: QuietWeekday) -> SleepQuietInterval {
        settings.sleepQuietSchedule.first(where: { $0.weekday == weekday })
            ?? SleepQuietInterval(weekday: weekday)
    }

    func setSleepQuietInterval(_ interval: SleepQuietInterval) {
        let normalizedInterval = SleepQuietInterval(
            weekday: interval.weekday,
            enabled: interval.enabled,
            startMinute: interval.startMinute,
            endMinute: interval.endMinute
        )
        if let index = settings.sleepQuietSchedule.firstIndex(where: { $0.weekday == interval.weekday }) {
            settings.sleepQuietSchedule[index] = normalizedInterval
        } else {
            settings.sleepQuietSchedule.append(normalizedInterval)
        }
        settings.sleepQuietSchedule = SleepQuietInterval.normalized(
            settings.sleepQuietSchedule,
            fallbackStartHour: settings.sleepQuietStartHour,
            fallbackEndHour: settings.sleepQuietEndHour
        )
        settings.sleepQuietStartHour = normalizedInterval.startMinute / 60
        settings.sleepQuietEndHour = normalizedInterval.endMinute / 60
        enforceSleepQuietRecordingPolicy()
        save()
    }

    func setSleepQuietIntervals(for weekdays: Set<QuietWeekday>, startMinute: Int, endMinute: Int) {
        guard !weekdays.isEmpty else { return }
        var updatedSchedule = settings.sleepQuietSchedule
        for weekday in weekdays {
            let interval = SleepQuietInterval(
                weekday: weekday,
                enabled: true,
                startMinute: startMinute,
                endMinute: endMinute
            )
            if let index = updatedSchedule.firstIndex(where: { $0.weekday == weekday }) {
                updatedSchedule[index] = interval
            } else {
                updatedSchedule.append(interval)
            }
        }
        settings.sleepQuietSchedule = SleepQuietInterval.normalized(
            updatedSchedule,
            fallbackStartHour: settings.sleepQuietStartHour,
            fallbackEndHour: settings.sleepQuietEndHour
        )
        settings.sleepQuietStartHour = startMinute / 60
        settings.sleepQuietEndHour = endMinute / 60
        enforceSleepQuietRecordingPolicy()
        save()
    }

    func syncTodayNow() {
        syncService.syncNow()
    }

    func deleteAllLocalData() {
        stopRecording()
        sessions.removeAll()
        segments.removeAll()
        bookmarks.removeAll()
        quickTags.removeAll()
        locations.removeAll()
        settings.lastUploadedExportFingerprint = nil
        settings.uploadedEventFingerprints.removeAll()
        currentSession = nil
        activeSegmentID = nil
        try? fileManager.removeItem(at: documentsURL.appendingPathComponent("recordings"))
        save()
    }

    func pruneExpiredData() {
        guard settings.retentionDays > 0 else { return }
        let cutoff = Calendar.current.date(byAdding: .day, value: -settings.retentionDays, to: Date()) ?? Date()
        let activeID = activeSegmentID
        let expiredSegments = segments.filter { segment in
            guard segment.id != activeID else { return false }
            let referenceDate = segment.endedAt ?? segment.observedAt
            return referenceDate < cutoff
        }
        for segment in expiredSegments {
            let url = documentsURL.appendingPathComponent(segment.mediaPath)
            try? fileManager.removeItem(at: url)
        }
        let expiredIDs = Set(expiredSegments.map(\.id))
        if !expiredIDs.isEmpty {
            segments.removeAll { expiredIDs.contains($0.id) }
        }
        bookmarks.removeAll { $0.observedAt < cutoff }
        quickTags.removeAll { $0.observedAt < cutoff }
        locations.removeAll { $0.observedAt < cutoff }
        sessions.removeAll { session in
            guard let endedAt = session.endedAt else { return false }
            return endedAt < cutoff && !segments.contains { $0.recordingSessionID == session.id }
        }
        pruneUploadedEventFingerprints()
        pruneEmptyRecordingFolders()
        save()
    }

    func makeExportArchive(onlyToday: Bool = false, onlyPending: Bool = false) throws -> URL {
        let plan = try makeExportPlan(onlyToday: onlyToday, onlyPending: onlyPending)
        return try makeExportArchive(from: plan, onlyToday: onlyToday)
    }

    private func makePendingSyncPackage(onlyToday: Bool = false) throws -> SyncUploadPackage {
        let plan = try makeExportPlan(onlyToday: onlyToday, onlyPending: true)
        return SyncUploadPackage(
            archiveURL: try makeExportArchive(from: plan, onlyToday: onlyToday),
            snapshot: try makeExportSnapshot(from: plan)
        )
    }

    private func makeExportArchive(from plan: SyncExportPlan, onlyToday: Bool) throws -> URL {
        let export = plan.export
        let exportName = "mobile-export-\(filenameTimestamp(Date()))"
        let tempRoot = fileManager.temporaryDirectory.appendingPathComponent(exportName, isDirectory: true)
        if fileManager.fileExists(atPath: tempRoot.path) {
            try fileManager.removeItem(at: tempRoot)
        }
        try fileManager.createDirectory(at: tempRoot, withIntermediateDirectories: true)

        let jsonURL = tempRoot.appendingPathComponent("mobile-export.json")
        let json = try JSONEncoder.captureEncoder(prettyPrinted: true).encode(export)
        try json.write(to: jsonURL, options: .atomic)

        var entries: [(source: URL, path: String)] = [(jsonURL, "mobile-export.json")]
        var copiedPaths = Set<String>()
        let exportedEventIDs = Set(export.events.map(\.id))
        for segment in exportedSegments(onlyToday: onlyToday) {
            guard exportedEventIDs.contains(segment.id) else { continue }
            guard !segment.mediaPath.isEmpty, copiedPaths.insert(segment.mediaPath).inserted else {
                continue
            }
            let source = documentsURL.appendingPathComponent(segment.mediaPath)
            guard fileManager.fileExists(atPath: source.path) else { continue }
            entries.append((source, segment.mediaPath))
        }

        let zipURL = fileManager.temporaryDirectory.appendingPathComponent("\(exportName).zip")
        if fileManager.fileExists(atPath: zipURL.path) {
            try fileManager.removeItem(at: zipURL)
        }
        try ZipWriter.write(entries: entries, to: zipURL)
        return zipURL
    }

    private func makeExportSnapshot(onlyToday: Bool = false, onlyPending: Bool = false) throws -> SyncPayloadSnapshot {
        let plan = try makeExportPlan(onlyToday: onlyToday, onlyPending: onlyPending)
        return try makeExportSnapshot(from: plan)
    }

    private func makeExportSnapshot(from plan: SyncExportPlan) throws -> SyncPayloadSnapshot {
        let export = plan.export
        let json = try JSONEncoder.captureEncoder(prettyPrinted: true).encode(export)
        let fingerprint = SHA256.hash(data: json).map { String(format: "%02x", $0) }.joined()
        return SyncPayloadSnapshot(
            fingerprint: fingerprint,
            eventCount: export.events.count,
            eventFingerprints: plan.eventFingerprints
        )
    }

    private func makeExportPlan(onlyToday: Bool = false, onlyPending: Bool = false) throws -> SyncExportPlan {
        let export = makeMobileExport(onlyToday: onlyToday)
        var allEventFingerprints: [String: String] = [:]
        for event in export.events {
            allEventFingerprints[event.id] = try fingerprint(for: event)
        }
        if onlyPending {
            try markLegacyExportAsUploadedIfNeeded(export: export, eventFingerprints: allEventFingerprints)
        }

        var events: [MobileExportEvent] = []
        var eventFingerprints: [String: String] = [:]
        for event in export.events {
            guard let fingerprint = allEventFingerprints[event.id] else { continue }
            if onlyPending, settings.uploadedEventFingerprints[event.id] == fingerprint {
                continue
            }
            events.append(event)
            eventFingerprints[event.id] = fingerprint
        }
        return SyncExportPlan(export: MobileExport(events: events), eventFingerprints: eventFingerprints)
    }

    private func markLegacyExportAsUploadedIfNeeded(
        export: MobileExport,
        eventFingerprints: [String: String]
    ) throws {
        guard settings.uploadedEventFingerprints.isEmpty,
              let lastUploadedExportFingerprint = settings.lastUploadedExportFingerprint else {
            return
        }
        guard try fingerprint(for: export) == lastUploadedExportFingerprint else {
            return
        }
        settings.uploadedEventFingerprints = eventFingerprints
        save()
    }

    private func fingerprint(for event: MobileExportEvent) throws -> String {
        let json = try JSONEncoder.captureEncoder(prettyPrinted: true).encode(event)
        return SHA256.hash(data: json).map { String(format: "%02x", $0) }.joined()
    }

    private func fingerprint(for export: MobileExport) throws -> String {
        let json = try JSONEncoder.captureEncoder(prettyPrinted: true).encode(export)
        return SHA256.hash(data: json).map { String(format: "%02x", $0) }.joined()
    }

    private func markUploadAccepted(_ snapshot: SyncPayloadSnapshot) {
        for (eventID, fingerprint) in snapshot.eventFingerprints {
            settings.uploadedEventFingerprints[eventID] = fingerprint
        }
        settings.lastUploadedExportFingerprint = snapshot.fingerprint
        pruneUploadedEventFingerprints()
        save()
    }

    private func countPendingUploadEvents(onlyToday: Bool) -> Int {
        let export = makeMobileExport(onlyToday: onlyToday)
        var count = 0
        for event in export.events {
            guard let fingerprint = try? fingerprint(for: event) else {
                count += 1
                continue
            }
            if settings.uploadedEventFingerprints[event.id] != fingerprint {
                count += 1
            }
        }
        return count
    }

    private func pruneUploadedEventFingerprints() {
        let liveEventIDs = Set(makeMobileExport(onlyToday: false).events.map(\.id))
        settings.uploadedEventFingerprints = settings.uploadedEventFingerprints.filter { liveEventIDs.contains($0.key) }
    }

    private func createSession() {
        let now = Date()
        let session = CaptureSessionRecord(
            id: "session-\(filenameTimestamp(now))",
            startedAt: now,
            endedAt: nil,
            state: .recording,
            segmentSeconds: settings.segmentSeconds,
            audioQuality: settings.audioQuality,
            locationMode: settings.locationMode
        )
        currentSession = session
        sessions.append(session)
    }

    private func registerAudioNotifications() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleAudioInterruption(_:)),
            name: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance()
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleRouteChange(_:)),
            name: AVAudioSession.routeChangeNotification,
            object: AVAudioSession.sharedInstance()
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleMediaServicesReset(_:)),
            name: AVAudioSession.mediaServicesWereResetNotification,
            object: AVAudioSession.sharedInstance()
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleAppDidBecomeActive(_:)),
            name: UIApplication.didBecomeActiveNotification,
            object: nil
        )
    }

    @objc private func handleAudioInterruption(_ notification: Notification) {
        guard let rawType = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: rawType)
        else { return }
        switch type {
        case .began:
            guard state == .recording else { return }
            shouldResumeAfterInterruption = true
            interruptionRecoveryTask?.cancel()
            addBookmark(title: WondL10n.t("Recording interrupted"), note: WondL10n.t("Audio session interruption began"))
            state = .interrupted
            updateCurrentSessionState(.interrupted)
            recorder?.stop()
            recorder = nil
            stopUITimer()
            notifyPassiveRecordingStop(
                title: WondL10n.t("Recording interrupted"),
                body: WondL10n.t("Audio recording stopped unexpectedly. Wond will try to resume.")
            )
            save()
        case .ended:
            let optionsRaw = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            let options = AVAudioSession.InterruptionOptions(rawValue: optionsRaw)
            let note = options.contains(.shouldResume)
                ? WondL10n.t("Audio session interruption ended; iOS allowed resume")
                : WondL10n.t("Audio session interruption ended; restoring because recording was active before interruption")
            addBookmark(title: WondL10n.t("Recording interruption ended"), note: note)
            if shouldResumeAfterInterruption {
                scheduleInterruptionRecovery(reason: note, delay: 0.8)
            }
        @unknown default:
            break
        }
    }

    @objc private func handleRouteChange(_ notification: Notification) {
        guard state == .recording || state == .paused || state == .interrupted else { return }
        let reasonRaw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
        let reason = reasonRaw.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))?.label ?? WondL10n.t("unknown")
        addBookmark(title: WondL10n.t("Audio route changed"), note: reason)
    }

    @objc private func handleMediaServicesReset(_ notification: Notification) {
        guard state == .recording || state == .paused || state == .interrupted else { return }
        shouldResumeAfterInterruption = state == .recording || state == .interrupted
        addBookmark(title: WondL10n.t("Audio service reset"), note: WondL10n.t("Media services reset by iOS"))
        state = .interrupted
        updateCurrentSessionState(.interrupted)
        recorder = nil
        stopUITimer()
        notifyPassiveRecordingStop(
            title: WondL10n.t("Recording stopped"),
            body: WondL10n.t("iOS reset audio services. Wond will try to resume recording.")
        )
        save()
        if shouldResumeAfterInterruption {
            scheduleInterruptionRecovery(reason: WondL10n.t("Media services reset by iOS"), delay: 1.5)
        }
    }

    @objc private func handleAppDidBecomeActive(_ notification: Notification) {
        guard state == .interrupted,
              currentSession?.endedAt == nil
        else { return }
        shouldResumeAfterInterruption = true
        addBookmark(title: WondL10n.t("Recording recovery check"), note: WondL10n.t("App became active while recording was interrupted"))
        scheduleInterruptionRecovery(reason: WondL10n.t("App became active while recording was interrupted"), delay: 0.5)
    }

    private func scheduleInterruptionRecovery(reason: String, delay: TimeInterval) {
        interruptionRecoveryTask?.cancel()
        interruptionRecoveryTask = Task { @MainActor [weak self] in
            let nanoseconds = UInt64(max(0, delay) * 1_000_000_000)
            if nanoseconds > 0 {
                try? await Task.sleep(nanoseconds: nanoseconds)
            }
            guard !Task.isCancelled else { return }
            await self?.resumeRecordingAfterInterruption(reason: reason)
        }
    }

    private func resumeRecordingAfterInterruption(reason: String) async {
        guard shouldResumeAfterInterruption,
              state == .interrupted,
              let currentSession,
              currentSession.endedAt == nil
        else { return }

        guard !isInSleepQuietHours() else {
            shouldResumeAfterInterruption = false
            interruptionRecoveryAttempts = 0
            stopRecordingForSleepQuietHours()
            return
        }

        interruptionRecoveryAttempts += 1
        await startRecording()

        if state == .recording {
            shouldResumeAfterInterruption = false
            interruptionRecoveryAttempts = 0
            lastError = nil
            addBookmark(title: WondL10n.t("Recording resumed after interruption"), note: reason)
            return
        }

        let failure = lastError ?? WondL10n.t("Could not restart after audio interruption")
        addBookmark(title: WondL10n.t("Recording resume failed"), note: failure)
        if interruptionRecoveryAttempts < 4 {
            scheduleInterruptionRecovery(reason: reason, delay: 5.0)
        } else {
            notifyPassiveRecordingStop(
                title: WondL10n.t("Recording could not resume"),
                body: failure
            )
        }
    }

    private func updateCurrentSessionState(_ newState: CaptureState) {
        guard var session = currentSession,
              let index = sessions.firstIndex(where: { $0.id == session.id })
        else { return }
        session.state = newState
        currentSession = session
        sessions[index] = session
    }

    private func finalizeCurrentSession() {
        guard var session = currentSession,
              let index = sessions.firstIndex(where: { $0.id == session.id })
        else { return }
        session.endedAt = Date()
        session.state = .idle
        sessions[index] = session
        currentSession = nil
    }

    private func configureAudioSession() throws {
        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .measurement, options: [])
        try audioSession.setActive(true)
    }

    private func startNewSegment() throws {
        guard let session = currentSession else { return }

        let startedAt = Date()
        if isInSleepQuietHours(startedAt) {
            stopRecordingForSleepQuietHours()
            return
        }
        requestLocationSampleIfNeeded()
        try configureAudioSession()

        let folderURL = recordingFolderURL(for: session.id, at: startedAt)
        try fileManager.createDirectory(at: folderURL, withIntermediateDirectories: true)

        let fileName = "\(filenameTimestamp(startedAt)).m4a"
        let fileURL = folderURL.appendingPathComponent(fileName)
        let relativePath = relativePath(forRecordingFile: fileURL)

        let segment = AudioSegmentRecord(
            id: "ios-audio-\(filenameTimestamp(startedAt))",
            recordingSessionID: session.id,
            observedAt: startedAt,
            endedAt: nil,
            durationSeconds: nil,
            device: UIDevice.current.name,
            mediaPath: relativePath,
            transcript: nil,
            location: nearestLocation(to: startedAt),
            fileSize: nil
        )
        segments.append(segment)
        activeSegmentID = segment.id

        let settings = audioRecorderSettings()
        let newRecorder = try AVAudioRecorder(url: fileURL, settings: settings)
        newRecorder.delegate = self
        newRecorder.isMeteringEnabled = true
        newRecorder.prepareToRecord()
        recorder = newRecorder
        let segmentDuration = TimeInterval(max(30, self.settings.segmentSeconds))
        let quietBoundary = secondsUntilSleepQuietHours(from: startedAt) ?? segmentDuration
        newRecorder.record(forDuration: min(segmentDuration, quietBoundary))
        save()
    }

    private func finishActiveSegment(successfully: Bool) {
        guard let activeSegmentID,
              let index = segments.firstIndex(where: { $0.id == activeSegmentID })
        else { return }
        let endedAt = Date()
        segments[index].endedAt = endedAt
        segments[index].durationSeconds = max(0, endedAt.timeIntervalSince(segments[index].observedAt))
        if segments[index].location == nil {
            let midpoint = segments[index].observedAt.addingTimeInterval(endedAt.timeIntervalSince(segments[index].observedAt) / 2)
            segments[index].location = nearestLocation(to: midpoint)
        }
        let fileURL = documentsURL.appendingPathComponent(segments[index].mediaPath)
        if let attributes = try? fileManager.attributesOfItem(atPath: fileURL.path),
           let size = attributes[.size] as? NSNumber {
            segments[index].fileSize = size.int64Value
        }
        if !successfully {
            lastError = WondL10n.t("The last segment did not finish cleanly.")
        }
        self.activeSegmentID = nil
        save()

        if state == .recording {
            do {
                try startNewSegment()
            } catch {
                state = .failed
                lastError = error.localizedDescription
                notifyPassiveRecordingStop(
                    title: WondL10n.t("Recording stopped"),
                    body: WondL10n.format("Could not start the next audio segment: %@", error.localizedDescription)
                )
                save()
            }
        }
    }

    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            self?.finishActiveSegment(successfully: flag)
        }
    }

    nonisolated func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        Task { @MainActor [weak self] in
            self?.state = .failed
            self?.lastError = error?.localizedDescription ?? WondL10n.t("Audio encoding failed.")
            self?.notifyPassiveRecordingStop(
                title: WondL10n.t("Recording failed"),
                body: error?.localizedDescription ?? WondL10n.t("Audio encoding failed.")
            )
            self?.save()
        }
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .list, .sound])
    }

    private func notifyPassiveRecordingStop(title: String, body: String) {
        Self.postPassiveStopNotification(title: title, body: body)
    }

    nonisolated private static func requestPassiveStopNotificationPermission() {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            guard settings.authorizationStatus == .notDetermined else { return }
            center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        }
    }

    nonisolated private static func postPassiveStopNotification(title: String, body: String) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            guard settings.authorizationStatus.canSendPassiveStopNotification else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            content.threadIdentifier = "wond-recording-stop"

            let request = UNNotificationRequest(
                identifier: "wond-recording-stop-\(UUID().uuidString)",
                content: content,
                trigger: nil
            )
            center.add(request)
        }
    }

    private func audioRecorderSettings() -> [String: Any] {
        [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: settings.audioQuality.sampleRate,
            AVNumberOfChannelsKey: 1,
            AVEncoderBitRateKey: settings.audioQuality.bitRate,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue
        ]
    }

    private func configureLocationTracking() {
        locationTimer?.invalidate()
        locationTimer = nil
        locationManager.stopUpdatingLocation()
        locationManager.stopMonitoringSignificantLocationChanges()
        isRequestingOneShotLocation = false

        guard settings.locationMode != .off else {
            locationStatusMessage = nil
            return
        }
        guard CLLocationManager.locationServicesEnabled() else {
            locationStatusMessage = WondL10n.t("Location services are disabled")
            return
        }

        switch locationManager.authorizationStatus {
        case .notDetermined:
            locationStatusMessage = WondL10n.t("Location permission requested")
            locationManager.requestWhenInUseAuthorization()
        case .restricted, .denied:
            locationStatusMessage = WondL10n.t("Location permission is disabled")
        case .authorizedWhenInUse:
            if settings.locationMode == .continuous {
                locationManager.requestAlwaysAuthorization()
            }
            startConfiguredLocationMode()
        case .authorizedAlways:
            startConfiguredLocationMode()
        @unknown default:
            locationStatusMessage = WondL10n.t("Location permission state is unknown")
        }
    }

    private func startConfiguredLocationMode() {
        locationManager.pausesLocationUpdatesAutomatically = true
        locationManager.allowsBackgroundLocationUpdates =
            settings.locationMode == .continuous && locationManager.authorizationStatus == .authorizedAlways
        locationManager.showsBackgroundLocationIndicator =
            settings.locationMode == .continuous && locationManager.authorizationStatus == .authorizedAlways

        switch settings.locationMode {
        case .off:
            locationStatusMessage = nil
        case .significantChange:
            locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
            locationManager.distanceFilter = 200
            locationManager.startMonitoringSignificantLocationChanges()
            requestLocationSampleIfNeeded()
            locationStatusMessage = latestLocation?.label ?? WondL10n.t("Waiting for location")
        case .periodic:
            locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
            locationManager.distanceFilter = 100
            requestLocationSampleIfNeeded()
            locationTimer = Timer.scheduledTimer(withTimeInterval: 300, repeats: true) { [weak self] _ in
                Task { @MainActor in
                    self?.requestLocationSampleIfNeeded()
                }
            }
            locationStatusMessage = latestLocation?.label ?? WondL10n.t("Waiting for location")
        case .continuous:
            locationManager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
            locationManager.distanceFilter = 25
            locationManager.startUpdatingLocation()
            locationStatusMessage = latestLocation?.label ?? WondL10n.t("Waiting for location")
        }
    }

    private func requestLocationSampleIfNeeded() {
        guard settings.locationMode != .off, !isRequestingOneShotLocation else { return }
        let status = locationManager.authorizationStatus
        guard status == .authorizedAlways || status == .authorizedWhenInUse else { return }
        isRequestingOneShotLocation = true
        locationManager.requestLocation()
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor [weak self] in
            self?.configureLocationTracking()
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations updates: [CLLocation]) {
        Task { @MainActor [weak self] in
            self?.isRequestingOneShotLocation = false
            for location in updates {
                self?.recordLocationUpdate(location)
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor [weak self] in
            self?.isRequestingOneShotLocation = false
            guard let self else { return }
            guard let locationError = error as? CLError else {
                self.locationStatusMessage = WondL10n.t("Location update failed")
                return
            }

            switch locationError.code {
            case .locationUnknown:
                self.locationStatusMessage = WondL10n.t("Waiting for location")
            case .denied:
                manager.stopUpdatingLocation()
                manager.stopMonitoringSignificantLocationChanges()
                self.locationStatusMessage = WondL10n.t("Location permission is disabled")
            case .network:
                self.locationStatusMessage = WondL10n.t("Location lookup is waiting for network")
            default:
                self.locationStatusMessage = WondL10n.t("Location update failed")
            }
        }
    }

    private func recordLocationUpdate(_ location: CLLocation) {
        guard settings.locationMode != .off,
              location.horizontalAccuracy >= 0,
              Date().timeIntervalSince(location.timestamp) < 60 * 60,
              shouldStoreLocation(location)
        else { return }

        let point = LocationPoint(
            id: "location-\(filenameTimestamp(location.timestamp))-\(UUID().uuidString.prefix(8))",
            observedAt: location.timestamp,
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            altitude: location.verticalAccuracy >= 0 ? location.altitude : nil,
            horizontalAccuracy: location.horizontalAccuracy,
            verticalAccuracy: location.verticalAccuracy >= 0 ? location.verticalAccuracy : nil,
            speed: location.speed >= 0 ? location.speed : nil,
            course: location.course >= 0 ? location.course : nil,
            address: nil,
            placeName: nil,
            locality: nil,
            administrativeArea: nil,
            subAdministrativeArea: nil,
            subLocality: nil,
            thoroughfare: nil,
            subThoroughfare: nil,
            isoCountryCode: nil,
            country: nil
        )
        locations.append(point)
        attachLocationToActiveRecords(point)
        locationStatusMessage = WondL10n.t("Resolving address")
        save()
        reverseGeocode(point, from: location)
    }

    private func shouldStoreLocation(_ location: CLLocation) -> Bool {
        guard let latestLocation else { return true }
        let latestCLLocation = CLLocation(
            latitude: latestLocation.latitude,
            longitude: latestLocation.longitude
        )
        let age = location.timestamp.timeIntervalSince(latestLocation.observedAt)
        let distance = location.distance(from: latestCLLocation)
        guard age > 5 || distance >= 25 else { return false }

        switch settings.locationMode {
        case .off:
            return false
        case .significantChange:
            return age >= 300 || distance >= 200
        case .periodic:
            return age >= 240 || distance >= 100
        case .continuous:
            return age >= 60 || distance >= max(25, location.horizontalAccuracy)
        }
    }

    private func reverseGeocode(_ point: LocationPoint, from location: CLLocation) {
        guard !geocoder.isGeocoding else {
            scheduleReverseGeocodeRetry(point, from: location)
            return
        }
        let now = Date()
        if let lastReverseGeocodeAt,
           let lastReverseGeocodeLocation,
           now.timeIntervalSince(lastReverseGeocodeAt) < 30,
           location.distance(from: lastReverseGeocodeLocation) < 50 {
            if let update = nearbyAddressUpdate(for: location, excludingLocationID: point.id) {
                applyAddressUpdate(update, toLocationID: point.id)
            } else {
                showCoordinateFallback(forLocationID: point.id)
            }
            return
        }
        lastReverseGeocodeAt = now
        lastReverseGeocodeLocation = location

        geocoder.reverseGeocodeLocation(location, preferredLocale: Locale.autoupdatingCurrent) { [weak self] placemarks, error in
            guard error == nil, let placemark = placemarks?.first else {
                Task { @MainActor in
                    self?.showCoordinateFallback(forLocationID: point.id)
                }
                return
            }
            let update = Self.addressUpdate(from: placemark)
            Task { @MainActor in
                self?.applyAddressUpdate(update, toLocationID: point.id)
            }
        }
    }

    private func scheduleReverseGeocodeRetry(_ point: LocationPoint, from location: CLLocation) {
        reverseGeocodeRetryTask?.cancel()
        reverseGeocodeRetryTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            self?.reverseGeocode(point, from: location)
        }
    }

    private func applyAddressUpdate(_ update: LocationAddressUpdate, toLocationID locationID: String) {
        guard let index = locations.firstIndex(where: { $0.id == locationID }) else { return }
        var point = locations[index]
        point.address = update.address
        point.placeName = update.placeName
        point.locality = update.locality
        point.administrativeArea = update.administrativeArea
        point.subAdministrativeArea = update.subAdministrativeArea
        point.subLocality = update.subLocality
        point.thoroughfare = update.thoroughfare
        point.subThoroughfare = update.subThoroughfare
        point.isoCountryCode = update.isoCountryCode
        point.country = update.country
        locations[index] = point

        for segmentIndex in segments.indices where segments[segmentIndex].location?.id == locationID {
            segments[segmentIndex].location = point
        }
        for bookmarkIndex in bookmarks.indices where bookmarks[bookmarkIndex].location?.id == locationID {
            bookmarks[bookmarkIndex].location = point
        }
        locationStatusMessage = point.label
        save()
    }

    private func showCoordinateFallback(forLocationID locationID: String) {
        guard let index = locations.firstIndex(where: { $0.id == locationID }) else { return }
        locationStatusMessage = locations[index].coordinateLabel
        save()
    }

    private func nearbyAddressUpdate(for location: CLLocation, excludingLocationID locationID: String) -> LocationAddressUpdate? {
        let candidates = locations.compactMap { point -> (LocationPoint, CLLocation)? in
            guard point.id != locationID,
                  point.address != nil || point.placeName != nil else { return nil }
            let candidateLocation = CLLocation(latitude: point.latitude, longitude: point.longitude)
            return (point, candidateLocation)
        }
        guard let nearest = candidates.min(by: {
            location.distance(from: $0.1) < location.distance(from: $1.1)
        }),
              location.distance(from: nearest.1) < 50 else { return nil }
        return addressUpdate(from: nearest.0)
    }

    private func addressUpdate(from point: LocationPoint) -> LocationAddressUpdate {
        LocationAddressUpdate(
            address: point.address,
            placeName: point.placeName,
            locality: point.locality,
            administrativeArea: point.administrativeArea,
            subAdministrativeArea: point.subAdministrativeArea,
            subLocality: point.subLocality,
            thoroughfare: point.thoroughfare,
            subThoroughfare: point.subThoroughfare,
            isoCountryCode: point.isoCountryCode,
            country: point.country
        )
    }

    private func attachLocationToActiveRecords(_ point: LocationPoint) {
        if let activeSegmentID,
           let index = segments.firstIndex(where: { $0.id == activeSegmentID }),
           segments[index].location == nil {
            segments[index].location = point
        }
    }

    private func nearestLocation(to date: Date, maximumAge: TimeInterval = 2 * 60 * 60) -> LocationPoint? {
        guard let nearest = locations.min(by: {
            abs($0.observedAt.timeIntervalSince(date)) < abs($1.observedAt.timeIntervalSince(date))
        }) else { return nil }
        guard abs(nearest.observedAt.timeIntervalSince(date)) <= maximumAge else { return nil }
        return nearest
    }

    nonisolated private static func addressUpdate(from placemark: CLPlacemark) -> LocationAddressUpdate {
        LocationAddressUpdate(
            address: formattedAddress(from: placemark),
            placeName: firstNonEmpty(placemark.areasOfInterest?.first, placemark.name),
            locality: cleanAddressPart(placemark.locality),
            administrativeArea: cleanAddressPart(placemark.administrativeArea),
            subAdministrativeArea: cleanAddressPart(placemark.subAdministrativeArea),
            subLocality: cleanAddressPart(placemark.subLocality),
            thoroughfare: cleanAddressPart(placemark.thoroughfare),
            subThoroughfare: cleanAddressPart(placemark.subThoroughfare),
            isoCountryCode: cleanAddressPart(placemark.isoCountryCode),
            country: cleanAddressPart(placemark.country)
        )
    }

    nonisolated private static func formattedAddress(from placemark: CLPlacemark) -> String? {
        let isoCountryCode = placemark.isoCountryCode?.uppercased()
        let compactRegion = ["CN", "HK", "JP", "MO", "TW"].contains(isoCountryCode)
        let street = streetAddress(from: placemark, compact: compactRegion)
        var parts: [String] = []

        if compactRegion {
            appendAddressPart(placemark.administrativeArea, to: &parts)
            appendAddressPart(placemark.subAdministrativeArea, to: &parts)
            appendAddressPart(placemark.locality, to: &parts)
            appendAddressPart(placemark.subLocality, to: &parts)
            appendAddressPart(street, to: &parts)
            return cleanAddressPart(parts.joined())
        }

        appendAddressPart(street, to: &parts)
        appendAddressPart(placemark.subLocality, to: &parts)
        appendAddressPart(placemark.locality, to: &parts)
        appendAddressPart(placemark.administrativeArea, to: &parts)
        return cleanAddressPart(parts.joined(separator: ", "))
    }

    nonisolated private static func streetAddress(from placemark: CLPlacemark, compact: Bool) -> String? {
        let thoroughfare = cleanAddressPart(placemark.thoroughfare)
        let subThoroughfare = cleanAddressPart(placemark.subThoroughfare)
        if compact {
            return cleanAddressPart([thoroughfare, subThoroughfare].compactMap(\.self).joined())
        }
        if let thoroughfare, let subThoroughfare {
            return "\(subThoroughfare) \(thoroughfare)"
        }
        return thoroughfare ?? subThoroughfare
    }

    nonisolated private static func appendAddressPart(_ value: String?, to parts: inout [String]) {
        guard let part = cleanAddressPart(value) else { return }
        if parts.contains(part) { return }
        if let last = parts.last {
            if part.hasPrefix(last) {
                parts[parts.count - 1] = part
                return
            }
            if last.hasPrefix(part) {
                return
            }
        }
        parts.append(part)
    }

    nonisolated private static func firstNonEmpty(_ values: String?...) -> String? {
        for value in values {
            if let clean = cleanAddressPart(value) {
                return clean
            }
        }
        return nil
    }

    nonisolated private static func cleanAddressPart(_ value: String?) -> String? {
        guard let value else { return nil }
        let cleaned = value
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? nil : cleaned
    }

    private func isInSleepQuietHours(_ date: Date = Date()) -> Bool {
        guard settings.sleepQuietHoursEnabled else { return false }
        let calendar = Calendar.current
        for dayOffset in -1...0 {
            guard let anchorDate = calendar.date(byAdding: .day, value: dayOffset, to: date) else { continue }
            let anchorStart = calendar.startOfDay(for: anchorDate)
            let weekdayRaw = calendar.component(.weekday, from: anchorStart)
            guard let weekday = QuietWeekday(rawValue: weekdayRaw) else { continue }
            let interval = sleepQuietInterval(for: weekday)
            guard let window = quietWindow(for: interval, anchoredTo: anchorStart, calendar: calendar) else { continue }
            if date >= window.start && date < window.end {
                return true
            }
        }
        return false
    }

    private func enforceSleepQuietRecordingPolicy() {
        guard isInSleepQuietHours() else { return }
        stopRecordingForSleepQuietHours()
    }

    private func stopRecordingForSleepQuietHours() {
        guard currentSession != nil else {
            recorder?.stop()
            recorder = nil
            stopUITimer()
            if state != .idle {
                state = .idle
                save()
            }
            return
        }

        addBookmark(
            title: WondL10n.t("Recording stopped for quiet hours"),
            note: WondL10n.t("Quiet schedule is active")
        )
        notifyPassiveRecordingStop(
            title: WondL10n.t("Recording stopped for quiet hours"),
            body: WondL10n.t("The quiet schedule is active, so Wond stopped recording.")
        )
        stopRecording()
    }

    private func secondsUntilSleepQuietHours(from date: Date) -> TimeInterval? {
        guard settings.sleepQuietHoursEnabled, !isInSleepQuietHours(date) else { return nil }
        let calendar = Calendar.current
        var nearest: Date?

        for dayOffset in 0...7 {
            guard let candidateDate = calendar.date(byAdding: .day, value: dayOffset, to: date) else { continue }
            let anchorStart = calendar.startOfDay(for: candidateDate)
            let weekdayRaw = calendar.component(.weekday, from: anchorStart)
            guard let weekday = QuietWeekday(rawValue: weekdayRaw) else { continue }
            let interval = sleepQuietInterval(for: weekday)
            guard let window = quietWindow(for: interval, anchoredTo: anchorStart, calendar: calendar),
                  window.start > date
            else { continue }
            if nearest == nil || window.start < nearest! {
                nearest = window.start
            }
        }

        guard let nearest else { return nil }
        return max(1, nearest.timeIntervalSince(date))
    }

    private func quietWindow(
        for interval: SleepQuietInterval,
        anchoredTo anchorStart: Date,
        calendar: Calendar
    ) -> (start: Date, end: Date)? {
        guard interval.enabled,
              let start = quietDate(for: interval.startMinute, anchoredTo: anchorStart, calendar: calendar),
              var end = quietDate(for: interval.endMinute, anchoredTo: anchorStart, calendar: calendar)
        else { return nil }
        if end <= start {
            end = calendar.date(byAdding: .day, value: 1, to: end) ?? end
        }
        return (start, end)
    }

    private func quietDate(for minute: Int, anchoredTo anchorStart: Date, calendar: Calendar) -> Date? {
        let dayOffset = quietDayOffset(for: minute)
        guard let dayStart = calendar.date(byAdding: .day, value: dayOffset, to: anchorStart) else { return nil }
        return calendar.date(byAdding: .minute, value: minute, to: dayStart)
    }

    private func quietDayOffset(for minute: Int) -> Int {
        minute < Self.sleepDayRolloverMinute ? 1 : 0
    }

    private static let sleepDayRolloverMinute = 12 * 60

    private func makeMobileExport(onlyToday: Bool = false) -> MobileExport {
        var events: [MobileExportEvent] = []
        for segment in exportedSegments(onlyToday: onlyToday).sorted(by: { $0.observedAt < $1.observedAt }) {
            events.append(
                MobileExportEvent(
                    id: segment.id,
                    kind: "audio_segment",
                    recordingSessionID: segment.recordingSessionID,
                    observedAt: segment.observedAt,
                    endedAt: segment.endedAt,
                    durationSeconds: segment.durationSeconds,
                    device: segment.device,
                    mediaPath: segment.mediaPath,
                    transcript: segment.transcript,
                    title: WondL10n.t("Audio segment"),
                    note: nil,
                    location: segment.location.map(MobileExportLocation.init)
                )
            )
        }
        let bookmarkRows = onlyToday ? todayBookmarks : bookmarks
        for bookmark in bookmarkRows.sorted(by: { $0.observedAt < $1.observedAt }) {
            events.append(
                MobileExportEvent(
                    id: bookmark.id,
                    kind: "bookmark",
                    recordingSessionID: bookmark.recordingSessionID,
                    observedAt: bookmark.observedAt,
                    endedAt: nil,
                    durationSeconds: nil,
                    device: UIDevice.current.name,
                    mediaPath: nil,
                    transcript: nil,
                    title: bookmark.title,
                    note: bookmark.note,
                    location: bookmark.location.map(MobileExportLocation.init)
                )
            )
        }
        let quickTagRows = onlyToday ? todayQuickTags : quickTags
        for quickTag in quickTagRows.sorted(by: { $0.observedAt < $1.observedAt }) {
            events.append(
                MobileExportEvent(
                    id: quickTag.id,
                    kind: "quick_tag",
                    recordingSessionID: quickTag.recordingSessionID,
                    observedAt: quickTag.observedAt,
                    endedAt: nil,
                    durationSeconds: nil,
                    device: quickTag.device,
                    mediaPath: nil,
                    transcript: nil,
                    title: quickTag.title,
                    note: quickTag.note,
                    tag: quickTag.tag,
                    sourceRef: quickTag.sourceRef,
                    location: quickTag.location.map(MobileExportLocation.init),
                    metadata: [
                        "tag": quickTag.tag,
                        "source_ref": quickTag.sourceRef ?? "",
                        "recording_session_id": quickTag.recordingSessionID ?? ""
                    ].filter { !$0.value.isEmpty }
                )
            )
        }
        let locationRows = onlyToday ? todayLocations : locations
        for location in locationRows.sorted(by: { $0.observedAt < $1.observedAt }) {
            events.append(
                MobileExportEvent(
                    id: location.id,
                    kind: "location_sample",
                    recordingSessionID: nil,
                    observedAt: location.observedAt,
                    endedAt: nil,
                    durationSeconds: nil,
                    device: UIDevice.current.name,
                    mediaPath: nil,
                    transcript: nil,
                    title: WondL10n.t("Location sample"),
                    note: location.address ?? location.placeName,
                    location: MobileExportLocation(location)
                )
            )
        }
        events.sort { $0.observedAt < $1.observedAt }
        return MobileExport(events: events)
    }

    private func exportedSegments(onlyToday: Bool) -> [AudioSegmentRecord] {
        let rows = onlyToday ? todaySegments : segments
        if onlyToday {
            return rows.filter { $0.endedAt != nil }
        }
        return rows
    }

    private func recordSyncStatus(_ message: String, at date: Date?) {
        settings.lastSyncStatus = message
        if let date {
            settings.lastSyncAt = date
        }
        save()
    }

    private func repairDocumentsDirectoryIfNeeded() {
        persistence.repairDocumentsDirectoryIfNeeded()
    }

    private func requestMicrophonePermission() async -> Bool {
        await withCheckedContinuation { continuation in
            if #available(iOS 17.0, *) {
                AVAudioApplication.requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            } else {
                AVAudioSession.sharedInstance().requestRecordPermission { granted in
                    continuation.resume(returning: granted)
                }
            }
        }
    }

    private func startUITimer() {
        uiTimer?.invalidate()
        uiTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refreshTimers()
            }
        }
        refreshTimers()
    }

    private func stopUITimer() {
        uiTimer?.invalidate()
        uiTimer = nil
        refreshTimers()
    }

    private func refreshTimers() {
        guard let session = currentSession else {
            elapsedSeconds = 0
            currentSegmentSeconds = 0
            return
        }
        elapsedSeconds = Date().timeIntervalSince(session.startedAt)
        if let currentSegment {
            currentSegmentSeconds = Date().timeIntervalSince(currentSegment.observedAt)
        } else {
            currentSegmentSeconds = 0
        }
    }

    private func recordingFolderURL(for sessionID: String, at date: Date) -> URL {
        persistence.recordingFolderURL(for: sessionID, at: date, dayFormatter: Self.dayFormatter)
    }

    private func relativePath(forRecordingFile fileURL: URL) -> String {
        persistence.relativePath(forRecordingFile: fileURL)
    }

    private func pruneEmptyRecordingFolders() {
        persistence.pruneEmptyRecordingFolders()
    }

    private func save() {
        guard !didFailLoadingDatabase else {
            lastError = WondL10n.t("Local data could not be loaded, so changes were not saved.")
            return
        }
        let database = CaptureDatabase(
            sessions: sessions,
            segments: segments,
            bookmarks: bookmarks,
            quickTags: quickTags,
            locations: locations,
            settings: settings
        )
        do {
            try persistence.save(database)
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func load() {
        do {
            guard let database = try persistence.load() else { return }
            sessions = database.sessions
            segments = database.segments
            bookmarks = database.bookmarks
            quickTags = database.quickTags
            locations = database.locations
            settings = database.settings
        } catch {
            didFailLoadingDatabase = true
            persistence.backupUnreadableDatabase(timestamp: filenameTimestamp(Date()))
            lastError = error.localizedDescription
        }
    }

    private func filterToday<T>(_ values: [T], date keyPath: KeyPath<T, Date>) -> [T] {
        let calendar = Calendar.current
        return values.filter { calendar.isDateInToday($0[keyPath: keyPath]) }
    }

    private func filenameTimestamp(_ date: Date) -> String {
        Self.fileFormatter.string(from: date)
    }

    private static let fileFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd-HHmmss"
        return formatter
    }()

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}

private extension AVAudioSession.RouteChangeReason {
    var label: String {
        switch self {
        case .unknown:
            return WondL10n.t("unknown")
        case .newDeviceAvailable:
            return WondL10n.t("new device available")
        case .oldDeviceUnavailable:
            return WondL10n.t("old device unavailable")
        case .categoryChange:
            return WondL10n.t("category change")
        case .override:
            return WondL10n.t("override")
        case .wakeFromSleep:
            return WondL10n.t("wake from sleep")
        case .noSuitableRouteForCategory:
            return WondL10n.t("no suitable route")
        case .routeConfigurationChange:
            return WondL10n.t("route configuration change")
        @unknown default:
            return WondL10n.t("unknown")
        }
    }
}

private extension UNAuthorizationStatus {
    var canSendPassiveStopNotification: Bool {
        switch self {
        case .authorized, .provisional, .ephemeral:
            return true
        case .notDetermined, .denied:
            return false
        @unknown default:
            return false
        }
    }
}
