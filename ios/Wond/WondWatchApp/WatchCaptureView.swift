import SwiftUI

struct WatchCaptureView: View {
    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Label("Watch recording removed", systemImage: "mic.slash")
                    .font(.headline)
                    .foregroundStyle(.secondary)

                Text("Use the iPhone app for audio capture.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding()
            .navigationTitle("Capture")
        }
    }
}
