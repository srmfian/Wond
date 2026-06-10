import AVFoundation
import SwiftUI

struct MobileSpeakersResponse: Decodable {
    var ok: Bool?
    var error: String?
    var speakers: [MobileSpeaker]
    var samples: [MobileSpeakerSample]
    var summary: MobileSpeakersSummary?
    var speakerCounts: [String: Int]
    var speakerTotal: Int?
    var speakersTruncated: Bool?
    var sampleCounts: [String: Int]
    var sampleTotal: Int?
    var sampleScopeTotal: Int?
    var sampleFilteredTotal: Int?
    var samplesTruncated: Bool?
    var config: MobileSpeakersConfig?

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case speakers
        case samples
        case summary
        case speakerCounts = "speaker_counts"
        case speakerTotal = "speaker_total"
        case speakersTruncated = "speakers_truncated"
        case sampleCounts = "sample_counts"
        case sampleTotal = "sample_total"
        case sampleScopeTotal = "sample_scope_total"
        case sampleFilteredTotal = "sample_filtered_total"
        case samplesTruncated = "samples_truncated"
        case config
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ok = try container.decodeIfPresent(Bool.self, forKey: .ok)
        error = try container.decodeIfPresent(String.self, forKey: .error)
        speakers = try container.decodeIfPresent([MobileSpeaker].self, forKey: .speakers) ?? []
        samples = try container.decodeIfPresent([MobileSpeakerSample].self, forKey: .samples) ?? []
        summary = try container.decodeIfPresent(MobileSpeakersSummary.self, forKey: .summary)
        speakerCounts = try container.decodeIfPresent([String: Int].self, forKey: .speakerCounts) ?? [:]
        speakerTotal = container.decodeFlexibleInt(forKey: .speakerTotal)
        speakersTruncated = container.decodeFlexibleBool(forKey: .speakersTruncated)
        sampleCounts = try container.decodeIfPresent([String: Int].self, forKey: .sampleCounts) ?? [:]
        sampleTotal = container.decodeFlexibleInt(forKey: .sampleTotal)
        sampleScopeTotal = container.decodeFlexibleInt(forKey: .sampleScopeTotal)
        sampleFilteredTotal = container.decodeFlexibleInt(forKey: .sampleFilteredTotal)
        samplesTruncated = container.decodeFlexibleBool(forKey: .samplesTruncated)
        config = try container.decodeIfPresent(MobileSpeakersConfig.self, forKey: .config)
    }
}

struct MobileSpeakersSummary: Decodable {
    var activeSpeakers: Int?
    var confirmedSpeakers: Int?
    var pendingAuto: Int?
    var hiddenSpeakers: Int?
    var samples: Int?

    enum CodingKeys: String, CodingKey {
        case activeSpeakers = "active_speakers"
        case confirmedSpeakers = "confirmed_speakers"
        case pendingAuto = "pending_auto"
        case hiddenSpeakers = "hidden_speakers"
        case samples
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        activeSpeakers = container.decodeFlexibleInt(forKey: .activeSpeakers)
        confirmedSpeakers = container.decodeFlexibleInt(forKey: .confirmedSpeakers)
        pendingAuto = container.decodeFlexibleInt(forKey: .pendingAuto)
        hiddenSpeakers = container.decodeFlexibleInt(forKey: .hiddenSpeakers)
        samples = container.decodeFlexibleInt(forKey: .samples)
    }
}

struct MobileSpeakersConfig: Decodable {
    var speakerRecognition: MobileSpeakerRecognitionConfig?

    enum CodingKeys: String, CodingKey {
        case speakerRecognition = "speaker_recognition"
    }
}

struct MobileSpeakerRecognitionConfig: Decodable {
    var autoMergeThreshold: Double?
    var candidateThreshold: Double?

    enum CodingKeys: String, CodingKey {
        case autoMergeThreshold = "auto_merge_threshold"
        case candidateThreshold = "candidate_threshold"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        autoMergeThreshold = container.decodeFlexibleDouble(forKey: .autoMergeThreshold)
        candidateThreshold = container.decodeFlexibleDouble(forKey: .candidateThreshold)
    }
}

struct MobileSpeaker: Identifiable, Decodable, Equatable {
    var id: Int
    var displayName: String?
    var identityStatus: String?
    var confidence: Double?
    var sampleCount: Int
    var aliasCount: Int
    var latestSampleAt: String?
    var createdAt: String?
    var evidence: MobileSpeakerEvidence?
    var embeddingCount: Int
    var confidenceSummary: MobileSpeakerConfidenceSummary?
    var metadata: MobileSpeakerMetadata

    enum CodingKeys: String, CodingKey {
        case id
        case displayName = "display_name"
        case identityStatus = "identity_status"
        case confidence
        case sampleCount = "sample_count"
        case aliasCount = "alias_count"
        case latestSampleAt = "latest_sample_at"
        case createdAt = "created_at"
        case evidence
        case embeddingCount = "embedding_count"
        case confidenceSummary = "confidence_summary"
        case metadata
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        displayName = try container.decodeIfPresent(String.self, forKey: .displayName)
        identityStatus = try container.decodeIfPresent(String.self, forKey: .identityStatus)
        confidence = container.decodeFlexibleDouble(forKey: .confidence)
        sampleCount = container.decodeFlexibleInt(forKey: .sampleCount) ?? 0
        aliasCount = container.decodeFlexibleInt(forKey: .aliasCount) ?? 0
        latestSampleAt = try container.decodeIfPresent(String.self, forKey: .latestSampleAt)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
        evidence = try container.decodeIfPresent(MobileSpeakerEvidence.self, forKey: .evidence)
        embeddingCount = container.decodeFlexibleInt(forKey: .embeddingCount) ?? 0
        confidenceSummary = try container.decodeIfPresent(MobileSpeakerConfidenceSummary.self, forKey: .confidenceSummary)
        metadata = try container.decodeIfPresent(MobileSpeakerMetadata.self, forKey: .metadata) ?? MobileSpeakerMetadata()
    }
}

struct MobileSpeakerEvidence: Decodable, Equatable {
    var sampleCount: Int?
    var observationCount: Int?
    var dayCount: Int?
    var firstSeenAt: String?
    var latestSeenAt: String?

    enum CodingKeys: String, CodingKey {
        case sampleCount = "sample_count"
        case observationCount = "observation_count"
        case dayCount = "day_count"
        case firstSeenAt = "first_seen_at"
        case latestSeenAt = "latest_seen_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sampleCount = container.decodeFlexibleInt(forKey: .sampleCount)
        observationCount = container.decodeFlexibleInt(forKey: .observationCount)
        dayCount = container.decodeFlexibleInt(forKey: .dayCount)
        firstSeenAt = try container.decodeIfPresent(String.self, forKey: .firstSeenAt)
        latestSeenAt = try container.decodeIfPresent(String.self, forKey: .latestSeenAt)
    }
}

struct MobileSpeakerConfidenceSummary: Decodable, Equatable {
    var level: String?
    var label: String?
    var detail: String?
    var value: Double?
    var threshold: Double?

    enum CodingKeys: String, CodingKey {
        case level
        case label
        case detail
        case value
        case threshold
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        level = try container.decodeIfPresent(String.self, forKey: .level)
        label = try container.decodeIfPresent(String.self, forKey: .label)
        detail = try container.decodeIfPresent(String.self, forKey: .detail)
        value = container.decodeFlexibleDouble(forKey: .value)
        threshold = container.decodeFlexibleDouble(forKey: .threshold)
    }
}

struct MobileSpeakerMetadata: Decodable, Equatable {
    var speakerReviewStatus: String? = nil
    var speakerHidden: Bool? = nil
    var hiddenThreshold: Double? = nil
    var autoMergeSourceCount: Int? = nil
    var autoMergeSources: [MobileSpeakerAutoMergeSource] = []

    enum CodingKeys: String, CodingKey {
        case speakerReviewStatus = "speaker_review_status"
        case speakerHidden = "speaker_hidden"
        case hiddenThreshold = "hidden_threshold"
        case autoMergeSourceCount = "auto_merge_source_count"
        case autoMergeSources = "auto_merge_sources"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        speakerReviewStatus = try container.decodeIfPresent(String.self, forKey: .speakerReviewStatus)
        speakerHidden = container.decodeFlexibleBool(forKey: .speakerHidden)
        hiddenThreshold = container.decodeFlexibleDouble(forKey: .hiddenThreshold)
        autoMergeSourceCount = container.decodeFlexibleInt(forKey: .autoMergeSourceCount)
        autoMergeSources = try container.decodeIfPresent([MobileSpeakerAutoMergeSource].self, forKey: .autoMergeSources) ?? []
    }
}

struct MobileSpeakerAutoMergeSource: Decodable, Equatable {
    var sourceDisplayName: String?
    var sourceSpeakerID: Int?
    var score: Double?

    enum CodingKeys: String, CodingKey {
        case sourceDisplayName = "source_display_name"
        case sourceSpeakerID = "source_speaker_id"
        case score
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        sourceDisplayName = try container.decodeIfPresent(String.self, forKey: .sourceDisplayName)
        sourceSpeakerID = container.decodeFlexibleInt(forKey: .sourceSpeakerID)
        score = container.decodeFlexibleDouble(forKey: .score)
    }
}

struct MobileSpeakerSample: Identifiable, Decodable, Equatable {
    var id: Int
    var speakerID: Int?
    var speakerName: String?
    var observationID: Int?
    var sourceKey: String?
    var transcript: String?
    var startSeconds: Double?
    var endSeconds: Double?
    var createdAt: String?
    var samplePath: String?
    var metadata: MobileSpeakerSampleMetadata

    enum CodingKeys: String, CodingKey {
        case id
        case speakerID = "speaker_id"
        case speakerName = "speaker_name"
        case observationID = "observation_id"
        case sourceKey = "source_key"
        case transcript
        case startSeconds = "start_seconds"
        case endSeconds = "end_seconds"
        case createdAt = "created_at"
        case samplePath = "sample_path"
        case metadata
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(Int.self, forKey: .id)
        speakerID = container.decodeFlexibleInt(forKey: .speakerID)
        speakerName = try container.decodeIfPresent(String.self, forKey: .speakerName)
        observationID = container.decodeFlexibleInt(forKey: .observationID)
        sourceKey = try container.decodeIfPresent(String.self, forKey: .sourceKey)
        transcript = try container.decodeIfPresent(String.self, forKey: .transcript)
        startSeconds = container.decodeFlexibleDouble(forKey: .startSeconds)
        endSeconds = container.decodeFlexibleDouble(forKey: .endSeconds)
        createdAt = try container.decodeIfPresent(String.self, forKey: .createdAt)
        samplePath = try container.decodeIfPresent(String.self, forKey: .samplePath)
        metadata = try container.decodeIfPresent(MobileSpeakerSampleMetadata.self, forKey: .metadata) ?? MobileSpeakerSampleMetadata()
    }
}

struct MobileSpeakerSampleMetadata: Decodable, Equatable {
    var status: String? = nil
    var error: String? = nil
    var localLabel: String? = nil
    var sampleRole: String? = nil
    var sampleConfidence: Double? = nil
    var sampleConfidenceModel: String? = nil
    var representativeSample: Bool? = nil
    var embeddingRepairStatus: String? = nil
    var embeddingModel: String? = nil

    enum CodingKeys: String, CodingKey {
        case status
        case error
        case localLabel = "local_label"
        case sampleRole = "sample_role"
        case sampleConfidence = "sample_confidence"
        case sampleConfidenceModel = "sample_confidence_model"
        case representativeSample = "representative_sample"
        case embeddingRepairStatus = "embedding_repair_status"
        case embeddingModel = "embedding_model"
    }

    init() {}

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try container.decodeIfPresent(String.self, forKey: .status)
        error = try container.decodeIfPresent(String.self, forKey: .error)
        localLabel = try container.decodeIfPresent(String.self, forKey: .localLabel)
        sampleRole = try container.decodeIfPresent(String.self, forKey: .sampleRole)
        sampleConfidence = container.decodeFlexibleDouble(forKey: .sampleConfidence)
        sampleConfidenceModel = try container.decodeIfPresent(String.self, forKey: .sampleConfidenceModel)
        representativeSample = container.decodeFlexibleBool(forKey: .representativeSample)
        embeddingRepairStatus = try container.decodeIfPresent(String.self, forKey: .embeddingRepairStatus)
        embeddingModel = try container.decodeIfPresent(String.self, forKey: .embeddingModel)
    }
}

struct SpeakerBrowserView: View {
    @EnvironmentObject private var store: CaptureStore

    @State private var payload: MobileSpeakersResponse?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var speakerFilter: SpeakerQueueFilter = .active
    @State private var speakerSort: SpeakerSort = .review
    @State private var speakerSearch = ""
    @State private var sampleScope: SpeakerSampleScope = .visible
    @State private var sampleFilter: SpeakerSampleFilter = .all
    @State private var sampleSort: SpeakerSampleSort = .needsWork
    @State private var sampleSearch = ""
    @State private var selectedSpeakerIDs: Set<Int> = []
    @State private var detailSpeaker: MobileSpeaker?
    @State private var playingSampleID: Int?
    @State private var audioPlayer: AVAudioPlayer?
    @State private var audioError: String?

    private let speakerRowLimit = 160
    private let sampleRowLimit = 40

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                speakerControlPanel

                List {
                    if let errorMessage {
                        Section {
                            Text(errorMessage)
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if payload == nil && isLoading {
                        Section {
                            HStack {
                                ProgressView()
                                Text("Loading Speakers")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    } else if payload == nil {
                        Section {
                            ContentUnavailableView("No Speakers", systemImage: "person.2")
                        }
                    } else {
                        speakerSection
                    }
                }
            }
            .navigationTitle("Speakers")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await refresh() }
                    } label: {
                        if isLoading {
                            ProgressView()
                        } else {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                    }
                    .disabled(isLoading)
                }
            }
            .task {
                if payload == nil {
                    await refresh()
                }
            }
            .refreshable {
                await refresh()
            }
            .onChange(of: speakerFilter) { _, _ in
                Task { await refresh() }
            }
            .onChange(of: speakerSort) { _, _ in
                Task { await refresh() }
            }
            .onChange(of: sampleScope) { _, _ in
                Task { await refresh() }
            }
            .onChange(of: sampleFilter) { _, _ in
                Task { await refresh() }
            }
            .onChange(of: sampleSort) { _, _ in
                Task { await refresh() }
            }
            .onDisappear {
                stopPlayback()
            }
            .sheet(item: $detailSpeaker) { speaker in
                SpeakerSampleSheet(speaker: speaker)
                    .environmentObject(store)
            }
        }
    }

    private var speakerControlPanel: some View {
        let totalRows = payload?.speakerTotal ?? speakers.count
        return VStack(alignment: .leading, spacing: 10) {
            filterScroller(filters: SpeakerQueueFilter.allCases, selected: speakerFilter) { filter in
                speakerFilter = filter
            } label: { filter in
                "\(filter.title) \(queueCount(filter))"
            }

            HStack(spacing: 10) {
                TextField("Search Speakers", text: $speakerSearch)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        Task { await refresh() }
                    }

                Picker("Sort", selection: $speakerSort) {
                    ForEach(SpeakerSort.allCases) { sort in
                        Text(sort.title).tag(sort)
                    }
                }
                .pickerStyle(.menu)
            }

            HStack(spacing: 12) {
                compactMetric("Active", payload?.summary?.activeSpeakers ?? queueCount(.active))
                compactMetric("Confirmed", payload?.summary?.confirmedSpeakers ?? confirmedSpeakerCount)
                compactMetric("Samples", payload?.summary?.samples ?? payload?.sampleTotal ?? samples.count)
                Spacer(minLength: 0)
                Text(WondL10n.format("%d / %d shown", speakers.count, totalRows))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.regularMaterial)
    }

    private var speakerSection: some View {
        let rows = speakers
        let totalRows = payload?.speakerTotal ?? rows.count
        return Section {
            if rows.isEmpty {
                ContentUnavailableView("No Speakers", systemImage: "person.2")
            } else {
                ForEach(Array(rows.prefix(speakerRowLimit))) { speaker in
                    speakerRow(speaker)
                }
                if payload?.speakersTruncated == true && totalRows > rows.count {
                    Text(WondL10n.format("%d more speakers", totalRows - rows.count))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            Text(speakerFilter.title)
        }
    }

    private func filterScroller<T: Identifiable & Equatable>(
        filters: [T],
        selected: T,
        action: @escaping (T) -> Void,
        label: @escaping (T) -> String
    ) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(filters) { filter in
                    Button {
                        action(filter)
                    } label: {
                        Text(label(filter))
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .foregroundStyle(filter == selected ? Color.accentColor : Color.primary)
                            .background {
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(filter == selected ? Color.accentColor.opacity(0.14) : Color.secondary.opacity(0.10))
                            }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 1)
        }
    }

    private func speakerRow(_ speaker: MobileSpeaker) -> some View {
        Button {
            detailSpeaker = speaker
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Image(systemName: speakerIsHidden(speaker) ? "eye.slash" : "person.wave.2")
                        .foregroundStyle(speakerIsHidden(speaker) ? Color.secondary : Color.accentColor)

                    VStack(alignment: .leading, spacing: 3) {
                        Text(speaker.displayName?.isEmpty == false ? speaker.displayName! : WondL10n.format("Speaker %d", speaker.id))
                            .font(.headline)
                        Text("ID \(speaker.id) · \(shortDateTime(speakerVisibleTime(speaker)) ?? "-")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    statusBadge(speakerReviewStatus(speaker).isEmpty ? (speaker.identityStatus ?? "info") : speakerReviewStatus(speaker))
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }

                if let sourceSummary = speakerMergeSourceSummary(speaker) {
                    Text(sourceSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 10) {
                    metric("\(speaker.sampleCount)", "Samples")
                    metric("\(speaker.evidence?.dayCount ?? 0)", "Days")
                    metric(speakerConfidenceText(speaker), "Confidence")
                    metric("\(speaker.embeddingCount)", "Embeddings")
                }
                .font(.caption)
            }
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
    }

    private func compactMetric(_ title: String, _ value: Int) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("\(value)")
                .font(.caption.weight(.semibold))
            Text(WondL10n.t(title))
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private func sampleRow(_ sample: MobileSpeakerSample) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(sample.speakerName ?? sample.speakerID.map { WondL10n.format("Speaker %d", $0) } ?? WondL10n.t("Unknown Speaker"))
                        .font(.headline)
                    Text(sampleSubtitle(sample))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                if sample.samplePath != nil {
                    Button {
                        Task { await toggleSamplePlayback(sample) }
                    } label: {
                        Label(playingSampleID == sample.id ? "Stop" : "Play", systemImage: playingSampleID == sample.id ? "stop.fill" : "play.fill")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }

            let badges = sampleBadges(sample)
            if !badges.isEmpty {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 6) {
                        ForEach(badges, id: \.self) { value in
                            sampleBadge(value)
                        }
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(badges, id: \.self) { value in
                                sampleBadge(value)
                            }
                        }
                    }
                }
            }

            if let transcript = sample.transcript, !transcript.isEmpty {
                Text(transcript)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .lineLimit(4)
            }
        }
        .padding(.vertical, 4)
    }

    private func metric(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .fontWeight(.semibold)
            Text(WondL10n.t(label))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statusBadge(_ status: String) -> some View {
        Text(statusTitle(status))
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(statusColor(status))
            .background {
                RoundedRectangle(cornerRadius: 8)
                    .fill(statusColor(status).opacity(0.13))
            }
    }

    private func sampleBadge(_ value: String) -> some View {
        Text(value)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(Color.secondary)
            .background {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.secondary.opacity(0.10))
            }
    }

    @MainActor
    private func refresh() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response = try await store.syncService.fetchSpeakers(parameters: speakerRequestParameters)
            payload = response
            if selectedSpeakerIDs.isEmpty && sampleScope == .selected {
                sampleScope = .visible
            }
        } catch {
            errorMessage = WondL10n.format("Speakers failed: %@", error.localizedDescription)
        }
    }

    private var speakerRequestParameters: [String: String] {
        var parameters: [String: String] = [
            "speaker_filter": speakerFilter.rawValue,
            "speaker_sort": speakerSort.rawValue,
            "speaker_limit": "\(speakerRowLimit)",
            "sample_scope": sampleScope.rawValue,
            "sample_filter": sampleFilter.rawValue,
            "sample_sort": sampleSort.rawValue,
            "sample_limit": "\(sampleRowLimit)"
        ]
        let speakerQuery = speakerSearch.trimmingCharacters(in: .whitespacesAndNewlines)
        if !speakerQuery.isEmpty {
            parameters["speaker_search"] = speakerQuery
        }
        let sampleQuery = sampleSearch.trimmingCharacters(in: .whitespacesAndNewlines)
        if !sampleQuery.isEmpty {
            parameters["sample_search"] = sampleQuery
        }
        if !selectedSpeakerIDs.isEmpty {
            parameters["selected_speaker_ids"] = selectedSpeakerIDs.sorted().map(String.init).joined(separator: ",")
        }
        return parameters
    }

    @MainActor
    private func toggleSamplePlayback(_ sample: MobileSpeakerSample) async {
        if playingSampleID == sample.id {
            stopPlayback()
            return
        }
        audioError = nil
        do {
            let data = try await store.syncService.fetchSpeakerSampleAudio(sampleID: sample.id)
            let player = try AVAudioPlayer(data: data)
            player.prepareToPlay()
            player.play()
            audioPlayer = player
            playingSampleID = sample.id
        } catch {
            audioError = WondL10n.format("Sample playback failed: %@", error.localizedDescription)
            stopPlayback()
        }
    }

    @MainActor
    private func stopPlayback() {
        audioPlayer?.stop()
        audioPlayer = nil
        playingSampleID = nil
    }

    private var speakers: [MobileSpeaker] {
        payload?.speakers ?? []
    }

    private var samples: [MobileSpeakerSample] {
        payload?.samples ?? []
    }

    private var activeSpeakers: [MobileSpeaker] {
        speakers.filter { !speakerIsHidden($0) }
    }

    private var confirmedSpeakerCount: Int {
        speakers.filter { speakerReviewStatus($0) == "confirmed" }.count
    }

    private var candidateThreshold: Double {
        payload?.config?.speakerRecognition?.candidateThreshold ?? 0.68
    }

    private var autoMergeThreshold: Double {
        payload?.config?.speakerRecognition?.autoMergeThreshold ?? 0.68
    }

    private var shownSpeakers: [MobileSpeaker] {
        sortSpeakers(filterSpeakers(speakers))
    }

    private var shownSpeakerIDs: Set<Int> {
        Set(shownSpeakers.map(\.id))
    }

    private var scopedSamples: [MobileSpeakerSample] {
        speakerSampleScopeRows(samples)
    }

    private var focusedSamples: [MobileSpeakerSample] {
        sortSpeakerSamples(filterSpeakerSamples(scopedSamples))
    }

    private func filterSpeakers(_ rows: [MobileSpeaker]) -> [MobileSpeaker] {
        let query = speakerSearch.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return rows.filter { speaker in
            if speakerFilter != .hidden && speakerFilter != .all && speakerIsHidden(speaker) {
                return false
            }
            if speakerFilter == .active && speakerIsHidden(speaker) {
                return false
            }
            if speakerFilter == .pendingAuto && !speakerIsAutoPending(speaker) {
                return false
            }
            if speakerFilter == .review && (speakerIsHidden(speaker) || !speakerNeedsReview(speaker)) {
                return false
            }
            if speakerFilter == .lowConfidence && (speakerIsHidden(speaker) || !speakerHasLowConfidence(speaker)) {
                return false
            }
            if speakerFilter == .hidden && !speakerIsHidden(speaker) {
                return false
            }
            guard !query.isEmpty else { return true }
            let evidence = speaker.evidence
            let sourceNames = speaker.metadata.autoMergeSources.map {
                "\($0.sourceDisplayName ?? "") \($0.sourceSpeakerID.map { "\($0)" } ?? "")"
            }.joined(separator: " ")
            let haystack: [String] = [
                "\(speaker.id)",
                speaker.displayName ?? "",
                speaker.identityStatus ?? "",
                speakerReviewStatus(speaker),
                sourceNames,
                speaker.confidence.map { "\($0)" } ?? "",
                "\(speaker.sampleCount)",
                "\(speaker.aliasCount)",
                evidence?.dayCount.map { "\($0)" } ?? "",
                evidence?.latestSeenAt ?? ""
            ]
            let searchableText = haystack.joined(separator: " ").lowercased()
            return searchableText.contains(query)
        }
    }

    private func sortSpeakers(_ rows: [MobileSpeaker]) -> [MobileSpeaker] {
        rows.sorted { left, right in
            switch speakerSort {
            case .samples:
                return compare(NumberSort(left.sampleCount, right.sampleCount, descending: true), left.id, right.id)
            case .confidence:
                return compare(NumberSort(left.confidence ?? -1, right.confidence ?? -1, descending: true), left.id, right.id)
            case .recent:
                return compare(DateSort(speakerVisibleDate(left), speakerVisibleDate(right), descending: true), left.id, right.id)
            case .id:
                return left.id < right.id
            case .review:
                let leftScore = speakerReviewScore(left)
                let rightScore = speakerReviewScore(right)
                if leftScore != rightScore {
                    return leftScore > rightScore
                }
                if speakerVisibleDate(left) != speakerVisibleDate(right) {
                    return (speakerVisibleDate(left) ?? .distantPast) > (speakerVisibleDate(right) ?? .distantPast)
                }
                return left.id < right.id
            }
        }
    }

    private func speakerSampleScopeRows(_ rows: [MobileSpeakerSample]) -> [MobileSpeakerSample] {
        switch sampleScope {
        case .selected:
            guard !selectedSpeakerIDs.isEmpty else { return [] }
            return rows.filter { sample in
                sample.speakerID.map { selectedSpeakerIDs.contains($0) } ?? false
            }
        case .all:
            return rows
        case .visible:
            guard !shownSpeakerIDs.isEmpty else { return [] }
            return rows.filter { sample in
                sample.speakerID.map { shownSpeakerIDs.contains($0) } ?? false
            }
        }
    }

    private func filterSpeakerSamples(_ rows: [MobileSpeakerSample]) -> [MobileSpeakerSample] {
        let query = sampleSearch.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return rows.filter { sample in
            if sampleFilter == .needsWork && !(sampleHasLowConfidence(sample) || sampleMissingEmbedding(sample) || sampleHasError(sample)) {
                return false
            }
            if sampleFilter == .lowConfidence && !sampleHasLowConfidence(sample) {
                return false
            }
            if sampleFilter == .missingEmbedding && !sampleMissingEmbedding(sample) {
                return false
            }
            if sampleFilter == .representative && !sampleIsRepresentative(sample) {
                return false
            }
            if sampleFilter == .playable && sample.samplePath == nil {
                return false
            }
            if sampleFilter == .detached && !sampleIsDetached(sample) {
                return false
            }
            guard !query.isEmpty else { return true }
            let metadata = sample.metadata
            let haystack: [String] = [
                "\(sample.id)",
                sample.speakerID.map { "\($0)" } ?? "",
                sample.speakerName ?? "",
                sample.observationID.map { "\($0)" } ?? "",
                sample.sourceKey ?? "",
                sample.transcript ?? "",
                sample.createdAt ?? "",
                metadata.status ?? "",
                metadata.error ?? "",
                metadata.localLabel ?? "",
                metadata.sampleRole ?? "",
                metadata.sampleConfidence.map { "\($0)" } ?? "",
                metadata.embeddingRepairStatus ?? ""
            ]
            let searchableText = haystack.joined(separator: " ").lowercased()
            return searchableText.contains(query)
        }
    }

    private func sortSpeakerSamples(_ rows: [MobileSpeakerSample]) -> [MobileSpeakerSample] {
        rows.sorted { left, right in
            switch sampleSort {
            case .recent:
                return compare(DateSort(sampleCreatedDate(left), sampleCreatedDate(right), descending: true), right.id, left.id)
            case .speaker:
                let leftName = left.speakerName ?? left.speakerID.map(String.init) ?? ""
                let rightName = right.speakerName ?? right.speakerID.map(String.init) ?? ""
                if leftName != rightName {
                    return leftName < rightName
                }
                return left.id < right.id
            case .duration:
                return compare(NumberSort(sampleDuration(left), sampleDuration(right), descending: true), right.id, left.id)
            case .needsWork:
                let leftScore = sampleReviewScore(left)
                let rightScore = sampleReviewScore(right)
                if leftScore != rightScore {
                    return leftScore > rightScore
                }
                let leftConfidence = sampleConfidenceValue(left)
                let rightConfidence = sampleConfidenceValue(right)
                if let leftConfidence, let rightConfidence, leftConfidence != rightConfidence {
                    return leftConfidence < rightConfidence
                }
                if (leftConfidence != nil) != (rightConfidence != nil) {
                    return leftConfidence != nil
                }
                return left.id > right.id
            }
        }
    }

    private func queueCount(_ filter: SpeakerQueueFilter) -> Int {
        if let value = payload?.speakerCounts[filter.rawValue] {
            return value
        }
        switch filter {
        case .active:
            return activeSpeakers.count
        case .pendingAuto:
            return speakers.filter(speakerIsAutoPending).count
        case .lowConfidence:
            return speakers.filter { !speakerIsHidden($0) && speakerHasLowConfidence($0) }.count
        case .review:
            return speakers.filter { !speakerIsHidden($0) && speakerNeedsReview($0) }.count
        case .hidden:
            return speakers.filter(speakerIsHidden).count
        case .all:
            return speakers.count
        }
    }

    private func sampleFilterCount(_ filter: SpeakerSampleFilter) -> Int {
        sampleFilterCount(filter, rows: scopedSamples)
    }

    private func sampleFilterCount(_ filter: SpeakerSampleFilter, rows: [MobileSpeakerSample]) -> Int {
        if let value = payload?.sampleCounts[filter.rawValue] {
            return value
        }
        switch filter {
        case .all:
            return rows.count
        case .needsWork:
            return rows.filter { sampleHasLowConfidence($0) || sampleMissingEmbedding($0) || sampleHasError($0) }.count
        case .lowConfidence:
            return rows.filter(sampleHasLowConfidence).count
        case .missingEmbedding:
            return rows.filter(sampleMissingEmbedding).count
        case .representative:
            return rows.filter(sampleIsRepresentative).count
        case .playable:
            return rows.filter { $0.samplePath != nil }.count
        case .detached:
            return rows.filter(sampleIsDetached).count
        }
    }

    private func toggleSpeakerSelection(_ id: Int) {
        if selectedSpeakerIDs.count == 1 && selectedSpeakerIDs.contains(id) {
            selectedSpeakerIDs.removeAll()
            sampleScope = .visible
        } else {
            selectedSpeakerIDs = [id]
            sampleScope = .selected
        }
        Task { await refresh() }
    }

    private func selectShownSpeakers() {
        selectedSpeakerIDs = Set(speakers.map(\.id))
        if !selectedSpeakerIDs.isEmpty {
            sampleScope = .selected
        }
        Task { await refresh() }
    }

    private func invertShownSpeakers() {
        for id in speakers.map(\.id) {
            if selectedSpeakerIDs.contains(id) {
                selectedSpeakerIDs.remove(id)
            } else {
                selectedSpeakerIDs.insert(id)
            }
        }
        sampleScope = selectedSpeakerIDs.isEmpty ? .visible : .selected
        Task { await refresh() }
    }

    private func clearSpeakerSelection() {
        selectedSpeakerIDs.removeAll()
        sampleScope = .visible
        Task { await refresh() }
    }

    private func speakerReviewStatus(_ speaker: MobileSpeaker) -> String {
        speaker.metadata.speakerReviewStatus?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    private func speakerIsAutoPending(_ speaker: MobileSpeaker) -> Bool {
        speakerReviewStatus(speaker) == "auto_merged_pending_review"
    }

    private func speakerIsHidden(_ speaker: MobileSpeaker) -> Bool {
        speaker.metadata.speakerHidden == true || speakerReviewStatus(speaker) == "low_similarity_hidden"
    }

    private func speakerNeedsReview(_ speaker: MobileSpeaker) -> Bool {
        let name = speaker.displayName ?? ""
        if speakerIsAutoPending(speaker) {
            return true
        }
        if speakerReviewStatus(speaker) == "confirmed" {
            return false
        }
        if speaker.identityStatus == "provisional" || speaker.sampleCount <= 0 {
            return true
        }
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if Int(trimmed) != nil {
            return true
        }
        return trimmed.range(of: #"^speaker\s*\d+$"#, options: [.regularExpression, .caseInsensitive]) != nil
    }

    private func speakerHasLowConfidence(_ speaker: MobileSpeaker) -> Bool {
        if speakerReviewStatus(speaker) == "confirmed" {
            return false
        }
        guard let confidence = speaker.confidence else { return false }
        return confidence > 0 && confidence < candidateThreshold
    }

    private func sampleConfidenceValue(_ sample: MobileSpeakerSample) -> Double? {
        sample.metadata.sampleConfidence
    }

    private func sampleHasLowConfidence(_ sample: MobileSpeakerSample) -> Bool {
        guard let confidence = sampleConfidenceValue(sample) else { return false }
        return confidence > 0 && confidence < candidateThreshold
    }

    private func sampleHasError(_ sample: MobileSpeakerSample) -> Bool {
        let status = (sample.metadata.status ?? "").lowercased()
        return sample.metadata.error?.isEmpty == false || ["error", "fail", "failed"].contains(status)
    }

    private func sampleMissingEmbedding(_ sample: MobileSpeakerSample) -> Bool {
        sample.metadata.sampleConfidenceModel == nil
            && sample.metadata.embeddingModel == nil
            && sample.metadata.embeddingRepairStatus != "ok"
    }

    private func sampleIsRepresentative(_ sample: MobileSpeakerSample) -> Bool {
        sample.metadata.representativeSample == true
    }

    private func sampleIsDetached(_ sample: MobileSpeakerSample) -> Bool {
        (sample.metadata.sampleRole ?? "").contains("detached")
    }

    private func speakerReviewScore(_ speaker: MobileSpeaker) -> Int {
        (speakerIsAutoPending(speaker) ? 2000 : 0)
            + (speakerNeedsReview(speaker) ? 1000 : 0)
            + (speaker.sampleCount <= 0 ? 200 : 0)
            + (speakerHasLowConfidence(speaker) ? 100 : 0)
    }

    private func sampleReviewScore(_ sample: MobileSpeakerSample) -> Int {
        (sampleMissingEmbedding(sample) ? 3000 : 0)
            + (sampleHasLowConfidence(sample) ? 2000 : 0)
            + (sampleHasError(sample) ? 1000 : 0)
    }

    private func speakerVisibleTime(_ speaker: MobileSpeaker) -> String? {
        speaker.evidence?.latestSeenAt ?? speaker.latestSampleAt ?? speaker.createdAt
    }

    private func speakerVisibleDate(_ speaker: MobileSpeaker) -> Date? {
        SpeakerDateParser.date(speakerVisibleTime(speaker))
    }

    private func sampleCreatedDate(_ sample: MobileSpeakerSample) -> Date? {
        SpeakerDateParser.date(sample.createdAt)
    }

    private func sampleDuration(_ sample: MobileSpeakerSample) -> Double {
        max(0, (sample.endSeconds ?? 0) - (sample.startSeconds ?? 0))
    }

    private func sampleSubtitle(_ sample: MobileSpeakerSample) -> String {
        var parts = [
            WondL10n.format("sample %d", sample.id),
            secondsRange(sample.startSeconds, sample.endSeconds)
        ].filter { !$0.isEmpty }
        if let observationID = sample.observationID {
            parts.append(WondL10n.format("obs %d", observationID))
        }
        if let confidence = sampleConfidenceValue(sample) {
            parts.append(WondL10n.format("sample confidence %@", percentText(confidence)))
        }
        if sampleIsRepresentative(sample) {
            parts.append(WondL10n.t("Representative"))
        }
        return parts.joined(separator: " · ")
    }

    private func sampleBadges(_ sample: MobileSpeakerSample) -> [String] {
        var badges: [String] = []
        if sampleHasLowConfidence(sample) {
            badges.append(WondL10n.t("Low Confidence"))
        }
        if sampleMissingEmbedding(sample) {
            badges.append(WondL10n.t("Missing Embedding"))
        }
        if sampleIsRepresentative(sample) {
            badges.append(WondL10n.t("Representative"))
        }
        if sampleIsDetached(sample) {
            badges.append(WondL10n.t("Detached"))
        }
        if sample.metadata.sampleRole == "manual_split_child" {
            badges.append(WondL10n.t("Split Child"))
        }
        if sample.samplePath != nil {
            badges.append(WondL10n.t("Playable"))
        }
        return badges
    }

    private func speakerConfidenceText(_ speaker: MobileSpeaker) -> String {
        guard let summary = speaker.confidenceSummary else {
            return percentText(speaker.confidence)
        }
        if summary.value == nil
            || summary.level == "insufficient_evidence"
            || summary.level == "missing_embedding"
            || summary.level == "no_samples" {
            return summary.label ?? "-"
        }
        return [summary.label, summary.value.map(percentText)].compactMap { $0 }.joined(separator: " ")
    }

    private func speakerMergeSourceSummary(_ speaker: MobileSpeaker) -> String? {
        if speakerIsHidden(speaker) {
            if let threshold = speaker.metadata.hiddenThreshold {
                return WondL10n.format("Hidden low-similarity · threshold %@", percentText(threshold))
            }
            return WondL10n.t("Hidden low-similarity")
        }
        let sources = speaker.metadata.autoMergeSources.suffix(3).reversed()
        guard !sources.isEmpty else { return nil }
        let sourceCount = speaker.metadata.autoMergeSourceCount ?? speaker.metadata.autoMergeSources.count
        let values = sources.map { source in
            "#\(source.sourceSpeakerID.map(String.init) ?? "-") \(source.sourceDisplayName ?? "") \(source.score.map(percentText) ?? "")"
        }
        return WondL10n.format("Auto merged %d sources: %@", sourceCount, values.joined(separator: " · "))
    }

    private func statusTitle(_ status: String) -> String {
        switch status {
        case "provisional":
            return WondL10n.t("Provisional")
        case "confirmed", "accepted", "named":
            return WondL10n.t("Confirmed")
        case "auto_merged_pending_review":
            return WondL10n.t("Pending Auto")
        case "low_similarity_hidden":
            return WondL10n.t("Hidden")
        case "needs_review":
            return WondL10n.t("Needs Review")
        default:
            return status.isEmpty ? WondL10n.t("Info") : WondL10n.t(status)
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "confirmed", "accepted", "named":
            return .green
        case "auto_merged_pending_review":
            return .orange
        case "low_similarity_hidden":
            return .secondary
        case "needs_review", "provisional":
            return .blue
        default:
            return .secondary
        }
    }

    private func shortDateTime(_ value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        if let date = SpeakerDateParser.date(value) {
            return date.formatted(date: .abbreviated, time: .shortened)
        }
        return value
    }

    private func percentText(_ value: Double?) -> String {
        guard let value else { return "-" }
        return value.formatted(.percent.precision(.fractionLength(value < 0.1 ? 1 : 0)))
    }

    private func secondsRange(_ start: Double?, _ end: Double?) -> String {
        guard let start, let end else { return "" }
        return "\(clockSeconds(start))-\(clockSeconds(end))"
    }

    private func clockSeconds(_ seconds: Double) -> String {
        let value = max(0, Int(seconds.rounded()))
        let minutes = value / 60
        let remaining = value % 60
        return "\(minutes):\(String(format: "%02d", remaining))"
    }

    private func compare(_ sort: NumberSort, _ leftID: Int, _ rightID: Int) -> Bool {
        if sort.left != sort.right {
            return sort.descending ? sort.left > sort.right : sort.left < sort.right
        }
        return leftID < rightID
    }

    private func compare(_ sort: DateSort, _ leftID: Int, _ rightID: Int) -> Bool {
        let left = sort.left ?? .distantPast
        let right = sort.right ?? .distantPast
        if left != right {
            return sort.descending ? left > right : left < right
        }
        return leftID < rightID
    }
}

private struct SpeakerSampleSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var store: CaptureStore

    let speaker: MobileSpeaker

    @State private var payload: MobileSpeakersResponse?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var sampleFilter: SpeakerSampleFilter = .all
    @State private var sampleSort: SpeakerSampleSort = .needsWork
    @State private var playingSampleID: Int?
    @State private var audioPlayer: AVAudioPlayer?
    @State private var audioError: String?

    private let sampleLimit = 80

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(displayName)
                                .font(.headline)
                            Spacer()
                            statusBadge(speakerStatus)
                        }

                        HStack(spacing: 10) {
                            metric("\(speaker.sampleCount)", "Samples")
                            metric("\(speaker.evidence?.dayCount ?? 0)", "Days")
                            metric(speakerConfidenceText, "Confidence")
                        }
                        .font(.caption)
                    }
                    .padding(.vertical, 4)
                }

                Section {
                    VStack(alignment: .leading, spacing: 12) {
                        filterScroller(filters: SpeakerSampleFilter.allCases, selected: sampleFilter) { filter in
                            sampleFilter = filter
                        } label: { filter in
                            "\(filter.title) \(sampleFilterCount(filter))"
                        }

                        HStack {
                            Picker("Sort", selection: $sampleSort) {
                                ForEach(SpeakerSampleSort.allCases) { sort in
                                    Text(sort.title).tag(sort)
                                }
                            }
                            .pickerStyle(.menu)

                            Spacer()

                            Text(WondL10n.format("%d / %d shown", samples.count, payload?.sampleFilteredTotal ?? samples.count))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    if isLoading {
                        HStack {
                            ProgressView()
                            Text("Loading Speakers")
                                .foregroundStyle(.secondary)
                        }
                    }

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    if let audioError {
                        Text(audioError)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    if !isLoading && samples.isEmpty {
                        ContentUnavailableView("No Samples", systemImage: "waveform")
                    } else {
                        ForEach(samples) { sample in
                            sampleRow(sample)
                        }
                        if payload?.samplesTruncated == true,
                           let total = payload?.sampleFilteredTotal,
                           total > samples.count {
                            Text(WondL10n.format("%d more samples", total - samples.count))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                } header: {
                    Text("Samples")
                }
            }
            .navigationTitle("Samples")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
            .task(id: requestKey) {
                await refresh()
            }
            .onDisappear {
                stopPlayback()
            }
        }
    }

    private var requestKey: String {
        "\(speaker.id)-\(sampleFilter.rawValue)-\(sampleSort.rawValue)"
    }

    private var displayName: String {
        speaker.displayName?.isEmpty == false ? speaker.displayName! : WondL10n.format("Speaker %d", speaker.id)
    }

    private var speakerStatus: String {
        let status = speaker.metadata.speakerReviewStatus?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return status.isEmpty ? (speaker.identityStatus ?? "info") : status
    }

    private var samples: [MobileSpeakerSample] {
        payload?.samples ?? []
    }

    @MainActor
    private func refresh() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            payload = try await store.syncService.fetchSpeakers(
                parameters: [
                    "speaker_filter": "all",
                    "speaker_sort": "id",
                    "speaker_limit": "0",
                    "sample_scope": "selected",
                    "selected_speaker_ids": "\(speaker.id)",
                    "sample_filter": sampleFilter.rawValue,
                    "sample_sort": sampleSort.rawValue,
                    "sample_limit": "\(sampleLimit)"
                ]
            )
        } catch {
            errorMessage = WondL10n.format("Speakers failed: %@", error.localizedDescription)
        }
    }

    private func filterScroller<T: Identifiable & Equatable>(
        filters: [T],
        selected: T,
        action: @escaping (T) -> Void,
        label: @escaping (T) -> String
    ) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(filters) { filter in
                    Button {
                        action(filter)
                    } label: {
                        Text(label(filter))
                            .font(.caption.weight(.semibold))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .foregroundStyle(filter == selected ? Color.accentColor : Color.primary)
                            .background {
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(filter == selected ? Color.accentColor.opacity(0.14) : Color.secondary.opacity(0.10))
                            }
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 1)
        }
    }

    private func sampleRow(_ sample: MobileSpeakerSample) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(sampleSubtitle(sample))
                        .font(.subheadline.weight(.semibold))
                    if let transcript = sample.transcript, !transcript.isEmpty {
                        Text(transcript)
                            .font(.body)
                            .foregroundStyle(.primary)
                            .lineLimit(4)
                    }
                }

                Spacer()

                if sample.samplePath != nil {
                    Button {
                        Task { await toggleSamplePlayback(sample) }
                    } label: {
                        Label(playingSampleID == sample.id ? "Stop" : "Play", systemImage: playingSampleID == sample.id ? "stop.fill" : "play.fill")
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }

            let badges = sampleBadges(sample)
            if !badges.isEmpty {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 6) {
                        ForEach(badges, id: \.self) { value in
                            sampleBadge(value)
                        }
                    }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(badges, id: \.self) { value in
                                sampleBadge(value)
                            }
                        }
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    @MainActor
    private func toggleSamplePlayback(_ sample: MobileSpeakerSample) async {
        if playingSampleID == sample.id {
            stopPlayback()
            return
        }
        audioError = nil
        do {
            let data = try await store.syncService.fetchSpeakerSampleAudio(sampleID: sample.id)
            let player = try AVAudioPlayer(data: data)
            player.prepareToPlay()
            player.play()
            audioPlayer = player
            playingSampleID = sample.id
        } catch {
            audioError = WondL10n.format("Sample playback failed: %@", error.localizedDescription)
            stopPlayback()
        }
    }

    @MainActor
    private func stopPlayback() {
        audioPlayer?.stop()
        audioPlayer = nil
        playingSampleID = nil
    }

    private func metric(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .fontWeight(.semibold)
            Text(WondL10n.t(label))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func statusBadge(_ status: String) -> some View {
        Text(statusTitle(status))
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(statusColor(status))
            .background {
                RoundedRectangle(cornerRadius: 8)
                    .fill(statusColor(status).opacity(0.13))
            }
    }

    private func sampleBadge(_ value: String) -> some View {
        Text(value)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .foregroundStyle(Color.secondary)
            .background {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color.secondary.opacity(0.10))
            }
    }

    private func sampleFilterCount(_ filter: SpeakerSampleFilter) -> Int {
        if let value = payload?.sampleCounts[filter.rawValue] {
            return value
        }
        return filter == .all ? samples.count : 0
    }

    private var speakerConfidenceText: String {
        guard let summary = speaker.confidenceSummary else {
            return percentText(speaker.confidence)
        }
        if summary.value == nil
            || summary.level == "insufficient_evidence"
            || summary.level == "missing_embedding"
            || summary.level == "no_samples" {
            return summary.label ?? "-"
        }
        return [summary.label, summary.value.map(percentText)].compactMap { $0 }.joined(separator: " ")
    }

    private func sampleSubtitle(_ sample: MobileSpeakerSample) -> String {
        var parts = [
            WondL10n.format("sample %d", sample.id),
            secondsRange(sample.startSeconds, sample.endSeconds)
        ].filter { !$0.isEmpty }
        if let confidence = sample.metadata.sampleConfidence {
            parts.append(WondL10n.format("sample confidence %@", percentText(confidence)))
        }
        if sample.metadata.representativeSample == true {
            parts.append(WondL10n.t("Representative"))
        }
        return parts.joined(separator: " · ")
    }

    private func sampleBadges(_ sample: MobileSpeakerSample) -> [String] {
        var badges: [String] = []
        if let confidence = sample.metadata.sampleConfidence, confidence > 0, confidence < candidateThreshold {
            badges.append(WondL10n.t("Low Confidence"))
        }
        if sample.metadata.sampleConfidenceModel == nil
            && sample.metadata.embeddingModel == nil
            && sample.metadata.embeddingRepairStatus != "ok" {
            badges.append(WondL10n.t("Missing Embedding"))
        }
        if sample.metadata.representativeSample == true {
            badges.append(WondL10n.t("Representative"))
        }
        if (sample.metadata.sampleRole ?? "").contains("detached") {
            badges.append(WondL10n.t("Detached"))
        }
        if sample.samplePath != nil {
            badges.append(WondL10n.t("Playable"))
        }
        return badges
    }

    private var candidateThreshold: Double {
        payload?.config?.speakerRecognition?.candidateThreshold ?? 0.68
    }

    private func statusTitle(_ status: String) -> String {
        switch status {
        case "provisional":
            return WondL10n.t("Provisional")
        case "confirmed", "accepted", "named":
            return WondL10n.t("Confirmed")
        case "auto_merged_pending_review":
            return WondL10n.t("Pending Auto")
        case "low_similarity_hidden":
            return WondL10n.t("Hidden")
        case "needs_review":
            return WondL10n.t("Needs Review")
        default:
            return status.isEmpty ? WondL10n.t("Info") : WondL10n.t(status)
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "confirmed", "accepted", "named":
            return .green
        case "auto_merged_pending_review":
            return .orange
        case "low_similarity_hidden":
            return .secondary
        case "needs_review", "provisional":
            return .blue
        default:
            return .secondary
        }
    }

    private func percentText(_ value: Double?) -> String {
        guard let value else { return "-" }
        return value.formatted(.percent.precision(.fractionLength(value < 0.1 ? 1 : 0)))
    }

    private func secondsRange(_ start: Double?, _ end: Double?) -> String {
        guard let start, let end else { return "" }
        return "\(clockSeconds(start))-\(clockSeconds(end))"
    }

    private func clockSeconds(_ seconds: Double) -> String {
        let value = max(0, Int(seconds.rounded()))
        let minutes = value / 60
        let remaining = value % 60
        return "\(minutes):\(String(format: "%02d", remaining))"
    }
}

private enum SpeakerQueueFilter: String, CaseIterable, Identifiable {
    case active
    case pendingAuto
    case lowConfidence
    case review
    case hidden
    case all

    var id: String { rawValue }

    var title: String {
        switch self {
        case .active:
            return WondL10n.t("Active")
        case .pendingAuto:
            return WondL10n.t("Pending Auto")
        case .lowConfidence:
            return WondL10n.t("Low Confidence")
        case .review:
            return WondL10n.t("Manual Review")
        case .hidden:
            return WondL10n.t("Hidden")
        case .all:
            return WondL10n.t("All")
        }
    }
}

private enum SpeakerSort: String, CaseIterable, Identifiable {
    case review
    case recent
    case samples
    case confidence
    case id

    var id: String { rawValue }

    var title: String {
        switch self {
        case .review:
            return WondL10n.t("Review First")
        case .recent:
            return WondL10n.t("Most Recent")
        case .samples:
            return WondL10n.t("Most Samples")
        case .confidence:
            return WondL10n.t("Highest Confidence")
        case .id:
            return WondL10n.t("ID Order")
        }
    }
}

private enum SpeakerSampleScope: String, CaseIterable, Identifiable {
    case visible
    case selected
    case all

    var id: String { rawValue }

    var title: String {
        switch self {
        case .visible:
            return WondL10n.t("Current")
        case .selected:
            return WondL10n.t("Selected")
        case .all:
            return WondL10n.t("All")
        }
    }
}

private enum SpeakerSampleFilter: String, CaseIterable, Identifiable {
    case all
    case needsWork
    case lowConfidence
    case missingEmbedding
    case representative
    case playable
    case detached

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all:
            return WondL10n.t("All")
        case .needsWork:
            return WondL10n.t("Needs Work")
        case .lowConfidence:
            return WondL10n.t("Low Confidence")
        case .missingEmbedding:
            return WondL10n.t("Missing Embedding")
        case .representative:
            return WondL10n.t("Representative")
        case .playable:
            return WondL10n.t("Playable")
        case .detached:
            return WondL10n.t("Detached")
        }
    }
}

private enum SpeakerSampleSort: String, CaseIterable, Identifiable {
    case needsWork
    case recent
    case speaker
    case duration

    var id: String { rawValue }

    var title: String {
        switch self {
        case .needsWork:
            return WondL10n.t("Issues First")
        case .recent:
            return WondL10n.t("Newest")
        case .speaker:
            return WondL10n.t("By Speaker")
        case .duration:
            return WondL10n.t("Longest")
        }
    }
}

private struct NumberSort {
    var left: Double
    var right: Double
    var descending: Bool

    init(_ left: Int, _ right: Int, descending: Bool) {
        self.left = Double(left)
        self.right = Double(right)
        self.descending = descending
    }

    init(_ left: Double, _ right: Double, descending: Bool) {
        self.left = left
        self.right = right
        self.descending = descending
    }
}

private struct DateSort {
    var left: Date?
    var right: Date?
    var descending: Bool

    init(_ left: Date?, _ right: Date?, descending: Bool) {
        self.left = left
        self.right = right
        self.descending = descending
    }
}

private enum SpeakerDateParser {
    static let standard: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    static let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static func date(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        return fractional.date(from: value) ?? standard.date(from: value)
    }
}

private extension KeyedDecodingContainer {
    func decodeFlexibleDouble(forKey key: Key) -> Double? {
        if let value = try? decodeIfPresent(Double.self, forKey: key) {
            return value
        }
        if let value = try? decodeIfPresent(Int.self, forKey: key) {
            return Double(value)
        }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            return Double(value)
        }
        return nil
    }

    func decodeFlexibleInt(forKey key: Key) -> Int? {
        if let value = try? decodeIfPresent(Int.self, forKey: key) {
            return value
        }
        if let value = try? decodeIfPresent(Double.self, forKey: key) {
            return Int(value)
        }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            return Int(value)
        }
        return nil
    }

    func decodeFlexibleBool(forKey key: Key) -> Bool? {
        if let value = try? decodeIfPresent(Bool.self, forKey: key) {
            return value
        }
        if let value = try? decodeIfPresent(Int.self, forKey: key) {
            return value != 0
        }
        if let value = try? decodeIfPresent(String.self, forKey: key) {
            switch value.lowercased() {
            case "1", "true", "yes", "on":
                return true
            case "0", "false", "no", "off":
                return false
            default:
                return nil
            }
        }
        return nil
    }
}
