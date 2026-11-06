# PRD: Native iOS Finance Companion

## Document Status

- Version: 1.0
- Status: Draft for implementation planning
- Initial device: iPhone 17 Pro
- Related document: `shared-contract.md`

## 1. Purpose

Provide an immediate answer to:

> Based on my latest synced finances and goals, what can I spend today and this week?

The first release is a read-only companion to the Mac backend, not an independent financial system.

## 2. Distribution and Cost

- Native iPhone application.
- No initial App Store release.
- Initial installation through free development provisioning.
- The user accepts periodic reprovisioning.
- Setup and reprovisioning instructions are required.
- Paid developer membership remains optional.

Provisioning requirements must be verified against current Apple documentation during implementation.

## 3. Initial Scope

- Protected local snapshot.
- Secure local-network synchronization.
- Offline dashboard and drill-downs.
- Personal and household views.
- Spending allowances.
- Goal progress.
- Debt and net-worth summaries.
- Freshness and completeness indicators.
- Manual sync action.

## 4. Initial Non-Goals

- Public-internet remote sync.
- Direct institution connections.
- Mobile financial editing.
- Notifications.
- Receipt photography.
- Cloud database.
- Guaranteed background refresh.

## 5. Primary User Journeys

### Initial Setup

1. Enable sync mode on the Mac.
2. Pair through a short-lived authorization flow.
3. Confirm the device on the Mac.
4. Download a snapshot.
5. Choose a default personal or household view.

### Daily Offline Use

1. Authenticate.
2. View daily and weekly allowances.
3. Check data freshness.
4. Drill into spending and goals.
5. Continue without Mac or network access.

### Refresh

1. Ensure the Mac is awake and sync is available.
2. Select "Sync now."
3. Validate the incoming snapshot.
4. Replace the old snapshot atomically.
5. Preserve the last valid snapshot if refresh fails.

## 6. Home Screen

Priority order:

1. Available spending today and this week.
2. Data freshness.
3. Original versus revised allowance.
4. Month-to-date spending and remaining capacity.
5. Savings-goal progress.
6. Material warnings.

Support household and personal view switching.

Warnings include:

- Stale snapshot.
- Unresolved possible duplicates.
- Missing balances.
- Upcoming cash shortfall.
- Underfunded planned expenses.

The app must explain that offline mode does not observe new spending.

## 7. Secondary Screens

- Category spending.
- Transaction search and details.
- Household-member comparison.
- Savings and planned expenses.
- Debt summary.
- Net worth with valuation dates.
- Data status and sync history.
- Settings and pairing.
- Local-data deletion.

Ordinary viewing must not require a running Mac.

## 8. Offline Behavior

- Retain the last valid snapshot.
- Distinguish missing values from zero.
- Preserve data after failed sync.
- Make stale-data warnings increasingly prominent.
- Do not describe old data as live.
- Do not create a new month's budget from an expired snapshot.
- Show historical data and request sync when current-period information is unavailable.

Proposed stale threshold: 24 hours, configurable.

Any date-based presentation changes must preserve the original financial cutoff and must not imply newly observed transactions.

## 9. Security and Synchronization

- Pairing required.
- Local-network presence is not sufficient authorization.
- Encrypt and authenticate sync traffic.
- Trust the explicitly paired Mac.
- Support revocation and re-pairing.
- Store no banking credentials.
- Protect snapshot storage and pairing secrets.
- Require device authentication for sensitive views.
- Obscure sensitive app-switcher previews.
- No telemetry or cloud upload by default.
- Disable the sync endpoint outside explicit sync mode.

Pairing and encryption design require technical review before release.

## 10. Financial Calculation Ownership

The backend owns all financial calculations.

The app must not implement an independent budgeting engine.

It renders:

- Spending allowances.
- Targets and revised capacity.
- Goal allocations.
- Debt and net-worth summaries.
- Warnings and calculation explanations.

See `shared-contract.md`.

## 11. Future Receipt Workflow

Receipt photography is a high-priority later enhancement.

Workflow:

1. Photograph or select a receipt.
2. Queue it locally.
3. Transfer it to the Mac.
4. Extract candidate merchant, total, and line items.
5. Match an existing transaction.
6. Propose category and household splits.
7. Require confirmation.

Requirements:

- Never automatically duplicate an existing expense.
- Handle taxes, tips, discounts, and rounding.
- Reconcile splits to the transaction amount.
- Preserve the original image.
- Flag uncertain extraction.
- Default to local processing.

Receipt upload and mobile editing require a future write-capable sync contract.

## 12. Acceptance Criteria

- [ ] Dashboard and drill-downs work fully offline after sync.
- [ ] Personal allocations reconcile with household totals.
- [ ] Sync time and underlying financial freshness are distinct.
- [ ] Failed sync preserves the previous valid snapshot.
- [ ] Invalid or unsupported snapshots are rejected.
- [ ] Unpaired devices cannot retrieve data.
- [ ] Revoked devices cannot sync.
- [ ] Sensitive views require authentication.
- [ ] Stale information cannot appear live.
- [ ] Month-boundary behavior does not fabricate current data.
- [ ] Reprovisioning and recovery instructions are tested.
- [ ] Reinstallation data-loss behavior is documented.
- [ ] No banking credentials or required paid integrations exist.

## 13. Later Enhancements

- Receipt photography.
- Mobile categorization and splitting.
- Goal and budget editing.
- Notifications.
- Institution refresh requests.
- Remote synchronization.
- Optional cloud hosting.

Each requires explicit scope and privacy approval.