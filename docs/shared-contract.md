# Shared Data, Synchronization, and Implementation Contract

## 1. Purpose

Define the boundary between the Python backend and the native iOS application.

This contract must prevent inconsistent financial calculations, unsafe synchronization, and unapproved external data processing.

## 2. Source of Truth

The backend is authoritative for:

- Transactions and account identity.
- Household attribution.
- Categorization and corrections.
- Budgets and savings goals.
- Actual versus planned values.
- Financial calculations.
- Data quality and review status.

The iOS application stores and renders approved snapshots.

## 3. Snapshot Contents

Each snapshot must include:

- Schema version.
- Unique snapshot ID.
- Generation timestamp.
- Financial-data cutoff and per-account freshness.
- Household timezone.
- Reporting period.
- Household members and allocations.
- Spending summaries.
- Original and revised allowances.
- Goals and assigned funds.
- Debt summaries.
- Net-worth summaries and valuation dates.
- Selected transaction history.
- Material warnings.
- Review counts.
- Calculation assumptions.

Proposed transaction detail window: latest 90 days, configurable.

Summaries may cover the full imported history.

Exclude:

- Raw statements.
- Banking credentials.
- Connection secrets.
- Unnecessary account identifiers.
- Unnecessary personal information.

## 4. Representation Rules

- Money uses integer cents or explicit decimal strings.
- Date-only values and timestamps are distinct.
- Timestamp timezone conventions are documented.
- Missing values are not represented as zero.
- Actual, projected, reserved, and allocated values remain distinct.
- Household allocations reconcile exactly.
- Snapshot generation uses a consistent database state.

## 5. Synchronization Rules

- Pairing precedes data access.
- Connections are encrypted and authenticated.
- Incoming snapshots are validated before installation.
- Updates are atomic.
- Failed updates retain the last valid snapshot.
- Unsupported schemas produce an actionable error.
- Successful installation is acknowledged.
- Devices can be revoked.
- Sync availability does not imply institution-data freshness.

The first release is read-only from the phone.

Future mobile writes require:

- Record versions.
- Conflict detection.
- Idempotent requests.
- Audit history.
- Explicit conflict-resolution behavior.

## 6. Required Decision Log

Record:

- Database and encryption approach.
- Parser strategy.
- Deduplication confidence rules.
- Transfer-matching rules.
- Safe-to-spend calculation details.
- Loan projection assumptions.
- Pairing protocol.
- Snapshot compatibility policy.
- Backup and recovery design.
- Resource benchmarks.

Ambiguous requirements must be resolved or explicitly documented before implementation.

## 7. Approval Gates

Do not introduce the following without approval:

- Cloud hosting.
- Financial institution connections.
- External AI processing.
- Paid dependencies or APIs.
- Large model downloads.
- Remote network access.
- Receipt-processing services.

Each proposal must describe:

- One-time and recurring costs.
- Data leaving the devices.
- Credential and token handling.
- Permissions and access scope.
- Operational dependencies.
- Failure and revocation behavior.
- Local-only fallback.

Institution integrations must not require the application to store banking passwords or initiate payments.

## 8. Development Data Policy

- Use synthetic fixtures by default.
- Use deliberately sanitized examples when necessary.
- Keep real financial documents outside the AI coding workspace.
- Restrict file and shell access appropriately.
- Do not commit statements, databases, credentials, or backups.
- Do not log sensitive financial details.
- Test for unintended network access.

Local execution of a development tool must not be confused with local model inference.

## 9. Implementation Sequence

1. Build synthetic financial fixtures.
2. Define the normalized data model.
3. Implement ingestion and provenance.
4. Implement deduplication and transfer tests.
5. Build account and review workflows.
6. Implement reports and balances.
7. Add budgeting, goals, and scenarios.
8. Add snapshot generation and secure sync.
9. Build the read-only iOS companion.
10. Evaluate optional enhancements.

## 10. Definition of Done

Each phase must include:

- Reproducible setup.
- Automated tests.
- Synthetic-data demonstration.
- Documented assumptions.
- Database migrations where applicable.
- Backup and recovery instructions.
- Security and privacy notes.
- Known limitations.
- User acceptance checks.

## 11. Claude Code Handoff

Implement these PRDs incrementally.

Begin with synthetic fixtures, the normalized financial model, and tests for transaction deduplication, internal transfers, credit-card payments, and balance reconciliation.

Do not access real financial files or introduce cloud services, external AI calls, institution connections, or paid dependencies without explicit approval.

Document ambiguous requirements in a decision log before implementing them.

Prioritize trustworthy financial accounting over visual polish.