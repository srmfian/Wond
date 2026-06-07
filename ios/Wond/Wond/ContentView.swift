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

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape")
                }
        }
    }
}
