# Implementation Status

Last updated: 2026-11-05. Branch: `feature/m1-foundation` (local only).

| Milestone | Status |
|---|---|
| M1 slice 1: scaffolding, money, schema, migrations | Complete, awaiting review |
| M1 slice 2: synthetic layouts, coverage, provenance, idempotent import | Not started |
| M1 slice 3: duplicate handling | Not started |
| M1 slice 4: CLI, import summaries, setup documentation | Not started |
| M2 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migration `0001_initial`: the M1 schema, with no rows written by any application
  code yet.

## What does not exist yet

There is no importer, deduplication, CLI or totals report. The application cannot
yet read a file. **It must not be used with real financial data** (M5 gate).

## Acceptance criteria progress

Fully passing: A19 (network blocked in tests).

Proven at module or schema level only, with end-to-end proof still to come: A8,
A9, A10, A11, A12, A13, A23.

All others are not yet testable. See [plan.md](plan.md).

## Known limitations

- `ledger_transaction` values can be updated. Keeping corrections out of base
  columns is an application rule for M2, not something the database enforces.
- The database cannot enforce that every transaction has at least one source.
  That is checked by test A13 in later slices.
- Merges cannot yet be undone. `transaction_source` has no history until M2.
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
