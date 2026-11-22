// The one installed snapshot (sync-protocol.md §4, D-079's I2): checked before it is installed,
// written atomically with file protection, the last valid one kept on any failure, and deleted
// with the pairing on request. A sync history of outcomes is kept beside it, holding no data.

import Foundation

public struct SyncEvent: Codable, Equatable, Sendable, Identifiable {
    public enum Outcome: String, Codable, Sendable { case installed, failed }
    public let at: Date
    public let outcome: Outcome
    public let detail: String
    public var id: Date { at }
}

public final class SnapshotStore: @unchecked Sendable {
    public let folder: URL
    let lock = NSLock()
    public static let snapshotName = "snapshot.json"
    static let historyName = "sync-history.json"
    static let historyLimit = 20

    public init(folder: URL) {
        self.folder = folder
    }

    public static func applicationSupport() throws -> SnapshotStore {
        let base = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                               appropriateFor: nil, create: true)
        return SnapshotStore(folder: base.appendingPathComponent("CommonCents", isDirectory: true))
    }

    var snapshotURL: URL { folder.appendingPathComponent(Self.snapshotName) }
    var historyURL: URL { folder.appendingPathComponent(Self.historyName) }

    /// The installed snapshot, checked again on every load, or nil when none is.
    public func installed() -> Snapshot? {
        guard let data = try? Data(contentsOf: snapshotURL) else { return nil }
        return try? Snapshot.decoded(fromVerified: data)
    }

    public var installedBytes: Int? {
        (try? FileManager.default.attributesOfItem(atPath: snapshotURL.path)[.size] as? Int) ?? nil
    }

    /// Checks the bytes, and installs them only if they pass. Throws, keeping the last valid
    /// snapshot, if they do not.
    @discardableResult
    public func install(_ data: Data, now: Date = Date()) throws -> Snapshot {
        lock.lock()
        defer { lock.unlock() }
        let snapshot: Snapshot
        do {
            snapshot = try Snapshot.decoded(fromVerified: data)
        } catch {
            record(SyncEvent(at: now, outcome: .failed, detail: "\(error)"))
            throw error
        }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        // Data.write(.atomic) writes a temporary file and renames it over the old one.
        var options: Data.WritingOptions = [.atomic]
        #if os(iOS)
        options.insert(.completeFileProtectionUnlessOpen)
        #endif
        try data.write(to: snapshotURL, options: options)
        record(SyncEvent(at: now, outcome: .installed, detail: "Snapshot \(snapshot.snapshotId)"))
        return snapshot
    }

    public func recordFailure(_ detail: String, now: Date = Date()) {
        lock.lock()
        defer { lock.unlock() }
        record(SyncEvent(at: now, outcome: .failed, detail: detail))
    }

    public func history() -> [SyncEvent] {
        guard let data = try? Data(contentsOf: historyURL) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode([SyncEvent].self, from: data)) ?? []
    }

    func record(_ event: SyncEvent) {
        let events = Array(([event] + history()).prefix(Self.historyLimit))
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? encoder.encode(events).write(to: historyURL, options: .atomic)
    }

    /// Removes the snapshot and its history. The pairing is the Keychain's, removed by its owner.
    public func deleteAll() throws {
        lock.lock()
        defer { lock.unlock() }
        for url in [snapshotURL, historyURL] where FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
    }
}
