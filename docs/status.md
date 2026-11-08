# Implementation Status

Last updated: 2026-11-08. Branch: `feature/m2-review`, from `643e1b1`. The owner intentionally pushed `feature/m1-foundation` up to `643e1b1`, and pushed `feature/m2-review` themselves. This clone records only a push of `673c025`. Live remote state and repository visibility are unverified (see [handoff.md](handoff.md)). Handoff: [handoff.md](handoff.md).

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
| M2.5: new evidence on decided records, and superseding chains | Accepted (D-048) |
| M2.6: value corrections | Accepted (D-049) |
| M2.7: resolving incomplete records | Accepted (D-050) |
| M2.8: coverage correction with history | Accepted (D-051) |
| M2.9: pending to posted | Accepted (D-052) |
| **M2 overall** | **Complete and accepted** |
| M3 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migrations `0001_initial`, `0002_block_replace`, `0003_reconciliation`,
  `0004_identity_and_primary`, `0005_decisions`, `0006_confirmation`, `0007_separation`,
  `0008_supersession_chains`, `0009_value_corrections`, `0010_record_resolutions`,
  `0011_coverage_declarations` and `0012_pending_posted_links`,
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
- `personal_finance.reconcile.correction_effects` and `corrections`: which corrected values apply
  to which transactions, and correcting and undoing values under one write lock (D-049).
  `reconcile.supersession` holds the chain rule that decisions and corrections share (D-048).
- `personal_finance.reconcile.record_resolutions`: completing and dismissing unresolved records, and
  undoing that, under one write lock (D-050).
- `personal_finance.reconcile.coverage_declarations`: declaring a document's coverage after import,
  and undoing that, under one write lock (D-051).
- `personal_finance.reconcile.rules` and `similarity`: the versioned matching
  configuration and the description heuristic.
- `personal_finance.reports.totals`: account inflows, outflows and net movement.
- `personal_finance.reports.import_summary`: run-level import counts in explicit units (D-036).
- `personal_finance.reports.review_evidence`: the evidence behind one review item or one
  transaction, and their revision tokens (D-040, D-047).
- `personal_finance.reports.decision_evidence`: what a decision binds, and the undo token (D-045).
- `personal_finance.reports.correction_evidence`: what a correction binds, and its undo token (D-049).
- `personal_finance.reports.resolution_evidence`: what a resolution resolved, and its undo token
  (D-050).
- `personal_finance.reports.coverage_evidence`: a document's claimed and declared coverage, and their
  tokens (D-051). `reports.undo_items` computes the undo token both share.
- CLI: `init`, `migrate`, `account add`, `import`, `reconcile`, `documents`, `transactions`,
  `trace`, `review list`, `review show`, `review reject`, `review confirm`, `review merges`,
  `review merge show`, `review separate`, `review decisions`, `review decision show`,
  `review undo`, `review transaction show`, `review correct`, `review corrections`,
  `review correction show`, `review correction undo`, `review complete`, `review dismiss`,
  `review resolutions`, `review resolution show`, `review resolution undo`, `review coverage show`,
  `review coverage declare`, `review coverage history`, `review coverage undo`, `totals`, run
  through the `bin/pf` launcher (D-038).

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

**Corrections (V18),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --corrected`. Full output is in `build/m2.6-bench/corrected.txt`, which is
ignored and may not survive.

First, three unmerged files of one dense group with a partition touching it, the shape where
derivation is quadratic. A correction moves no record, so it does not derive, while the later import
pays derivation in full. This shape reaches that cost: the later import takes 2.1s at 2,000.

| Transactions | Transaction show and token | Correct | Later import | Correction show and token | Undo |
|---|---|---|---|---|---|
| 98 | 0.000s | 0.001s | 0.010s | 0.001s | 0.001s |
| 500 | 0.000s | 0.002s | 0.137s | 0.002s | 0.003s |
| 998 | 0.000s | 0.002s | 0.523s | 0.003s | 0.006s |
| 2,000 | 0.001s | 0.003s | 2.104s | 0.007s | 0.012s |

Second, one account where every transaction but one has an active amount correction. Every
correction and every reconcile rewrites the account's derived rows, which is linear in corrections.

| Corrections | Rewrite of derived rows | Totals | Transaction show and one correction | Later import |
|---|---|---|---|---|
| 99 | 0.002s | 0.000s | 0.003s | 0.005s |
| 499 | 0.010s | 0.001s | 0.016s | 0.023s |
| 999 | 0.013s | 0.001s | 0.032s | 0.032s |
| 1,999 | 0.022s | 0.002s | 0.048s | 0.060s |
| 3,999 | 0.065s | 0.006s | 0.113s | 0.152s |

A chain of 50 corrections reads its states in 0.0001s and 2,000 in 0.0017s, and correction show on
the newest of 2,000 takes 0.011s. **Corrections add no quadratic recomputation.** A correction stays
below a later import of the same account in every row, though with thousands of corrections and
nothing else to derive the two are close, because both rewrite every derived row. Matching was not
changed.

**Resolutions (U19),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --resolved`. Two exports of the same purchases under complete coverage, with
one row of the first that the parser cannot read. That row blocks every confident pair, so resolving it
pays for every merge it unblocks, and undoing it for every split. The shape asserts that it does:
merged and split equal the pairs in every run. Full output is in `build/m2.7-bench/`, which is ignored
and may not survive.

| Kind | Pairs | Item show | Resolve | Later import | Resolution show | Undo |
|---|---|---|---|---|---|---|
| Dismiss | 500 | 0.005s | 0.243s | 0.044s | 0.128s | 0.408s |
| Dismiss | 2,000 | 0.002s | 1.141s | 0.222s | 0.526s | 1.962s |
| Dismiss | 5,000 | 0.003 to 0.059s | 1.094 to 4.568s | 0.305 to 0.440s | 0.788 to 1.046s | 3.116 to 11.551s |
| Complete | 500 | 0.001s | 0.132s | 0.039s | 0.106s | 0.220s |
| Complete | 2,000 | 0.004s | 1.217s | 0.738s | 0.545s | 2.132s |
| Complete | 5,000 | 0.004 to 0.014s | 1.500 to 3.023s | 0.235 to 0.886s | 0.561 to 1.510s | 2.611 to 5.420s |

The 5,000 rows were run three times, and the machine was loaded during the first run. For comparison,
an import that makes the same merges, the second export into a ledger without the unreadable row,
took 0.238s at 500, 1.309s at 2,000 and 6.745s at 5,000. **A resolution costs what the merges or
splits it causes cost.** The later import in the table merges nothing, so it is cheaper by design.
D-050's stop rule compared against that import, which this shows to be the wrong comparison.
Matching was not changed.

**Coverage declarations (K17),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --declared`. Two exports of the same purchases, the first of unknown
coverage and the second complete. Declaring the first complete pays for every merge that makes, and
the shape asserts it: merged and split equal the pairs. The last column imports the second export into
a ledger where the first was declared complete at import, which makes the same merges. Full output is
in `build/m2.8-bench/declared.txt`, which is ignored and may not survive.

| Pairs | Coverage show | Declare | Later import | Undo show | Undo | Merging import |
|---|---|---|---|---|---|---|
| 500 | 0.000s | 0.060s | 0.017s | 0.029s | 0.104s | 0.073s |
| 2,000 | 0.000s | 0.298s | 0.067s | 0.112s | 0.492s | 0.439s |
| 5,000 | 0.000s | 0.864s | 0.165s | 0.308s | 1.415s | 1.892s |

**A declaration costs no more than an import making the same merges.** Matching was not changed.

**Pending to posted (Q17),** measured 2026-11-08 on the same machine with
`measure_reconciliation.py --pending`. A pending export and a posted export of the same purchases on
one day, each posted at another amount. The shape asserts that it raises pending-to-posted
candidates. Full output is in `build/m2.9-bench/pending.txt`, which is ignored and may not survive.

| Descriptions | Pairs | Items | Steps | Posted import | Derive | Later import |
|---|---|---|---|---|---|---|
| Distinct merchants | 100 | 100 | 100 | 0.018s | 0.005s | 0.010s |
| Distinct merchants | 500 | 500 | 500 | 0.082s | 0.031s | 0.045s |
| Distinct merchants | 2,000 | 2,000 | 2,000 | 0.470s | 0.153s | 0.214s |
| One block | 100 | 1 | 10,000 | 0.066s | 0.057s | 0.064s |
| One block | 500 | 1 | 250,000 | 1.462s | 1.491s | 1.435s |
| One block | 2,000 | 1 | 4,000,000 | 24.021s | 40.590s | 30.960s |

The first version compared every pending unit with every posted unit in its window, so distinct
merchants cost what one block now costs: 4,000,000 steps and 35s at 2,000. **Distinct merchants are now
linear.** In one block every description is alike under D-032, so every pending row really is related
to every posted row, the output is one item of 4,000 transactions, and the cost is quadratic and paid
by every later import. That is the documented limit of distinct spellings per block, reached here
through amounts that differ.

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
  columns is an application rule, not something the database enforces. Corrections live in their
  own tables, and `ledger_transaction` keeps the primary source's values (D-049).
- Only amount, transaction date, posting date and description can be corrected, and no value can
  be cleared. An unresolved record can be corrected once completed.
- A completion supplies only values the parser could not read, and never a status or an ID. A row
  whose status was unreadable keeps `unknown`. There is no superseding a resolution: undo it, then
  resolve again. Undoing a completion waits for any decision or correction binding it.
- A completed record never merges automatically, so a re-export of it is reviewed as a possible
  duplicate. Same-document checks run only at import, so it is never flagged against rows of its
  own file.
- A correction binds the records of its transaction when made. One made after a merge binds more
  records, so a later split gives it `basis_changed` where an earlier correction would not. Item
  and transaction tokens then differ too, because they cover the bound records.
- Disagreeing corrections, or one whose records end up in several transactions, use the source
  value until one is undone. There is no command to settle them other than undo.
- Every correction and reconcile rewrites the account's derived correction rows.
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
  confident ID-less pairing for its document until it is dismissed or completed (D-050).
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
- Coverage can be declared after import with `review coverage declare`, complete or unknown only.
  Coverage a document's metadata states can only be withdrawn. One document at a time (D-051). A
  repeat import with a different declaration still fails with `coverage_conflict`, which names the
  command.
- The original file is not kept. Row contents and the file's hash are stored, and
  archiving arrives at M5.
- A pending and a posted row with one reliable ID merge whatever their amount. Without one, a changed
  amount raises a candidate for review, never a merge, and many alike descriptions in one block make
  that quadratic. Within one document, only rows D-021 flags, with equal amounts, can be confirmed
  together (D-052).
- After upgrading to rules version 2, every account reads as not current until `reconcile`.
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
