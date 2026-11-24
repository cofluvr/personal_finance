// The app's charts (the owner's review of 2026-11-23: "graphs and graphics wherever possible").
// A chart plots figures the snapshot already holds, and labels them with Money.text. It never
// shows a figure the phone worked out: a bar's length is Swift Charts' drawing, not a number the
// app states (D-079 point 4). Every chart sits beside the rows that give its exact figures.

import Charts
import CommonCentsKit
import SwiftUI
import UIKit

/// The reference data-viz palette, light and dark steps (validated as a set, used unchanged).
enum Palette {
    static let blue = Color(light: 0x2a78d6, dark: 0x3987e5)
    static let orange = Color(light: 0xeb6834, dark: 0xd95926)
    static let red = Color(light: 0xe34948, dark: 0xe66767)
    /// Categorical slots in their fixed order: a member keeps the same slot everywhere.
    static let categorical: [Color] = [
        blue, orange, Color(light: 0x1baf7a, dark: 0x199e70), Color(light: 0xeda100, dark: 0xc98500),
        Color(light: 0xe87ba4, dark: 0xd55181), Color(light: 0x008300, dark: 0x0ca30c),
        Color(light: 0x6250d6, dark: 0x9085e9), red,
    ]
    /// A recessive mark: what is not yet there, or not the one that limits.
    static let track = Color(light: 0xc3c2b7, dark: 0x52514e)
    // Status colors, reserved for states and always shown with their label.
    static let good = Color(light: 0x0ca30c, dark: 0x0ca30c)
    static let warning = Color(light: 0xfab219, dark: 0xfab219)
    static let critical = Color(light: 0xd03b3b, dark: 0xd03b3b)

    /// A member's color: slot by member index, past the eighth a neutral gray, never a cycled hue.
    static func member(_ memberIndex: Int) -> Color {
        memberIndex < categorical.count ? categorical[memberIndex] : track
    }
}

extension Color {
    init(light: UInt32, dark: UInt32) {
        self.init(uiColor: UIColor { traits in
            let hex = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
                           blue: CGFloat(hex & 0xff) / 255, alpha: 1)
        })
    }
}

/// Axis ticks in whole dollars, as Money.text writes them.
func moneyAxis() -> some AxisContent {
    AxisMarks { value in
        AxisGridLine().foregroundStyle(Palette.track.opacity(0.5))
        AxisValueLabel {
            if let cents = value.as(Int.self) { Text(Money.dollars(cents)) }
        }
    }
}

// MARK: Two or three figures side by side

struct ComparedFigure: Identifiable {
    let label: String
    let cents: Int
    let emphasized: Bool
    var id: String { label }
}

/// Horizontal bars for a few figures of one kind, each labelled with its amount. The emphasized
/// bar is in color, the rest recessive: the lower of the two limits, the revised allowance.
struct ComparisonBars: View {
    let figures: [ComparedFigure]
    var emphasisNote = ""
    @ScaledMetric(relativeTo: .body) private var barRowHeight: CGFloat = 36

    init(_ figures: [(String, Int?, Bool)], emphasisNote: String = "") {
        self.figures = figures.compactMap { label, cents, emphasized in
            cents.map { ComparedFigure(label: label, cents: $0, emphasized: emphasized) }
        }
        self.emphasisNote = emphasisNote
    }

    var body: some View {
        if !figures.isEmpty {
            Chart(figures) { figure in
                BarMark(x: .value("Amount", figure.cents), y: .value("Figure", figure.label), height: .ratio(0.55))
                    .cornerRadius(4)
                    .foregroundStyle(figure.emphasized ? Palette.blue : Palette.track)
                    .annotation(position: .trailing, spacing: 6) {
                        Text(Money.text(figure.cents)).font(.caption.monospacedDigit().weight(.semibold))
                            .foregroundStyle(.primary)
                    }
                    .accessibilityLabel(figure.label)
                    .accessibilityValue("\(Money.text(figure.cents))\(figure.emphasized ? emphasisNote : "")")
            }
            .chartXAxis(.hidden)
            .chartXScale(range: .plotDimension(endPadding: 84))
            .chartYAxis { AxisMarks { AxisValueLabel().font(.caption) } }
            .frame(height: barRowHeight * CGFloat(figures.count))
        }
    }
}

// MARK: Spent of a target

/// How much of a month's target is spent, as a capacity bar. Red past the target. Nothing is
/// drawn without a target: a member with no part in the plan has none.
struct SpentGauge: View {
    let actualCents: Int
    let targetCents: Int?
    var title = "Spent, actual"

    var body: some View {
        if let targetCents, targetCents > 0 {
            let over = actualCents > targetCents
            Gauge(value: Double(actualCents), in: 0...Double(targetCents)) {
                Text(title).font(.subheadline)
            } currentValueLabel: {
                Text(Money.text(actualCents))
            } minimumValueLabel: {
                Text("$0").font(.caption2)
            } maximumValueLabel: {
                Text(Money.text(targetCents)).font(.caption2)
            }
            .gaugeStyle(.linearCapacity)
            .tint(over ? Palette.critical : Palette.blue)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(title)
            .accessibilityValue("\(Money.text(actualCents)) of \(Money.text(targetCents))\(over ? ", over the target" : "")")
        }
    }
}

// MARK: Months

func shortMonthName(_ month: String) -> String {
    String(monthName(month).prefix(3))
}

/// Income and spending for each month the snapshot carries. The chosen month is drawn solid and
/// the others faded; tapping a month chooses it.
struct MonthlyTrendChart: View {
    let months: [Snapshot.Month]
    let chosenMonth: String
    let choose: (String) -> Void
    @ScaledMetric(relativeTo: .body) private var chartHeight: CGFloat = 180
    @State private var touchedMonth: String?

    var body: some View {
        Chart(months) { month in
            BarMark(x: .value("Month", month.month), y: .value("Amount", month.income.inCents))
                .cornerRadius(4)
                .foregroundStyle(by: .value("Flow", "Income"))
                .position(by: .value("Flow", "Income"))
                .opacity(month.month == chosenMonth ? 1 : 0.35)
            BarMark(x: .value("Month", month.month), y: .value("Amount", month.spending.outCents))
                .cornerRadius(4)
                .foregroundStyle(by: .value("Flow", "Spending"))
                .position(by: .value("Flow", "Spending"))
                .opacity(month.month == chosenMonth ? 1 : 0.35)
        }
        .chartForegroundStyleScale(["Income": Palette.blue, "Spending": Palette.orange])
        .chartXAxis {
            AxisMarks { value in
                AxisValueLabel { Text(value.as(String.self).map(shortMonthName) ?? "") }
            }
        }
        .chartYAxis { moneyAxis() }
        .chartLegend(position: .top, alignment: .leading)
        .chartXSelection(value: $touchedMonth)
        // Charts would read grouped bars as raw cents: the chart speaks as one element instead.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Income and spending by month")
        .accessibilityValue(months.map { month in
            "\(monthName(month.month)): income \(Money.text(month.income.inCents)), spending \(Money.text(month.spending.outCents))"
        }.joined(separator: "; "))
        .onChange(of: touchedMonth) { _, month in
            if let month { choose(month) }
        }
        .frame(height: chartHeight)
    }
}

/// A month's spending by category, largest first, one hue: the job is comparing sizes.
struct CategoryBars: View {
    let categories: [Snapshot.CategoryTotals]
    @ScaledMetric(relativeTo: .body) private var barRowHeight: CGFloat = 30

    var body: some View {
        let shown = categories.filter { $0.outCents > 0 }.sorted { $0.outCents > $1.outCents }
        if !shown.isEmpty {
            Chart(shown, id: \.category) { category in
                BarMark(x: .value("Spent", category.outCents),
                        y: .value("Category", category.category ?? "Uncategorized"), height: .ratio(0.6))
                    .cornerRadius(4)
                    .foregroundStyle(Palette.blue)
                    .annotation(position: .trailing, spacing: 6) {
                        Text(Money.text(category.outCents)).font(.caption.monospacedDigit())
                    }
                    .accessibilityLabel(category.category ?? "Uncategorized")
                    .accessibilityValue(Money.text(category.outCents))
            }
            .chartXAxis(.hidden)
            .chartXScale(range: .plotDimension(endPadding: 84))
            .chartYAxis { AxisMarks { AxisValueLabel().font(.caption) } }
            .frame(height: barRowHeight * CGFloat(shown.count))
        }
    }
}

/// One bar of the household's spending, split into each member's part and the unattributed rest,
/// as the Mac allocated them. Members keep their color slot.
struct MemberSplitBar: View {
    let snapshot: Snapshot
    let householdMonth: Snapshot.HouseholdMonth
    @ScaledMetric(relativeTo: .body) private var chartHeight: CGFloat = 64

    struct Part: Identifiable {
        let name: String
        let cents: Int
        let color: Color
        var id: String { name }
    }

    var parts: [Part] {
        var parts = householdMonth.members.map { part in
            Part(name: snapshot.member(part.memberIndex)?.name ?? "Member \(part.memberIndex)",
                 cents: part.outCents, color: Palette.member(part.memberIndex))
        }
        parts.append(Part(name: "Unattributed", cents: householdMonth.unattributed.outCents, color: Palette.track))
        return parts
    }

    var body: some View {
        let drawn = parts.filter { $0.cents > 0 }
        if !drawn.isEmpty {
            Chart(drawn) { part in
                BarMark(x: .value("Spent", part.cents), y: .value("Household", "Spending"), height: .ratio(0.7))
                    .foregroundStyle(by: .value("Member", part.name))
                    .accessibilityLabel(part.name)
                    .accessibilityValue(Money.text(part.cents))
            }
            .chartForegroundStyleScale(domain: parts.map(\.name), range: parts.map(\.color))
            .chartXAxis(.hidden)
            .chartYAxis(.hidden)
            .chartLegend(position: .bottom, alignment: .leading)
            .frame(height: chartHeight)
        }
    }
}

// MARK: Transactions

/// Each day's money in and out over the window, as the transactions list holds it: in above the
/// line, out below. Bars on the same day stack, as Swift Charts draws them.
struct CashFlowChart: View {
    let transactions: [Snapshot.Transaction]
    @ScaledMetric(relativeTo: .body) private var chartHeight: CGFloat = 160

    struct Dated: Identifiable {
        let transaction: Snapshot.Transaction
        let day: Date
        var id: String { transaction.transactionId }
    }

    var body: some View {
        let dated = transactions.compactMap { transaction in
            Dates.day(transaction.date).map { Dated(transaction: transaction, day: $0) }
        }
        if !dated.isEmpty {
            Chart(dated) { item in
                BarMark(x: .value("Day", item.day, unit: .day), y: .value("Amount", item.transaction.amountCents))
                    .foregroundStyle(by: .value("Flow", item.transaction.amountCents < 0 ? "Out" : "In"))
                RuleMark(y: .value("Zero", 0)).foregroundStyle(Palette.track).lineStyle(StrokeStyle(lineWidth: 1))
            }
            .chartForegroundStyleScale(["In": Palette.blue, "Out": Palette.red])
            .chartYAxis { moneyAxis() }
            .chartXAxis {
                AxisMarks(values: .stride(by: .month)) { _ in
                    AxisValueLabel(format: .dateTime.month(.abbreviated), centered: false)
                }
            }
            .chartLegend(position: .top, alignment: .leading)
            .environment(\.timeZone, TimeZone(identifier: "UTC")!)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Money in and out by day")
            .accessibilityValue("\(dated.count) transactions, each read in the list below")
            .frame(height: chartHeight)
        }
    }
}

// MARK: Accounts

/// Each account's counted balance, assets to the right of zero and debts to the left. An account
/// with no balance yet is left out of the chart and listed below it as "No balance".
struct NetWorthBars: View {
    let snapshot: Snapshot
    @ScaledMetric(relativeTo: .body) private var barRowHeight: CGFloat = 34

    var body: some View {
        let counted = snapshot.content.netWorth.accounts.filter { $0.balanceCents != nil }
        if !counted.isEmpty {
            Chart(counted) { account in
                let name = snapshot.account(account.accountIndex)?.displayName ?? "Account"
                BarMark(x: .value("Counted", account.countedCents), y: .value("Account", name), height: .ratio(0.55))
                    .cornerRadius(4)
                    .foregroundStyle(by: .value("Kind", account.countedCents < 0 ? "Owed" : "Held"))
                    .annotation(position: account.countedCents < 0 ? .leading : .trailing, spacing: 6) {
                        Text(Money.text(account.countedCents)).font(.caption.monospacedDigit())
                    }
                    .accessibilityLabel(name)
                    .accessibilityValue(Money.text(account.countedCents))
                RuleMark(x: .value("Zero", 0)).foregroundStyle(Palette.track)
            }
            .chartForegroundStyleScale(["Held": Palette.blue, "Owed": Palette.red])
            .chartXAxis(.hidden)
            .chartXScale(range: .plotDimension(startPadding: 96, endPadding: 96))
            .chartYAxis { AxisMarks(position: .leading) { AxisValueLabel().font(.caption) } }
            .chartLegend(position: .top, alignment: .leading)
            .frame(height: barRowHeight * CGFloat(counted.count + 1))
        }
    }
}

/// A loan's due periods, one bar each, colored by what happened: the status colors, each named
/// in the legend, so color is never the only sign.
struct LoanDueChart: View {
    let loan: Snapshot.Loan
    @ScaledMetric(relativeTo: .body) private var chartHeight: CGFloat = 140

    static let states: KeyValuePairs<String, Color> = [
        "On schedule": Palette.good, "Extra": Palette.blue, "Short": Palette.warning,
        "Missed": Palette.critical, "Upcoming": Palette.track,
    ]

    static func stateName(_ state: String) -> String {
        state.replacingOccurrences(of: "_", with: " ").capitalized(with: nil).replacingOccurrences(of: "Schedule", with: "schedule")
    }

    /// Only the states this loan's periods are in, each keeping its own color.
    var shownStates: [(key: String, value: Color)] {
        let present = Set(loan.duePeriods.map { Self.stateName($0.state) })
        return Self.states.filter { present.contains($0.key) }
    }

    var body: some View {
        if !loan.duePeriods.isEmpty {
            Chart(loan.duePeriods, id: \.due) { period in
                BarMark(x: .value("Due", Dates.shortDay(period.due)), y: .value("Due amount", period.dueCents))
                    .cornerRadius(4)
                    .foregroundStyle(by: .value("State", Self.stateName(period.state)))
            }
            .chartForegroundStyleScale(domain: shownStates.map(\.key), range: shownStates.map(\.value))
            .chartXAxis {
                AxisMarks { value in
                    AxisValueLabel { Text(value.as(String.self).map { String($0.suffix(6)) } ?? "") }
                }
            }
            .chartYAxis { moneyAxis() }
            .chartLegend(position: .top, alignment: .leading)
            .frame(height: chartHeight)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Payments due")
            .accessibilityValue(loan.duePeriods.map { period in
                "\(Dates.shortDay(period.due)): \(Money.text(period.dueCents)) due, \(Money.text(period.paidCents)) paid, \(Self.stateName(period.state))"
            }.joined(separator: "; "))
        }
    }
}

// MARK: Goals

/// A goal's assigned amount and what it still needs, as one bar. With nothing still needed
/// recorded, only the assigned part is drawn.
struct FundProgressBar: View {
    let fund: Snapshot.Fund
    @ScaledMetric(relativeTo: .body) private var chartHeight: CGFloat = 44

    struct Part: Identifiable {
        let name: String
        let cents: Int
        var id: String { name }
    }

    var body: some View {
        let parts = [Part(name: "Assigned", cents: fund.assignedCents),
                     fund.outstandingCents.map { Part(name: "Still needed", cents: $0) }].compactMap { $0 }
        if parts.contains(where: { $0.cents > 0 }) {
            Chart(parts) { part in
                BarMark(x: .value("Amount", part.cents), y: .value("Goal", fund.name), height: .ratio(0.6))
                    .foregroundStyle(by: .value("Part", part.name))
                    .accessibilityLabel("\(fund.name), \(part.name.lowercased())")
                    .accessibilityValue(Money.text(part.cents))
            }
            .chartForegroundStyleScale(["Assigned": Palette.blue, "Still needed": Palette.track])
            .chartXAxis(.hidden)
            .chartYAxis(.hidden)
            .chartLegend(position: .bottom, alignment: .leading)
            .frame(height: chartHeight)
        }
    }
}
