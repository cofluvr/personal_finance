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

Early implementation of the Python backend. It imports two invented CSV layouts only, matches duplicates across overlapping files within an account, and must not be used with real financial data. See [implementation status](docs/status.md) and the [M1 acceptance matrix](docs/m1-acceptance.md).

## Development Setup

Requires Python 3.12 or later on macOS. Installing the development tools is the only step that needs network access. The application itself has no runtime dependencies.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Tests run offline and use only synthetic data. Decisions are recorded in the [decision log](docs/decisions.md), the delivery order is in the [implementation plan](docs/plan.md), and supported formats are in [document layouts](docs/layouts.md).

## Running pf

`bin/pf` runs the application with this checkout's `.venv`. Nothing needs installing beyond creating that environment, and it works from any directory and from paths containing spaces.

```sh
bin/pf --help
bin/pf import --help
```

To run it by name, add the `bin` folder to `PATH`, or link `bin/pf` from a folder already on it. Alternatively, `python -m pip install .` in a virtual environment installs the package and a `pf` script. Building it downloads setuptools.

| Exit code | Meaning |
|---|---|
| 0 | The command finished |
| 1 | `import` finished, but at least one file failed. Other files in the run are kept |
| 2 | The command stopped: bad usage, a validation error, a busy ledger, or an unexpected problem |
| 141 | The program reading the output closed it early, as in `bin/pf transactions \| head` |

## Synthetic Example

Run these from the repository root. Keep real data out of this repository, and databases outside it. Totals are account movements, not income or spending.

```sh
DB="$(mktemp -d)/demo.db"
F=tests/fixtures/synthetic

bin/pf init --db "$DB"
bin/pf account add --db "$DB" --name "Synthetic Checking" --type checking
bin/pf account add --db "$DB" --name "Synthetic Card" --type credit_card

# Coverage is stated in the first file. The second has none, so it stays unknown.
bin/pf import --db "$DB" --account "Synthetic Checking" --layout synthetic_checking_v1 \
  $F/checking_jan_complete.csv $F/checking_problem_rows.csv

# This file states no coverage, so the user declares it explicitly.
bin/pf import --db "$DB" --account "Synthetic Card" --layout synthetic_card_v1 \
  --declare-complete-coverage --coverage-start 2026-01-01 --coverage-end 2026-01-31 \
  --coverage-basis posting $F/card_jan_no_metadata.csv

bin/pf documents --db "$DB"
bin/pf review list --db "$DB"
bin/pf review show --db "$DB" ITEM_ID
bin/pf totals --db "$DB"
bin/pf transactions --db "$DB"
bin/pf trace --db "$DB" TRANSACTION_ID

# Importing reconciles the account. This does the same without a new file.
bin/pf reconcile --db "$DB"
```

`transactions`, `trace` and `review show` show descriptions and amounts because that is their purpose. `import`, `reconcile`, `documents`, `review list`, `review reject`, `review decisions`, `review decision show` and `review undo` do not, and `totals` shows only aggregates. The application writes no logs: output goes to the terminal, and the ledger is the only file it writes.

## Reading a Review Item

`review list` gives each open item an ID, and `review show` displays one item's evidence.

## Rejecting a Candidate Pair

```sh
bin/pf review reject --db "$DB" --account ACCOUNT ITEM_ID --revision REVISION --pair T1 T2
bin/pf review decisions --db "$DB"
bin/pf review decision show --db "$DB" DECISION_ID
bin/pf review undo --db "$DB" --account ACCOUNT DECISION_ID --revision REVISION
```

`review reject` records that two transactions in a `cross_document_candidates` item are different events. Other kinds of item cannot be acted on yet, and possible duplicates cannot yet be confirmed, so true duplicates stay open and counted.

- Name a pair from the direct pairs listed by `review show`. Two transactions that only share an item through a third are refused. Repeat `--pair` to record several pairs as one decision.
- The account, item and revision from `review show` are checked together, and any change to the evidence since you looked refuses the command. An account that is not current is refused: run `reconcile`, then look again.
- Rejecting changes no totals and moves no records. The decision covers the records in those two transactions now, not new records, so a re-export can raise the question again.
- An item closes when nothing undecided remains in it.

**Decision conflicts** are listed apart from possible duplicates. If a later file would automatically merge records you kept apart, the whole match is withheld and its records stay separate and counted, so later evidence can raise the transaction count and account movements, and can split an earlier automatic merge. If an automatic split divides a transaction a decision was based on, the decision stands and you are told its basis changed.

`review undo` needs the revision from `review decision show`, and is refused if anything relevant to regrouping has changed since. It keeps the decision on record and re-derives from the evidence held now. It does not restore earlier totals: if files have arrived since, the result is what the ledger would be had the decision never been made.

| Section | Meaning |
|---|---|
| Machine-generated reasons | Why the item exists. These are heuristics, not proof |
| Current logical transaction values | What the ledger counts now |
| Primary-source selection | Which record supplies those values, and why the others did not |
| Original source cells | The row exactly as read |
| Parsed source values | What the parser read from that row |
| Coverage evidence | What each document claims, and the last date matching relies on |
| Revision | Identifies this evidence. It changes when any of it changes, and a repeat import that changes nothing leaves it alone |

A value the source did not provide is shown as `missing`. Members of a possible-duplicate group are all counted in full, and no exact adjustment can be stated. See [D-040](docs/decisions.md).

## Reading an Import Summary

Each count keeps its own unit, so do not add different lines together. A file's lines describe the moment it was imported. The run summary and the account lines read the ledger after the last file.

| Line | Meaning |
|---|---|
| Files attempted | Equals imported + already imported + failed |
| Source rows read | Non-blank data rows in newly imported files. Equals valid + unresolved |
| Final logical transactions for those valid records | Distinct transactions those records now belong to |
| Confidently consolidated records | Valid records whose transaction also has a record from another document |
| Net change in live logical transactions | The ledger's signed change. It can exceed the rows read, because a new file can split an earlier merge, and it can be zero |
| Source memberships changed | Source records moved to a different transaction during reconciliation |
| Open review groups | Possible duplicates awaiting review, with the distinct transactions they affect. Groups can overlap |
| Decision conflicts | New evidence that disagrees with a stored decision, counted apart from possible duplicates. One transaction can appear in several of these counts |
| Unresolved records | Rows that could not be read as a transaction. They are not in totals |

A failed file never counts towards rows read. It shows either `Source rows: unavailable`, or a count of rows read and then rolled back, of which none were kept. See [D-036](docs/decisions.md).

## Upgrading a Ledger

After updating the code, an older ledger must be upgraded before use. Commands refuse it and change nothing until then. `migrate` upgrades the schema, and `reconcile` then updates how transactions are grouped.

```sh
bin/pf migrate --db "$DB"
bin/pf reconcile --db "$DB"
```
