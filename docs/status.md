# Implementation Status

Last updated: 2026-11-05. Branch: `feature/m1-foundation`. The owner pushed `c75aee0` to `origin`, and later commits are local, including all of slice 3. Remote state and repository visibility are unverified (see [handoff.md](handoff.md)). Handoff: [handoff.md](handoff.md).

| Milestone | Status |
|---|---|
| M1 slice 1: scaffolding, money, schema, migrations | Complete, provisionally accepted |
| M1 slice 2: synthetic layouts, coverage, provenance, idempotent import | Complete, provisionally accepted |
| M1 slice 3: cross-document duplicate handling | Complete, awaiting review |
| M1 slice 4: import summaries, log checks, entry point, setup documentation | Not started |
| M2 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migrations `0001_initial`, `0002_block_replace` and `0003_reconciliation`. The CLI
  applies outstanding migrations whenever it opens a ledger.
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
- CLI: `init`, `account add`, `import`, `reconcile`, `documents`, `transactions`,
  `trace`, `review list`, `totals`.

## What does not exist yet

No real institution layout is supported. **It must not be used with real financial
data** (M5 gate). Review items cannot be resolved yet (M2).

## Acceptance criteria progress

Passing end to end: A1 to A16, A19 to A24, A26 to A46.

Partly proven, with more to come in slice 4: A17 (counts shown, full check in slice 4),
A18 (CLI output checked; no logging exists yet), A25 (`totals` checked; re-check at
slice 4).

A39 has no approved time target yet. D-034 proposes one.

The security controls proposal is **not applied** and provides no protection
(D-025).

## Reconciliation measurements

From `tests/benchmarks/measure_reconciliation.py`, on this machine, 2026-11-05. All rows
are in one account with unknown coverage, so every overlap is compared. Each file
repeats 10% of the month before.

| Shape | Rows | Files | First import | Last import | All imports | Candidate steps |
|---|---|---|---|---|---|---|
| Ordinary | 5,260 | 24 | 0.02s | 0.14s | 1.83s | 464 |
| Ordinary | 26,300 | 24 | 0.06s | 0.84s | 11.39s | 2,341 |
| Ordinary | 105,200 | 24 | 0.30s | 4.68s | 62.41s | 9,894 |
| Dense, one merchant and amount | 5,260 | 24 | 0.01s | 0.14s | 1.80s | 63,201 |
| Dense, one merchant and amount | 26,300 | 24 | 0.06s | 1.12s | 13.44s | 319,317 |
| Dense, one merchant and amount | 105,200 | 24 | 0.32s | 6.52s | 77.03s | 1,272,777 |
| 500 spellings, one block | 105,200 | 24 | 0.48s | 4.56s | 68.99s | 1,219,200 |

- Each import re-derives the account, so its cost grows with account size, and total
  cost across a series of imports grows faster than the row count.
- Stress, full re-exports of 2,000 dense rows: 6 files 2.47s in total, 12 files 8.07s,
  24 files 31.40s. Steps were 59,985, 263,934 and 1,103,724, so work grows about 4 times
  each time the file count doubles. **This shape is quadratic in overlapping files.**
- Stress, 12 re-exports of 8,000 dense rows: 96,000 rows, last import 5.54s, 38.65s in
  total.
- Stress, distinct spellings of one amount in one similarity block, derivation alone:
  1,000 took 0.45s, 2,000 took 1.85s, 5,000 took 10.24s, 10,000 took 40.72s. **This is
  quadratic in distinct spellings.** It needs one amount and one first-token prefix
  across thousands of spellings, which is not expected, but nothing prevents it.
- These are measurements of these shapes, not general guarantees. The expected dataset
  of about 100,000 rows across 30 accounts is nearer the smallest rows above.

## Known limitations

- `ledger_transaction` values can be updated. Keeping corrections out of base
  columns is an application rule for M2, not something the database enforces.
- The database cannot enforce that every transaction has at least one source.
  Tests check this after success, failure and crash.
- Users cannot undo merges until M2. Automatic moves are recorded in
  `transaction_link_history`, and automatic splits happen only for machine-made merges.
- Import holds the write lock through reconciliation. At about 100,000 rows in one
  account that exceeds the 5-second wait, so a concurrent writer reports `database_busy`.
- An ID-bearing row against an ID-less row can only be a possible duplicate, so such
  overlaps stay flagged and counted twice. Revisit for CSV-to-PDF matching (M7).
- Similarity has known misses and false positives (D-032). A miss on rows without
  reliable IDs is counted twice with no flag, unless coverage proves an exact match.
  Rows with a blank description are never matched or flagged.
- An unresolved row with no parsed fields, such as `wrong_column_count`, blocks all
  confident ID-less pairing for its document.
- Long runs of repeated purchases become several overlapping review items. Reviewing
  them as a group arrives in M2.
- A revived transaction ID gets a new `created_at`. `trace` shows every source but does
  not mark which one supplied the displayed values.
- Reading commands also apply outstanding migrations, so they can write once after an
  upgrade.
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
