import Foundation

enum CaptureState: String, Codable {
    case idle
    case recording
    case paused
    case interrupted
    case permissionNeeded
    case failed

    var title: String {
        switch self {
        case .idle:
            return WondL10n.t("Stopped")
        case .recording:
            return WondL10n.t("Recording")
        case .paused:
            return WondL10n.t("Paused")
        case .interrupted:
            return WondL10n.t("Interrupted")
        case .permissionNeeded:
            return WondL10n.t("Permission Needed")
        case .failed:
            return WondL10n.t("Error")
        }
    }
}

enum AudioQuality: String, Codable, CaseIterable, Identifiable {
    case speech
    case balanced
    case high

    var id: String { rawValue }

    var title: String {
        switch self {
        case .speech:
            return WondL10n.t("Speech")
        case .balanced:
            return WondL10n.t("Balanced")
        case .high:
            return WondL10n.t("High")
        }
    }

    var sampleRate: Double {
        switch self {
        case .speech:
            return 16_000
        case .balanced:
            return 24_000
        case .high:
            return 44_100
        }
    }

    var bitRate: Int {
        switch self {
        case .speech:
            return 32_000
        case .balanced:
            return 64_000
        case .high:
            return 128_000
        }
    }
}

enum LocationMode: String, Codable, CaseIterable, Identifiable {
    case off
    case significantChange
    case periodic
    case continuous

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off:
            return WondL10n.t("Off")
        case .significantChange:
            return WondL10n.t("Significant Change")
        case .periodic:
            return WondL10n.t("Periodic")
        case .continuous:
            return WondL10n.t("Continuous")
        }
    }
}

enum QuickTagKind: String, Codable, CaseIterable, Identifiable {
    case important
    case todo
    case idea
    case meeting
    case ignore

    var id: String { rawValue }

    var title: String {
        switch self {
        case .important:
            return WondL10n.t("Important")
        case .todo:
            return WondL10n.t("To Do")
        case .idea:
            return WondL10n.t("Idea")
        case .meeting:
            return WondL10n.t("Meeting")
        case .ignore:
            return WondL10n.t("Ignore")
        }
    }

    var iconName: String {
        switch self {
        case .important:
            return "star.fill"
        case .todo:
            return "checkmark.circle.fill"
        case .idea:
            return "lightbulb.fill"
        case .meeting:
            return "person.2.fill"
        case .ignore:
            return "eye.slash.fill"
        }
    }

    var defaultNote: String {
        switch self {
        case .important:
            return WondL10n.t("Marked important on mobile")
        case .todo:
            return WondL10n.t("Marked as follow-up on mobile")
        case .idea:
            return WondL10n.t("Marked as an idea on mobile")
        case .meeting:
            return WondL10n.t("Marked as meeting context on mobile")
        case .ignore:
            return WondL10n.t("Marked to ignore in summaries")
        }
    }
}

enum QuietWeekday: Int, Codable, CaseIterable, Identifiable {
    case sunday = 1
    case monday = 2
    case tuesday = 3
    case wednesday = 4
    case thursday = 5
    case friday = 6
    case saturday = 7

    var id: Int { rawValue }

    static let settingsOrder: [QuietWeekday] = [
        .monday,
        .tuesday,
        .wednesday,
        .thursday,
        .friday,
        .saturday,
        .sunday
    ]

    var title: String {
        switch self {
        case .monday:
            return WondL10n.t("Monday")
        case .tuesday:
            return WondL10n.t("Tuesday")
        case .wednesday:
            return WondL10n.t("Wednesday")
        case .thursday:
            return WondL10n.t("Thursday")
        case .friday:
            return WondL10n.t("Friday")
        case .saturday:
            return WondL10n.t("Saturday")
        case .sunday:
            return WondL10n.t("Sunday")
        }
    }
}

struct SleepQuietInterval: Codable, Equatable, Identifiable {
    var weekday: QuietWeekday
    var enabled: Bool
    var startMinute: Int
    var endMinute: Int

    var id: Int { weekday.rawValue }

    init(
        weekday: QuietWeekday,
        enabled: Bool = true,
        startMinute: Int = 23 * 60,
        endMinute: Int = 7 * 60
    ) {
        self.weekday = weekday
        self.enabled = enabled
        self.startMinute = Self.clampedMinute(startMinute)
        self.endMinute = Self.clampedMinute(endMinute)
    }

    static func defaultWeek(startHour: Int = 23, endHour: Int = 7) -> [SleepQuietInterval] {
        let start = clampedHour(startHour) * 60
        let end = clampedHour(endHour) * 60
        return QuietWeekday.allCases.map {
            SleepQuietInterval(weekday: $0, startMinute: start, endMinute: end)
        }
    }

    static func normalized(
        _ intervals: [SleepQuietInterval],
        fallbackStartHour: Int = 23,
        fallbackEndHour: Int = 7
    ) -> [SleepQuietInterval] {
        let fallback = Dictionary(
            uniqueKeysWithValues: defaultWeek(startHour: fallbackStartHour, endHour: fallbackEndHour).map {
                ($0.weekday, $0)
            }
        )
        let provided = intervals.reduce(into: [QuietWeekday: SleepQuietInterval]()) { result, interval in
            result[interval.weekday] = interval
        }

        return QuietWeekday.allCases.map { weekday in
            let interval = provided[weekday] ?? fallback[weekday] ?? SleepQuietInterval(weekday: weekday)
            return SleepQuietInterval(
                weekday: weekday,
                enabled: interval.enabled,
                startMinute: interval.startMinute,
                endMinute: interval.endMinute
            )
        }
    }

    private static func clampedHour(_ value: Int) -> Int {
        max(0, min(23, value))
    }

    private static func clampedMinute(_ value: Int) -> Int {
        max(0, min(23 * 60 + 59, value))
    }
}

struct CaptureSettings: Codable, Equatable {
    var segmentSeconds: Int = 300
    var audioQuality: AudioQuality = .balanced
    var locationMode: LocationMode = .off
    var retentionDays: Int = 30
    var autoSyncEnabled: Bool = false
    var syncToken: String = ""
    var remoteSyncURL: String = ""
    var wifiOnlyAutoSync: Bool = true
    var lastSyncAt: Date?
    var lastSyncStatus: String?
    var lastUploadedExportFingerprint: String?
    var uploadedEventFingerprints: [String: String] = [:]
    var sleepQuietHoursEnabled: Bool = true
    var sleepQuietStartHour: Int = 23
    var sleepQuietEndHour: Int = 7
    var sleepQuietSchedule: [SleepQuietInterval] = SleepQuietInterval.defaultWeek()

    enum CodingKeys: String, CodingKey {
        case segmentSeconds
        case audioQuality
        case locationMode
        case retentionDays
        case autoSyncEnabled
        case syncToken
        case remoteSyncURL
        case wifiOnlyAutoSync
        case lastSyncAt
        case lastSyncStatus
        case lastUploadedExportFingerprint
        case uploadedEventFingerprints
        case sleepQuietHoursEnabled
        case sleepQuietStartHour
        case sleepQuietEndHour
        case sleepQuietSchedule
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        segmentSeconds = try container.decodeIfPresent(Int.self, forKey: .segmentSeconds) ?? 300
        audioQuality = try container.decodeIfPresent(AudioQuality.self, forKey: .audioQuality) ?? .balanced
        locationMode = try container.decodeIfPresent(LocationMode.self, forKey: .locationMode) ?? .off
        retentionDays = try container.decodeIfPresent(Int.self, forKey: .retentionDays) ?? 30
        autoSyncEnabled = try container.decodeIfPresent(Bool.self, forKey: .autoSyncEnabled) ?? false
        syncToken = try container.decodeIfPresent(String.self, forKey: .syncToken) ?? ""
        remoteSyncURL = try container.decodeIfPresent(String.self, forKey: .remoteSyncURL) ?? ""
        wifiOnlyAutoSync = try container.decodeIfPresent(Bool.self, forKey: .wifiOnlyAutoSync) ?? true
        lastSyncAt = try container.decodeIfPresent(Date.self, forKey: .lastSyncAt)
        lastSyncStatus = try container.decodeIfPresent(String.self, forKey: .lastSyncStatus)
        lastUploadedExportFingerprint = try container.decodeIfPresent(String.self, forKey: .lastUploadedExportFingerprint)
        uploadedEventFingerprints = try container.decodeIfPresent([String: String].self, forKey: .uploadedEventFingerprints) ?? [:]
        sleepQuietHoursEnabled = try container.decodeIfPresent(Bool.self, forKey: .sleepQuietHoursEnabled) ?? true
        sleepQuietStartHour = try container.decodeIfPresent(Int.self, forKey: .sleepQuietStartHour) ?? 23
        sleepQuietEndHour = try container.decodeIfPresent(Int.self, forKey: .sleepQuietEndHour) ?? 7
        let decodedSchedule = try container.decodeIfPresent([SleepQuietInterval].self, forKey: .sleepQuietSchedule)
        sleepQuietSchedule = SleepQuietInterval.normalized(
            decodedSchedule ?? SleepQuietInterval.defaultWeek(
                startHour: sleepQuietStartHour,
                endHour: sleepQuietEndHour
            ),
            fallbackStartHour: sleepQuietStartHour,
            fallbackEndHour: sleepQuietEndHour
        )
    }
}

struct CaptureSessionRecord: Identifiable, Codable, Equatable {
    var id: String
    var startedAt: Date
    var endedAt: Date?
    var state: CaptureState
    var segmentSeconds: Int
    var audioQuality: AudioQuality
    var locationMode: LocationMode
}

struct LocationPoint: Identifiable, Codable, Equatable {
    var id: String
    var observedAt: Date
    var latitude: Double
    var longitude: Double
    var altitude: Double?
    var horizontalAccuracy: Double
    var verticalAccuracy: Double?
    var speed: Double?
    var course: Double?
    var address: String?
    var placeName: String?
    var locality: String?
    var administrativeArea: String?
    var subAdministrativeArea: String?
    var subLocality: String?
    var thoroughfare: String?
    var subThoroughfare: String?
    var isoCountryCode: String?
    var country: String?

    var label: String {
        address ?? placeName ?? WondL10n.t("Address pending")
    }

    var coordinateLabel: String {
        "\(latitude.formatted(.number.precision(.fractionLength(5)))), \(longitude.formatted(.number.precision(.fractionLength(5))))"
    }
}

struct AudioSegmentRecord: Identifiable, Codable, Equatable {
    var id: String
    var recordingSessionID: String
    var observedAt: Date
    var endedAt: Date?
    var durationSeconds: Double?
    var device: String
    var mediaPath: String
    var transcript: String?
    var location: LocationPoint?
    var fileSize: Int64?
}

struct BookmarkRecord: Identifiable, Codable, Equatable {
    var id: String
    var recordingSessionID: String?
    var observedAt: Date
    var title: String
    var note: String?
    var location: LocationPoint?
}

struct QuickTagRecord: Identifiable, Codable, Equatable {
    var id: String
    var recordingSessionID: String?
    var observedAt: Date
    var tag: String
    var title: String
    var note: String?
    var device: String
    var sourceRef: String?
    var location: LocationPoint?
}

struct CaptureDatabase: Codable {
    var sessions: [CaptureSessionRecord] = []
    var segments: [AudioSegmentRecord] = []
    var bookmarks: [BookmarkRecord] = []
    var quickTags: [QuickTagRecord] = []
    var locations: [LocationPoint] = []
    var settings: CaptureSettings = CaptureSettings()
}

struct MobileExport: Encodable {
    var events: [MobileExportEvent]
}

struct MobileExportEvent: Encodable {
    var id: String
    var kind: String
    var recordingSessionID: String?
    var observedAt: Date
    var endedAt: Date?
    var durationSeconds: Double?
    var device: String?
    var mediaPath: String?
    var transcript: String?
    var title: String?
    var note: String?
    var tag: String? = nil
    var sourceRef: String? = nil
    var location: MobileExportLocation?
    var metadata: [String: String]? = nil

    enum CodingKeys: String, CodingKey {
        case id
        case kind
        case recordingSessionID = "recording_session_id"
        case observedAt = "observed_at"
        case endedAt = "ended_at"
        case durationSeconds = "duration_seconds"
        case device
        case mediaPath = "media_path"
        case transcript
        case title
        case note
        case tag
        case sourceRef = "source_ref"
        case location
        case metadata
    }
}

struct MobileExportLocation: Encodable {
    var latitude: Double
    var longitude: Double
    var altitude: Double?
    var horizontalAccuracy: Double
    var verticalAccuracy: Double?
    var speed: Double?
    var course: Double?
    var address: String?
    var placeName: String?
    var locality: String?
    var administrativeArea: String?
    var subAdministrativeArea: String?
    var subLocality: String?
    var thoroughfare: String?
    var subThoroughfare: String?
    var isoCountryCode: String?
    var country: String?

    init(_ point: LocationPoint) {
        latitude = point.latitude
        longitude = point.longitude
        altitude = point.altitude
        horizontalAccuracy = point.horizontalAccuracy
        verticalAccuracy = point.verticalAccuracy
        speed = point.speed
        course = point.course
        address = point.address
        placeName = point.placeName
        locality = point.locality
        administrativeArea = point.administrativeArea
        subAdministrativeArea = point.subAdministrativeArea
        subLocality = point.subLocality
        thoroughfare = point.thoroughfare
        subThoroughfare = point.subThoroughfare
        isoCountryCode = point.isoCountryCode
        country = point.country
    }

    enum CodingKeys: String, CodingKey {
        case latitude
        case longitude
        case altitude
        case horizontalAccuracy = "horizontal_accuracy"
        case verticalAccuracy = "vertical_accuracy"
        case speed
        case course
        case address
        case placeName = "place_name"
        case locality
        case administrativeArea = "administrative_area"
        case subAdministrativeArea = "sub_administrative_area"
        case subLocality = "sub_locality"
        case thoroughfare
        case subThoroughfare = "sub_thoroughfare"
        case isoCountryCode = "iso_country_code"
        case country
    }
}

struct SpeakerReviewResponse: Decodable {
    var ok: Bool
    var speakers: [SpeakerReviewItem]
}

struct SpeakerReviewItem: Identifiable, Decodable, Equatable {
    var id: Int
    var displayName: String
    var identityStatus: String
    var confidence: Double?
    var sampleCount: Int
    var observationCount: Int
    var dayCount: Int
    var firstSeenAt: String?
    var latestSeenAt: String?
    var latestSampleAt: String?
    var samples: [SpeakerReviewSample]

    enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case identityStatus = "identity_status"
        case confidence
        case sampleCount = "sample_count"
        case observationCount = "observation_count"
        case dayCount = "day_count"
        case firstSeenAt = "first_seen_at"
        case latestSeenAt = "latest_seen_at"
        case latestSampleAt = "latest_sample_at"
        case samples
    }
}

struct SpeakerReviewSample: Identifiable, Decodable, Equatable {
    var id: Int
    var createdAt: String?
    var startSeconds: Double?
    var endSeconds: Double?
    var durationSeconds: Double?
    var transcript: String?
    var hasAudio: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case createdAt = "created_at"
        case startSeconds = "start_seconds"
        case endSeconds = "end_seconds"
        case durationSeconds = "duration_seconds"
        case transcript
        case hasAudio = "has_audio"
    }
}

struct NameSpeakerRequest: Encodable {
    var speakerID: Int
    var displayName: String

    enum CodingKeys: String, CodingKey {
        case speakerID = "speaker_id"
        case displayName = "display_name"
    }
}

struct AskRequest: Encodable {
    var question: String
}

struct AskResponse: Decodable, Equatable {
    var ok: Bool
    var answer: String?
    var error: String?
    var citations: [AskCitation]
    var retrieval: AskRetrieval?
    var mode: String?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ok = try container.decode(Bool.self, forKey: .ok)
        answer = try container.decodeIfPresent(String.self, forKey: .answer)
        error = try container.decodeIfPresent(String.self, forKey: .error)
        citations = try container.decodeIfPresent([AskCitation].self, forKey: .citations) ?? []
        retrieval = try container.decodeIfPresent(AskRetrieval.self, forKey: .retrieval)
        mode = try container.decodeIfPresent(String.self, forKey: .mode)
    }

    enum CodingKeys: String, CodingKey {
        case ok
        case answer
        case error
        case citations
        case retrieval
        case mode
    }
}

struct MacStatusResponse: Decodable, Equatable {
    var ok: Bool
    var service: String?
    var macOnline: Bool?
    var generatedAt: String?
    var lastMobileObservedAt: String?
    var lastMobileCapturedAt: String?
    var pendingServerImportFiles: Int?
    var audio: MacAudioStatus?
    var failures: [MacFailureReason]
    var recentMobile: [MacRecentMobileEvent]

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ok = try container.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        service = try container.decodeIfPresent(String.self, forKey: .service)
        macOnline = try container.decodeIfPresent(Bool.self, forKey: .macOnline)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        lastMobileObservedAt = try container.decodeIfPresent(String.self, forKey: .lastMobileObservedAt)
        lastMobileCapturedAt = try container.decodeIfPresent(String.self, forKey: .lastMobileCapturedAt)
        pendingServerImportFiles = try container.decodeIfPresent(Int.self, forKey: .pendingServerImportFiles)
        audio = try container.decodeIfPresent(MacAudioStatus.self, forKey: .audio)
        failures = try container.decodeIfPresent([MacFailureReason].self, forKey: .failures) ?? []
        recentMobile = try container.decodeIfPresent([MacRecentMobileEvent].self, forKey: .recentMobile) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case ok
        case service
        case macOnline = "mac_online"
        case generatedAt = "generated_at"
        case lastMobileObservedAt = "last_mobile_observed_at"
        case lastMobileCapturedAt = "last_mobile_captured_at"
        case pendingServerImportFiles = "pending_server_import_files"
        case audio
        case failures
        case recentMobile = "recent_mobile"
    }
}

struct MacAudioStatus: Decodable, Equatable {
    var total: Int
    var statuses: [String: Int]
    var pending: Int
    var errors: Int
    var complete: Bool
    var latestAnalyzed: String?

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        total = try container.decodeIfPresent(Int.self, forKey: .total) ?? 0
        statuses = try container.decodeIfPresent([String: Int].self, forKey: .statuses) ?? [:]
        pending = try container.decodeIfPresent(Int.self, forKey: .pending) ?? 0
        errors = try container.decodeIfPresent(Int.self, forKey: .errors) ?? 0
        complete = try container.decodeIfPresent(Bool.self, forKey: .complete) ?? false
        latestAnalyzed = try container.decodeIfPresent(String.self, forKey: .latestAnalyzed)
    }

    enum CodingKeys: String, CodingKey {
        case total
        case statuses
        case pending
        case errors
        case complete
        case latestAnalyzed = "latest_analyzed"
    }
}

struct MacFailureReason: Identifiable, Decodable, Equatable {
    var observedAt: String?
    var title: String?
    var error: String?

    var id: String {
        [observedAt, title, error].compactMap { $0 }.joined(separator: "|")
    }

    enum CodingKeys: String, CodingKey {
        case observedAt = "observed_at"
        case title
        case error
    }
}

struct MacRecentMobileEvent: Identifiable, Decodable, Equatable {
    var observedAt: String?
    var kind: String?
    var title: String?
    var capturedAt: String?

    var id: String {
        [observedAt, kind, title, capturedAt].compactMap { $0 }.joined(separator: "|")
    }

    enum CodingKeys: String, CodingKey {
        case observedAt = "observed_at"
        case kind
        case title
        case capturedAt = "captured_at"
    }
}

struct AskRetrieval: Decodable, Equatable {
    var status: String?
    var mode: String?
    var model: String?
    var indexed: Int?
    var error: String?
}

struct AskCitation: Identifiable, Decodable, Equatable {
    var type: String?
    var key: String?
    var score: Double?
    var time: String?
    var source: String?
    var kind: String?
    var path: String?
    var name: String?
    var observationID: Int?

    var id: String {
        [
            type,
            key,
            observationID.map(String.init),
            path,
            name,
            time,
            source,
            kind,
            score.map { String(format: "%.4f", $0) }
        ]
        .compactMap { $0 }
        .joined(separator: "|")
    }

    enum CodingKeys: String, CodingKey {
        case type
        case key
        case score
        case time
        case source
        case kind
        case path
        case name
        case observationID = "id"
    }
}

extension ISO8601DateFormatter {
    static let capture: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()
}

extension JSONEncoder {
    static func captureEncoder(prettyPrinted: Bool = false) -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(ISO8601DateFormatter.capture.string(from: date))
        }
        if prettyPrinted {
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        }
        return encoder
    }
}

extension JSONDecoder {
    static func captureDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            if let date = ISO8601DateFormatter.capture.date(from: value) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Invalid ISO8601 date: \(value)"
            )
        }
        return decoder
    }
}
