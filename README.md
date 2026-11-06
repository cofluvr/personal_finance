# Local-First Personal Finance

A personal finance application that turns financial statements into trustworthy spending insights, actionable budgets, and forward-looking financial plans.

The project has two primary deliverables:

1. **Python backend and local web interface** for importing financial documents, reconciling transactions, tracking finances, and planning.
2. **Native iOS companion** for viewing spending allowances and financial summaries on the go, including offline access after syncing with the Mac.

## Product Goals

- Understand how much was spent each month and on what.
- Calculate daily and weekly spending allowances that protect savings goals.
- Track household finances with personal and shared expense attribution.
- Reliably exclude internal transfers and credit-card payments from spending totals.
- Plan for annual expenses, graduated loan payments, savings goals, and future financial changes.
- Keep financial data local by default.
- Avoid required subscriptions or paid APIs.

## Core Features

### Document Ingestion and Reconciliation

- Import CSV exports and text-based PDF statements.
- Initial institution targets: Capital One, US Bank, and American Express.
- Identify accounts from statement metadata.
- Detect duplicate transactions across overlapping documents.
- Reconcile pending and posted versions of transactions.
- Identify transfers between owned accounts.
- Preserve source-document provenance and user corrections.

### Spending and Household Management

- Configurable categories, subcategories, and tags.
- Fixed versus discretionary expense classification.
- Transaction splits across categories and household members.
- Personal, shared, and household-wide reporting.
- Local browser-based review interface.

### Budgeting and Planning

- Daily and weekly spending guidance.
- Original targets alongside revised remaining allowances.
- Emergency funds, house savings, and early loan payoff goals.
- Annual and irregular expense reserves.
- Graduated loan payment schedules.
- Conservative financial scenarios.
- Configurable reserves for untaxed side income.
- Cash-flow, debt, and net-worth summaries.

### iOS Companion

- Secure local-network synchronization.
- Protected offline snapshots.
- At-a-glance spending allowances.
- Personal and household views.
- Clear freshness and incomplete-data warnings.

## Privacy and Security Principles

- The Mac is the authoritative source of financial data.
- The iPhone stores only the information needed for offline viewing.
- No cloud-hosted database by default.
- No banking passwords stored by the application.
- No external AI processing of real financial data by default.
- No telemetry or financial-data transmission by default.
- Real statements, credentials, and databases remain outside the AI coding workspace.
- Any future institution connection or cloud service requires explicit approval.

Claude Code may be used to develop the application using synthetic or sanitized fixtures. It is not assumed to provide local model inference.

## Initial Scope

The initial application supports:

- USD.
- Approximately two years of history across up to 30 accounts.
- Checking, savings, credit cards, loans, investments, and retirement accounts.
- One administrator managing all household data.
- On-demand operation on macOS.
- A read-only iOS companion after local synchronization.

## Delivery Plan

1. Financial foundation: ingestion, normalization, deduplication, transfers, and review.
2. Planning: budgets, goals, annual expenses, loans, and scenarios.
3. Mobile companion: secure synchronization and offline viewing.
4. Optional enhancements: receipts, mobile editing, institution connections, and cloud hosting.

## Planned Enhancements

- Receipt photography and item-level transaction splitting.
- Mobile transaction corrections and goal editing.
- Scheduled financial institution refreshes.
- Optional local AI-assisted categorization.
- XLSX ingestion.
- Notifications.
- Optional private cloud hosting.

These features are not part of the initial release unless explicitly reprioritized.

## Product Documentation

- [Backend PRD](docs/PRD-backend.md)
- [iOS PRD](docs/PRD-ios.md)
- [Shared Data and Sync Contract](docs/shared-contract.md)

## Development Principles

- Correct accounting before polished visualizations.
- Preserve original records and explain derived values.
- Never silently discard uncertain financial information.
- Keep actual transactions separate from hypothetical scenarios.
- Use exact monetary arithmetic.
- Require tests for duplicates, transfers, and financial allocations.
- Keep operational maintenance low.

## Project Status

Early implementation of the Python backend. It imports two invented CSV layouts only, matches duplicates across overlapping files within an account, and must not be used with real financial data. See [implementation status](docs/status.md).

## Development Setup

Requires Python 3.12 or later on macOS. Installing the development tools is the only step that needs network access. The application has no runtime dependencies.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Tests run offline and use only synthetic data. Decisions are recorded in the [decision log](docs/decisions.md), the delivery order is in the [implementation plan](docs/plan.md), and supported formats are in [document layouts](docs/layouts.md).

## Synthetic Example

Keep databases outside this repository. Totals are account movements, not income or spending.

```sh
pf() { PYTHONPATH=src .venv/bin/python -m personal_finance "$@"; }
DB="$(mktemp -d)/demo.db"
F=tests/fixtures/synthetic

pf init --db "$DB"
pf account add --db "$DB" --name "Synthetic Checking" --type checking
pf account add --db "$DB" --name "Synthetic Card" --type credit_card

# Coverage is stated in the first file. The second has none, so it stays unknown.
pf import --db "$DB" --account "Synthetic Checking" --layout synthetic_checking_v1 \
  $F/checking_jan_complete.csv $F/checking_problem_rows.csv

# This file states no coverage, so the user declares it explicitly.
pf import --db "$DB" --account "Synthetic Card" --layout synthetic_card_v1 \
  --declare-complete-coverage --coverage-start 2026-01-01 --coverage-end 2026-01-31 \
  --coverage-basis posting $F/card_jan_no_metadata.csv

pf documents --db "$DB"
pf review list --db "$DB"
pf totals --db "$DB"
pf transactions --db "$DB"
pf trace --db "$DB" TRANSACTION_ID

# Importing reconciles the account. This does the same without a new file.
pf reconcile --db "$DB"
```

After updating the code, an older ledger must be upgraded before use. Commands refuse it and change nothing until then. `migrate` upgrades the schema, and `reconcile` then updates how transactions are grouped.

```sh
pf migrate --db "$DB"
pf reconcile --db "$DB"
```
