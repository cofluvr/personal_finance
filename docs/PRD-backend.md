# PRD: Python Backend and Local Finance Workspace

## Document Status

- Version: 1.0
- Status: Draft for implementation planning
- Primary platform: macOS
- Primary currency: USD
- Related document: `shared-contract.md`

Normative language:

- **Must:** Required for the applicable release.
- **Should:** Recommended unless an alternative is documented.
- **Later:** Outside the initial release.
- **Proposed default:** May be changed during implementation with user approval.

## 1. Purpose

Create a local-first personal finance system that transforms financial documents into a reliable ledger, useful spending reports, and forward-looking financial plans.

The primary workflow is:

1. Add financial documents to one folder.
2. Run the import process from a terminal in VS Code.
3. Review uncertain records in a local browser interface.
4. View spending, cash flow, savings, debt, and net worth.
5. Understand available daily and weekly spending.
6. Explore future scenarios without changing actual financial records.

The system must minimize recurring manual maintenance while preserving correctness and traceability.

## 2. Users and Environment

- One technically comfortable administrator manages household finances.
- Multiple household members may be represented.
- Separate household-member logins are not required initially.
- Initial hardware: M2 MacBook Pro.
- Physical RAM remains to be confirmed; reported free disk space is approximately 110 GB.
- Initial execution is on demand.
- Expected dataset: approximately two years across up to 30 accounts.
- Financial records must remain in an explicitly non-cloud-synced location on the Mac.

Supported financial account types:

- Checking and savings.
- Credit cards.
- Loans, including individually tracked loan subaccounts.
- Investments.
- Retirement accounts.

## 3. Delivery Phases

### Phase 1A: Financial Foundation

- CSV and text-based PDF ingestion.
- Account identification.
- Transaction normalization.
- Transaction-level deduplication.
- Transfer and credit-card payment handling.
- Review interface.
- Balances and basic reports.

### Phase 1B: Planning

- Categories and household allocations.
- Budgets and spending allowances.
- Savings goals.
- Annual and irregular expense reserves.
- Graduated loan schedules.
- Financial scenarios.
- Lightweight tax reserves.

### Phase 1C: Mobile Integration

- Versioned snapshot generation.
- Secure local-network synchronization.
- Device pairing and revocation.

### Later, Subject to Approval

- Institution connections and scheduled refresh.
- XLSX ingestion.
- Receipt image processing.
- Optional local AI categorization.
- Cloud hosting.
- Multi-user access.

## 4. Initial Non-Goals

- Banking-password storage.
- Automated bank website login or scraping.
- Payment initiation.
- Detailed tax calculation or filing.
- Investment trading or recommendations.
- Required paid APIs or subscriptions.
- External AI processing of real financial data.
- Scanned-statement OCR.
- Always-on background operation.

## 5. Document Ingestion

### Initial Formats and Institutions

Formats:

- CSV transaction exports.
- Downloaded PDF statements with selectable text.

Initial institutions:

- Capital One.
- US Bank.
- American Express.

Institution support must be defined by tested document layouts and account types. Supporting one layout does not imply support for every document from that institution.

### Workflow

The importer must:

1. Discover files in one input folder.
2. Register source fingerprints.
3. Select a parser.
4. Extract account metadata, transactions, and available balances.
5. Normalize extracted records.
6. Reconcile duplicates and transfer candidates.
7. Apply categorization rules.
8. Commit results.
9. Produce an import summary.
10. Archive successfully handled files without deleting originals.

### Requirements

- Repeated imports must be safe and idempotent.
- Failure in one file must not prevent processing other files.
- Unsupported or failed files must remain available for review.
- Uncertain records must be imported and flagged where possible.
- Records missing essential fields must remain in an unresolved-import queue.
- Missing amounts, dates, or balances must not be fabricated.
- Transactions must retain source-file and source-record references.
- Import summaries must identify new, duplicate, reconciled, flagged, and failed records.
- Concurrent runs must not corrupt the ledger.
- Parser changes must preserve explicit user corrections.

## 6. Account Identity and Household Attribution

### Account Identity

Each account must have an immutable internal ID.

Matching attributes may include:

- Institution.
- Account type.
- Available account identifier, such as last four digits.
- Statement metadata.
- Previously confirmed source mappings.

Institution plus last four digits must not be assumed universally unique.

Ambiguous accounts must require user confirmation rather than silent merging.

### Household Attribution

The model must distinguish:

- Account ownership.
- Transaction attribution.
- Shared-expense allocation.

Requirements:

- Assign default attribution by account.
- Override attribution per transaction.
- Split transactions by amount or percentage.
- Support personal, shared, and household-total views.
- Compare household members side by side.
- Ensure all allocations sum to the transaction amount.

Proposed default: shared expenses use a configurable 50/50 split.

## 7. Normalized Financial Model

The model should include:

- Accounts and household members.
- Source documents and source records.
- Transactions and transaction splits.
- Balance observations.
- Duplicate and transfer relationships.
- Categorization rules and corrections.
- Budgets and planning periods.
- Goals and fund allocations.
- Recurring obligations.
- Loan terms and payment schedules.
- Scenario events.
- Review issues.
- Snapshots and paired devices.

### Transaction Fields

Where available:

- Internal transaction ID.
- Account ID.
- External transaction ID.
- Transaction date.
- Posting date.
- Optional timestamp.
- Exact amount and currency.
- Inflow/outflow direction.
- Original description.
- Normalized merchant.
- Financial type.
- Category, subcategory, and tags.
- Pending/posted status.
- Household allocations.
- Source provenance.
- Confidence and review flags.
- User overrides and relationship history.

### Financial Representation

- Use decimal arithmetic or integer cents.
- Never use floating-point arithmetic for monetary calculations.
- Normalize source-specific debit/credit conventions.
- Preserve original source values.
- Keep transaction type separate from spending category.
- Distinguish missing information from zero.

## 8. Transaction-Level Deduplication

**Priority: Critical**

Detect duplicates across:

- Repeated imports.
- Overlapping exports.
- CSV and PDF versions of the same activity.
- Pending and posted transaction versions.

### Evidence

Use available evidence including:

- Account identity.
- External transaction identifiers.
- Amount and direction.
- Transaction and posting dates.
- Descriptions.
- Source periods.
- Pending/posted status.

Matching merchant, amount, and date alone must not automatically merge legitimate repeated purchases.

### Outcomes

- Confident duplicate: count once and preserve all source evidence.
- Possible duplicate: retain both and flag for review.
- Confirmed distinct: preserve both and remember the decision.
- Pending-to-posted match: reconcile into one logical transaction.

Pending transactions must reduce spending capacity immediately. Their status must remain available internally for later reconciliation.

Reports must disclose unresolved possible duplicates that may affect totals.

## 9. Transfers and Financial Correctness

**Priority: Critical**

### Required Treatment

- Owned-account transfers are neither income nor spending.
- Credit-card payments are not additional spending when purchases are recorded.
- Investment contributions are separate from everyday spending.
- Loan principal reduces debt.
- Loan interest is an expense.
- Full loan payments remain visible in cash-flow planning.
- Refunds reduce the applicable spending category where identifiable.
- Household reimbursements must not duplicate household expenses.

### Matching Requirements

Support:

- Cross-institution transfers.
- Different posting dates.
- One-sided imported transfers.
- Fees separate from transferred principal.
- Manual confirmation and rejection.
- Reversal of incorrect matches.

Equal amounts alone are insufficient proof.

Incomplete account coverage must produce warnings, especially when credit-card payments exist without underlying purchase history.

## 10. Categorization and Corrections

### Proposed Starting Categories

- Housing.
- Utilities and communications.
- Food.
- Transportation.
- Health.
- Shopping and household.
- Entertainment.
- Travel.
- Gifts and donations.
- Insurance.
- Interest and financial fees.
- Other/uncategorized.

Support configurable subcategories, tags, and fixed/discretionary classifications.

Income, transfers, debt principal, and investment contributions must remain distinct financial types.

### Correction Actions

- Change one transaction.
- Apply a rule to future matches.
- Apply a rule to matching historical transactions.
- Preview affected records.
- Undo changes.

Explicit transaction corrections must take precedence over general rules.

### Local AI

AI is not required for initial categorization.

A future local model must:

- Run only on request.
- Receive sanitized, allowlisted fields.
- Have no access to original statements, credentials, account identifiers, or unrestricted files.
- Propose categories and reusable rules.
- Require approval for bulk changes.
- Operate without network transmission.

Claude Code is a development tool, not the assumed local categorization runtime.

## 11. Income and Recurring Expenses

### Salary

- Detect salary deposits and biweekly cadence.
- Suggest the normal take-home amount.
- Require initial confirmation.
- Reconcile expected and actual deposits.
- Flag unexpected changes.

Three-paycheck months must not increase normal spending targets. The extra paycheck is allocated to savings goals.

Proposed default: side income is excluded from baseline spending until received. After tax reservation, it goes toward goals unless overridden.

### Recurring Expenses

Infer candidates from transactions:

- Amount or range.
- Frequency.
- Next expected date.
- Fixed/discretionary status.

Require confirmation before relying on an inferred obligation.

Manual input is secondary but remains necessary for future events and incomplete history. Corrections should improve reusable detection behavior where appropriate.

## 12. Budgets and Safe-to-Spend Guidance

### Budget Structure

- Calendar-month periods.
- Household allowance with personal allocations.
- Optional category allowances.
- Separate fixed commitments and discretionary spending.
- No spending-budget rollover.
- Unused capacity is allocated to savings.

An allocation to savings is not evidence of an actual bank transfer.

### Protected Funds

Reserve funds for:

1. Side-income tax reserves.
2. Required bills and minimum debt payments.
3. Annual and irregular expenses.
4. Minimum checking buffer.
5. Emergency-fund restoration.
6. Approved savings and extra debt-payment goals.

Prevent double reservation of the same obligation.

### Required Outputs

- Original monthly target.
- Actual spending.
- Remaining capacity.
- Revised daily and weekly allowances.
- Dollars above or below target pace.
- Reduction needed to recover.
- Equivalent days of original allowance where meaningful.

Proposed convention:

- Daily allowance uses remaining calendar days, including today.
- Weekly allowance covers the next seven days, capped at month end.

Negative remaining capacity must be shown and explained.

### Cash-Flow Constraint

Monthly budget capacity and near-term liquidity must be evaluated separately.

The system must not recommend spending that would breach protected balances or leave an upcoming obligation unfunded before the next paycheck.

Show the constraint limiting the allowance. Label calculations provisional when relevant data is incomplete.

## 13. Savings and Planned Expenses

### Goals

Support:

- Monthly contributions.
- Percentage-of-income contributions.
- Target amounts by deadlines.

Multiple goals may share an account, but the same funds cannot be allocated twice.

### Emergency Fund

Support:

- Fixed minimum balance.
- Configurable months of essential expenses.

Recommend restoration when underfunded. Do not change other allocations without approval.

### Retirement and Investments

- Include balances in net worth.
- Show balance and contribution history where available.
- Keep retirement separate from house/debt goal prioritization.
- Do not subtract payroll deductions again from take-home income.

### Annual and Irregular Expenses

Support:

- Target amount.
- Due date or recurrence.
- Existing assigned funds.
- Monthly reservation.
- Underfunding warnings.

Reservations reduce spending capacity but are not actual spending. The eventual purchase is counted once and consumes its allocation.

## 14. Graduated Loan Planning

Store:

- Balance and observation date.
- Interest terms.
- Payment schedules with effective dates.
- Due dates.
- Remaining term where available.
- Extra-payment assumptions.

Requirements:

- Compare actual payments to the applicable schedule.
- Support changing scheduled payment amounts.
- Distinguish confirmed balances from projections.
- Compare highest-interest-first, smallest-balance-first, and custom payoff orders.
- Support user-configured allocation between debt and other goals.

Projections must not be labeled lender-exact until relevant accrual, allocation, fee, and schedule rules are validated.

## 15. Financial Scenarios

Support:

- Salary changes.
- Bonuses and side income.
- Recurring expense changes.
- One-time purchases.
- Home purchases and financing.
- Closing and ongoing ownership costs.
- Loan payoff and new borrowing.

Behavior:

- Active baseline plus named alternatives.
- Side-by-side comparison.
- Conservative defaults.
- Uncertain income excluded unless explicitly enabled.
- Approval before promotion to the active plan.
- No changes to actual transaction history.

Outputs:

- Required saving.
- Available spending.
- Goal completion estimates.
- Cash shortfalls.
- Debt and net-worth effects.
- Assumptions and missing inputs.

## 16. Lightweight Tax Reserve

- User configures a reserve percentage.
- User labels eligible income sources.
- Reserve funds from eligible actual income.
- Track allocations and recorded payments/releases.
- Exclude reserved funds from spendable income.

Label the result as a planning reserve, not a calculated tax liability.

## 17. Balances and Net Worth

- Use observed balances, not transaction totals alone.
- Extract statement balances where available.
- Allow manual observations.
- Record valuation dates.
- Prevent aggregate loans and subaccounts from being counted twice.
- Warn about incomplete or mixed-date valuations.
- Keep scenario assets out of actual net worth.

## 18. Local Web Interface

Required sections:

1. Dashboard.
2. Transactions and search.
3. Import results and review queue.
4. Accounts and household members.
5. Budgets, goals, and planned expenses.
6. Scenarios.
7. Settings and backups.

Required visuals:

- Category spending.
- Spending over time.
- Target versus actual spending pace.
- Goal progress.
- Household comparison.
- Income and cash flow.
- Debt history.
- Net worth with valuation dates.

Proposed export scope: CSV initially; formatted PDF and image exports later.

## 19. Security and Operations

- No telemetry by default.
- Local UI bound to loopback.
- Explicit sync mode for mobile access.
- Restricted filesystem permissions.
- Encryption design covering sensitive database, caches, and backups.
- Secrets kept out of source code and ordinary configuration.
- Sensitive descriptions excluded from routine logs.
- Original statements retained until explicit deletion.
- Backup restore tested.
- Real data kept outside the AI coding workspace.
- Dependency and runtime network behavior documented.

Security controls must be verified; no absolute-security guarantee may be claimed.

## 20. Resource Targets

Proposed targets, subject to benchmarking:

- No mandatory model download.
- Warn before optional components exceed 5 GB.
- Report software, database, originals, and backup storage separately.
- No heavy always-running process.
- Benchmark with 100,000 synthetic transactions.
- Common dashboard queries targeted below two seconds.
- Import-time targets established after representative files are available.

## 21. Acceptance Criteria

- [ ] Reimporting identical files changes no totals.
- [ ] Overlapping CSV/PDF records count once when confidently matched.
- [ ] Legitimate repeated purchases remain distinct.
- [ ] Pending-to-posted reconciliation avoids double counting.
- [ ] Confirmed internal transfers affect neither income nor spending.
- [ ] Credit-card payments do not duplicate purchases.
- [ ] Ambiguous matches remain visible and reversible.
- [ ] All transaction splits reconcile exactly.
- [ ] Annual reservations and purchases are not double-counted.
- [ ] Third paychecks do not increase normal spending targets.
- [ ] Goal allocations cannot silently exceed available funds.
- [ ] Graduated payments follow the configured schedule.
- [ ] Reports disclose incomplete data and material review issues.
- [ ] Backups restore records, rules, corrections, and goals.
- [ ] Core operation succeeds without internet access.

## 22. Inputs Needed Before Implementation

- Redacted examples for supported document layouts.
- Representative graduated-loan documents.
- Actual RAM and macOS version.
- Local data and backup destinations.
- Household and account assignments.
- Initial goals, emergency minimum, and checking buffer.
- Side-income labels and tax reserve percentage.
- House-versus-debt allocation preference.
- Delivery deadline, if any.