// Canonical JSON, as the backend writes it (shared-contract §6, snapshot/canonical.py): UTF-8,
// keys sorted by code point, no insignificant whitespace, and no number but an integer. A strict
// parser keeps what Foundation's would lose: an integer from a float, and each object's keys.

import Foundation

public indirect enum JSONValue: Equatable, Sendable {
    case null
    case bool(Bool)
    case integer(Int64)
    case string(String)
    case array([JSONValue])
    /// Keys in the order the bytes held them, so a repeated or unsorted key can be refused.
    case object([(String, JSONValue)])

    public static func == (left: JSONValue, right: JSONValue) -> Bool {
        switch (left, right) {
        case (.null, .null): return true
        case let (.bool(a), .bool(b)): return a == b
        case let (.integer(a), .integer(b)): return a == b
        case let (.string(a), .string(b)): return a == b
        case let (.array(a), .array(b)): return a == b
        case let (.object(a), .object(b)):
            return a.count == b.count && zip(a, b).allSatisfy { $0.0 == $1.0 && $0.1 == $1.1 }
        default: return false
        }
    }

    public subscript(key: String) -> JSONValue? {
        guard case let .object(pairs) = self else { return nil }
        return pairs.first { $0.0 == key }?.1
    }

    public var fields: [(String, JSONValue)]? {
        if case let .object(pairs) = self { return pairs }
        return nil
    }

    public var items: [JSONValue]? {
        if case let .array(values) = self { return values }
        return nil
    }

    public var text: String? {
        if case let .string(value) = self { return value }
        return nil
    }

    public var whole: Int64? {
        if case let .integer(value) = self { return value }
        return nil
    }
}

public enum CanonicalJSONError: Error, Equatable, CustomStringConvertible {
    case notUTF8JSON
    case notAnInteger
    case notCanonical

    public var description: String {
        switch self {
        case .notUTF8JSON: return "the file is not UTF-8 JSON"
        case .notAnInteger: return "the file holds a number that is not an integer"
        case .notCanonical:
            return "the file is not in canonical form: its bytes differ from its value's canonical encoding"
        }
    }
}

/// A strict JSON parser over bytes: integers only, every string a valid escape sequence.
struct StrictParser {
    let bytes: [UInt8]
    var position = 0

    init(_ data: Data) { bytes = Array(data) }

    mutating func document() throws -> JSONValue {
        skipSpace()
        let value = try parseValue()
        skipSpace()
        guard position == bytes.count else { throw CanonicalJSONError.notUTF8JSON }
        return value
    }

    mutating func skipSpace() {
        while position < bytes.count, [0x20, 0x09, 0x0A, 0x0D].contains(bytes[position]) {
            position += 1
        }
    }

    mutating func expect(_ literal: String) throws {
        let expected = Array(literal.utf8)
        guard position + expected.count <= bytes.count,
              Array(bytes[position..<position + expected.count]) == expected
        else { throw CanonicalJSONError.notUTF8JSON }
        position += expected.count
    }

    mutating func parseValue() throws -> JSONValue {
        guard position < bytes.count else { throw CanonicalJSONError.notUTF8JSON }
        switch bytes[position] {
        case UInt8(ascii: "n"): try expect("null"); return .null
        case UInt8(ascii: "t"): try expect("true"); return .bool(true)
        case UInt8(ascii: "f"): try expect("false"); return .bool(false)
        case UInt8(ascii: "\""): return .string(try parseString())
        case UInt8(ascii: "["): return try parseArray()
        case UInt8(ascii: "{"): return try parseObject()
        case UInt8(ascii: "-"), UInt8(ascii: "0")...UInt8(ascii: "9"): return try parseNumber()
        default: throw CanonicalJSONError.notUTF8JSON
        }
    }

    mutating func parseNumber() throws -> JSONValue {
        let start = position
        if bytes[position] == UInt8(ascii: "-") { position += 1 }
        while position < bytes.count, (UInt8(ascii: "0")...UInt8(ascii: "9")).contains(bytes[position]) {
            position += 1
        }
        if position < bytes.count, [UInt8(ascii: "."), UInt8(ascii: "e"), UInt8(ascii: "E")]
            .contains(bytes[position]) {
            throw CanonicalJSONError.notAnInteger
        }
        guard let text = String(bytes: bytes[start..<position], encoding: .utf8),
              let value = Int64(text) else { throw CanonicalJSONError.notUTF8JSON }
        return .integer(value)
    }

    mutating func parseString() throws -> String {
        position += 1
        var scalars = String.UnicodeScalarView()
        var raw: [UInt8] = []
        func flush() throws {
            guard !raw.isEmpty else { return }
            guard let piece = String(bytes: raw, encoding: .utf8) else {
                throw CanonicalJSONError.notUTF8JSON
            }
            scalars.append(contentsOf: piece.unicodeScalars)
            raw.removeAll()
        }
        while true {
            guard position < bytes.count else { throw CanonicalJSONError.notUTF8JSON }
            let byte = bytes[position]
            position += 1
            if byte == UInt8(ascii: "\"") { break }
            if byte < 0x20 { throw CanonicalJSONError.notUTF8JSON }
            if byte != UInt8(ascii: "\\") { raw.append(byte); continue }
            try flush()
            guard position < bytes.count else { throw CanonicalJSONError.notUTF8JSON }
            let escape = bytes[position]
            position += 1
            switch escape {
            case UInt8(ascii: "\""): scalars.append("\"")
            case UInt8(ascii: "\\"): scalars.append("\\")
            case UInt8(ascii: "/"): scalars.append("/")
            case UInt8(ascii: "b"): scalars.append("\u{08}")
            case UInt8(ascii: "f"): scalars.append("\u{0C}")
            case UInt8(ascii: "n"): scalars.append("\n")
            case UInt8(ascii: "r"): scalars.append("\r")
            case UInt8(ascii: "t"): scalars.append("\t")
            case UInt8(ascii: "u"):
                var unit = try hexUnit()
                if (0xD800..<0xDC00).contains(unit) {
                    try expect("\\u")
                    let low = try hexUnit()
                    guard (0xDC00..<0xE000).contains(low) else { throw CanonicalJSONError.notUTF8JSON }
                    unit = 0x10000 + ((unit - 0xD800) << 10) + (low - 0xDC00)
                }
                guard let scalar = Unicode.Scalar(unit) else { throw CanonicalJSONError.notUTF8JSON }
                scalars.append(scalar)
            default: throw CanonicalJSONError.notUTF8JSON
            }
        }
        try flush()
        return String(scalars)
    }

    mutating func hexUnit() throws -> UInt32 {
        guard position + 4 <= bytes.count,
              let text = String(bytes: bytes[position..<position + 4], encoding: .ascii),
              let value = UInt32(text, radix: 16) else { throw CanonicalJSONError.notUTF8JSON }
        position += 4
        return value
    }

    mutating func parseArray() throws -> JSONValue {
        position += 1
        var values: [JSONValue] = []
        skipSpace()
        if position < bytes.count, bytes[position] == UInt8(ascii: "]") { position += 1; return .array([]) }
        while true {
            skipSpace()
            values.append(try parseValue())
            skipSpace()
            guard position < bytes.count else { throw CanonicalJSONError.notUTF8JSON }
            if bytes[position] == UInt8(ascii: "]") { position += 1; return .array(values) }
            try expect(",")
        }
    }

    mutating func parseObject() throws -> JSONValue {
        position += 1
        var pairs: [(String, JSONValue)] = []
        skipSpace()
        if position < bytes.count, bytes[position] == UInt8(ascii: "}") { position += 1; return .object([]) }
        while true {
            skipSpace()
            guard position < bytes.count, bytes[position] == UInt8(ascii: "\"") else {
                throw CanonicalJSONError.notUTF8JSON
            }
            let key = try parseString()
            skipSpace()
            try expect(":")
            skipSpace()
            pairs.append((key, try parseValue()))
            skipSpace()
            guard position < bytes.count else { throw CanonicalJSONError.notUTF8JSON }
            if bytes[position] == UInt8(ascii: "}") { position += 1; return .object(pairs) }
            try expect(",")
        }
    }
}

public enum CanonicalJSON {
    /// The value the bytes hold, refused unless they are exactly its canonical encoding.
    public static func parsed(_ data: Data) throws -> JSONValue {
        var parser = StrictParser(data)
        let value = try parser.document()
        guard encoded(value) == data else { throw CanonicalJSONError.notCanonical }
        return value
    }

    /// Python's json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).
    public static func encoded(_ value: JSONValue) -> Data {
        var out = String()
        write(value, into: &out)
        return Data(out.utf8)
    }

    public static func sha256Hex(of value: JSONValue) -> String {
        SHA256Hex.of(encoded(value))
    }

    static func write(_ value: JSONValue, into out: inout String) {
        switch value {
        case .null: out += "null"
        case let .bool(flag): out += flag ? "true" : "false"
        case let .integer(number): out += String(number)
        case let .string(text): writeString(text, into: &out)
        case let .array(values):
            out += "["
            for (index, item) in values.enumerated() {
                if index > 0 { out += "," }
                write(item, into: &out)
            }
            out += "]"
        case let .object(pairs):
            out += "{"
            let sorted = pairs.sorted { Array($0.0.unicodeScalars.map(\.value))
                .lexicographicallyPrecedes($1.0.unicodeScalars.map(\.value)) }
            for (index, pair) in sorted.enumerated() {
                if index > 0 { out += "," }
                writeString(pair.0, into: &out)
                out += ":"
                write(pair.1, into: &out)
            }
            out += "}"
        }
    }

    static func writeString(_ text: String, into out: inout String) {
        out += "\""
        for scalar in text.unicodeScalars {
            switch scalar {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            default:
                if scalar.value < 0x20 {
                    out += String(format: "\\u%04x", scalar.value)
                } else {
                    out.unicodeScalars.append(scalar)
                }
            }
        }
        out += "\""
    }
}
