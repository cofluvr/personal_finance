// The phone's side of sync-protocol.md: the pairing codes, the paired Mac kept in the Keychain,
// and a client that pins the Mac's certificate, fetches, checks, installs and only then
// acknowledges. tests/sync_reference_client.py is the same in Python.

import CryptoKit
import Foundation
import Security

public struct PairedMac: Codable, Equatable, Sendable {
    public var address: String
    public var port: Int
    /// The SHA-256 of the Mac's certificate's DER bytes, 64 lowercase hex digits.
    public let fingerprint: String
    public let deviceId: String
    public let deviceSecret: String
    public let pairedAt: Date

    public var fingerprintPrefix: String { String(fingerprint.prefix(16)) }
}

public struct PairingCode: Equatable, Sendable {
    public let address: String
    public let port: Int
    /// Nil when typed as a manual code: the person compares the presented prefix instead.
    public let fingerprint: String?
    public let secret: String

    static let scheme = "commoncents-pair:v1"
    static let reconnect = "commoncents-connect:v1"

    /// The QR code's payload, or a typed manual code.
    public static func parsed(_ text: String) -> PairingCode? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasPrefix(scheme + "?") {
            let fields = query(trimmed, scheme: scheme)
            guard Set(fields.keys) == ["address", "port", "fingerprint", "secret"],
                  let port = Int(fields["port"]!), let fingerprint = fields["fingerprint"],
                  fingerprint.count == 64 else { return nil }
            return PairingCode(address: fields["address"]!, port: port, fingerprint: fingerprint,
                               secret: fields["secret"]!)
        }
        return manual(trimmed)
    }

    /// The reconnect code `pf sync serve` shows: a new address and port, no secret.
    public static func reconnection(_ text: String) -> (address: String, port: Int, fingerprint: String)? {
        let fields = query(text.trimmingCharacters(in: .whitespacesAndNewlines), scheme: reconnect)
        guard Set(fields.keys) == ["address", "port", "fingerprint"], let port = Int(fields["port"]!)
        else { return nil }
        return (fields["address"]!, port, fields["fingerprint"]!)
    }

    static func query(_ text: String, scheme: String) -> [String: String] {
        guard text.hasPrefix(scheme + "?") else { return [:] }
        var fields: [String: String] = [:]
        for part in text.dropFirst(scheme.count + 1).split(separator: "&") {
            let pieces = part.split(separator: "=", maxSplits: 1).map(String.init)
            guard pieces.count == 2, fields[pieces[0]] == nil else { return [:] }
            fields[pieces[0]] = pieces[1]
        }
        return fields
    }

    /// 38 bytes as unpadded RFC 4648 base32, in groups of four: address, port, secret.
    static func manual(_ text: String) -> PairingCode? {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        var bits = 0, value = 0
        var bytes: [UInt8] = []
        for character in text.uppercased() where character != "-" && character != " " {
            guard let index = alphabet.firstIndex(of: character) else { return nil }
            value = (value << 5) | index
            bits += 5
            if bits >= 8 {
                bytes.append(UInt8((value >> (bits - 8)) & 0xFF))
                bits -= 8
            }
        }
        guard bytes.count == 38 else { return nil }
        let address = bytes[0..<4].map(String.init).joined(separator: ".")
        let port = Int(bytes[4]) << 8 | Int(bytes[5])
        let secret = Data(bytes[6...]).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
        return PairingCode(address: address, port: port, fingerprint: nil, secret: secret)
    }
}

public protocol PairingKeeper: Sendable {
    func load() -> PairedMac?
    func save(_ paired: PairedMac) throws
    func delete() throws
}

/// The paired Mac in the Keychain, readable only while the phone is unlocked, never synced.
public struct KeychainPairing: PairingKeeper {
    let service = "CommonCents.paired-mac"

    public init() {}

    var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: "mac", kSecUseDataProtectionKeychain as String: true]
    }

    public func load() -> PairedMac? {
        var found: CFTypeRef?
        var search = query
        search[kSecReturnData as String] = true
        guard SecItemCopyMatching(search as CFDictionary, &found) == errSecSuccess,
              let data = found as? Data else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(PairedMac.self, from: data)
    }

    public func save(_ paired: PairedMac) throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try delete()
        var item = query
        item[kSecValueData as String] = try encoder.encode(paired)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let status = SecItemAdd(item as CFDictionary, nil)
        guard status == errSecSuccess else { throw SyncError.keychain(status) }
    }

    public func delete() throws {
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw SyncError.keychain(status)
        }
    }
}

public enum SyncError: Error, Equatable, CustomStringConvertible {
    case notPaired
    case pinMismatch(presented: String)
    case refused(status: Int)
    case unauthorized
    case unsupportedMajor(supported: [Int])
    case badAnswer
    case keychain(OSStatus)
    case unreachable(String)
    case snapshot(String)

    public var description: String {
        switch self {
        case .notPaired: return "This phone is not paired with a Mac."
        case let .pinMismatch(presented):
            return "The Mac's certificate is not the paired one (\(presented.prefix(16))). Pair again only if you rotated its identity."
        case .refused(let status): return "The Mac refused the request (\(status))."
        case .unauthorized: return "The Mac no longer accepts this phone. Pair it again."
        case let .unsupportedMajor(supported):
            return "The Mac serves snapshot version \(supported.map(String.init).joined(separator: ", ")).x, and this app reads \(SnapshotValidator.supportedMajor).x. Update the app or the Mac."
        case .badAnswer: return "The Mac's answer was not one the protocol allows."
        case .keychain(let status): return "The Keychain refused (\(status))."
        case .unreachable(let detail):
            let reason = detail.trimmingCharacters(in: CharacterSet(charactersIn: ". "))
            return "The Mac was not reachable: \(reason). Is it awake, with sync serve running, on this network?"
        case .snapshot(let reason): return "The snapshot was refused: \(reason)"
        }
    }
}

/// Pins the certificate: anything but the expected SHA-256 is cancelled before a byte is sent.
final class PinningDelegate: NSObject, URLSessionDelegate, @unchecked Sendable {
    let expected: String?
    private(set) var presented: String?

    init(expected: String?) {
        self.expected = expected
    }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge)
        async -> (URLSession.AuthChallengeDisposition, URLCredential?) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let leaf = chain.first else { return (.cancelAuthenticationChallenge, nil) }
        let digest = SHA256.hash(data: SecCertificateCopyData(leaf) as Data)
            .map { String(format: "%02x", $0) }.joined()
        presented = digest
        // With no expected pin (a typed manual code), the person compares the prefix first.
        guard expected == nil || digest == expected else {
            return (.cancelAuthenticationChallenge, nil)
        }
        return (.useCredential, URLCredential(trust: trust))
    }
}

public struct SyncClient: Sendable {
    public let store: SnapshotStore
    public let keeper: PairingKeeper

    public init(store: SnapshotStore, keeper: PairingKeeper) {
        self.store = store
        self.keeper = keeper
    }

    static func session(pinning expected: String?) -> (URLSession, PinningDelegate) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.tlsMinimumSupportedProtocolVersion = .TLSv13
        configuration.timeoutIntervalForRequest = 15
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        let delegate = PinningDelegate(expected: expected)
        return (URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil),
                delegate)
    }

    static func url(_ address: String, _ port: Int, _ path: String) -> URL {
        URL(string: "https://\(address):\(port)\(path)")!
    }

    static func exchange(_ request: URLRequest, pinning expected: String?)
        async throws -> (Data, HTTPURLResponse, String?) {
        let (session, delegate) = session(pinning: expected)
        defer { session.finishTasksAndInvalidate() }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw SyncError.badAnswer }
            return (data, http, delegate.presented)
        } catch let error as URLError where error.code == .cancelled {
            throw SyncError.pinMismatch(presented: delegate.presented ?? "none")
        } catch let error as URLError {
            throw SyncError.unreachable(error.localizedDescription)
        }
    }

    /// Pairs with the Mac a code names, keeping the pairing in the Keychain. For a typed code,
    /// confirmPrefix is asked whether the presented certificate's first 16 digits match.
    public func pair(_ code: PairingCode, now: Date = Date(),
                     confirmPrefix: @Sendable (String) async -> Bool = { _ in false })
        async throws -> PairedMac {
        var request = URLRequest(url: Self.url(code.address, code.port, "/v1/pair"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["pairing_secret": code.secret])
        let (data, response, presented) = try await Self.exchange(request, pinning: code.fingerprint)
        guard let presented else { throw SyncError.badAnswer }
        if code.fingerprint == nil, !(await confirmPrefix(String(presented.prefix(16)))) {
            throw SyncError.pinMismatch(presented: presented)
        }
        guard response.statusCode == 200 else {
            throw response.statusCode == 401 ? SyncError.unauthorized
                : SyncError.refused(status: response.statusCode)
        }
        guard let body = try JSONSerialization.jsonObject(with: data) as? [String: String],
              Set(body.keys) == ["device_id", "device_secret"] else { throw SyncError.badAnswer }
        let paired = PairedMac(address: code.address, port: code.port, fingerprint: presented,
                               deviceId: body["device_id"]!, deviceSecret: body["device_secret"]!,
                               pairedAt: now)
        try keeper.save(paired)
        return paired
    }

    /// Fetch, check, install, then acknowledge. Any failure keeps the last valid snapshot.
    @discardableResult
    public func syncNow(now: Date = Date()) async throws -> Snapshot {
        do {
            return try await fetchInstallAcknowledge(now: now)
        } catch {
            store.recordFailure("\(error)", now: now)
            throw error
        }
    }

    func fetchInstallAcknowledge(now: Date) async throws -> Snapshot {
        guard let paired = keeper.load() else { throw SyncError.notPaired }
        let bearer = "Bearer \(paired.deviceId).\(paired.deviceSecret)"
        var request = URLRequest(url: Self.url(paired.address, paired.port, "/v1/snapshot/latest"))
        request.setValue(bearer, forHTTPHeaderField: "Authorization")
        request.setValue(String(SnapshotValidator.supportedMajor),
                         forHTTPHeaderField: "Accept-Snapshot-Major")
        let (data, response, _) = try await Self.exchange(request, pinning: paired.fingerprint)
        switch response.statusCode {
        case 200: break
        case 401: throw SyncError.unauthorized
        case 409:
            let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            throw SyncError.unsupportedMajor(supported: body?["supported_majors"] as? [Int] ?? [])
        default: throw SyncError.refused(status: response.statusCode)
        }
        guard SHA256Hex.of(data) == response.value(forHTTPHeaderField: "Snapshot-SHA256") else {
            throw SyncError.snapshot("the bytes do not match their digest")
        }
        let snapshot: Snapshot
        do {
            snapshot = try store.install(data, now: now)
        } catch let refused as SnapshotRefused {
            throw SyncError.snapshot(refused.reason)
        }
        var acknowledgement = URLRequest(url: Self.url(paired.address, paired.port, "/v1/ack"))
        acknowledgement.httpMethod = "POST"
        acknowledgement.setValue(bearer, forHTTPHeaderField: "Authorization")
        acknowledgement.setValue("application/json", forHTTPHeaderField: "Content-Type")
        acknowledgement.httpBody = try JSONSerialization.data(withJSONObject: [
            "snapshot_id": snapshot.snapshotId, "content_sha256": snapshot.contentSha256])
        let (_, acknowledged, _) = try await Self.exchange(acknowledgement, pinning: paired.fingerprint)
        guard acknowledged.statusCode == 204 else {
            throw SyncError.refused(status: acknowledged.statusCode)
        }
        return snapshot
    }

    /// Takes a new address and port from a reconnect code, only for the same certificate.
    public func reconnect(_ text: String) throws -> PairedMac {
        guard var paired = keeper.load() else { throw SyncError.notPaired }
        guard let found = PairingCode.reconnection(text) else { throw SyncError.badAnswer }
        guard found.fingerprint == paired.fingerprint else {
            throw SyncError.pinMismatch(presented: found.fingerprint)
        }
        paired.address = found.address
        paired.port = found.port
        try keeper.save(paired)
        return paired
    }

    /// Deleting local data removes the snapshot, its history and the pairing.
    public func deleteLocalData() throws {
        try store.deleteAll()
        try keeper.delete()
    }
}
