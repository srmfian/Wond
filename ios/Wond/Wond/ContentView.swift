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

            SpeakerBrowserView()
                .tabItem {
                    Label("Speakers", systemImage: "person.wave.2")
                }

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
        }
    }
}
