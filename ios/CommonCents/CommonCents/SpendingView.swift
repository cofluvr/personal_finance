// Spending, Transactions, Goals and Accounts (mock-ups 5 to 8). Every amount is one the snapshot
// holds; a missing balance says so and is never 0; projections and estimates carry their labels.

import CommonCentsKit
import SwiftUI

struct SpendingView: View {
    @Environment(AppModel.self) private var model
    @State private var month: String?

    var body: some View {
        Group {
            if let snapshot = model.snapshot, !snapshot.content.months.isEmpty {
                let months = snapshot.content.months.map(\.month)
                let chosen = month ?? months.last!
                List {
                    Picker("Month", selection: Binding(get: { chosen }, set: { month = $0 })) {
                        ForEach(months.reversed(), id: \.self) { Text(monthName($0) + " " + $0.prefix(4)).tag($0) }
                    }
                    if let row = snapshot.content.months.first(where: { $0.month == chosen }) {
                        Section("By category · actual") {
                            ForEach(row.spendingByCategory, id: \.category) { category in
                                Row(category.category ?? "Uncategorized", Money.text(category.outCents),
                                    note: "\(category.transactions) transactions")
                            }
                            Row("Spending", Money.text(row.spending.outCents), note: "actual")
                        }
                    }
                    if let household = snapshot.content.household.months.first(where: { $0.month == chosen }) {
                        Section(header: Text("Members · actual"),
                                footer: Text("Members' parts add exactly to the household total, as the Mac checks.")) {
                            ForEach(household.members, id: \.memberIndex) { part in
                                Row(snapshot.member(part.memberIndex)?.name ?? "Member", Money.text(part.outCents), note: "allocated")
                            }
                            Row("Unattributed", Money.text(household.unattributed.outCents))
                            Row("Household", Money.text(household.household.outCents))
                        }
                    }
                    Section {
                        NavigationLink("Transactions, last \(snapshot.content.period.windowDays) days") {
                            TransactionsView(snapshot: snapshot)
                        }
                    }
                }
            } else {
                NoSnapshotView()
            }
        }
        .navigationTitle("Spending")
    }
}

struct TransactionsView: View {
    let snapshot: Snapshot
    @State private var search = ""

    var body: some View {
        let shown = snapshot.content.transactions.reversed().filter { transaction in
            search.isEmpty || (transaction.description ?? "").localizedCaseInsensitiveContains(search)
                || (transaction.category ?? "").localizedCaseInsensitiveContains(search)
        }
        List(shown) { transaction in
            NavigationLink {
                TransactionDetail(snapshot: snapshot, transaction: transaction)
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text(transaction.description ?? "No description")
                        Spacer()
                        Text(Money.text(transaction.amountCents)).monospacedDigit()
                    }
                    Text([snapshot.account(transaction.accountIndex)?.displayName, Dates.shortDay(transaction.date),
                          transaction.category, transaction.status == "pending" ? "pending" : nil]
                        .compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .searchable(text: $search, prompt: "Search the last \(snapshot.content.period.windowDays) days")
        .navigationTitle("Transactions")
    }
}

struct TransactionDetail: View {
    let snapshot: Snapshot
    let transaction: Snapshot.Transaction

    var body: some View {
        List {
            Row("Amount", Money.text(transaction.amountCents), note: "actual")
            Row("Account", snapshot.account(transaction.accountIndex)?.displayName ?? "Unknown")
            Row("Date", Dates.shortDay(transaction.date))
            Row("Status", transaction.status)
            Row("Type", transaction.financialType ?? "Not classified")
            Row("Category", transaction.category ?? "Uncategorized")
            if !transaction.memberParts.isEmpty {
                Row("Split", transaction.memberParts.map {
                    "\(snapshot.member($0.memberIndex)?.name ?? "Member") \(Money.text($0.amountCents))"
                }.joined(separator: " · "))
            }
            if !transaction.tags.isEmpty { Row("Tags", transaction.tags.joined(separator: ", ")) }
            Text("To change it, use the Mac. The phone is read-only.").font(.footnote).foregroundStyle(.secondary)
        }
        .navigationTitle(transaction.description ?? "Transaction")
    }
}

struct GoalsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if let snapshot = model.snapshot {
                List {
                    ForEach(snapshot.content.funds.filter { $0.state == "active" }) { fund in
                        Section {
                            Row(fund.name, fund.standing.replacingOccurrences(of: "_", with: " ").capitalized,
                                note: [fund.kind, fund.due.map { "due \(Dates.shortDay($0))" }].compactMap { $0 }.joined(separator: " · "))
                            Row("Assigned", Money.text(fund.assignedCents), note: "reserved")
                            Row("Still needed", Money.text(fund.outstandingCents), note: "planned")
                            Row("Planned this month", Money.text(fund.plannedContributionCents), note: "planned")
                            if let required = fund.requiredHeldCents { Row("Required to hold", Money.text(required), note: "reserved") }
                        }
                    }
                    Text("An assignment says what a balance already holds. Nothing here moves money.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            } else {
                NoSnapshotView()
            }
        }
        .navigationTitle("Goals")
    }
}

struct AccountsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if let snapshot = model.snapshot {
                let worth = snapshot.content.netWorth
                List {
                    Section {
                        VStack(alignment: .leading) {
                            Text("Net worth, observed").font(.subheadline).foregroundStyle(.secondary)
                            Text(Money.text(worth.totalCents)).font(.largeTitle.bold()).monospacedDigit()
                            let missing = worth.accounts.filter { $0.balanceCents == nil }.count
                            if missing > 0 {
                                Tag("Incomplete: \(missing) account\(missing == 1 ? " has" : "s have") no balance yet", tone: .orange)
                            }
                        }
                    }
                    Section("Balances, with the date each was observed") {
                        ForEach(worth.accounts) { account in
                            Row(snapshot.account(account.accountIndex)?.displayName ?? "Account",
                                Money.text(account.balanceCents, missing: "No balance"),
                                note: account.observedOn.map(Dates.shortDay) ?? "Never observed")
                        }
                    }
                    if !snapshot.content.loans.isEmpty {
                        Section("Debt") {
                            ForEach(snapshot.content.loans) { loan in
                                Row(snapshot.account(loan.accountIndex)?.displayName ?? "Loan",
                                    Money.text(loan.owedCents, missing: "No balance"),
                                    note: loan.observedOn.map { "owed as of \(Dates.shortDay($0))" })
                                if let next = loan.duePeriods.first(where: { $0.state == "upcoming" }) {
                                    Row("Next payment", Money.text(next.dueCents), note: Dates.shortDay(next.due))
                                }
                                if let projection = loan.projection {
                                    Row("Paid off", projection.paidOff.map(Dates.monthAndYear) ?? "Not within the projection",
                                        note: projection.label)
                                }
                            }
                        }
                    }
                }
            } else {
                NoSnapshotView()
            }
        }
        .navigationTitle("Accounts")
    }
}
