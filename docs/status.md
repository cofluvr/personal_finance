# Implementation Status

Last updated: 2026-11-05. Branch: `feature/m1-foundation`. The owner pushed `c75aee0` to `origin`, and later commits are local. Remote state and repository visibility are unverified (see [handoff.md](handoff.md)). Handoff: [handoff.md](handoff.md).

| Milestone | Status |
|---|---|
| M1 slice 1: scaffolding, money, schema, migrations | Complete, provisionally accepted |
| M1 slice 2: synthetic layouts, coverage, provenance, idempotent import | Complete, provisionally accepted |
| M1 slice 3: cross-document duplicate handling | Not started, scoped in [handoff.md](handoff.md) |
| M1 slice 4: import summaries, log checks, entry point, setup documentation | Not started |
| M2 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migrations `0001_initial` and `0002_block_replace`.
- `personal_finance.ingest`: two invented layouts, explicit coverage, atomic
  per-file import.
- `personal_finance.reconcile.same_document`: flags possible duplicates within one
  document. Merges nothing.
- `personal_finance.reports.totals`: account inflows, outflows and net movement.
- CLI: `init`, `account add`, `import`, `documents`, `transactions`, `trace`,
  `review list`, `totals`.

## What does not exist yet

**Cross-document duplicate detection does not exist.** Importing two overlapping
files that are not byte-identical counts their shared rows twice. Import and totals
output both say so.

No real institution layout is supported. **It must not be used with real financial
data** (M5 gate).

## Acceptance criteria progress

Passing end to end: A1, A9, A10, A11, A12, A13, A14, A15, A19, A23, A26, A29, A30,
A31, A40, A41.

Partly proven, with more to come in later slices: A8 (schema only), A17 (counts
shown, full check in slice 4), A18 (CLI output checked; no logging exists yet), A25
(`totals` checked; re-check at slice 4).

All others depend on slice 3. See [plan.md](plan.md).

The security controls proposal is **not applied** and provides no protection
(D-025).

## Known limitations

- `ledger_transaction` values can be updated. Keeping corrections out of base
  columns is an application rule for M2, not something the database enforces.
- The database cannot enforce that every transaction has at least one source.
  Tests check this after success, failure and crash.
- Merges cannot yet be undone. `transaction_source` has no history until M2.
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
