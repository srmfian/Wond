import SwiftUI

struct AskView: View {
    @EnvironmentObject private var store: CaptureStore

    @State private var question = ""
    @State private var response: AskResponse?
    @State private var errorMessage: String?
    @State private var isAsking = false
    @FocusState private var questionFocused: Bool

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ZStack(alignment: .topLeading) {
                        TextEditor(text: $question)
                            .frame(minHeight: 104)
                            .focused($questionFocused)
                            .textInputAutocapitalization(.sentences)

                        if question.isEmpty {
                            Text("Question")
                                .foregroundStyle(.tertiary)
                                .padding(.top, 8)
                                .padding(.leading, 5)
                                .allowsHitTesting(false)
                        }
                    }

                    HStack {
                        Button {
                            Task { await ask() }
                        } label: {
                            Label("Ask", systemImage: "magnifyingglass")
                        }
                        .disabled(askDisabled)

                        Spacer()

                        if isAsking {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }

                if let response {
                    Section("Answer") {
                        Text(response.answer?.isEmpty == false ? response.answer! : WondL10n.t("No answer"))
                            .textSelection(.enabled)
                    }

                    if let retrieval = response.retrieval {
                        Section("Retrieval") {
                            if let mode = response.mode ?? retrieval.mode {
                                LabeledContent("Mode", value: mode)
                            }
                            if let status = retrieval.status {
                                LabeledContent("Status", value: WondL10n.t(status))
                            }
                            if let model = retrieval.model, !model.isEmpty {
                                LabeledContent("Model", value: model)
                            }
                            if let indexed = retrieval.indexed {
                                LabeledContent("Indexed", value: "\(indexed)")
                            }
                        }
                    }

                    if !response.citations.isEmpty {
                        Section("Citations") {
                            ForEach(response.citations) { citation in
                                AskCitationRow(citation: citation)
                            }
                        }
                    }
                } else if !isAsking {
                    Section {
                        ContentUnavailableView("No Answer", systemImage: "magnifyingglass")
                    }
                }
            }
            .navigationTitle("Ask")
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") {
                        questionFocused = false
                    }
                }
            }
        }
    }

    private var trimmedQuestion: String {
        question.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var askDisabled: Bool {
        isAsking || trimmedQuestion.isEmpty
    }

    @MainActor
    private func ask() async {
        let value = trimmedQuestion
        guard !value.isEmpty else { return }
        questionFocused = false
        isAsking = true
        errorMessage = nil
        defer { isAsking = false }
        do {
            response = try await store.syncService.ask(question: value)
        } catch {
            errorMessage = WondL10n.format("Ask failed: %@", error.localizedDescription)
        }
    }
}

private struct AskCitationRow: View {
    var citation: AskCitation

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Label(title, systemImage: icon)
                    .font(.body)
                Spacer()
                if let score = citation.score {
                    Text(score.formatted(.number.precision(.fractionLength(2))))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }

            if !detail.isEmpty {
                Text(detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .padding(.vertical, 3)
    }

    private var icon: String {
        if citation.type == "report" {
            return "doc.text"
        }
        return "recordingtape"
    }

    private var title: String {
        if citation.type == "report" {
            return citation.name ?? pathName ?? WondL10n.t("Report")
        }
        if let source = citation.source, let kind = citation.kind {
            return "\(source) / \(kind)"
        }
        if let id = citation.observationID {
            return WondL10n.format("Observation %d", id)
        }
        return citation.type.map { WondL10n.t($0.capitalized) } ?? WondL10n.t("Citation")
    }

    private var detail: String {
        [
            citation.time,
            citation.key,
            citation.path
        ]
        .compactMap { $0 }
        .filter { !$0.isEmpty }
        .joined(separator: " / ")
    }

    private var pathName: String? {
        guard let path = citation.path else { return nil }
        return URL(fileURLWithPath: path).lastPathComponent
    }
}
