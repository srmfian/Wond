import Foundation

enum WondL10n {
    static func t(_ key: String) -> String {
        Bundle.main.localizedString(forKey: key, value: key, table: nil)
    }

    static func format(_ key: String, _ arguments: CVarArg...) -> String {
        String(format: t(key), locale: Locale.current, arguments: arguments)
    }
}
