import SwiftUI

struct ContentView: View {
    var body: some View {
        TabView {
            CaptureView()
                .tabItem {
                    Label("Capture", systemImage: "record.circle")
                }

            CaptureTimelineView()
                .tabItem {
                    Label("Today", systemImage: "calendar")
                }

            AskView()
                .tabItem {
                    Label("Ask", systemImage: "magnifyingglass")
                }

            SpeakerReviewView()
                .tabItem {
                    Label("Review", systemImage: "person.crop.circle.badge.questionmark")
                }

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
        }
    }
}
