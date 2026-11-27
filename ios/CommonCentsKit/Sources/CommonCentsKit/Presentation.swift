// What the app may compute (D-079 point 4): formatting cents, and comparing the snapshot's own
// time with the phone's clock for the stale warning and the month boundary. No money arithmetic:
// every figure shown is one the backend wrote.

import Foundation

public enum Money {
    /// "$1,234.56", "−$5.00", or "No balance" for a missing value, never "$0.00".
    public static func text(_ cents: Int?, missing: String = "Not available") -> String {
        guard let cents else { return missing }
        let digits = String(cents.magnitude)
        let padded = String(repeating: "0", count: max(0, 3 - digits.count)) + digits
        let whole = String(padded.dropLast(2))
        let grouped = whole.reversed().enumerated().reduce(into: "") { text, pair in
            if pair.offset > 0, pair.offset.isMultiple(of: 3) { text.append(",") }
            text.append(pair.element)
        }
        let sign = cents < 0 ? "\u{2212}" : ""
        return "\(sign)$\(String(grouped.reversed())).\(padded.suffix(2))"
    }

    /// "$1,234", for a chart's axis ticks: Money.text without its cents, by dropping text.
    public static func dollars(_ cents: Int) -> String {
        String(text(cents).dropLast(3))
    }
}

public enum Freshness: Equatable, Sendable {
    case fresh
    /// Older than the threshold: shown more prominently the older it gets.
    case stale(hours: Int)

    public static let defaultThresholdHours = 24

    public static func of(generatedAt: String, now: Date,
                          thresholdHours: Int = defaultThresholdHours) -> Freshness {
        guard let generated = Dates.instant(generatedAt) else { return .stale(hours: Int.max) }
        let hours = Int(now.timeIntervalSince(generated) / 3600)
        return hours >= thresholdHours ? .stale(hours: hours) : .fresh
    }
}

public enum Dates {
    static func instantFormatter() -> ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }

    public static func instant(_ text: String) -> Date? { instantFormatter().date(from: text) }

    /// A YYYY-MM-DD date as midnight UTC, for placing it on a chart's time axis.
    public static func day(_ day: String) -> Date? { dayFormatter("yyyy-MM-dd").date(from: day) }

    /// A YYYY-MM-DD date as "Mon 4 May", in UTC so the backend's date is never shifted.
    public static func shortDay(_ day: String?) -> String {
        guard let day, let date = dayFormatter("yyyy-MM-dd").date(from: day) else {
            return "No date"
        }
        return dayFormatter("EEE d MMM").string(from: date)
    }

    /// A YYYY-MM-DD date as "May 2047", for a date years away such as a loan's payoff.
    public static func monthAndYear(_ day: String?) -> String {
        guard let day, let date = dayFormatter("yyyy-MM-dd").date(from: day) else {
            return "No date"
        }
        return dayFormatter("MMM yyyy").string(from: date)
    }

    static func dayFormatter(_ format: String) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = format
        return formatter
    }

    /// The month the phone's clock is in, in the household's timezone when the snapshot names
    /// one, as YYYY-MM.
    public static func currentMonth(now: Date, timezone: String?) -> String {
        let formatter = dayFormatter("yyyy-MM")
        formatter.timeZone = timezone.flatMap(TimeZone.init(identifier:)) ?? .current
        return formatter.string(from: now)
    }
}

/// PRD §8: past the snapshot's month the app never presents its budget or safe to spend as this
/// month's. It shows the snapshot's month as history and asks for a sync.
public enum MonthBoundary: Equatable, Sendable {
    case current
    case passed(snapshotMonth: String, phoneMonth: String)

    public static func of(_ snapshot: Snapshot, now: Date) -> MonthBoundary {
        let phone = Dates.currentMonth(now: now, timezone: snapshot.content.household.timezone)
        let own = snapshot.content.period.month
        return phone > own ? .passed(snapshotMonth: own, phoneMonth: phone) : .current
    }
}
