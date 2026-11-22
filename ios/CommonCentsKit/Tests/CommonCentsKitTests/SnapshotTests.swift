// The phone's checks against the backend's own golden snapshot and copies of it changed one way
// each (D-079, the I1 to I3 slice plan; shared-contract §6). Synthetic data only.

import Foundation
import Testing
@testable import CommonCentsKit

let repository = URL(fileURLWithPath: #filePath)
    .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    .deletingLastPathComponent().deletingLastPathComponent()
let golden = try! Data(contentsOf: repository
    .appendingPathComponent("tests/fixtures/synthetic/snapshots/v1.0/household.json"))

/// The golden document changed by `change`, its digest recomputed unless told not to.
func changed(redigest: Bool = true, _ change: (inout [String: Any]) -> Void) -> Data {
    var document = try! JSONSerialization.jsonObject(with: golden) as! [String: Any]
    change(&document)
    var parser = StrictParser(try! JSONSerialization.data(withJSONObject: document))
    var value = try! parser.document()
    if redigest, case var .object(pairs) = value, let content = value["content"] {
        pairs.removeAll { $0.0 == "content_sha256" }
        pairs.append(("content_sha256", .string(CanonicalJSON.sha256Hex(of: content))))
        value = .object(pairs)
    }
    return CanonicalJSON.encoded(value)
}

func content(_ document: inout [String: Any], _ change: (inout [String: Any]) -> Void) {
    var inner = document["content"] as! [String: Any]
    change(&inner)
    document["content"] = inner
}

func refusal(_ data: Data) -> String? {
    do {
        _ = try SnapshotValidator.verified(data)
        return nil
    } catch let refused as SnapshotRefused {
        return refused.reason
    } catch {
        return "\(error)"
    }
}

@Suite struct CanonicalBytes {
    @Test func theGoldenSnapshotIsAcceptedAndDecodes() throws {
        #expect(refusal(golden) == nil)
        let snapshot = try Snapshot.decoded(fromVerified: golden)
        #expect(snapshot.schemaVersion == "1.0")
        #expect(snapshot.content.accounts.isEmpty == false)
        #expect(snapshot.content.cutoff.asOf == snapshot.content.period.windowLastDay)
    }

    @Test func reencodingGivesTheSameBytes() throws {
        var parser = StrictParser(golden)
        #expect(CanonicalJSON.encoded(try parser.document()) == golden)
    }

    @Test func anInsignificantSpaceIsRefused() {
        var spaced = golden
        spaced.insert(UInt8(ascii: " "), at: 1)
        #expect(refusal(spaced)?.contains("not in canonical form") == true
                || refusal(spaced)?.contains("not UTF-8 JSON") == true)
    }

    @Test func aFloatIsRefused() {
        let text = String(decoding: golden, as: UTF8.self)
        let floated = text.replacingOccurrences(of: "\"window_days\":90", with: "\"window_days\":90.0")
        #expect(floated != text)
        #expect(refusal(Data(floated.utf8)) == "the file holds a number that is not an integer.")
    }

    @Test func aOneByteChangeIsRefusedByTheDigest() {
        let text = String(decoding: golden, as: UTF8.self)
        let account = text.range(of: "\"display_name\":\"")!
        var bytes = Array(text.utf8)
        let index = text.utf8.distance(from: text.utf8.startIndex, to: account.upperBound.samePosition(in: text.utf8)!)
        bytes[index] = bytes[index] == UInt8(ascii: "Z") ? UInt8(ascii: "Y") : UInt8(ascii: "Z")
        #expect(refusal(Data(bytes)) == "the snapshot's content does not match its digest.")
    }

    @Test func escapesMatchPythons() throws {
        let value: JSONValue = .object([("b", .string("line\nbreak \"quoted\" \u{01} é")), ("a", .integer(-5))])
        #expect(String(decoding: CanonicalJSON.encoded(value), as: UTF8.self)
                == "{\"a\":-5,\"b\":\"line\\nbreak \\\"quoted\\\" \\u0001 é\"}")
    }
}

@Suite struct TheSchema {
    @Test func aWrongTypeIsRefused() {
        let data = changed { content(&$0) { $0["accounts"] = "none" } }
        #expect(refusal(data) == "the snapshot does not match its schema: snapshot.content.accounts is not a array.")
    }

    @Test func aMissingRequiredFieldIsRefused() {
        let data = changed { content(&$0) { $0.removeValue(forKey: "review") } }
        #expect(refusal(data) == "the snapshot does not match its schema: snapshot.content.review is missing.")
    }

    @Test func anUnknownEnumValueIsRefused() {
        let data = changed { content(&$0) { $0["warnings"] = [["kind": "surprise", "detail": "x"]] } }
        #expect(refusal(data) == "the snapshot does not match its schema: snapshot.content.warnings[0].kind is not one of its values.")
    }

    @Test func anotherMajorIsRefusedNamingBoth() {
        let data = changed { $0["schema_version"] = "2.0" }
        #expect(refusal(data) == "the snapshot does not match its schema: schema version 2.0 is not supported: this app reads 1.x. Update the app or the Mac so both use 2.x.")
    }

    @Test func anotherMinorAndUnknownFieldsAreAccepted() {
        let data = changed {
            $0["schema_version"] = "1.7"
            content(&$0) { $0["a_later_field"] = ["anything": 1] }
        }
        #expect(refusal(data) == nil)
    }

    @Test func aNullWhereNoneIsAllowedIsRefused() {
        let data = changed { content(&$0) { $0["review"] = NSNull() } }
        #expect(refusal(data) == "the snapshot does not match its schema: snapshot.content.review is null, and may not be.")
    }

    @Test func anEnvelopeOfOtherFieldsIsRefused() {
        let data = changed { $0["extra"] = 1 }
        #expect(refusal(data) == "this is not a snapshot: its envelope is not one.")
    }
}

@Suite struct ReconciliationAndExclusions {
    @Test func brokenGroupsAreRefused() {
        let data = changed { content(&$0) {
            var months = $0["months"] as! [[String: Any]]
            months[0]["net_cents"] = (months[0]["net_cents"] as! Int) + 1
            $0["months"] = months
        } }
        #expect(refusal(data)?.hasPrefix("the snapshot does not reconcile: month ") == true)
    }

    @Test func anExcludedKeyIsRefused() {
        let data = changed { content(&$0) { $0["external_id"] = "X1" } }
        #expect(refusal(data) == "the snapshot holds an excluded key: content.external_id.")
    }
}

@Suite struct TheStore {
    func store() -> SnapshotStore {
        SnapshotStore(folder: FileManager.default.temporaryDirectory
            .appendingPathComponent("commoncents-\(UUID().uuidString)"))
    }

    @Test func aValidSnapshotIsInstalledAndRead() throws {
        let store = store()
        #expect(store.installed() == nil)
        let snapshot = try store.install(golden)
        #expect(store.installed()?.snapshotId == snapshot.snapshotId)
        #expect(store.history().first?.outcome == .installed)
    }

    @Test func aFailedInstallKeepsTheLastValidSnapshot() throws {
        let store = store()
        try store.install(golden)
        let bytes = try Data(contentsOf: store.snapshotURL)
        #expect(throws: SnapshotRefused.self) { try store.install(changed(redigest: false) { content(&$0) { $0["assumptions"] = [] } }) }
        #expect(throws: SnapshotRefused.self) { try store.install(changed { $0["schema_version"] = "9.0" }) }
        #expect(try Data(contentsOf: store.snapshotURL) == bytes)
        #expect(store.history().map(\.outcome) == [.failed, .failed, .installed])
        let leftovers = try FileManager.default.contentsOfDirectory(atPath: store.folder.path)
        #expect(Set(leftovers) == ["snapshot.json", "sync-history.json"])
    }

    @Test func deletingRemovesTheSnapshotAndItsHistory() throws {
        let store = store()
        try store.install(golden)
        try store.deleteAll()
        #expect(store.installed() == nil && store.history().isEmpty)
    }
}

@Suite struct Showing {
    @Test func centsAreFormattedNeverComputed() {
        #expect(Money.text(123456) == "$1,234.56")
        #expect(Money.text(-500) == "\u{2212}$5.00")
        #expect(Money.text(7) == "$0.07")
        #expect(Money.text(0) == "$0.00")
        #expect(Money.text(nil) == "Not available")
        #expect(Money.text(100_000_000_00) == "$100,000,000.00")
        #expect(Dates.monthAndYear("2047-05-05") == "May 2047")
        #expect(Dates.shortDay("2026-05-04") == "Mon 4 May")
        #expect(Dates.shortDay(nil) == "No date")
    }

    @Test func freshnessComesFromTheSnapshotsOwnTime() {
        let generated = "2026-05-04T17:00:00.000Z"
        let then = Dates.instant(generated)!
        #expect(Freshness.of(generatedAt: generated, now: then.addingTimeInterval(23 * 3600)) == .fresh)
        #expect(Freshness.of(generatedAt: generated, now: then.addingTimeInterval(24 * 3600)) == .stale(hours: 24))
        #expect(Freshness.of(generatedAt: generated, now: then.addingTimeInterval(3600), thresholdHours: 1) == .stale(hours: 1))
    }

    @Test func aNewMonthNeverPresentsTheOldBudgetAsCurrent() throws {
        let snapshot = try Snapshot.decoded(fromVerified: golden)
        let month = snapshot.content.period.month
        let inMonth = Dates.dayFormatter("yyyy-MM-dd").date(from: "\(month)-15")!
        #expect(MonthBoundary.of(snapshot, now: inMonth) == .current)
        let later = Calendar(identifier: .gregorian).date(byAdding: .month, value: 1, to: inMonth)!
        guard case let .passed(own, phone) = MonthBoundary.of(snapshot, now: later) else {
            Issue.record("a later month must be reported as passed")
            return
        }
        #expect(own == month && phone > month)
    }
}

@Suite struct Codes {
    @Test func aPairingPayloadIsRead() {
        let fingerprint = String(repeating: "ab", count: 32)
        let code = PairingCode.parsed("commoncents-pair:v1?address=192.168.1.20&port=8443&fingerprint=\(fingerprint)&secret=S3cr3t")
        #expect(code == PairingCode(address: "192.168.1.20", port: 8443, fingerprint: fingerprint, secret: "S3cr3t"))
        #expect(PairingCode.parsed("commoncents-pair:v2?address=a&port=1&fingerprint=f&secret=s") == nil)
        #expect(PairingCode.parsed("commoncents-pair:v1?address=a&port=1&fingerprint=\(fingerprint)") == nil)
    }

    @Test func theBackendsManualCodeIsReadTheSame() {
        // Made by personal_finance.sync.pairing.manual_code for this secret.
        let code = PairingCode.parsed("YCUA-CFBA-7MA3-BHIR-6GQS-EMVF-GJZ2-SQVU-VVJP-LMLD-HU25-W7RZ-5O7T-367Q-DME5-C")
        #expect(code == PairingCode(address: "192.168.1.20", port: 8443, fingerprint: nil,
                                    secret: "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE"))
        #expect(PairingCode.parsed("YCUA-CFBA") == nil)
    }

    @Test func aReconnectCodeHoldsNoSecret() {
        let found = PairingCode.reconnection("commoncents-connect:v1?address=10.0.0.4&port=9000&fingerprint=ff")
        #expect(found?.address == "10.0.0.4" && found?.port == 9000 && found?.fingerprint == "ff")
        #expect(PairingCode.reconnection("commoncents-connect:v1?address=a&port=1&fingerprint=f&secret=s") == nil)
    }
}

@Suite struct NoCalculationOnThePhone {
    /// D-079 point 4: outside the validator's reconciliation checks, which show nothing, no
    /// source adds, subtracts, multiplies or divides a money value.
    @Test func noSourceDoesArithmeticOnMoney() throws {
        let sources = repository.appendingPathComponent("ios")
        let money = try Regex(#"[A-Za-z]*[Cc]ents\b[^\n]*[-+*/] |[-+*/] [^\n]*[A-Za-z]*[Cc]ents\b|reduce\(0, \+\)"#)
        var found: [String] = []
        let files = FileManager.default.enumerator(atPath: sources.path)!
        for case let path as String in files where path.hasSuffix(".swift")
            && !path.contains("/Tests/") && !path.contains(".build/")
            && !path.hasSuffix("SnapshotValidator.swift") {
            let text = try String(contentsOf: sources.appendingPathComponent(path), encoding: .utf8)
            for (number, line) in text.split(separator: "\n", omittingEmptySubsequences: false).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//")
                && line.contains(money) {
                found.append("\(path):\(number + 1): \(line)")
            }
        }
        #expect(found.isEmpty, "\(found)")
    }
}
