# Implementation Status

Last updated: 2026-11-07. Branch: `feature/m2-review`, from `643e1b1`. The owner intentionally pushed `feature/m1-foundation` up to `643e1b1`, and pushed `feature/m2-review` themselves. This clone records only a push of `673c025`. Live remote state and repository visibility are unverified (see [handoff.md](handoff.md)). Handoff: [handoff.md](handoff.md).

| Milestone | Status |
|---|---|
| M1 slice 1: scaffolding, money, schema, migrations | Accepted |
| M1 slice 2: synthetic layouts, coverage, provenance, idempotent import | Accepted |
| M1 slice 3: cross-document duplicate handling | Accepted |
| M1 slice 4: import summaries, log checks, entry point, setup documentation | Accepted |
| **M1 overall** | **Complete and accepted** |
| M2.1: review evidence and revision tokens | Accepted |
| M2.2: decision core, pair rejection and undo | Accepted |
| M2.3: confirmation, partitions and superseding | Accepted (D-046) |
| M2.4: separating machine-made merges | Accepted (D-047) |
| M2.5: new evidence on decided records, and superseding chains | Implemented, awaiting review (D-048) |
| M2.6 to M2.9 | Provisional, not approved |
| M3 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migrations `0001_initial`, `0002_block_replace`, `0003_reconciliation`,
  `0004_identity_and_primary`, `0005_decisions`, `0006_confirmation`, `0007_separation` and
  `0008_supersession_chains`,
  applied by `init` and `migrate` only (D-035).
- `personal_finance.ingest`: two invented layouts, explicit coverage, atomic
  per-file import.
- `personal_finance.reconcile.same_document`: flags possible duplicates within one
  document. Merges nothing.
- `personal_finance.reconcile.cross_document`: derives an account's transactions and
  review items as a pure function of its stored evidence.
- `personal_finance.reconcile.apply`: applies that result atomically with the import,
  recording every source movement.
- `personal_finance.reconcile.decisions`: rejecting pairs, confirming partitions, separating
  automatic merges, superseding and undoing decisions, each under one write lock (D-043, D-045,
  D-046, D-047, D-048).
- `personal_finance.reconcile.rules` and `similarity`: the versioned matching
  configuration and the description heuristic.
- `personal_finance.reports.totals`: account inflows, outflows and net movement.
- `personal_finance.reports.import_summary`: run-level import counts in explicit units (D-036).
- `personal_finance.reports.review_evidence`: the evidence behind one review item or one
  transaction, and their revision tokens (D-040, D-047).
- `personal_finance.reports.decision_evidence`: what a decision binds, and the undo token (D-045).
- CLI: `init`, `migrate`, `account add`, `import`, `reconcile`, `documents`, `transactions`,
  `trace`, `review list`, `review show`, `review reject`, `review confirm`, `review merges`,
  `review merge show`, `review separate`, `review decisions`, `review decision show`,
  `review undo`, `totals`, run through the `bin/pf` launcher (D-038).

## What does not exist yet

No real institution layout is supported. **It must not be used with real financial
data** (M5 gate). Only candidate items, decision conflicts and automatically merged transactions
can be acted on.

## Acceptance criteria progress

All 47 criteria pass, each mapped to named tests in [m1-acceptance.md](m1-acceptance.md).
A17 is met against the corrected wording in [plan.md](plan.md). A18 is met because M1 has
no logs and its output stays clean (D-037).

**M1 is complete and accepted.** The owner gave final sign-off on 2026-11-06, based on the
acceptance tests and the clean-install verification in [m1-acceptance.md](m1-acceptance.md).
The limitations and deferred benchmarks below still stand.

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

**Dense constrained groups (S16),** measured 2026-11-06 on the same machine with
`measure_reconciliation.py --constrained`. Each candidate group is one amount, date and description
across two unmerged documents, the worst shape for this code. Discovery stores no pairs (D-031), so
any group a constraint touches has its direct links compared again, pair by pair.

| Units in the group | Derivation, no constraints | One constraint | Constraints on 10% of units | Pairs compared |
|---|---|---|---|---|
| 100 | 0.001s | 0.005s | 0.005s | 4,950 |
| 500 | 0.004s | 0.115s | 0.112s | 124,750 |
| 1,000 | 0.008s | 0.479s | 1.056s | 499,500 |
| 2,000 | 0.037s | 2.611s | 1.898s | 1,999,000 |
| 4,000 | 0.046s | 7.542s | 9.613s | 7,998,000 |

**This is quadratic in the units of a touched group.** Doubling the group compares 4 times as many
pairs, and the number of constraints does not change that count. Every later import and reconcile of that account
pays it. Groups no constraint touches are not recomputed. Matching semantics were not changed to
reduce this. A real ledger holds such a group only if the same amount and description recur within
the date window across thousands of rows.

| Transactions in the item | Loading evidence and token | Whole `review reject`, under the write lock | Undo token and preview | Whole `review undo`, under the write lock |
|---|---|---|---|---|
| 100 | 0.006s | 0.013s | 0.008s | 0.012s |
| 500 | 0.016s | 0.162s | 0.123s | 0.132s |
| 1,000 | 0.031s | 0.499s | 0.531s | 0.509s |
| 2,000 | 0.066s | 2.170s | 1.962s | 3.105s |

The first version of `review reject` took 19.6s at 2,000 because validation listed every direct
pair in the item. It now checks only the stated pairs. `review show` lists at most 50 pairs for the
same reason. These timings vary by up to about 2 times between runs here, and other work on the
machine was not controlled. Pairs compared are exact.

**Confirmation (C19),** measured 2026-11-07 on the same machine with
`measure_reconciliation.py --confirmed`. Three unmerged documents, so that a confirmed transaction
still links with the third and stays in the group, which is the worst shape. With only two
documents a confirmed transaction holds both and links with nothing, which made confirmation look
far cheaper than it is. That first run was discarded.

| Units in the group | One rejection | One confirmation | One partition | Confirmations on 10% | Partitions on 10% |
|---|---|---|---|---|---|
| 100 | 0.006s | 0.001s | 0.006s | 0.001s | 0.004s |
| 500 | 0.130s | 0.004s | 0.132s | 0.004s | 0.102s |
| 1,000 | 0.576s | 0.009s | 0.563s | 0.008s | 0.443s |
| 2,000 | 2.118s | 0.017s | 2.046s | 0.018s | 1.590s |
| 4,000 | 8.573s | 0.034s | 8.333s | 0.032s | 6.277s |

Derivation alone. A confirmation that only joins writes no `different_event` pair, so it touches no
group and compares nothing again. A partition keeps its groups apart, which touches the group just
as a rejection does, and costs the same. Confirmed units are fewer, so many confirmations compare
slightly fewer pairs.

| Transactions in the item | Decision | Whole decision command | Later import | Undo token and preview | Whole undo |
|---|---|---|---|---|---|
| 2,001 | Rejection | 2.189s | 2.118s | 2.145s | 2.129s |
| 2,001 | Confirmation | 0.106s | 0.037s | 0.067s | 0.109s |
| 2,001 | Partition | 2.247s | 2.181s | 2.174s | 2.250s |

Through a real ledger, under the write lock. Smaller items scale the same way, and the full output
is in `build/m2.3-bench/confirmed.txt`, which is ignored and may not survive. **Confirmation does
not make the quadratic recomputation worse.** A partition costs what a rejection costs, within the
variation of these runs, and a plain confirmation costs far less. Matching was not changed.

**Separation (P19),** measured 2026-11-07 on the same machine with
`measure_reconciliation.py --separated`. Two documents with complete coverage pair every row exactly,
and a third of unknown coverage holds the same rows, so every merge and every separated record
links with all of the third, in one group. With only the two merging documents a separated record
would link with nothing, which would make separating look far cheaper than it is.

| Merges | Units in the group | One rejection | One partition | One separation | Separations on 10% | Pairs compared, one separation | On 10% |
|---|---|---|---|---|---|---|---|
| 50 | 100 | 0.005s | 0.005s | 0.005s | 0.005s | 5,050 | 5,460 |
| 250 | 500 | 0.110s | 0.112s | 0.122s | 0.127s | 125,250 | 137,550 |
| 500 | 1,000 | 0.444s | 0.523s | 0.436s | 0.495s | 500,500 | 550,725 |
| 1,000 | 2,000 | 1.720s | 1.706s | 1.664s | 1.881s | 2,001,000 | 2,203,950 |
| 2,000 | 4,000 | 6.957s | 6.817s | 6.614s | 7.726s | 8,002,000 | 8,817,900 |

Derivation alone. A rejection and a partition compare n(n − 1)/2 pairs for n units. A separation
touches the group the same way and adds one unit for each record it takes out of a merge, so ten
percent of merges separated makes about ten percent more units and about ten percent more pairs.

| Transactions | Decision | Whole decision command | Later import | Undo token and preview | Whole undo |
|---|---|---|---|---|---|
| 2,000 | Rejection | 1.892s | 1.740s | 1.754s | 1.764s |
| 2,000 | Separation | 1.690s | 1.740s | 1.812s | 1.783s |

Through a real ledger, under the write lock. A rejection of the merged transaction against a row of
the third file is the baseline, since a partition into single transactions on a candidate item is
refused (D-046). Smaller ledgers scale the same way, and the full output is in
`build/m2.4-bench/separated.txt`, which is ignored and may not survive. **Separating does not make
the quadratic recomputation worse** than a rejection or a partition, apart from the units it adds.
Matching was not changed.

**Superseding (N18),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --superseded`. Three unmerged documents, so that a record separated from
a confirmed pair still links with all of the third, in one group. A partition keeps a confirmed
pair apart from a record of the third. A separation superseding a plain confirmation leaves only its
pair of different events, which touches the group the same way.

| Units in the group | One partition | One superseding separation | Partitions on 1 in 30 | Superseding on 1 in 30 | Pairs compared, superseding |
|---|---|---|---|---|---|
| 100 | 0.006s | 0.006s | 0.005s | 0.006s | 4,950 |
| 500 | 0.131s | 0.128s | 0.120s | 0.128s | 124,750 |
| 1,000 | 0.513s | 0.516s | 0.468s | 0.512s | 499,500 |
| 2,000 | 2.412s | 2.100s | 1.887s | 2.077s | 1,999,000 |
| 4,000 | 8.940s | 8.472s | 9.083s | 10.261s | 7,998,000 |

Derivation alone. Partitions compare slightly fewer pairs because their confirmed pairs are one unit,
while a superseding separation leaves both records as units.

| Transactions | Decision | Whole decision command | Later import | Undo token and preview | Whole undo |
|---|---|---|---|---|---|
| 2,001 | Partition | 2.340s | 2.077s | 2.228s | 2.185s |
| 2,001 | Superseding separation | 2.662s | 2.151s | 2.145s | 2.272s |

Through a real ledger, under the write lock. The confirmation being superseded is made first and not
timed. Smaller ledgers scale the same way, and the full output is in `build/m2.5-bench/superseded.txt`,
which is ignored and may not survive. **A superseding separation does not make the quadratic
recomputation worse** than a partition, within the variation of these runs. Matching was not changed.

`decision_states` read 50 chained decisions in 0.0001s and 2,000 in 0.0016s, reading each decision
once. The alike listing in `review show` stops at the 51 it needs: 0.0014s on 2,000 lookalike
transactions and 0.023s on 20,000. Its first version built every match before printing 50, a million
at 2,000 lookalikes taking 0.99s, and was made lazy.

## Known limitations

- Only `cross_document_candidates` items can be rejected, and only they and decision conflicts can
  be confirmed. External-ID and same-document items stay open.
- A group may hold one record per document, so two alike rows of one file are always separate
  transactions (D-008).
- Superseding by confirmation needs an open item holding the transactions. A rejection that closed
  its item must be undone first. Only one decision can be superseded at a time, by a confirmation
  or, for a confirmation, by a separation. A rejection supersedes nothing.
- A decision binds the records it names, and no decision transfers to a new record. A re-export
  raises the question again, so overlapping exports can bring repeat reviews. `review show` lists
  records alike a decided record to help, and binds nothing.
- Withholding can raise totals through new evidence, though it is disclosed. A decision conflict
  is settled by confirming a partition of all its transactions in one decision. A rejection never
  settles one.
- `review show` escapes file names in its decided section, but its older sections print them as
  typed, so a file name holding a newline can imitate a line there (noted below for all names).
- Setup and both entry points have only been verified on this Mac with Python 3.12.6.
  `bin/pf` needs `.venv` at the root of its checkout.
- Dependencies are pinned without hashes, and setuptools is only bounded as `>=68`, so a
  later package build can use a different version. An editable install is untested.
- A file's counts in an import summary describe the moment it was imported. Later files in
  the same run can change them, so only the run summary and the account lines are final.
- `internal_error` and the unexpected-error message carry no detail by design, so such a
  problem must be reproduced with synthetic data to be diagnosed.
- File and account names are shown as typed, so a name holding sensitive text is displayed
  and stored. The argument parser also echoes invalid option values.
- An interrupted import leaves earlier files in the run committed, with no summary.
- `ledger_transaction` values can be updated. Keeping corrections out of base
  columns is an application rule for M2, not something the database enforces.
- The database cannot enforce that every transaction has at least one source.
  Tests check this after success, failure and crash.
- A separation names every record of one transaction, at most 50. It splits records a
  confirmation joined only by superseding that confirmation, and does not act on a transaction in
  an open conflict. Automatic moves are recorded in
  `transaction_link_history`, and automatic splits happen only for machine-made merges.
- A separation binds the records it names. A re-export of them is withheld and raised as a
  conflict, so overlapping exports can bring repeat reviews.
- `review decision show` lists every record pair of a separation, up to 1,225 for 50 records.
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
- `review show` does not say whether a transaction also sits in another review item (D-031).
  Its output for a long group is long, and there is no grouped review of long runs yet.
- Nothing consumes the revision token yet. It is shown for M2.2 to use, and today only tests
  compare it. It covers only inputs that exist, and is not a security measure.
- `review show` needs the full item ID. A later import can replace an item, and the ID then
  reads as not found.
- `review show` escapes descriptions and IDs, but prints file names as typed (D-037).
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
