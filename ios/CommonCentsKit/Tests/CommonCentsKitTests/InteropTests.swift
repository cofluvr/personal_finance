// The client against the real Mac server (ios/interop/run_interop.py sets COMMONCENTS_INTEROP to
// its plan). Without it these tests return at once: they need the server it starts.

import Foundation
import Testing
@testable import CommonCentsKit

final class MemoryPairing: PairingKeeper, @unchecked Sendable {
    var paired: PairedMac?
    func load() -> PairedMac? { paired }
    func save(_ paired: PairedMac) throws { self.paired = paired }
    func delete() throws { paired = nil }
}

@Suite(.serialized) struct Interop {
    static let plan: [String: String]? = {
        guard let path = ProcessInfo.processInfo.environment["COMMONCENTS_INTEROP"],
              let data = FileManager.default.contents(atPath: path) else { return nil }
        return try? JSONSerialization.jsonObject(with: data) as? [String: String]
    }()

    @Test func pairsSyncsInstallsAndAcknowledges() async throws {
        guard let plan = Self.plan else { return }
        let store = SnapshotStore(folder: FileManager.default.temporaryDirectory
            .appendingPathComponent("interop-\(UUID().uuidString)"))
        let keeper = MemoryPairing()
        let client = SyncClient(store: store, keeper: keeper)
        let code = try #require(PairingCode.parsed(plan["pairing"]!))
        let paired = try await client.pair(code)
        #expect(paired.fingerprint == code.fingerprint)
        // The pairing code works once: the window closed with its use, and its server with it.
        await #expect(throws: SyncError.self) { _ = try await client.pair(code) }
        let moved = try client.reconnect(plan["reconnect"]!)
        #expect(moved.port != paired.port && moved.deviceId == paired.deviceId)
        let snapshot = try await client.syncNow()
        #expect(snapshot.snapshotId == plan["snapshot_id"])
        #expect(snapshot.contentSha256 == plan["content_sha256"])
        #expect(store.installed()?.snapshotId == plan["snapshot_id"])
        #expect(store.history().first?.outcome == .installed)

        // Another certificate pin is refused before anything is sent, and the snapshot kept.
        let impostor = MemoryPairing()
        impostor.paired = PairedMac(address: moved.address, port: moved.port,
                                    fingerprint: String(repeating: "0", count: 64),
                                    deviceId: moved.deviceId, deviceSecret: moved.deviceSecret,
                                    pairedAt: Date())
        let refused = SyncClient(store: store, keeper: impostor)
        await #expect(throws: SyncError.self) { _ = try await refused.syncNow() }
        #expect(store.installed()?.snapshotId == plan["snapshot_id"])

        // A wrong secret is unauthorized.
        let wrong = MemoryPairing()
        wrong.paired = PairedMac(address: moved.address, port: moved.port,
                                 fingerprint: moved.fingerprint, deviceId: moved.deviceId,
                                 deviceSecret: String(repeating: "A", count: 43), pairedAt: Date())
        await #expect(throws: SyncError.unauthorized) {
            _ = try await SyncClient(store: store, keeper: wrong).syncNow()
        }
    }
}
