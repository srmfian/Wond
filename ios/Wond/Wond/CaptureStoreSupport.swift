import Foundation

struct SyncExportPlan {
    var export: MobileExport
    var eventFingerprints: [String: String]
}

struct LocationAddressUpdate {
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
}

struct CaptureStorePersistence {
    let fileManager: FileManager
    let databaseFileName: String

    init(fileManager: FileManager = .default, databaseFileName: String = "capture-store.json") {
        self.fileManager = fileManager
        self.databaseFileName = databaseFileName
    }

    var documentsURL: URL {
        fileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
    }

    var databaseURL: URL {
        documentsURL.appendingPathComponent(databaseFileName)
    }

    func repairDocumentsDirectoryIfNeeded() {
        let url = documentsURL
        var isDirectory = ObjCBool(false)
        if fileManager.fileExists(atPath: url.path, isDirectory: &isDirectory) {
            guard !isDirectory.boolValue else { return }
            let migratedStore = try? Data(contentsOf: url)
            try? fileManager.removeItem(at: url)
            try? fileManager.createDirectory(at: url, withIntermediateDirectories: true)
            if let migratedStore {
                try? migratedStore.write(to: databaseURL, options: .atomic)
            }
            return
        }
        try? fileManager.createDirectory(at: url, withIntermediateDirectories: true)
    }

    func save(_ database: CaptureDatabase) throws {
        let data = try JSONEncoder.captureEncoder(prettyPrinted: true).encode(database)
        try data.write(to: databaseURL, options: .atomic)
    }

    func load() throws -> CaptureDatabase? {
        guard fileManager.fileExists(atPath: databaseURL.path) else { return nil }
        let data = try Data(contentsOf: databaseURL)
        return try JSONDecoder.captureDecoder().decode(CaptureDatabase.self, from: data)
    }

    func backupUnreadableDatabase(timestamp: String) {
        guard fileManager.fileExists(atPath: databaseURL.path) else { return }
        let backupURL = documentsURL.appendingPathComponent("capture-store-unreadable-\(timestamp).json")
        try? fileManager.copyItem(at: databaseURL, to: backupURL)
    }

    func recordingFolderURL(for sessionID: String, at date: Date, dayFormatter: DateFormatter) -> URL {
        let day = dayFormatter.string(from: date)
        return documentsURL
            .appendingPathComponent("recordings", isDirectory: true)
            .appendingPathComponent(day, isDirectory: true)
            .appendingPathComponent(sessionID, isDirectory: true)
    }

    func relativePath(forRecordingFile fileURL: URL) -> String {
        let root = documentsURL.path
        let path = fileURL.path
        if path.hasPrefix(root) {
            return String(path.dropFirst(root.count + 1))
        }
        return fileURL.lastPathComponent
    }

    func pruneEmptyRecordingFolders() {
        let recordings = documentsURL.appendingPathComponent("recordings", isDirectory: true)
        guard let enumerator = fileManager.enumerator(
            at: recordings,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else { return }
        let folders = enumerator.compactMap { $0 as? URL }.filter { url in
            (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        }
        for folder in folders.sorted(by: { $0.path.count > $1.path.count }) {
            if (try? fileManager.contentsOfDirectory(atPath: folder.path).isEmpty) == true {
                try? fileManager.removeItem(at: folder)
            }
        }
    }
}
