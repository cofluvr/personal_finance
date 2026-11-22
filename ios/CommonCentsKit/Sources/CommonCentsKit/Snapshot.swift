// The snapshot as the app reads it, after SnapshotValidator has accepted its bytes (schema 1.x).
// Every money field is integer cents as the backend wrote it, and a missing value is nil, never 0.
// Fields the app does not show are left out: a consumer ignores what it does not know.

import Foundation

public struct Snapshot: Decodable, Sendable {
    public let schemaVersion: String
    public let snapshotId: String
    public let generatedAt: String
    public let contentSha256: String
    public let content: Content

    public struct Content: Decodable, Sendable {
        public let cutoff: Cutoff
        public let period: Period
        public let accounts: [Account]
        public let household: Household
        public let months: [Month]
        public let budget: Budget?
        public let safeToSpend: SafeToSpend?
        public let funds: [Fund]
        public let loans: [Loan]
        public let netWorth: NetWorth
        public let transactions: [Transaction]
        public let warnings: [Warning]
        public let review: Review
        public let assumptions: [String]
    }

    public struct Cutoff: Decodable, Sendable {
        public let asOf: String
        public let accounts: [AccountFreshness]
    }

    public struct AccountFreshness: Decodable, Sendable {
        public let accountIndex: Int
        public let lastCoveredDay: String?
        public let lastImportDate: String?
        public let latestObservationDate: String?
    }

    public struct Period: Decodable, Sendable {
        public let month: String
        public let windowDays: Int
        public let windowFirstDay: String
        public let windowLastDay: String
    }

    public struct Account: Decodable, Sendable, Identifiable {
        public let accountIndex: Int
        public let displayName: String
        public let accountType: String
        public var id: Int { accountIndex }
    }

    public struct Household: Decodable, Sendable {
        public let members: [Member]
        public let months: [HouseholdMonth]
        public let timezone: String?
    }

    public struct Member: Decodable, Sendable, Identifiable {
        public let memberIndex: Int
        public let name: String
        public var id: Int { memberIndex }
    }

    public struct Totals: Decodable, Sendable {
        public let transactions: Int
        public let outCents: Int
        public let inCents: Int
    }

    public struct MemberTotals: Decodable, Sendable {
        public let memberIndex: Int
        public let transactions: Int
        public let outCents: Int
        public let inCents: Int
    }

    public struct HouseholdMonth: Decodable, Sendable {
        public let month: String
        public let household: Totals
        public let members: [MemberTotals]
        public let unattributed: Totals
    }

    public struct CategoryTotals: Decodable, Sendable {
        public let category: String?
        public let transactions: Int
        public let outCents: Int
        public let inCents: Int
    }

    public struct Month: Decodable, Sendable, Identifiable {
        public let month: String
        public let transactions: Int
        public let netCents: Int
        public let income: Totals
        public let spending: Totals
        public let unclassified: Totals
        public let spendingByCategory: [CategoryTotals]
        public var id: String { month }
    }

    public struct Budget: Decodable, Sendable {
        public let month: String
        public let targetCents: Int
        public let actualCents: Int
        public let remainingCapacityCents: Int
        public let originalDailyCents: Int
        public let revisedDailyCents: Int
        public let revisedWeeklyCents: Int
        public let daysRemaining: Int
    }

    public struct Reason: Decodable, Sendable, Hashable {
        public let reason: String
        public let details: [String]
    }

    public struct SafeToSpend: Decodable, Sendable {
        public let todayCents: Int?
        public let weekCents: Int?
        public let limiting: String?
        public let budgetDailyCents: Int?
        public let liquidityDailyCents: Int?
        public let liquidCents: Int?
        public let protectedCents: Int
        public let nextPaycheck: String?
        public let horizonDays: Int
        public let horizonLastDay: String
        public let provisional: Bool
        public let reasons: [Reason]
    }

    public struct Fund: Decodable, Sendable, Identifiable {
        public let name: String
        public let kind: String
        public let state: String
        public let standing: String
        public let assignedCents: Int
        public let outstandingCents: Int?
        public let plannedContributionCents: Int?
        public let requiredHeldCents: Int?
        public let due: String?
        public let monthsLeft: Int?
        public var id: String { "\(kind) \(name)" }
    }

    public struct DuePeriod: Decodable, Sendable {
        public let due: String
        public let dueCents: Int
        public let paidCents: Int
        public let state: String
    }

    public struct Projection: Decodable, Sendable {
        public let label: String
        public let months: Int
        public let paidOff: String?
        public let totalInterestCents: Int
    }

    public struct Loan: Decodable, Sendable, Identifiable {
        public let accountIndex: Int
        public let owedCents: Int?
        public let observedOn: String?
        public let duePeriods: [DuePeriod]
        public let projection: Projection?
        public var id: Int { accountIndex }
    }

    public struct NetWorthAccount: Decodable, Sendable, Identifiable {
        public let accountIndex: Int
        public let balanceCents: Int?
        public let countedCents: Int
        public let observedOn: String?
        public let how: String
        public var id: Int { accountIndex }
    }

    public struct NetWorth: Decodable, Sendable {
        public let asOf: String
        public let totalCents: Int
        public let accounts: [NetWorthAccount]
    }

    public struct MemberPart: Decodable, Sendable {
        public let memberIndex: Int
        public let amountCents: Int
    }

    public struct Transaction: Decodable, Sendable, Identifiable {
        public let transactionId: String
        public let accountIndex: Int
        public let date: String
        public let amountCents: Int
        public let description: String?
        public let status: String
        public let financialType: String?
        public let category: String?
        public let tags: [String]
        public let memberParts: [MemberPart]
        public var id: String { transactionId }
    }

    public struct Warning: Decodable, Sendable, Hashable {
        public let kind: String
        public let detail: String
    }

    public struct Review: Decodable, Sendable {
        public let possibleDuplicate: Int
        public let unresolvedRecord: Int
    }

    /// Decodes a snapshot the validator has accepted. Anything else is refused first.
    public static func decoded(fromVerified data: Data) throws -> Snapshot {
        _ = try SnapshotValidator.verified(data)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Snapshot.self, from: data)
    }

    public func account(_ index: Int) -> Account? {
        content.accounts.first { $0.accountIndex == index }
    }

    public func member(_ index: Int) -> Member? {
        content.household.members.first { $0.memberIndex == index }
    }
}
