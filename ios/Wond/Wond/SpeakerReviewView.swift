import AVFoundation
import SwiftUI

struct SpeakerReviewView: View {
    @EnvironmentObject private var store: CaptureStore

    @State private var speakers: [SpeakerReviewItem] = []
    @State private var names: [Int: String] = [:]
    @State private var isLoading = false
    @State private var namingSpeakerID: Int?
    @State private var loadingSampleID: Int?
    @State private var statusMessage: String?
    @State private var audioPlayer: AVAudioPlayer?

    var body: some View {
        NavigationStack {
            List {
                if let statusMessage {
                    Section {
                        Text(statusMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }

                if speakers.isEmpty && !isLoading {
                    ContentUnavailableView("No Review Items", systemImage: "person.crop.circle.badge.checkmark")
                }

                ForEach(speakers) { speaker in
                    Section {
                        speakerHeader(speaker)
                        ForEach(speaker.samples) { sample in
                            sampleRow(sample)
                        }
                    } header: {
                        Text("Speaker \(speaker.id)")
                    }
                }
            }
            .navigationTitle("Review")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await refresh() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(isLoading)
                }
            }
            .refreshable {
                await refresh()
            }
            .task {
                if speakers.isEmpty {
                    await refresh()
                }
            }
            .overlay {
                if isLoading {
                    ProgressView()
                }
            }
        }
    }

    private func speakerHeader(_ speaker: SpeakerReviewItem) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text(speaker.displayName)
                    .font(.headline)
                Spacer()
                Text(confidenceText(speaker.confidence))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 14) {
                Label("\(speaker.sampleCount)", systemImage: "waveform")
                Label("\(speaker.observationCount)", systemImage: "recordingtape")
                Label("\(speaker.dayCount)", systemImage: "calendar")
            }
            .font(.caption)
            .foregroundStyle(.secondary)

            TextField("Name", text: nameBinding(for: speaker))
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled()

            Button {
                Task { await confirmName(for: speaker) }
            } label: {
                Label("Confirm Name", systemImage: "checkmark.circle")
            }
            .disabled(confirmNameDisabled(for: speaker))
        }
        .padding(.vertical, 4)
    }

    private func sampleRow(_ sample: SpeakerReviewSample) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Button {
                Task { await play(sample) }
            } label: {
                Image(systemName: loadingSampleID == sample.id ? "hourglass" : "play.circle")
                    .font(.title3)
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.borderless)
            .disabled(!sample.hasAudio || loadingSampleID != nil)

            VStack(alignment: .leading, spacing: 4) {
                Text(sample.transcript?.isEmpty == false ? sample.transcript! : "No transcript")
                    .font(.body)
                    .lineLimit(4)
                Text(sampleMeta(sample))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 3)
    }

    @MainActor
    private func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            speakers = try await store.syncService.fetchSpeakerReviews()
            for speaker in speakers where names[speaker.id] == nil {
                names[speaker.id] = ""
            }
            statusMessage = speakers.isEmpty ? "No speakers are ready for naming." : nil
        } catch {
            statusMessage = "Review refresh failed: \(error.localizedDescription)"
        }
    }

    @MainActor
    private func confirmName(for speaker: SpeakerReviewItem) async {
        let name = (names[speaker.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        namingSpeakerID = speaker.id
        defer { namingSpeakerID = nil }
        do {
            try await store.syncService.nameSpeaker(id: speaker.id, displayName: name)
            speakers.removeAll { $0.id == speaker.id }
            names[speaker.id] = nil
            statusMessage = "Named \(name)."
        } catch {
            statusMessage = "Name update failed: \(error.localizedDescription)"
        }
    }

    @MainActor
    private func play(_ sample: SpeakerReviewSample) async {
        loadingSampleID = sample.id
        defer { loadingSampleID = nil }
        do {
            let data = try await store.syncService.fetchSpeakerSample(sampleID: sample.id)
            let player = try AVAudioPlayer(data: data)
            audioPlayer = player
            player.prepareToPlay()
            player.play()
        } catch {
            statusMessage = "Sample playback failed: \(error.localizedDescription)"
        }
    }

    private func nameBinding(for speaker: SpeakerReviewItem) -> Binding<String> {
        Binding(
            get: { names[speaker.id] ?? "" },
            set: { names[speaker.id] = $0 }
        )
    }

    private func confirmNameDisabled(for speaker: SpeakerReviewItem) -> Bool {
        namingSpeakerID != nil || (names[speaker.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func confidenceText(_ value: Double?) -> String {
        guard let value else { return "No score" }
        return value.formatted(.percent.precision(.fractionLength(0...1)))
    }

    private func sampleMeta(_ sample: SpeakerReviewSample) -> String {
        var parts: [String] = []
        if let duration = sample.durationSeconds {
            parts.append("\(duration.formatted(.number.precision(.fractionLength(1))))s")
        }
        if let start = sample.startSeconds, let end = sample.endSeconds {
            parts.append("\(start.formatted(.number.precision(.fractionLength(1))))-\(end.formatted(.number.precision(.fractionLength(1))))s")
        }
        if !sample.hasAudio {
            parts.append("Audio unavailable")
        }
        return parts.isEmpty ? "Sample" : parts.joined(separator: " / ")
    }
}
