// Checking a snapshot before it is installed (sync-protocol.md §4), in snapshot/files.py's
// order: canonical bytes, the envelope, the digest, the schema, the reconciliations, the excluded
// keys. The schema is the backend's schema_v1.json, copied into this package's resources.

import CryptoKit
import Foundation

enum SHA256Hex {
    static func of(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

public struct SnapshotRefused: Error, Equatable, CustomStringConvertible {
    public let reason: String
    public var description: String { reason }
}

public enum SnapshotValidator {
    public static let format = "commoncents-snapshot"
    static let envelopeFields = ["content", "content_sha256", "format", "generated_at",
                                 "schema_version", "snapshot_id"]
    /// Point 3 of D-075: no key by these names may appear anywhere in the content.
    static let excludedKeys: Set<String> = [
        "raw", "raw_text", "raw_row", "cells", "file_name", "path", "document_hash",
        "content_hash", "sha256", "external_id", "source_record_id", "record_id",
        "source_document_id", "last4", "institution", "source_description", "created_at",
        "imported_at", "device", "device_id", "pairing",
    ]
    static let types = ["object", "array", "string", "integer", "boolean"]

    public static let schema: JSONValue = {
        let url = Bundle.module.url(forResource: "schema_v1", withExtension: "json")!
        var parser = StrictParser(try! Data(contentsOf: url))
        return try! parser.document()
    }()

    public static var supportedMajor: Int { major(schema["schema_version"]!.text!)! }

    static func major(_ version: String) -> Int? {
        let parts = version.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 2, parts.allSatisfy({ !$0.isEmpty && $0.allSatisfy(\.isNumber) })
        else { return nil }
        return Int(parts[0])
    }

    /// The snapshot, refused at the first check it fails.
    public static func verified(_ data: Data) throws -> JSONValue {
        let document: JSONValue
        do {
            document = try CanonicalJSON.parsed(data)
        } catch let error as CanonicalJSONError {
            throw SnapshotRefused(reason: "\(error).")
        }
        guard let fields = document.fields,
              fields.map(\.0).sorted() == envelopeFields,
              document["format"]?.text == format,
              let content = document["content"] else {
            throw SnapshotRefused(reason: "this is not a snapshot: its envelope is not one.")
        }
        guard CanonicalJSON.sha256Hex(of: content) == document["content_sha256"]?.text else {
            throw SnapshotRefused(reason: "the snapshot's content does not match its digest.")
        }
        if let error = schemaErrors(document).first {
            throw SnapshotRefused(reason: "the snapshot does not match its schema: \(error).")
        }
        if let error = unreconciled(content).first {
            throw SnapshotRefused(reason: "the snapshot does not reconcile: \(error).")
        }
        if let key = excluded(content, at: "content").first {
            throw SnapshotRefused(reason: "the snapshot holds an excluded key: \(key).")
        }
        return document
    }

    // The schema subset (D-075's M19.1 slice plan point 5). Unknown fields are ignored.

    static func schemaErrors(_ document: JSONValue) -> [String] {
        if let version = document["schema_version"]?.text, let found = major(version),
           found != supportedMajor {
            return ["schema version \(version) is not supported: this app reads "
                    + "\(supportedMajor).x. Update the app or the Mac so both use \(found).x"]
        }
        var errors: [String] = []
        check(document, against: schema["document"]!, at: "snapshot", into: &errors)
        return errors
    }

    static func check(_ value: JSONValue, against spec: JSONValue, at place: String,
                      into errors: inout [String]) {
        if case .null = value {
            if spec["nullable"] != .bool(true) { errors.append("\(place) is null, and may not be") }
            return
        }
        let type = spec["type"]!.text!
        switch (type, value) {
        case ("object", .object(let pairs)):
            for (name, field) in spec["fields"]!.fields! {
                guard let item = pairs.first(where: { $0.0 == name })?.1 else {
                    if field["required"] == .bool(true) { errors.append("\(place).\(name) is missing") }
                    continue
                }
                check(item, against: field, at: "\(place).\(name)", into: &errors)
            }
        case ("array", .array(let values)):
            for (index, item) in values.enumerated() {
                check(item, against: spec["items"]!, at: "\(place)[\(index)]", into: &errors)
            }
        case ("string", .string(let text)):
            if let allowed = spec["enum"]?.items, !allowed.contains(.string(text)) {
                errors.append("\(place) is not one of its values")
            }
            if let pattern = spec["pattern"]?.text,
               text.wholeMatch(of: try! Regex(pattern)) == nil {
                errors.append("\(place) is not of its pattern")
            }
        case ("integer", .integer), ("boolean", .bool):
            return
        default:
            errors.append("\(place) is not a \(type)")
        }
    }

    // D-075 point 6's reconciliations, exactly as snapshot/validate.py states them.

    static func moved(_ group: JSONValue) -> Int64 {
        (group["in_cents"]?.whole ?? 0) - (group["out_cents"]?.whole ?? 0)
    }

    static func unreconciled(_ content: JSONValue) -> [String] {
        var errors: [String] = []
        for month in content["months"]?.items ?? [] {
            let name = month["month"]?.text ?? "?"
            let groups = ["income", "spending", "confirmed_transfers", "unconfirmed_transfer_kinds",
                          "unclassified"]
            if groups.map({ moved(month[$0]!) }).reduce(0, +) != month["net_cents"]?.whole {
                errors.append("month \(name): the five groups do not add to net movement")
            }
            for side in ["out_cents", "in_cents"] {
                let byCategory = (month["spending_by_category"]?.items ?? [])
                    .map { $0[side]?.whole ?? 0 }.reduce(0, +)
                if byCategory != month["spending"]?[side]?.whole {
                    errors.append("month \(name): categories do not add to spending")
                }
            }
        }
        for month in content["household"]?["months"]?.items ?? [] {
            for side in ["out_cents", "in_cents"] {
                let parts = (month["members"]?.items ?? []).map { $0[side]?.whole ?? 0 }.reduce(0, +)
                if parts + (month["unattributed"]?[side]?.whole ?? 0) != month["household"]?[side]?.whole {
                    errors.append("household month \(month["month"]?.text ?? "?"): members and "
                                  + "unattributed do not add to the household")
                }
            }
        }
        for transaction in content["transactions"]?.items ?? [] {
            let parts = transaction["member_parts"]?.items ?? []
            if !parts.isEmpty,
               parts.map({ $0["amount_cents"]?.whole ?? 0 }).reduce(0, +) != transaction["amount_cents"]?.whole {
                errors.append("transaction \(transaction["transaction_id"]?.text ?? "?"): member "
                              + "parts do not add to its amount")
            }
        }
        return errors
    }

    static func excluded(_ value: JSONValue, at place: String) -> [String] {
        switch value {
        case let .object(pairs):
            return pairs.flatMap { name, item in
                (excludedKeys.contains(name) ? ["\(place).\(name)"] : [])
                    + excluded(item, at: "\(place).\(name)")
            }
        case let .array(values):
            return values.enumerated().flatMap { excluded($1, at: "\(place)[\($0)]") }
        default:
            return []
        }
    }
}
