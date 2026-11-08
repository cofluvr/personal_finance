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

`transactions`, `trace`, `review show`, `review merge show` and `review transaction show` show descriptions and amounts because that is their purpose. `import`, `reconcile`, `documents`, `review list`, `review reject`, `review confirm`, `review merges`, `review separate`, `review decisions`, `review decision show`, `review undo`, `review correct`, `review corrections`, `review correction show`, `review correction undo`, `review complete`, `review dismiss`, `review resolutions`, `review resolution show`, `review resolution undo`, `review coverage show`, `review coverage declare`, `review coverage history` and `review coverage undo` do not, and `totals` shows only aggregates. The application writes no logs: output goes to the terminal, and the ledger is the only file it writes.

## Reading a Review Item

`review list` gives each open item an ID, and `review show` displays one item's evidence.

## Rejecting a Candidate Pair

```sh
bin/pf review reject --db "$DB" --account ACCOUNT ITEM_ID --revision REVISION --pair T1 T2
bin/pf review decisions --db "$DB"
bin/pf review decision show --db "$DB" DECISION_ID
bin/pf review undo --db "$DB" --account ACCOUNT DECISION_ID --revision REVISION
```

`review reject` records that two transactions in a `cross_document_candidates` item are different events. Other kinds of item cannot be rejected.

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

## Confirming Duplicates

```sh
bin/pf review confirm --db "$DB" --account ACCOUNT ITEM_ID --revision REVISION --group T1 T2 [--group T3]
```

`review confirm` records which transactions in a `cross_document_candidates` or `decision_conflict` item are one event. Each `--group` is one event, different groups are different events, and transactions you leave out stay undecided, so you can confirm part of a group.

- A group must be linked directly, may hold only one record from any document, and may not join two different IDs that the source guarantees unique. Two alike rows of one file go in separate groups.
- Confirming joins each group into one transaction, so totals can go down. It changes nothing else, or it is refused. `totals` says how many transactions hold confirmed records.
- On a candidate item, at least one group must hold two transactions. Keeping transactions apart is `review reject`.
- A confirmation survives repeat imports, `reconcile`, new files and rules changes. A new automatic match joins a confirmed transaction only when that keeps one record per document and breaks no decision. Otherwise the match is withheld and raised as a conflict.
- Confirming every transaction of a conflict, in one decision, settles it. A rejection never does.
- At most 50 transactions can be named in one decision.

To replace an earlier rejection that a group contradicts, add `--supersedes DECISION_ID --supersedes-revision REVISION`, with the revision from `review decision show`. Every pair of the old decision must be either contradicted by the groups or kept with `--keep N`, using the pair numbers that `review decision show` prints. Undoing the new decision restores the old one, unless decisions made since contradict it. A superseded decision cannot be undone directly. In a chain of several, only the newest applies and can be undone, and each undo restores the one before it. When the rejection closed its item, there is nothing to confirm on: undo it, which raises the item again, then confirm. See [D-046](docs/decisions.md).

## Separating an Automatic Merge

```sh
bin/pf review merges --db "$DB" --account ACCOUNT
bin/pf review merge show --db "$DB" TRANSACTION_ID
bin/pf review separate --db "$DB" --account ACCOUNT TRANSACTION_ID --revision REVISION --group R1 R2 [--group R3] \
   [--supersedes DECISION_ID --supersedes-revision REVISION --keep N]
```

A confident automatic merge raises no review item, so `review merges` lists the transactions holding records joined automatically, by a reliable ID or an exact pair under complete coverage. `review merge show` gives one transaction's evidence, the record IDs to name, and its revision.

`review separate` records which of that transaction's records are one event. Each `--group` names record IDs, and records in different groups are different events.

- Every record of the transaction must be in exactly one group, and there must be at least two groups, so that nothing is separated without being stated.
- Separating can raise the transaction count and totals. It changes nothing but this transaction, or it is refused. `totals` says how many transactions hold records you separated. A group of several records stays together as a confirmed transaction.
- Records a confirmation joined must stay in one group, unless you name that confirmation with `--supersedes` and its revision from `review decision show`. Its pairs your groups split are contradicted, and every other pair must be kept with `--keep N`. `review decision show` gives the transaction a confirmed pair is now in. A transaction in an open decision conflict is settled through the conflict instead.
- When the records shared an ID the source declares reliable, the output says that this decision overrides it.
- The decision binds these records only. A later file holding the same event, such as a re-export with the same ID, is withheld and raised as a conflict, never merged silently. `review show` lists such records as alike a decided record, and you decide them by confirming a partition on that item. No decision transfers to a new record (D-048).
- `review undo` lets the merge return if the evidence still supports it, so totals can fall. At most 50 records can be named. See [D-047](docs/decisions.md).

## Correcting a Value

```sh
bin/pf review transaction show --db "$DB" TRANSACTION_ID
bin/pf review correct --db "$DB" --account ACCOUNT TRANSACTION_ID --revision REVISION \
   --field amount --value=-12.50 [--supersedes CORRECTION_ID --supersedes-revision REVISION]
bin/pf review corrections --db "$DB" --account ACCOUNT
bin/pf review correction show --db "$DB" CORRECTION_ID
bin/pf review correction undo --db "$DB" --account ACCOUNT CORRECTION_ID --revision REVISION
```

`review correct` records a corrected value for one field of a transaction: `amount`, `transaction_date`, `posting_date` or `description`. Write a negative amount as `--value=-12.50`, so that it is not read as an option, and a date as `YYYY-MM-DD`. The revision comes from `review transaction show`.

- The source values are kept. Totals and `transactions` use the corrected value, `trace` and `review show` show both, and matching never reads a correction, so it never merges or splits anything.
- A correction binds the records the transaction holds when you make it. A re-export that merges with them later keeps it applied. A new record that does not merge is not corrected.
- To change a corrected field again, name the correction applying there with `--supersedes` and its revision from `review correction show`. Only the newest of a chain applies, and each undo restores the one before it.
- If corrections that disagree end up in one transaction, or a correction's records end up in several transactions, the source value is used and `totals` says so on its own line. Undo one correction to settle it. `review confirm` and `review separate` refuse to cause either. See [D-049](docs/decisions.md).

## Resolving an Unresolved Row

```sh
bin/pf review show --db "$DB" ITEM_ID
bin/pf review complete --db "$DB" --account ACCOUNT ITEM_ID --revision REVISION \
   [--amount=-12.50] [--transaction-date YYYY-MM-DD] [--posting-date YYYY-MM-DD] [--description TEXT]
bin/pf review dismiss --db "$DB" --account ACCOUNT ITEM_ID --revision REVISION
bin/pf review resolutions --db "$DB" --account ACCOUNT
bin/pf review resolution show --db "$DB" RESOLUTION_ID
bin/pf review resolution undo --db "$DB" --account ACCOUNT RESOLUTION_ID --revision REVISION
```

An `unresolved_record` item is a row the parser could not read as a transaction. `review complete` supplies what it could not read, and the row becomes a transaction. `review dismiss` says the row adds no transaction: a blank line, a heading or summary, or an event already counted elsewhere. The revision comes from `review show`.

- A completion supplies only what is missing: an amount, a date or a description. It must leave the row with an amount and at least one date, and it cannot replace a value that was read. Complete the row first, then use `review correct` for that. A row whose values were all read, such as one with an unknown status, is completed with nothing supplied.
- Source cells and parsed values are kept. `review show`, `review transaction show` and `trace` show what you supplied apart from what was read, and `transactions` marks the transaction.
- Matching never pairs a completed row on the values you typed. An identical row in another file is raised as a possible duplicate, and `review confirm` can join them. A row read from a file supplies the displayed values before one you completed.
- An unresolved row can keep confident matches in its file from happening, because it could distort the count. A dismissed row no longer does, so totals can fall. A completed row still does wherever its values could match.
- `review resolution undo` makes the row unresolved again. Undoing a completion is refused while a decision or correction binds the row: undo those first. Completing it again brings back the same transaction ID. See [D-050](docs/decisions.md).

## Correcting a Document's Coverage

```sh
bin/pf documents --db "$DB"
bin/pf review coverage show --db "$DB" DOCUMENT_ID
bin/pf review coverage declare --db "$DB" --account ACCOUNT DOCUMENT_ID --revision REVISION \
   --coverage-kind complete --coverage-start YYYY-MM-DD --coverage-end YYYY-MM-DD --coverage-basis posting
bin/pf review coverage declare --db "$DB" --account ACCOUNT DOCUMENT_ID --revision REVISION --coverage-kind unknown
bin/pf review coverage history --db "$DB" --account ACCOUNT
bin/pf review coverage undo --db "$DB" --account ACCOUNT DECLARATION_ID --revision REVISION
```

Coverage given at import can be changed later. `documents` lists each document's ID, and `review coverage show` gives the revision to declare with and, while a declaration applies, the revision to undo it.

- `complete` states, as at import, that nothing in the interval is missing on that date basis. `unknown` withdraws a claim. A document that states its own coverage can only have it withdrawn.
- The claim made at import is kept. `documents` and `review show` show the declared coverage apart from it, and `totals` counts documents with declared coverage.
- Matching uses the declared coverage from then on, so rows can merge or split and totals can change. The output says how many transactions there were before and after.
- Each declaration replaces the one before it. Undo restores that one, or the claim at import. A repeat import with a declaration is compared with the coverage in effect. See [D-051](docs/decisions.md).

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
| Rows completed or dismissed | Rows you resolved by hand, each on its own line |

A failed file never counts towards rows read. It shows either `Source rows: unavailable`, or a count of rows read and then rolled back, of which none were kept. See [D-036](docs/decisions.md).

## Upgrading a Ledger

After updating the code, an older ledger must be upgraded before use. Commands refuse it and change nothing until then. `migrate` upgrades the schema, and `reconcile` then updates how transactions are grouped.

```sh
bin/pf migrate --db "$DB"
bin/pf reconcile --db "$DB"
```
