// Today and "Why this number" (mock-ups 2 to 4). The figures are the snapshot's safe to spend and
// budget pace. A stale snapshot dims them and dates them; past its month they are labelled with
// their own month and never presented as this month's (PRD §8).

import CommonCentsKit
import SwiftUI

struct TodayView: View {
    @Environment(AppModel.self) private var model
    @State private var scope: ViewScope = .household

    var body: some View {
        Group {
            if let snapshot = model.snapshot {
                content(snapshot)
            } else {
                NoSnapshotView()
            }
        }
        .navigationTitle("Today")
        .onAppear { scope = model.defaultView }
    }

    @ViewBuilder
    func content(_ snapshot: Snapshot) -> some View {
        let now = Date()
        let freshness = Freshness.of(generatedAt: snapshot.generatedAt, now: now,
                                     thresholdHours: model.staleThresholdHours)
        let boundary = MonthBoundary.of(snapshot, now: now)
        let notCurrent = freshness != .fresh || boundary != .current
        List {
            StatusBanners(snapshot: snapshot, freshness: freshness, boundary: boundary)
            ScopePicker(snapshot: snapshot, scope: $scope)
            Section {
                if case let .member(index) = scope {
                    MemberPace(snapshot: snapshot, memberIndex: index)
                } else {
                    SafeToSpendHero(snapshot: snapshot, notCurrent: notCurrent)
                }
                FreshnessLine(snapshot: snapshot)
            }
            .opacity(notCurrent ? 0.6 : 1)
            BudgetSection(snapshot: snapshot, boundary: boundary)
            GoalsGlance(snapshot: snapshot)
            WarningsGlance(snapshot: snapshot)
        }
        .toolbar {
            NavigationLink("Why?") { WhyView(snapshot: snapshot) }
        }
    }
}

struct ScopePicker: View {
    let snapshot: Snapshot
    @Binding var scope: ViewScope

    var body: some View {
        if !snapshot.content.household.members.isEmpty {
            Picker("View", selection: $scope) {
                Text("Household").tag(ViewScope.household)
                ForEach(snapshot.content.household.members) { member in
                    Text(member.name).tag(ViewScope.member(member.memberIndex))
                }
            }
            .pickerStyle(.segmented)
            .listRowBackground(Color.clear)
        }
    }
}

struct SafeToSpendHero: View {
    let snapshot: Snapshot
    let notCurrent: Bool
    /// Follows Dynamic Type from the mock-ups' 46 points.
    @ScaledMetric(relativeTo: .largeTitle) private var heroSize: CGFloat = 46

    var body: some View {
        VStack(spacing: 4) {
            if let safe = snapshot.content.safeToSpend {
                Text(notCurrent ? "Safe to spend · as of \(Dates.shortDay(snapshot.content.cutoff.asOf))"
                                : "Safe to spend today")
                    .font(.subheadline).foregroundStyle(.secondary)
                Text(Money.text(safe.todayCents)).font(.system(size: heroSize, weight: .bold)).monospacedDigit()
                    .minimumScaleFactor(0.5).lineLimit(1)
                Text("\(notCurrent ? "That week" : "This week") \(Money.text(safe.weekCents))")
                HStack {
                    if let limiting = safe.limiting {
                        Tag(limiting == "budget" ? "Limited by budget" : "Limited by cash until payday")
                    }
                    if safe.provisional { Tag("Provisional", tone: .orange) }
                    if notCurrent { Tag("Not current", tone: .red) }
                }
            } else {
                Text("Safe to spend is not available").font(.headline)
                Text("The Mac needs the household's timezone set first.").font(.footnote).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// A member's budget pace (D-080), never a member's safe to spend, which the Mac does not compute.
struct MemberPace: View {
    let snapshot: Snapshot
    let memberIndex: Int

    var body: some View {
        let name = snapshot.member(memberIndex)?.name ?? "This member"
        if let pace = snapshot.content.budget?.members?.first(where: { $0.memberIndex == memberIndex }) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(name)'s budget pace").font(.headline)
                Row("Revised daily allowance", Money.text(pace.revisedDailyCents, missing: "No part in the plan"),
                    note: "budget pace")
                Row("Revised weekly allowance", Money.text(pace.revisedWeeklyCents, missing: "No part in the plan"),
                    note: "budget pace")
                Row("Spent, actual", "\(Money.text(pace.actualCents)) of \(Money.text(pace.targetCents, missing: "no target"))")
                if pace.provisional {
                    Tag("Provisional: some spending is not yet attributed", tone: .orange)
                }
                Text("Safe to spend is the household's: the Mac does not divide cash between members.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        } else {
            Text("The Mac has not sent members' figures in this snapshot. Sync to update.")
                .font(.callout).foregroundStyle(.secondary)
        }
    }
}

struct BudgetSection: View {
    let snapshot: Snapshot
    let boundary: MonthBoundary

    var body: some View {
        if let budget = snapshot.content.budget {
            Section(header: Text("\(monthName(budget.month)) budget")) {
                if case let .passed(own, _) = boundary {
                    Text("\(monthName(own))'s final figures. Sync for this month's.").font(.footnote).foregroundStyle(.orange)
                }
                Row("Original daily allowance", Money.text(budget.originalDailyCents))
                Row("Revised daily allowance", Money.text(budget.revisedDailyCents), note: "budget pace")
                Row("Revised weekly allowance", Money.text(budget.revisedWeeklyCents), note: "budget pace")
                Row("Spent, actual", "\(Money.text(budget.actualCents)) of \(Money.text(budget.targetCents))")
                Row("Remaining capacity", Money.text(budget.remainingCapacityCents), note: "budget pace")
                Row("Days left, as of the snapshot", "\(budget.daysRemaining)")
            }
        }
    }
}

struct GoalsGlance: View {
    let snapshot: Snapshot

    var body: some View {
        let funds = snapshot.content.funds.filter { $0.state == "active" }.prefix(3)
        if !funds.isEmpty {
            Section("Goals") {
                ForEach(Array(funds)) { fund in
                    Row(fund.name, Money.text(fund.assignedCents), note: fund.due.map { "due \(Dates.shortDay($0))" } ?? fund.kind)
                }
            }
        }
    }
}

struct WarningsGlance: View {
    let snapshot: Snapshot

    var body: some View {
        let warnings = snapshot.content.warnings
        if let first = warnings.first {
            Section(warnings.count == 1 ? "1 thing to check" : "\(warnings.count) things to check") {
                Text(first.detail).font(.callout)
                if warnings.count > 1 {
                    NavigationLink("The rest, under Why this number") { WhyView(snapshot: snapshot) }
                }
            }
        }
    }
}

struct WhyView: View {
    let snapshot: Snapshot

    var body: some View {
        List {
            if let safe = snapshot.content.safeToSpend {
                Section("Two limits, the lower wins") {
                    Row("Budget, daily", Money.text(safe.budgetDailyCents), note: "budget pace",
                        mark: safe.limiting == "budget")
                    Row("Cash until payday, daily", Money.text(safe.liquidityDailyCents), note: "estimated",
                        mark: safe.limiting == "liquidity")
                }
                Section("Cash until payday · \(safe.horizonDays) days to \(Dates.shortDay(safe.horizonLastDay))") {
                    Row("Next paycheck", Dates.shortDay(safe.nextPaycheck))
                    Row("Liquid balance", Money.text(safe.liquidCents), note: "estimated")
                    Row("Protected", Money.text(safe.protectedCents), note: "reserved")
                }
                if !safe.reasons.isEmpty {
                    Section("Provisional because") {
                        ForEach(safe.reasons, id: \.self) { reason in
                            VStack(alignment: .leading) {
                                Text(reason.reason.replacingOccurrences(of: "_", with: " ")).font(.callout.bold())
                                ForEach(reason.details, id: \.self) { Text($0).font(.footnote) }
                            }
                        }
                    }
                }
            }
            if !snapshot.content.warnings.isEmpty {
                Section("Things to check") {
                    ForEach(snapshot.content.warnings, id: \.self) { Text($0.detail).font(.callout) }
                }
            }
            Section("How these were calculated") {
                ForEach(snapshot.content.assumptions, id: \.self) { Text($0).font(.footnote) }
                Text("Estimated from the bank data on the Mac. Offline, the phone can't see new spending.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Why this number")
    }
}

// Shared pieces.

struct StatusBanners: View {
    let snapshot: Snapshot
    let freshness: Freshness
    let boundary: MonthBoundary

    var body: some View {
        if case let .stale(hours) = freshness {
            Banner(title: hours >= 72 ? "Snapshot is \(hours / 24) days old" : "Snapshot is \(hours) hours old",
                   text: "These figures were calculated on \(Dates.shortDay(snapshot.content.cutoff.asOf)). Spending since then isn't included. Sync with the Mac to update.",
                   tone: hours >= 72 ? .red : .orange)
        }
        if case let .passed(own, _) = boundary {
            Banner(title: "A new month has started",
                   text: "These are \(monthName(own))'s figures. The phone never starts a new month's budget from an old snapshot. Sync with the Mac.",
                   tone: .orange)
        }
    }
}

struct FreshnessLine: View {
    let snapshot: Snapshot

    var body: some View {
        let generated = Dates.instant(snapshot.generatedAt)
        let latest = snapshot.content.cutoff.accounts.compactMap(\.lastCoveredDay).max()
        HStack(spacing: 6) {
            Circle().fill(.green).frame(width: 8, height: 8).accessibilityHidden(true)
            Text("Synced \(generated.map { $0.formatted(.relative(presentation: .named)) } ?? "at an unknown time") · bank data through \(Dates.shortDay(latest ?? snapshot.content.cutoff.asOf))")
        }
        .font(.caption).foregroundStyle(.secondary)
    }
}

struct NoSnapshotView: View {
    var body: some View {
        ContentUnavailableView("No snapshot yet", systemImage: "iphone.and.arrow.forward",
                               description: Text("Pair this phone with the Mac under Sync, then sync once. Nothing is shown until a valid snapshot is installed."))
    }
}

struct Banner: View {
    let title: String
    let text: String
    let tone: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.callout.bold())
            Text(text).font(.footnote)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(tone.opacity(0.16), in: .rect(cornerRadius: 12))
        .listRowBackground(Color.clear)
        .accessibilityElement(children: .combine)
    }
}

struct Tag: View {
    let text: String
    let tone: Color

    init(_ text: String, tone: Color = .secondary) {
        self.text = text
        self.tone = tone
    }

    var body: some View {
        Text(text).font(.caption2.weight(.semibold)).padding(.horizontal, 7).padding(.vertical, 2)
            .background(tone.opacity(0.18), in: .capsule).foregroundStyle(tone)
    }
}

struct Row: View {
    let label: String
    let value: String
    let note: String?
    let mark: Bool

    init(_ label: String, _ value: String, note: String? = nil, mark: Bool = false) {
        self.label = label
        self.value = value
        self.note = note
        self.mark = mark
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(label)
                if let note { Text(note).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer()
            Text(value + (mark ? " ✓" : "")).monospacedDigit().fontWeight(.semibold)
        }
        .accessibilityElement(children: .combine)
    }
}

func monthName(_ month: String) -> String {
    let parser = DateFormatter()
    parser.locale = Locale(identifier: "en_US_POSIX")
    parser.timeZone = TimeZone(identifier: "UTC")
    parser.dateFormat = "yyyy-MM"
    guard let date = parser.date(from: month) else { return month }
    parser.dateFormat = "MMMM"
    return parser.string(from: date)
}
