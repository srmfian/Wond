import Combine
import CommonCrypto
import CryptoKit
import Foundation
import Network
import Security

struct SyncPayloadSnapshot {
    var fingerprint: String
    var eventCount: Int
    var eventFingerprints: [String: String]
}

struct SyncUploadPackage {
    var archiveURL: URL
    var snapshot: SyncPayloadSnapshot
}

struct SyncUploadResponse: Decodable {
    var ok: Bool?
    var error: String?
    var imported: Int?
    var skipped: Int?
    var reports: [String]?
    var analyzed: [String]?
    var cleaned: [String]?
    var errors: [String]?

    var summaryText: String {
        var parts: [String] = []
        if let imported {
            parts.append(WondL10n.format("imported %d", imported))
        }
        if let skipped {
            parts.append(WondL10n.format("skipped %d", skipped))
        }
        if let analyzed, !analyzed.isEmpty {
            parts.append(WondL10n.format("analyzed %d", analyzed.count))
        }
        if let reports, !reports.isEmpty {
            parts.append(WondL10n.format("reports %d", reports.count))
        }
        return parts.joined(separator: ", ")
    }
}

@MainActor
final class SyncService: NSObject, ObservableObject, URLSessionTaskDelegate, URLSessionDataDelegate {
    @Published private(set) var isBrowsing = false
    @Published private(set) var isUploading = false
    @Published private(set) var lastStatus: String?
    @Published private(set) var lastUploadResponse: SyncUploadResponse?
    @Published private(set) var lastMacStatus: MacStatusResponse?
    @Published private(set) var lastMacStatusError: String?

    var uploadPackageProvider: (() throws -> SyncUploadPackage)?
    var tokenProvider: (() -> String)?
    var remoteURLProvider: (() -> String)?
    var wifiOnlyProvider: (() -> Bool)?
    var onStatus: ((String, Date?) -> Void)?
    var onUploadAccepted: ((SyncPayloadSnapshot) -> Void)?

    private let pathMonitor = NWPathMonitor()
    private let pathQueue = DispatchQueue(label: "Wond.SyncPath")
    private var lastUploadAttempt: Date?
    private var isOnWiFi = false
    private var responseData: [Int: Data] = [:]
    private var uploadDestinations: [Int: String] = [:]
    private var uploadSnapshots: [Int: SyncPayloadSnapshot] = [:]
    private lazy var backgroundSession: URLSession = {
        let bundleIdentifier = Bundle.main.bundleIdentifier ?? "com.example.Wond"
        let configuration = URLSessionConfiguration.background(withIdentifier: "\(bundleIdentifier).sync-upload")
        configuration.sessionSendsLaunchEvents = true
        configuration.isDiscretionary = false
        configuration.waitsForConnectivity = true
        return URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }()

    override init() {
        super.init()
        pathMonitor.pathUpdateHandler = { [weak self] path in
            Task { @MainActor in
                guard let self else { return }
                self.isOnWiFi = path.status == .satisfied && path.usesInterfaceType(.wifi)
                if self.isBrowsing,
                   self.canAutoSyncOnCurrentNetwork(),
                   self.shouldUploadAutomatically(),
                   let remoteURL = self.configuredRemoteURL() {
                    await self.upload(
                        to: remoteURL,
                        destinationName: remoteURL.host ?? "Remote Mac",
                        allowCellular: !(self.wifiOnlyProvider?() ?? true)
                    )
                }
            }
        }
        pathMonitor.start(queue: pathQueue)
    }

    func start() {
        guard !isBrowsing else { return }
        isBrowsing = true
        guard let remoteURL = configuredRemoteURL() else {
            update(WondL10n.t("Remote sync URL is required"))
            return
        }
        update(WondL10n.t("Remote sync ready"))
        if canAutoSyncOnCurrentNetwork(), shouldUploadAutomatically() {
            Task {
                await upload(
                    to: remoteURL,
                    destinationName: remoteURL.host ?? WondL10n.t("Remote Mac"),
                    allowCellular: !(wifiOnlyProvider?() ?? true)
                )
            }
        }
    }

    func stop() {
        isBrowsing = false
        update(WondL10n.t("Sync stopped"))
    }

    func syncNow() {
        guard let remoteURL = configuredRemoteURL() else {
            update(WondL10n.t("Remote sync URL is required"))
            return
        }
        Task {
            await upload(to: remoteURL, destinationName: remoteURL.host ?? WondL10n.t("Remote Mac"), allowCellular: true)
        }
    }

    func ask(question: String) async throws -> AskResponse {
        guard let url = configuredEndpointURL(path: "/ask") else {
            throw SyncError.server(WondL10n.t("Remote sync URL is required"))
        }
        let payload = AskRequest(question: question)
        let body = try JSONEncoder().encode(payload)
        var request = try authenticatedAPIRequest(url: url, method: "POST", body: body)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateHTTPResponse(response, data: data)
        let askResponse = try JSONDecoder().decode(AskResponse.self, from: data)
        if askResponse.ok == false {
            throw SyncError.server(askResponse.error ?? WondL10n.t("Ask failed"))
        }
        return askResponse
    }

    func fetchSpeakers(parameters: [String: String] = [:]) async throws -> MobileSpeakersResponse {
        var values = parameters
        values["speaker_limit"] = values["speaker_limit"] ?? "160"
        values["sample_limit"] = values["sample_limit"] ?? "40"
        let queryItems = values.keys.sorted().map { key in
            URLQueryItem(name: key, value: values[key])
        }
        guard let url = configuredEndpointURL(
            path: "/speakers",
            queryItems: queryItems
        ) else {
            throw SyncError.server(WondL10n.t("Remote sync URL is required"))
        }
        let request = try authenticatedAPIRequest(url: url, method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateHTTPResponse(response, data: data)
        let payload = try JSONDecoder().decode(MobileSpeakersResponse.self, from: data)
        if payload.ok == false {
            throw SyncError.server(payload.error ?? WondL10n.t("Speakers unavailable"))
        }
        return payload
    }

    func fetchSpeakerSampleAudio(sampleID: Int) async throws -> Data {
        guard let url = configuredEndpointURL(path: "/speaker-sample/\(sampleID)") else {
            throw SyncError.server(WondL10n.t("Remote sync URL is required"))
        }
        let request = try authenticatedAPIRequest(url: url, method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateHTTPResponse(response, data: data)
        return data
    }

    func refreshMacStatus() async {
        do {
            lastMacStatusError = nil
            lastMacStatus = try await fetchMacStatus()
        } catch {
            lastMacStatusError = error.localizedDescription
            update(WondL10n.format("Mac status failed: %@", error.localizedDescription))
        }
    }

    func fetchMacStatus() async throws -> MacStatusResponse {
        guard let url = configuredEndpointURL(path: "/status") else {
            throw SyncError.server(WondL10n.t("Remote sync URL is required"))
        }
        let request = try authenticatedAPIRequest(url: url, method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateHTTPResponse(response, data: data)
        let payload = try JSONDecoder().decode(MacStatusResponse.self, from: data)
        if payload.ok == false {
            throw SyncError.server(WondL10n.t("Mac status unavailable"))
        }
        return payload
    }

    private func shouldUploadAutomatically() -> Bool {
        if isUploading {
            return false
        }
        guard let lastUploadAttempt else {
            self.lastUploadAttempt = Date()
            return true
        }
        if Date().timeIntervalSince(lastUploadAttempt) > 600 {
            self.lastUploadAttempt = Date()
            return true
        }
        return false
    }

    private func canAutoSyncOnCurrentNetwork() -> Bool {
        if wifiOnlyProvider?() ?? true {
            return isOnWiFi
        }
        return true
    }

    private func upload(to uploadURL: URL, destinationName: String, allowCellular: Bool) async {
        do {
            isUploading = true
            update(WondL10n.t("Preparing today's upload"))
            let token = tokenProvider?() ?? ""
            guard !token.isEmpty else {
                throw SyncError.server(WondL10n.t("Sync token is required for encrypted upload"))
            }
            guard let uploadPackageProvider else {
                throw SyncError.server(WondL10n.t("No upload package provider"))
            }
            let package = try uploadPackageProvider()
            let snapshot = package.snapshot
            guard snapshot.eventCount > 0 else {
                update(WondL10n.t("Sync skipped: no new data"))
                isUploading = false
                return
            }
            let archiveURL = package.archiveURL
            let encryptedURL = try encryptedEnvelope(for: archiveURL, token: token)
            let encryptedData = try Data(contentsOf: encryptedURL)
            let bodyHash = SHA256.hash(data: encryptedData).map { String(format: "%02x", $0) }.joined()
            let timestamp = String(Int(Date().timeIntervalSince1970))
            let signature = hmacSignature(token: token, timestamp: timestamp, bodyHash: bodyHash)
            var request = URLRequest(url: uploadURL)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(encryptedURL.lastPathComponent, forHTTPHeaderField: "X-Filename")
            request.setValue("AESGCM-v1", forHTTPHeaderField: "X-Wond-Encrypted")
            request.setValue(timestamp, forHTTPHeaderField: "X-Wond-Timestamp")
            request.setValue(bodyHash, forHTTPHeaderField: "X-Wond-Body-SHA256")
            request.setValue(signature, forHTTPHeaderField: "X-Wond-Signature")
            if !allowCellular {
                request.allowsCellularAccess = false
                request.allowsExpensiveNetworkAccess = false
                request.allowsConstrainedNetworkAccess = false
            }
            let task = backgroundSession.uploadTask(with: request, fromFile: encryptedURL)
            responseData[task.taskIdentifier] = Data()
            uploadDestinations[task.taskIdentifier] = destinationName
            uploadSnapshots[task.taskIdentifier] = snapshot
            task.resume()
            update(WondL10n.format("Queued background upload to %@", destinationName))
        } catch {
            update(WondL10n.format("Sync failed: %@", error.localizedDescription))
            isUploading = false
        }
    }

    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        Task { @MainActor [weak self] in
            self?.responseData[dataTask.taskIdentifier, default: Data()].append(data)
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            let destination = self.uploadDestinations.removeValue(forKey: task.taskIdentifier) ?? "Mac"
            let snapshot = self.uploadSnapshots.removeValue(forKey: task.taskIdentifier)
            let data = self.responseData.removeValue(forKey: task.taskIdentifier) ?? Data()
            defer { self.isUploading = false }
            if let error {
                self.update(WondL10n.format("Sync failed: %@", error.localizedDescription))
                return
            }
            guard let http = task.response as? HTTPURLResponse else {
                self.update(WondL10n.t("Sync failed: invalid response"))
                return
            }
            guard (200..<300).contains(http.statusCode) else {
                let body = String(data: data, encoding: .utf8) ?? ""
                self.update(WondL10n.format("Sync failed: HTTP %d %@", http.statusCode, body))
                return
            }
            if let response = try? JSONDecoder().decode(SyncUploadResponse.self, from: data) {
                self.lastUploadResponse = response
                if response.ok == false {
                    self.update(WondL10n.format("Sync failed: %@", response.error ?? WondL10n.t("server rejected upload")))
                    return
                }
                if let errors = response.errors, !errors.isEmpty {
                    self.update(WondL10n.format("Sync failed: %@", errors.prefix(2).joined(separator: "; ")))
                    return
                }
            }
            if let snapshot {
                let detail = self.lastUploadResponse?.summaryText ?? ""
                let suffix = detail.isEmpty ? "" : " (\(detail))"
                self.update(WondL10n.format("Synced %d new items to %@%@", snapshot.eventCount, destination, suffix), at: Date())
                self.onUploadAccepted?(snapshot)
            } else {
                self.update(WondL10n.format("Synced to %@", destination), at: Date())
            }
        }
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        Task { @MainActor in
            AppDelegate.backgroundSessionCompletionHandler?()
            AppDelegate.backgroundSessionCompletionHandler = nil
        }
    }

    private func encryptedEnvelope(for archiveURL: URL, token: String) throws -> URL {
        let plaintext = try Data(contentsOf: archiveURL)
        var salt = Data(count: 16)
        var nonceBytes = Data(count: 12)
        _ = salt.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, 16, $0.baseAddress!) }
        _ = nonceBytes.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, 12, $0.baseAddress!) }
        let key = try deriveKey(token: token, salt: salt)
        let nonce = try AES.GCM.Nonce(data: nonceBytes)
        let sealed = try AES.GCM.seal(plaintext, using: key, nonce: nonce, authenticating: Data("WondSyncV1".utf8))
        guard let combined = sealed.combined else {
            throw SyncError.server(WondL10n.t("Encryption failed"))
        }
        let envelope = EncryptedEnvelope(
            version: 1,
            algorithm: "AES-256-GCM",
            kdf: "PBKDF2-HMAC-SHA256",
            iterations: 200_000,
            salt: salt.base64EncodedString(),
            nonce: nonceBytes.base64EncodedString(),
            ciphertext: combined.dropFirst(12).base64EncodedString()
        )
        let output = FileManager.default.temporaryDirectory
            .appendingPathComponent(archiveURL.deletingPathExtension().lastPathComponent)
            .appendingPathExtension("pcsync")
        let data = try JSONEncoder().encode(envelope)
        try data.write(to: output, options: .atomic)
        return output
    }

    private func hmacSignature(token: String, timestamp: String, bodyHash: String) -> String {
        let key = SymmetricKey(data: Data(token.utf8))
        let message = Data("\(timestamp)\n\(bodyHash)".utf8)
        let signature = HMAC<SHA256>.authenticationCode(for: message, using: key)
        return Data(signature).base64EncodedString()
    }

    private func hmacSignature(
        token: String,
        timestamp: String,
        method: String,
        requestTarget: String,
        bodyHash: String
    ) -> String {
        let key = SymmetricKey(data: Data(token.utf8))
        let message = Data("\(timestamp)\n\(method.uppercased())\n\(requestTarget)\n\(bodyHash)".utf8)
        let signature = HMAC<SHA256>.authenticationCode(for: message, using: key)
        return Data(signature).base64EncodedString()
    }

    private func deriveKey(token: String, salt: Data) throws -> SymmetricKey {
        let password = Data(token.utf8)
        var derived = Data(repeating: 0, count: 32)
        let derivedLength = derived.count
        let status: Int32 = derived.withUnsafeMutableBytes { derivedBytes in
            salt.withUnsafeBytes { saltBytes in
                password.withUnsafeBytes { passwordBytes in
                    CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2),
                        passwordBytes.bindMemory(to: Int8.self).baseAddress,
                        password.count,
                        saltBytes.bindMemory(to: UInt8.self).baseAddress,
                        salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                        200_000,
                        derivedBytes.bindMemory(to: UInt8.self).baseAddress,
                        derivedLength
                    )
                }
            }
        }
        guard status == Int32(kCCSuccess) else {
            throw SyncError.server(WondL10n.t("Key derivation failed"))
        }
        return SymmetricKey(data: derived)
    }

    private func configuredRemoteURL() -> URL? {
        let raw = remoteURLProvider?().trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !raw.isEmpty else { return nil }
        if let url = URL(string: raw), url.scheme != nil {
            return normalizedUploadURL(url)
        }
        if let url = URL(string: "https://\(raw)") {
            return normalizedUploadURL(url)
        }
        return nil
    }

    private func configuredEndpointURL(path: String, queryItems: [URLQueryItem] = []) -> URL? {
        guard let uploadURL = configuredRemoteURL() else { return nil }
        var components = URLComponents(url: uploadURL, resolvingAgainstBaseURL: false)
        components?.path = path
        components?.query = nil
        components?.queryItems = queryItems.isEmpty ? nil : queryItems
        return components?.url
    }

    private func normalizedUploadURL(_ url: URL) -> URL? {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        if components?.path.isEmpty ?? true {
            components?.path = "/upload"
        }
        return components?.url
    }

    private func authenticatedAPIRequest(url: URL, method: String, body: Data = Data()) throws -> URLRequest {
        let token = tokenProvider?() ?? ""
        guard !token.isEmpty else {
            throw SyncError.server(WondL10n.t("Sync token is required"))
        }
        let bodyHash = sha256Hex(body)
        let timestamp = String(Int(Date().timeIntervalSince1970))
        let requestTarget = requestTarget(for: url)
        let signature = hmacSignature(
            token: token,
            timestamp: timestamp,
            method: method,
            requestTarget: requestTarget,
            bodyHash: bodyHash
        )
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(timestamp, forHTTPHeaderField: "X-Wond-Timestamp")
        request.setValue(bodyHash, forHTTPHeaderField: "X-Wond-Body-SHA256")
        request.setValue(signature, forHTTPHeaderField: "X-Wond-Signature")
        if !body.isEmpty {
            request.httpBody = body
        }
        return request
    }

    private func requestTarget(for url: URL) -> String {
        var target = url.path.isEmpty ? "/" : url.path
        if let query = url.query, !query.isEmpty {
            target += "?\(query)"
        }
        return target
    }

    private func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func validateHTTPResponse(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else {
            throw SyncError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw SyncError.server("HTTP \(http.statusCode) \(body)")
        }
    }

    private func update(_ message: String, at date: Date? = nil) {
        lastStatus = message
        onStatus?(message, date)
    }
}

enum SyncError: LocalizedError {
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return WondL10n.t("Invalid server response")
        case .server(let message):
            return message
        }
    }
}

struct EncryptedEnvelope: Encodable {
    var version: Int
    var algorithm: String
    var kdf: String
    var iterations: Int
    var salt: String
    var nonce: String
    var ciphertext: String
}
