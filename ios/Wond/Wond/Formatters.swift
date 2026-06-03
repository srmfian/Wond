import Foundation

enum CaptureFormatters {
    static func clock(_ date: Date) -> String {
        date.formatted(date: .omitted, time: .shortened)
    }

    static func day(_ date: Date) -> String {
        date.formatted(date: .abbreviated, time: .omitted)
    }

    static func duration(_ seconds: TimeInterval) -> String {
        let value = max(0, Int(seconds.rounded()))
        let hours = value / 3600
        let minutes = (value % 3600) / 60
        let remainingSeconds = value % 60
        if hours > 0 {
            return WondL10n.format("%dh %dm", hours, minutes)
        }
        if minutes > 0 {
            return WondL10n.format("%dm %ds", minutes, remainingSeconds)
        }
        return WondL10n.format("%ds", remainingSeconds)
    }

    static func bytes(_ value: Int64?) -> String {
        guard let value else { return "" }
        return ByteCountFormatter.string(fromByteCount: value, countStyle: .file)
    }
}
