# Implementation Status

Last updated: 2026-11-05. Branch: `feature/m1-foundation`. The owner pushed `c75aee0` to `origin`, and later commits are local, including all of slice 3. Remote state and repository visibility are unverified (see [handoff.md](handoff.md)). Handoff: [handoff.md](handoff.md).

| Milestone | Status |
|---|---|
| M1 slice 1: scaffolding, money, schema, migrations | Accepted |
| M1 slice 2: synthetic layouts, coverage, provenance, idempotent import | Accepted |
| M1 slice 3: cross-document duplicate handling | Accepted |
| M1 slice 4: import summaries, log checks, entry point, setup documentation | In progress |
| M2 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migrations `0001_initial`, `0002_block_replace`, `0003_reconciliation` and
  `0004_identity_and_primary`, applied by `init` and `migrate` only (D-035).
- `personal_finance.ingest`: two invented layouts, explicit coverage, atomic
  per-file import.
- `personal_finance.reconcile.same_document`: flags possible duplicates within one
  document. Merges nothing.
- `personal_finance.reconcile.cross_document`: derives an account's transactions and
  review items as a pure function of its stored evidence.
- `personal_finance.reconcile.apply`: applies that result atomically with the import,
  recording every source movement.
- `personal_finance.reconcile.rules` and `similarity`: the versioned matching
  configuration and the description heuristic.
- `personal_finance.reports.totals`: account inflows, outflows and net movement.
- CLI: `init`, `migrate`, `account add`, `import`, `reconcile`, `documents`, `transactions`,
  `trace`, `review list`, `totals`.

## What does not exist yet

No real institution layout is supported. **It must not be used with real financial
data** (M5 gate). Review items cannot be resolved yet (M2).

## Acceptance criteria progress

Passing end to end: A1 to A16, A19 to A24, A26 to A46.

Partly proven, with more to come in slice 4: A17 (counts shown, full check in slice 4,
against the corrected wording in [plan.md](plan.md)),
A18 (CLI output checked; no logging exists yet), A25 (`totals` checked; re-check at
slice 4).

A39 has provisional benchmarks, met by the figures below (D-034).

The security controls proposal is **not applied** and provides no protection
(D-025).

## Reconciliation measurements

Measured 2026-11-05 with `tests/benchmarks/measure_reconciliation.py`.

**Machine:** Mac14,7 with an Apple M2, 8 cores, 8 GB memory, macOS 27.2, Python 3.12.6,
SQLite 3.45.3. Other work on the machine was not controlled.

**Fixtures:** one account, `synthetic_card_v1`, unknown coverage, 24 monthly files. Each
later file repeats the last 10% of the month before.

| Fixture | Parameters |
|---|---|
| Ordinary | Seed 7, 400 merchants, random amounts from 1.00 to 199.99, random day in the month |
| Dense | One merchant, one amount (5.00), rows spread evenly over 30 days |

**What a timing covers:** one `import_files` call, which reads and parses the file,
writes records, reconciles the account and commits. Setup is excluded: generating data,
writing the CSV files and creating the database.

| Fixture | Rows a month | Source records | Logical transactions | Last import | Slowest import | All 24 imports |
|---|---|---|---|---|---|---|
| Ordinary | 200 | 5,260 | 5,260 | 0.14s | 0.14s | 1.84s |
| Ordinary | 1,000 | 26,300 | 26,300 | 0.90s | 0.90s | 11.44s |
| Ordinary | 4,000 | 105,200 | 105,200 | 4.92s | 4.92s | 61.34s |
| Dense | 200 | 5,260 | 5,260 | 0.16s | 0.16s | 2.03s |
| Dense | 1,000 | 26,300 | 26,300 | 1.16s | 1.18s | 14.19s |
| Dense | 4,000 | 105,200 | 105,200 | 5.32s | 5.57s | 67.74s |

The 4,000-row fixtures meet the D-034 benchmarks.

Unknown coverage means nothing merges, so source records equal logical transactions.
These fixtures therefore measure candidate discovery, not the cost of applying many
merges at once.

**Known stress limitations, which are not covered by the benchmarks:**

- Full re-exports of 2,000 dense rows: 6 files took 2.48s in total, 12 files 8.04s and 24
  files 32.38s. Candidate steps were 59,985, 263,934 and 1,103,724, so work grows about 4
  times each time the file count doubles. **This is quadratic in overlapping files.**
- 12 re-exports of 8,000 dense rows: 96,000 records, slowest import 6.09s, 39.45s in total.
- Distinct spellings of one amount in one similarity block, derivation alone, measured
  before the closeout, which did not change this code: 1,000 took 0.45s, 2,000 took
  1.85s, 5,000 took 10.24s and 10,000 took 40.72s. **This is quadratic in distinct
  spellings.** It is not expected in practice, but nothing prevents it.
- These are measurements of these shapes, not general guarantees. The expected dataset of
  about 100,000 rows across 30 accounts is nearer the smallest rows above.

## Known limitations

- `ledger_transaction` values can be updated. Keeping corrections out of base
  columns is an application rule for M2, not something the database enforces.
- The database cannot enforce that every transaction has at least one source.
  Tests check this after success, failure and crash.
- Users cannot undo merges until M2. Automatic moves are recorded in
  `transaction_link_history`, and automatic splits happen only for machine-made merges.
- Import holds the write lock through reconciliation. At about 100,000 rows in one
  account that can exceed the 5-second wait, so a concurrent writer reports
  `database_busy`. It explains what to do, leaves nothing partial, and a retry succeeds.
- `reconcile` across all accounts commits each account separately. If it stops at a busy
  ledger, accounts already reported stay reconciled and the rest are untouched.
- An ID-bearing row against an ID-less row can only be a possible duplicate, so such
  overlaps stay flagged and counted twice. Revisit for CSV-to-PDF matching (M7).
- Similarity has known misses and false positives (D-032). A miss on rows without
  reliable IDs is counted twice with no flag, unless coverage proves an exact match.
  Rows with a blank description are never matched or flagged.
- An unresolved row with no parsed fields, such as `wrong_column_count`, blocks all
  confident ID-less pairing for its document.
- Long runs of repeated purchases become several overlapping review items. Reviewing
  them as a group arrives in M2.
- A transaction merged before migration 0004 shows no primary source until its account is
  reconciled. The account reads as not current until then, and `totals` says so.
- An ID retired before migration 0004 has no stored `created_at`. If revived, it uses its
  first record's link time. `trace` labels that as approximate, but the column itself
  carries no marker. Adding one is a prerequisite before any UI or export presents legacy
  creation timestamps (follow-up F2).
- A multi-step upgrade is atomic per step, not as a whole. After a failure the ledger stays
  at the last good version, and commands refuse it until `migrate` succeeds.
- Coverage cannot be changed after import. A file imported with unknown coverage
  cannot be declared complete later. The attempt fails with `coverage_conflict`,
  existing data stays unchanged, and the message explains the limitation. M2 adds
  the correction and history workflow.
- The original file is not kept. Row contents and the file's hash are stored, and
  archiving arrives at M5.
- Pending and posted rows are only flagged when amount and description match. A
  tip or a changed description is not detected in one document until M2.
- Identical rows in one document are always separate. This is true of the invented
  layouts and must be proven for each real layout.
- Failed attempts may go unrecorded if the database stays busy. The CLI still
  reports them.
- A file with a large number of rows holds the write lock for the whole import.
  Other writers wait up to 5 seconds and then report `database_busy`.
- `create_database` leaves its file behind if a migration fails, and a later
  attempt then refuses to overwrite it.
- Edited migration files are not detected. Only the version number is tracked.
- The database is not encrypted, and `0600` is only applied at creation.
- The test network guard covers Python sockets in the test process. It does not
  cover subprocesses or native code.
- Uppercase extensions such as `.CSV` are ignored only because git sets
  `core.ignorecase` on macOS. On a case-sensitive setup they would not be.
- Amount parsing accepts a small generic syntax. Trailing minus signs and CR/DR
  suffixes are rejected until a layout proves they are needed.
