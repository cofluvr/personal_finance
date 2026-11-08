# Implementation Status

Last updated: 2026-11-08. Branch: `feature/m2-review`, from `643e1b1`. The owner intentionally pushed `feature/m1-foundation` up to `643e1b1`, and pushed `feature/m2-review` themselves. This clone records only a push of `673c025`. Live remote state and repository visibility are unverified (see [archive/handoff-history.md](archive/handoff-history.md)). Handoff: [handoff.md](handoff.md).

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
| M3.1: financial types | Accepted (D-053) |
| M3.2: transfers across accounts | Built, awaiting review (D-054) |
| M3 to M8 | Not started |

## What exists

- `personal_finance.money`: exact parsing and formatting of amounts.
- `personal_finance.db.migrate`: database creation, connections, migrations.
- Migrations `0001_initial`, `0002_block_replace`, `0003_reconciliation`,
  `0004_identity_and_primary`, `0005_decisions`, `0006_confirmation`, `0007_separation`,
  `0008_supersession_chains`, `0009_value_corrections`, `0010_record_resolutions`,
  `0011_coverage_declarations`, `0012_pending_posted_links`, `0013_type_classifications` and
  `0014_transfer_matches`,
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
- `personal_finance.reconcile.classification_effects` and `classifications`: which financial type
  applies to which transaction, sharing the corrections' effective-value rule, and classifying and
  undoing under one write lock (D-053).
- `personal_finance.reconcile.transfer_effects` and `transfers`: which transfer matches apply and
  which pairs are candidates, read after each account derives alone, and matching and undoing
  under one write lock (D-054).
- `personal_finance.reconcile.rules` and `similarity`: the versioned matching
  configuration and the description heuristic.
- `personal_finance.reports.totals`: account inflows, outflows and net movement, types, and transfers
  between accounts.
- `personal_finance.reports.import_summary`: run-level import counts in explicit units (D-036).
- `personal_finance.reports.review_evidence`: the evidence behind one review item or one
  transaction, and their revision tokens (D-040, D-047).
- `personal_finance.reports.decision_evidence`: what a decision binds, and the undo token (D-045).
- `personal_finance.reports.correction_evidence`: what a correction binds, and its undo token (D-049).
- `personal_finance.reports.classification_evidence`: what a classification binds, and its undo
  token (D-053).
- `personal_finance.reports.transfer_evidence`: what a transfer match binds, and its undo token
  (D-054).
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
  `review coverage declare`, `review coverage history`, `review coverage undo`, `review classify`,
  `review classifications`, `review classification show`, `review classification undo`,
  `review transfers`, `review transfer match`, `review transfer show`, `review transfer undo`, `totals`, run
  through the `bin/pf` launcher (D-038).

## What does not exist yet

No real institution layout is supported. **It must not be used with real financial
data** (M5 gate). Only candidate items, decision conflicts and automatically merged transactions
can be acted on.

## Acceptance criteria progress

All 47 criteria pass, each mapped to named tests in [m1-acceptance.md](m1-acceptance.md).
A17 is met against the corrected wording in [archive/plan-m1-m2.md](archive/plan-m1-m2.md). A18 is met because M1 has
no logs and its output stays clean (D-037).

**M1 is complete and accepted.** The owner gave final sign-off on 2026-11-06, based on the
acceptance tests and the clean-install verification in [m1-acceptance.md](m1-acceptance.md).
The limitations and deferred benchmarks below still stand.

A39 has provisional benchmarks, met by the figures below (D-034).

The security controls proposal is **not applied** and provides no protection
(D-025).

## Reconciliation measurements

In [benchmarks.md](benchmarks.md). Reconciliation is quadratic in fully overlapping files, in
distinct spellings per block, and in the units of a group a decision touches.

## Known limitations

- Only a person classifies, one transaction at a time. A type must fit the transaction's
  direction. A card, loan or investment payment may be money in on the account it pays, and interest
  is money out only, so interest earned is `income` (D-053, D-054).
- Disagreeing classifications, one whose records end up in several transactions, or one whose
  transaction's amount a correction's undo turns against it, leave the transaction unclassified
  until one is undone. There is no command to settle them other than undo.
- `totals` lists financial types and matched transfers next to account movement. It is not yet
  income or spending, which wait for M3.4.
- Only a person matches a transfer, one pair at a time, and only a candidate: a transfer-kind type
  on one side, the exactly opposite amount in another account, and dates within 5 days. Fees apart
  from the amount transferred, a transfer split over several transactions, and one-sided transfers
  are not matched (M3.3) (D-054).
- A match binds the records of both transactions when made, so a re-export that does not merge is
  unmatched. A match is never superseded: undo it and match again.
- A match whose side splits, that reaches a transaction another match reaches, whose amounts stop
  offsetting or whose type stops fitting no longer applies until undone. `totals` discloses it, and
  so do undos, but an import summary does not.
- Candidates are computed whenever `review transfers` or `totals` runs, quadratic in transactions of
  one amount on nearby dates. Every write rewrites every match's outcome, linear in matches. Both are
  measured in [benchmarks.md](benchmarks.md).

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
  resolve again. Undoing a completion waits for any decision, correction or classification
  binding it.
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
