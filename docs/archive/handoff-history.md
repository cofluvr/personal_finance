# Handoff History, M1 to M3.2

Moved out of [handoff.md](../handoff.md) on 2026-11-08 to keep each session's required reading small. The text is
unchanged from the handoff at `80ca837`, with links adjusted to this folder. Measurements it
places in status.md are now in [benchmarks.md](../benchmarks.md). Read a section here only when a task
needs it.

## Status summary, as written at M3.1

For a fresh session. Written 2026-11-08. **M1 is complete and accepted**, and its limitations and
deferred benchmarks still stand. See [m1-acceptance.md](../m1-acceptance.md).

**M2.1 to M2.6 are accepted.** The owner accepted M2.2 as built on 2026-11-07, including
the choices at the end of D-045, with no changes. The owner accepted M2.3 as built on 2026-11-07,
including the rules and limits recorded in D-046 and "M2.3 as built" below, with no changes. The owner
accepted M2.4 as built on 2026-11-07, including the rules and implementation choices recorded in
D-047 and the limits in "M2.4 as built" below, with no changes. The owner accepted M2.5 as built on
2026-11-08, including the rules and implementation choices recorded in D-048 and the limits in
"M2.5 as built" below, with no changes. The owner accepted M2.6 as built on 2026-11-08, including
the rules and implementation choices recorded in D-049 and the limits in "M2.6 as built" below, with
no changes. On 2026-11-08 the owner asked for M2.7, M2.8 and M2.9 to be built in turn with the lead
engineer's recommendations, each recorded as its own decision before its code, and **accepted all
three as built the same day**, including the amendment of A34, continuing past D-050's stop rule, and
the limits in "M2.7 as built" to "M2.9 as built" below. **M2 is complete and accepted.** The owner
approved the M3.1 plan, financial types, as D-053 with no changes on 2026-11-08. **M3.1 is built and
awaits review**, with the implementation choices and the points for review at the end of D-053, and
the limits in "M3.1 as built" below. M3.2 is not started. M2.1's decisions are D-040 and
D-041, M2.2's rules are D-042 to D-045, with D-045 overriding the others where they differ, M2.3's are
D-046, M2.4's are D-047, M2.5's are D-048, M2.6's are D-049, and M2.7's are D-050. The owner
approved implementing M2.7 on 2026-11-08 with the lead engineer's recommendations, which are
recorded as D-050. M2.8's rules are D-051 and M2.9's D-052.

## Completed

**Slice 1:** scaffolding, `.gitignore`, exact money module, schema, migrations,
decision log, status document, test network guard.

**Slice 2:** two invented CSV layouts, explicit coverage (document metadata or user
declaration), immutable source records, parser records per version, atomic per-file
import, same-document possible-duplicate flags, and the CLI: `init`, `account add`,
`import`, `documents`, `transactions`, `trace`, `review list`, `totals`.

**Follow-ups, both real bugs now fixed:** very long digit strings raised the wrong
error type, and `INSERT OR REPLACE` bypassed the immutability triggers (migration
`0002`).

**Since the slice 2 report:** rejected file associations and coverage conflicts now
explain themselves, with tests for a byte-identical file under another account, and
for complete coverage not hiding unresolved rows.

**Slice 3:** cross-document reconciliation. `derive()` is a pure function of an
account's stored evidence, applied as a diff in the import's database transaction.
Reliable-ID matching, ID-less exact pairing and candidate discovery are separate paths.
Migration `0003` adds stored interpretation, record origins, append-only movement
history and the reconciliation marker. Adds the `reconcile` command, and replaces the
old overlap notice with accurate disclosure.

**Found while building slice 3:** the CLI never applied migrations to an existing
ledger. The first A16 generator never produced a split and almost no exact pairs, so
focused generators and an exhaustive split test were added.

**Slice 3 closeout:** migration is an explicit `migrate` command, and read commands are
read-only and explain an outdated schema (D-035). Migration `0004` preserves a retired
ID's `created_at` for revival and records the primary source, which `trace` now names and
explains. `database_busy` was verified, including a commit blocked after reconciliation.

**Slice 4:** import summaries in explicit units (D-036), a new
`reports/import_summary.py`, a safe CLI boundary and privacy tests (D-037), the `bin/pf`
launcher and a declared `pf` script (D-038), and setup and usage documentation.

**Found while building slice 4:** the old summary called records accepted "transactions",
which was wrong when a file split an earlier merge: one row took the ledger from 1 to 3.
Per-file group counts could not be added up, failed files showed invented zeros, and the
first version of the boundary reported a closed pipe as an unexpected problem.

**M2.1:** `review list` prints item IDs, and the read-only `review show` presents one item's
evidence in separate sections (D-040). A new `reports/review_evidence.py` loads the evidence
and computes a revision token over all material evidence. No migration. D-037 now places
`review show` with `trace`.

**Found while building M2.1:** `review list` printed no issue IDs, so nothing could refer to an
item. A review item can keep its ID while its members change, which is why the token exists. A
quoted CSV cell can hold a newline, so unescaped output could imitate a section. Planning
probes also showed a pending 20.00 and posted 24.00 with no ID count as 44.00 with no review
item at all, a silent double count that the M2.9 direction covers.

**M2.2:** migration 0005, with append-only decision, constraint and event tables. Constraints in
`derive()`, whole-group withholding and `decision_conflict` items. `review reject`, `review decisions`,
`review decision show`, `review undo`. Revision version 2. A new `reconcile/decisions.py` and
`reports/decision_evidence.py`. S1 to S23 pass.

**Found while building M2.2:** `_settled_groups` would have blocked a resolved item from returning
after undo, so closing is removal (D-045). Validation first listed every direct pair in an item,
taking 19.6s at 2,000 transactions, and now checks only the stated pairs. `review show` would have
printed about a million pair lines on a dense group, and now stops at 50. `review show` still prints
file names as typed in its older sections, which is the existing documented limitation and was left
alone as outside M2.2.

A privacy test depended on random ID order and failed at random, hiding four surviving breaks until
a rerun exposed them. Read which test caught a break, not only that one did.

**M2.3:** migration 0006, adding `decision.kind` and `decision.supersedes_decision_id`. `same_event`
units in `derive()`, settling conflicts by confirmation, `review confirm` with explicit partitions,
superseding a rejection by confirmation, undo that restores a superseded decision, item revision
version 3, decision revision version 2, and a `totals` line for confirmed transactions. C1 to C21
pass, and S1 to S23 still pass.

**Found while building M2.3:**

- Settling a conflict whenever every pair was decided would have changed M2.2: a withheld match
  already fully covered by rejections raises a conflict under D-044. Only a confirmation's partition
  settles one, so rejections behave exactly as before.
- A partition of only one-transaction groups on a candidate item would be a rejection that gets
  around D-045's direct-only rule. It is refused there and allowed on conflicts.
- A rejection that closed its item leaves nothing to confirm on, so superseding it needs undo first.
- Deliberate breaks found two real bugs. A chain group could join two different unique IDs, which
  D-026 says are different events. A withheld merge touching several confirmed units merged those
  units together. Both are fixed and tested.
- Joining a group through a withheld merge was unreachable, since such transactions are always
  direct candidates. That path, a document check in undo and two immaterial undo token fields were
  removed rather than kept untested.
- The first confirmation benchmark used two documents, so a confirmed transaction linked with
  nothing and confirmation looked far cheaper than it is. It was rerun with three.
- A break-script edit failed silently once and the benchmark ran on unchanged code. That run was
  discarded. Chain commands with `&&`, as for commits.

**M2.4:** migration 0007, which renames `decision.review_issue_id` and `item_revision` to `target_id`
and `target_revision`, adds `target_kind`, and rebuilds `decision_constraint` with `left_part` and
`right_part`. `review merges`, `review merge show` with the transaction token `t1`, and
`review separate`, which stores a partition of one transaction's records as a confirmation targeting
that transaction. A `totals` line for separated transactions, and `measure_reconciliation.py
--separated`. P1 to P22 pass, and S1 to S23 and C1 to C21 still pass.

**M2.5:** migration 0008, which clears the reconciliation marker of accounts holding a superseding
chain. The fix for F4: a decision stays superseded while anything superseding it has not been undone,
and refusals name the newest of a chain. Undo token version 3. `review separate --supersedes`, so a
separation can supersede a confirmation, a separation included. A listing in `review show` of records
alike a decided record, which binds nothing. `measure_reconciliation.py --superseded`. N1 to N18
pass, and S1 to S23, C1 to C21 and P1 to P22 still pass.

**M2.6:** migration 0009, with append-only `value_correction`, `value_correction_record` and
`value_correction_event`, and the derived `transaction_correction`. Corrections of amount, dates and
description, anchored on records and applied after derivation, which never reads them. Totals use
effective amounts. `review transaction show`, `review correct`, `review corrections`,
`review correction show` and `review correction undo`. `review confirm` and `review separate` refuse
to leave a correction unsettled. Tokens `r4`, `t2` and `d4`, keeping their digests on ledgers without
corrections, and the new `c1`. The chain rule moved to `reconcile/supersession.py`, shared with
decisions. `measure_reconciliation.py --corrected`. V1 to V18 pass, and S, C, P and N still pass.

**Found while building M2.6:**

- Two modules needed the chain rule, and corrections and `apply` would have imported each other, so
  the rule and the state constants moved to their own module. `apply` still exports the constants.
- The 0008 migration tests built a ledger at the latest version and set it back to 7, which stops
  working once 0009 creates tables. They now drop 0009's empty tables and migrate only to 8.
- A rejection test assumed `pair_up`'s first transaction was `a.csv`. Its order follows content
  hashes, so the test now names the file.
- Equivalent corrections made at different points can bind different records, which item tokens
  cover, so the order test compares everything but revisions and checks binding separately.
- The first benchmark edit matched nothing, because the docstring wraps differently, and the
  script stopped before writing. Nothing ran on unchanged code. A first walkthrough one-liner
  extracted no record IDs and ran later steps with empty arguments. It was discarded and rewritten
  as a script.
- Deliberate breaks: 34 applied once each with an unbroken control passing. 32 caught at first. Two
  survivors were test gaps, now closed: superseding one of two agreeing corrections, and a date in
  basic format, which Python 3.12 accepts. Three `c1` inputs, its state, the bound records' evidence
  and other corrections of the field, were noticed only by the pin. They cannot change while a
  token can be checked, so they were removed before review, keeping version 1. A rerun found a
  third survivor, an agreeing correction's undo, which changes only the outcome after. It is now
  tested.

**Found while building M2.5:**

- F4, at the M2.4 review: a chain of two revived its first decision. A `derive()` check showed it
  could change the ledger, not only the listed states: with the revived rejection, an automatic
  merge into the confirmed unit was withheld with a conflict, and without it the merge joined. So
  0008 makes such accounts stale rather than only changing how states are read.
- Under the corrected rule a decision is superseded exactly when a decision not undone supersedes it,
  so the recursive state walk became a direct lookup, linear in decisions.
- `load_decision` unpacked exactly one active successor, which a chain of two would have broken. It now
  names the immediate successor and the newest of the chain.
- The tests of migration 0007 migrated to the latest version, so they would have started testing
  0008. They now stop at 7.
- Importing `TestConfirm` by name into a new test file made pytest collect its tests a second time.
  The module is imported instead.
- One test was written after a module-level function and became a nested function no one collects.
  A count of the tests run showed it. It was moved into its class.
- The alike listing first built every match before printing 50, a million on 2,000 lookalikes. It is
  lazy now, and its cap is tested.
- The order test's expected count was wrong at 120. All 60 valid cases matched, and the count was
  corrected with its arithmetic.
- A ledger's file padding depends on import count, so the order test writes fixed bytes per file.
- Deliberate breaks left 4 of 31 surviving, all test gaps, now closed: separate's options checked
  together, the listing's cap at exactly 50, a row of the same file offered as alike, and a record
  differing only in description. The same-file test first passed without the check it claimed to
  test, because the rejected row shared no item with its twin. A lookalike file now joins them. A fifth survivor was a filter for parsed records that could never
  fire, and was removed. One break matched twice and did not apply, and was rerun with more context.

**Found while building M2.4:**

- A separation's two sides start in one transaction, which `decision_constraint`'s check refused.
  That table is referenced by nothing, so it was rebuilt directly. Dropping it fires none of its
  triggers, checked before writing the migration.
- The 0005 and 0006 migration tests migrated straight to the latest version, so they would have
  started testing 0007 too. They now stop at their own version.
- A kept group must be `same_event`: under whole-group withholding, a merge with one
  `different_event` pair inside it is withheld whole, so two records kept together would otherwise
  be separated as well.
- D-046's direct-link rule cannot apply to a separation, because two records sharing a reliable ID
  can differ in description. "Joined by this one automatic merge" replaces it.
- The first listing of separable transactions reloaded every constraint once per transaction. It
  now loads them once.
- A test injected a conflict on `MIN(transaction_id)`, which depended on generated ID order and
  failed at random. It now names the file.
- The first order test for separations found nothing valid: an earlier fixture fully covered by the
  merging exports joined their merge. The merging exports now have their own row.
- An ID-property test reached reliable-ID merges in 5 of 200 examples, because a repeated ID in one
  document is separated before matching. IDs are now a set per document: 102 of 200.
- Deliberate breaks left 7 of 50 surviving, all test gaps, now closed. One fix first relied on
  random IDs itself, and its catch was credited to another test. It was rewritten to separate,
  undo and separate again on the same records.
- A wording branch for a plain `stable` ID guarantee could never print, since no layout declares
  one, and was folded into one notice that names the stored guarantee.

**M2.7:** migration 0010, with append-only `record_resolution` and `record_resolution_event`.
`review complete` supplies what the parser could not read and makes the row a transaction, and
`review dismiss` states it adds none. Both close the item by removal, and `review resolution undo`
raises it again. A completed record never merges automatically, still blocks confident pairing in its
file by its completed values, and raises an external-ID item when it shares a reliable ID. A source
record is preferred over a completed one as primary. Tokens `r5`, `t3` and `d5` keep their digests,
and `u1` is new. `measure_reconciliation.py --resolved`. U1 to U19 pass, and S, C, P, N and V still
pass.

**Found while building M2.7:**

- Every transaction comes from a derivation group, so a completed row has to enter `derive()`. To keep
  typed values from authorizing a merge, it takes no part in reliable-ID matching or exact pairing.
- Its reliable ID would otherwise put it in a lane that never meets a record with the same ID, so
  the same event would count twice with no flag. A shared ID now raises an external-ID item.
- Reconcile assumed every record has an origin and a link. A record entering by completion gets its
  origin when first derived, and one leaving by undo loses its link without a link history row.
- Undoing a completion while any decision binding it is not undone, even a superseded one, would let
  a later undo restore a constraint on a record outside the ledger. So undo waits for both decisions
  and corrections that are not undone.
- The migration tests of 0008 and 0009 rebuild a ledger at the latest version and set it back. They
  now drop 0010's tables too, and the 0009 test migrates only to 9.
- The reason-explanation test only found reasons written as `return "..."`, so it would have missed
  the new reason constants. It now reads `REASON_* = "..."` too.
- `trace` printed descriptions as stored. A completed one is typed by a person, so it is escaped now.
- The benchmark's stop rule compared a resolution with a later import that merges nothing. An import
  making the same merges costs as much as a resolution, so the work was not stopped. Reported in
  D-050 and [status.md](../status.md).
- Deliberate breaks: 54 applied, with an unbroken control passing 320. One deleted a loop's only
  line, a syntax error rather than a catch, and was rerun with `pass`. 7 survived: 5 test gaps, now
  closed, 1 redundant scope step, removed, and 1 equivalent, since a completion only supplies values
  the parse lacks. The commit closing them, `9878d67`, says 6 survived and 4 were gaps, which is
  wrong. Every `u1` input but its views was noticed only by the pin, and they were removed. A final
  run of 49 on `9878d67` found the groups and items views each noticed only by the pin, since the items
  give the grouping, so the groups were removed in `6067cf3` and the `u1` breaks rerun there: all
  caught by `test_a_related_file_changes_it`.

**M2.8:** migration 0011, with append-only `coverage_declaration` and `coverage_declaration_event`.
`review coverage show`, `declare`, `history` and `undo`. Matching uses the declaration in effect,
else the claim at import, which stays unchanged. A document stating its own coverage can only have it
withdrawn. Chains follow D-048. Repeat imports compare with the coverage in effect. `documents` names
document IDs. Tokens `r6` and `t4` keep their digests, and `v1` and `k1` are new.
`measure_reconciliation.py --declared`. K1 to K17 pass, and S, C, P, N, V and U still pass.

**Found while building M2.8:**

- `review show` built each document's evidence from the claim alone. Its effective end and pending
  rule now follow the declaration, and the claim stays shown as stored.
- The `coverage_conflict` explanation said coverage was fixed at import and pointed at "M2". It now
  names `review coverage declare`, and its test was rewritten for that.
- A first `v1` passed a dataclass to `list()` and failed on every show. Reproducing it took a probe
  through `bin/pf` in a new `build/` folder, after the harness refused an `rm -rf` of the old one.
- The benchmark first reused a loop variable named like the result, and stopped before printing.
- The migration tests of 0008 to 0010 now drop 0011's tables too.
- Deliberate breaks: 32 applied, with an unbroken control passing 286. 29 caught, none only by a pin.
  3 survived: 2 test gaps, now closed, a chain of three and the evidence's effective end, and 1
  equivalent: leaving superseded declarations in the lookup gives the same result, because rows come
  back in insertion order and the newest is last. The filter stays.

**M2.9:** rules version 2, so every account is stale until `reconcile`. A pending and a posted row
sharing a reliable ID merge whatever their amount. Without an ID, a pending and a posted row alike but
for their amount raise a candidate with reason `pending_amount_changed`. Migration 0012 is the D-008
migration: `transaction_source` is rebuilt with a partial unique index exempting confirmed links, and
`review confirm` can join a same-document pending and posted pair. `totals` discloses changed amounts
and stale pending. `measure_reconciliation.py --pending`. Q1 to Q17 pass, and S, C, P, N, V, U and K
still pass.

**Found while building M2.9:**

- **A34, an accepted M1 criterion, changed.** It said a status conflict under one reliable ID is
  flagged. D-006 itself said "until M2", and D-052 makes such a pending and posted pair one event. The
  test and A34's wording now say it holds for dates. For the owner's review.
- The `d5` pin changed with the rules fingerprint it covers. Computing it under rules version 1 gave
  the old digest, so nothing else moved.
- Changed-amount discovery first compared every pending unit with every posted unit in its window:
  2,000 pairs took 35s, paid by every later import. It now looks posted units up by description and
  block (D-032), which is linear for distinct merchants and quadratic only in one block of alike
  descriptions.
- A reason-explanation test reads reason names from source text, and took `keys.add(("block", ...))`
  for a reason. The code was written as one set expression instead.
- New unit tests first passed an amount as `row()`'s third positional argument, which is the row
  number, so they compared equal amounts. Caught when they failed, and rewritten with keywords.
- Deliberate breaks: 27 applied, with an unbroken control passing 340. 18 caught by relevant tests, 2
  did not apply, and 7 survived, all test gaps, now closed. A rerun found the window and description
  checks of the pending link surviving, reachable only through a confirmation's direct-link check, and
  a test of a chain of three closed both. **The description break was twice credited with 279 and
  281 failures**: its replacement renamed a function, a bad break. Applied by hand it failed nothing
  relevant, and once fixed it was caught by the new test.

**M3.1:** migration 0013, with append-only `type_classification`, `type_classification_record` and
`type_classification_event`, and the derived `transaction_classification`. `review classify`,
`review classifications`, `review classification show` and `review classification undo`. Nine types
and `unclassified`, each type fitting one direction but `transfer`. A classification binds the records
of its transaction and shares D-049's effective-value rule and D-048's chains. `totals` lists each
type and the unclassified transactions below account movement, which no type changes. Tokens `r7`,
`t5`, `d6` and `c2` keep their digests without classifications, and `f1` is new.
`measure_reconciliation.py --classified`. F1 to F14 pass, and S, C, P, N, V, U, K and Q still pass.

**Found while building M3.1:**

- **D-053's direction rule and the receiving account.** On a card, loan or investment account a
  payment received is money in, which `card_payment`, `loan_payment` and `investment_contribution`
  refuse, so that side can only be a `transfer`. Built as approved, because it only refuses. For the
  owner's review, at the end of D-053.
- A correction can turn an amount's sign under a classification, and undoing a correction never
  refuses (D-049), so a fourth derived state, `against_direction`, leaves such a transaction
  unclassified and disclosed. `review correct` refuses to cause it.
- Undoing a completion would have left a classification binding a record outside the ledger, a
  `KeyError` on the next rewrite. It now waits for classifications too, as for corrections (D-050).
- The 0012 migration test populated a version 11 ledger through the import API, which now writes
  0013's table, so the fixture adds 0013's tables by hand. Its migration, and the older ones' tests,
  now stop at their own version or drop 0013's tables.
- The test helper did not know `review classification` takes `--db` third, so the first run of the
  new tests failed on argument parsing, not on the code.
- `pair_up`'s first transaction follows content hashes, which a new test assumed was `a.csv`. It
  now names the file.
- A schema test first passed on a primary-key clash, not the check it named. Each schema refusal
  now has a control insert that succeeds.
- The walk to the newest of a chain was copied three times, and is shared now.
- The walkthrough script first tried a direction refusal on a transaction already classified, and
  got the right refusal for that instead. The step was rewritten.
- Deliberate breaks: 62 applied, with an unbroken control passing 408. 50 caught, each by a relevant
  test, and 1 a syntax error, a bad break that removed a loop's only line. 12 survived: 7 test gaps,
  now closed, 3 immaterial inputs or redundant code, removed, 1 early return that only saved work,
  removed, and 1 equivalent, the amounts in `d6`'s views, which change only its digest since
  identical groups give identical amounts. The type in `f1` was noticed only by the pin and removed.
  A rerun of all 62 on `735e010`, control passing 414: 57 caught, each by a relevant test, 4 no longer
  applying to removed code, and the equivalent one surviving.

## Tests actually executed

| Check | Result |
|---|---|
| The suite at the start of the M3.1 session, `08e4225` | 1410 passed, exit code 0 |
| The suite gating each M3.1 commit, last at `735e010` | 1512 passed, exit code 0 |
| Targeted deliberate breaks, M3.1 | 62 breaks with an unbroken control passing (408 tests). 50 caught, 1 syntax error, 12 survived: 7 test gaps closed, 4 removed, 1 equivalent. Rerun on `735e010`, control passing 414: 57 caught, 4 did not apply to removed code, the equivalent one survived. Script and results in `build/m3.1-breaks/`, ignored and may not survive |
| `tests/scenarios/test_classifications.py` repeated 3 times | 75 passed each time, exit code 0, before the gap tests |
| Order test for classifications | Exhaustive: 60 cases, every valid point of every order of four files, all equal, with later records never bound |
| Migration 0013 on populated data | A decision, correction, completion and declaration kept, no account stale, atomic on failure |
| Walkthrough through `bin/pf`, ledger in `build/m3.1-walk` | Net -13.00 throughout. Purchase -30.00, refund 30.00, a cafe purchase -6.50, the bookshop superseded as a fee and undone back to a purchase. A refund on a purchase, an unknown type, a second classification without `--supersedes`, undoing a superseded classification and a correction against the type refused with exit code 2. Script and output in `build/m3.1-walk/` |
| Classification measurements | See [status.md](../status.md). Linear, and below a later import |
| Token pins | `r7-`, `t5-`, `d6-` and `c2-` read the digests pinned before M3.1. `f1-d981b70d43d9af68` is new |
| The suite gating each M2.9 commit, last at `9708bc6` | 1410 passed, exit code 0 |
| Targeted deliberate breaks, M2.9 | 27 breaks with an unbroken control passing (340 tests). 18 caught, 2 did not apply, 7 survived, all test gaps, closed. Reruns on `a2330ab` and `9708bc6`: all caught by relevant tests, after a bad break that renamed a function was fixed. Script and results in `build/m2.9-breaks/`, ignored and may not survive |
| Order test for pending and posted exports | Exhaustive: all 24 orders of four files, equal |
| Migration 0012 on populated data | Built from the first 11 migrations: every link kept, version 11 refuses the confirmed link 0012 allows, and a failure leaves version 11 |
| Walkthrough through `bin/pf`, ledger in `build/m2.9-walk` | Net -108.00, -151.50 after the cafe posted with a tip under its ID, -143.50 after confirming the bakery's pending and posted rows, -103.50 after confirming the garage's rows of one file, -143.50 after undoing that, which reopened its item. A same-document group of one row refused with exit code 2 |
| Pending measurements | See [status.md](../status.md). Linear for distinct merchants, quadratic in one block of alike descriptions |
| Rules and token pins | Rules fingerprint `e50fad61…` at version 2. `d5-ecb0f4cc0ef102ac`, checked to differ from `d5-2a1e1dd2ac99de82` only by the rules fingerprint |
| The suite gating each M2.8 commit | 1379 passed at `9b97453`, exit code 0. See the commit recording M2.8 for the last |
| Targeted deliberate breaks, M2.8 | 32 breaks with an unbroken control passing (286 tests): 29 caught, none only by a pin, 2 test gaps closed, 1 equivalent. Script and results in `build/m2.8-breaks/`, ignored and may not survive |
| Order test for declarations | Exhaustive: 60 cases, every valid point of every order of four files, all equal |
| Walkthrough through `bin/pf`, ledger in `build/m2.8-walk` | Net -31.00, -24.50 after declaring January complete, -15.50 after declaring both months, -24.50 and -31.00 after undoing each. A basis the layout lacks, an old `v1`, undoing a superseded declaration refused with exit code 2, and a repeat import with other coverage failed with exit code 1 |
| Declaration measurements | See [status.md](../status.md). A declaration costs no more than an import making the same merges |
| The suite gating each M2.7 commit, last at `6067cf3` | 1335 passed, exit code 0 |
| Targeted deliberate breaks, M2.7 | 54 breaks with an unbroken control passing (320 tests). 7 survived: 5 test gaps, now closed, 1 redundant step, removed, 1 equivalent. On `9878d67`, 49 breaks with the control passing 321: 48 caught and the equivalent one surviving. The `u1` breaks on `6067cf3`: all caught by a relevant test. Script and results in `build/m2.7-breaks/`, ignored and may not survive |
| Order test for resolutions | Exhaustive: 60 cases each for a dismissal and a completion, every valid point of every order of four files, all equal |
| Walkthrough through `bin/pf`, ledger in `build/m2.7-walk` | Net -13.00 blocked, -6.50 after dismissing, -10.75 after completing a row, -11.00 after correcting it, -10.75 and -6.50 after undoing both, -13.00 after undoing the dismissal. A value that was read, undoing a corrected completion and a stale `u1` token refused with exit code 2 |
| Resolution measurements | See [status.md](../status.md). A resolution costs what the merges it unblocks cost |
| Token pins | `r5-`, `t3-` and `d5-` read the digests pinned before M2.7. `u1-eef46741adfc3a9f` is new |
| `.venv/bin/python -m pytest -q` at the start of the M2.6 review session, `4aac5c3` | 1275 passed, exit code 0 |
| The same suite gating the commit recording M2.6's acceptance | 1275 passed, exit code 0 |
| The suite gating each M2.6 commit, last at `43d5748` | 1275 passed, exit code 0 |
| Targeted deliberate breaks, M2.6 | 34 breaks with an unbroken control passing (255 tests): 32 caught, each by a relevant test, 2 survived, both test gaps, now closed. 2 more were caught only by the `c1` pin, and their inputs were removed as immaterial. A rerun found 1 more survivor, a test gap, now closed, and 1 more input caught only by the pin, removed. On the final code, 33 breaks with the control passing 258: all caught. Script and results in `build/m2.6-breaks/`, ignored and may not survive |
| `tests/scenarios/test_corrections.py` repeated 3 times | 61 passed each time, exit code 0, before the 3 tests breaks added |
| Order test for corrections | Exhaustive: 60 cases, every valid point of every order of four files, all equal, with later records never bound |
| Walkthrough through `bin/pf`, ledger in `build/m2.6-walk2` | Net -6.50 merged, -13.00 separated, -11.00 with corrections of 6.00 and 5.00, -6.50 once undoing the separation made them disagree, disclosed on its own line, -6.00 after undoing the 5.00 one, and -6.50 after both. Stale `c1` and `t2` tokens refused with exit code 2 |
| Correction measurements | See [status.md](../status.md). A correction does not derive, and stays below a later import |
| Token pins | `r3-d41e2251fcd3a611`, `r3-74d05de08ff20c6b`, `r3-8f8c8b328e5b7256`, `t1-4ae2352458f9c44c` and `d3-2a1e1dd2ac99de82`, pinned before M2.6, now read `r4-`, `t2-` and `d4-` with the same digests. `c1-e2235f95e29f164e` is new |
| `.venv/bin/python -m pytest -q` at the start of the M2.5 review session, `ceb4f4a` | 1190 passed, exit code 0 |
| The same suite gating the commit recording M2.5's acceptance | 1190 passed, exit code 0 |
| The suite gating each M2.5 commit, last at `59b67ec` | 1190 passed, exit code 0 |
| Targeted deliberate breaks, M2.5 | 31 breaks with an unbroken control passing (379 tests). 25 caught, each by a relevant test, 5 survived and 1 did not apply. 4 survivors were test gaps, now closed, and 1 was a filter that could never fire, removed. On the final code, 30 breaks with the control passing 384: all caught, after the same-file test was given a lookalike so that both rows of one file share an item. Script and results in `build/m2.5-breaks/`, ignored and may not survive |
| The new scenario files repeated 3 times before the final commit | 47 passed each time, exit code 0 |
| Order test for superseding separations | Exhaustive, not a property test: 60 cases, every valid point of every order of four files, all equal |
| Walkthrough through `bin/pf`, ledger in `build/m2.5-walk` | Net movement -13.00, then -6.50 after confirming, -13.00 after a separation superseding it, -19.50 after a re-export listed as alike, and -13.00 after undoing the separation, which restored the confirmation. A stale undo token and undoing the superseded confirmation refused with exit code 2 |
| Superseding measurements | See [status.md](../status.md). A superseding separation costs what a partition costs |
| Token pins | `d2-2a1e1dd2ac99de82`, `t1-4ae2352458f9c44c` and `r3-74d05de08ff20c6b` computed on unchanged code before M2.5's changes. The first now reads `d3-` with the same digest, and the others are unchanged |
| `.venv/bin/python -m pytest -q` at the start of the M2.4 review session, `55c008f` | 1143 passed, exit code 0 |
| The suite gating each M2.4 commit, last at `54b6dc2` | 1143 passed, exit code 0 |
| Targeted deliberate breaks, M2.4 | 50 breaks with an unbroken control passing (320 tests). 43 caught, each by a relevant test, and 7 survived. No break failed to apply or caused a syntax error. After 7 new tests, the control passed 328 and all 7 were caught, one only after its test was made independent of ID order. Script and results in `build/m2.4-breaks/`, ignored and may not survive |
| The new scenario files repeated 3 times at `54b6dc2` | 83 passed each time, exit code 0 |
| Separation order property test, instrumented once | 100 examples compared, 12 discarded as invalid. About 6% of valid replays reached a conflict, so conflicts rely on the exhaustive test |
| ID merge property test, instrumented once | 102 of 200 examples reached a reliable-ID merge and 58 an exact pair |
| Item token before and after the shared loading code | `r3-d41e2251fcd3a611` at `3a765fe` and after, from a throwaway worktree in `build/`, since removed. Pinned by a test |
| Separation walkthrough through `bin/pf`, ledger in `build/m2.4-walk` | Totals 6.50, then 13.00 after separating three files into {a,b} and {c}, then 6.50 after undo. Stale token, an unnamed record and undoing twice refused with exit code 2 |
| Separation measurements | See [status.md](../status.md). A separation costs what a rejection or partition costs on the same group, plus the units it adds |
| `.venv/bin/python -m pytest -q` at the start of the M2.3 review session, `0d3b707` | 1063 passed, exit code 0 |
| `.venv/bin/python -m pytest` at the start of the M2.3 session, `673c025` | 970 passed, exit code 0 |
| The same suite gating each M2.3 commit, last at `f9baed0` | 1063 passed, exit code 0 |
| Targeted deliberate breaks, M2.3 | 62 breaks, all caught at `f9baed0`, each by a relevant test, with an unbroken control passing. The first run found 2 real bugs and 2 test gaps, removed 1 unreachable path and 2 immaterial token fields, and had 4 mislabelled breaks whose catch was credited to the wrong test. 2 breaks matched nothing after a code change and were corrected and rerun. Script and results in `build/m2.3-breaks/`, ignored and may not survive |
| Order property tests for confirmation, instrumented once | 100 examples compared, 45 discarded as invalid |
| Confirmation walkthrough through `bin/pf`, ledger in `build/m2.3-walk` | Totals 19.50, then 13.00 after a superseding confirmation, then 19.50 after undo, which restored the rejection. Stale token, contradiction and undoing a superseded decision refused with exit code 2 |
| Confirmation measurements | See [status.md](../status.md). A partition costs what a rejection costs, and a confirmation far less |
| `.venv/bin/python -m pytest` at the M2.2 code commit, `56e0adc`, gating that commit | 970 passed, exit code 0 |
| The same suite at the start of the M2.2 session, `1caeb52` | 816 passed, exit code 0 |
| Targeted deliberate breaks, M2.2 | 79 breaks, all caught on a final run at `56e0adc`, after closing 7 test gaps and removing 1 redundant check. An earlier run reported 4 false catches, because a flaky test failed at random and took the credit. Script and results in `build/m2.2-breaks/`, ignored and may not survive |
| `tests/scenarios` repeated 3 times at `56e0adc` | 431 passed each time, exit code 0 |
| `tests/scenarios/test_decisions.py` repeated 5 times, after removing an ID-order dependence | 86 passed each time |
| Order test, instrumented once | 150 examples actually compared, about 100 with differing orders or points. About 6% reached a conflict, so conflicts rely mainly on the exhaustive tests |
| README example through `bin/pf`, ledger in `build/` | Exit code 0. Inflows 2530.00, outflows 256.05, net 2273.95, 10 transactions |
| Partial rejection, conflict and undo walkthrough through `bin/pf`, ledger in `build/` | Totals 13.00, then 19.50, then 6.50 after undo. Stale tokens refused with exit code 2 |
| Dense constrained measurements | See [status.md](../status.md) |
| `.venv/bin/python -m pytest` at the M2.1 code commit, `eea61e4`, gating that commit | 816 passed, exit code 0 |
| Targeted deliberate breaks, M2.1 | 53 breaks, all caught on a final run, after closing 1 test gap and removing 1 unneeded sort key. Script and results in `build/m2.1-breaks/`, ignored and may not survive |
| `tests/scenarios` repeated 3 times at `eea61e4` | 317 passed each time |
| README flow with `review list` and `review show` through `bin/pf`, ledger in `build/` | Exit code 0, and 2 for an unknown item. Ledger file unchanged by both. Inflows 2530.00, outflows 256.05, net 2273.95, 10 transactions |
| `.venv/bin/python -m pytest` at the start of the M2 planning session, `643e1b1` | 712 passed, exit code 0 |
| Clean install at `6815e19`: fresh clone and environment, pinned dependencies, full suite | **712 passed**, exit code 0 |
| README example at `6815e19`, through `bin/pf` and through the installed `pf` | Exit code 0 for both, identical output apart from IDs and paths |
| Exit codes at `6815e19`, both entry points | 0, 1, 2 and 141 as documented |
| `.venv/bin/python -m pytest` at the final code commit, `c33b417` | 712 passed, exit code 0 |
| The same suite in a source checkout of `c33b417`, in a path with spaces | 712 passed, exit code 0 |
| `tests/scenarios` repeated 3 times at `c33b417` | 281 passed each time |
| Targeted deliberate breaks, slice 4 | 44 breaks, all caught on a final run, after closing 3 test gaps. Script and results in `build/slice4-breaks/`, ignored and may not survive |
| README example through `bin/pf` in zsh, commands extracted from the README | Exit code 0. Inflows 2530.00, outflows 256.05, net 2273.95, 10 transactions. Its `mktemp -d` line was replaced to stay in `build/` |
| The same README example in the source checkout, with a stdlib-only `.venv` | Exit code 0, same totals. Shows no installed package is needed at runtime |
| `.venv/bin/python -m pytest` at the slice 3 code commit, `dfe412f` | 651 passed |
| Targeted deliberate breaks, F1 | 2 breaks on the shared check, both caught |
| `.venv/bin/python -m pytest` at `143f57c` | 641 passed |
| `.venv/bin/python -m pytest` after the closeout, `34a81d1` | 640 passed |
| Scenario tests repeated 3 times after the closeout | 212 passed each time |
| Targeted deliberate breaks, closeout | 22 breaks, all caught, after closing 3 test gaps |
| `.venv/bin/python -m pytest` at the end of slice 3, before the closeout | 604 passed |
| Scenario tests repeated 5 times, before the closeout | 177 passed each time |
| A16, one-off runs of 3,000 examples of each generator | All passed. Focused run reached 1,650 exact merges and 700 boundary-date reasons, but only 1 split, which the exhaustive test covers |
| Deliberate breaks in a throwaway copy, slice 3 | 69 distinct breaks, all caught, after closing 8 test gaps and removing one rank term that could never decide anything |
| Reconciliation measurements | See [status.md](../status.md) |
| `.venv/bin/python -m pytest` at `c5c0991` | 411 passed |
| Scenario tests repeated 5 times, including concurrency | All passed (at 406 tests, before the last 5 were added) |
| Deliberate breaks in a throwaway copy, slice 1 | 26 distinct breaks, all caught after fixing two test gaps |
| Deliberate breaks in a throwaway copy, slice 2 | 50 distinct breaks, all caught after adding tests for three survivors |
| README example, re-run after slice 3 in zsh | Totals correct, with `trace` and `reconcile` also run |

The commands, versions and substitutions of the clean install are in
[m1-acceptance.md](../m1-acceptance.md). The `c33b417` source-checkout run above was not a clean
install: pytest came from the existing `.venv`, used read-only. Deliberate-break checks are not part of the suite, so repeat them for new
code. The slice 3 script and results are in `build/slice3-breaks/`, which is ignored and
may not survive.

## Fixed follow-ups

**F1. Marked current without primary-source metadata. Fixed in `dfe412f`.** Migration 0004
leaves a transaction merged before it with no primary source, while its marker still
matched. `stale_accounts` is now the single definition of current (D-033): the rules must
match and every live transaction must record its primary source. Accounts with no
transactions are never stale. No migration was needed. A repeat import or `reconcile`
catches up, and `totals` discloses the account until then.

**F4. Supersession chains revived a superseded decision. Found at the M2.4 review, fixed in `425c684`.**
In a chain A ← B ← C, where rejection A keeps X and Y apart, confirmation B joins them and supersedes
A, and confirmation C supersedes B keeping its `same_event` pair, `review decisions` listed A as
active once C was made. The ledger held X and Y together while A said they were different events,
and no conflict was raised. `decision_states` followed D-046's wording, under which a decision is
superseded only by an active one. Reproduced in `build/m2.5-probe/`. D-048 amends the rule.

## Boundary notes from slice 4

- The session's own lapses: at the start it read one memory file under `~/.claude` and wrote
  test output to the scratchpad. The first README run also left a synthetic ledger in the
  system temp folder, because `mktemp -d` ignored `TMPDIR` here. That folder was removed.
- Harness-managed, not the session's own action: one oversized source listing was saved
  under `~/.claude`.
- Unavoidable: the interpreter behind `.venv` and pytest's temp folders sit outside the
  repository.
- zsh has no `PIPESTATUS`, and an unquoted `--include=*.py` fails there. Capture exit codes
  by writing to a file and reading `$?`.

## M2.2 as built

Scope and acceptance tests are in [plan.md](../plan.md) (S1 to S23). Tests are in
`tests/scenarios/test_decisions.py`, `test_decision_order.py`, `test_decision_migration.py` and
`tests/unit/test_constraints.py`. Choices made where the rules left one are at the end of D-045,
and were accepted with M2.2.

**Known limits of M2.2:**

- Only `cross_document_candidates` items can be rejected. External-ID and same-document items stay
  open.
- With no confirm until M2.3, true duplicates stay open and counted. Two purchases in three exports
  with unknown coverage stay at 39.00 against a true 13.00, and rejection cannot fix that.
- Withholding can raise totals through new evidence, though it is disclosed.
- A decision does not transfer to a re-export, so overlapping re-exports can raise repeat reviews.
- Link recomputation is quadratic in the groups a constraint touches, and every later import of
  that account pays it. Measured in [status.md](../status.md).
- A decision conflict has no action of its own. The only response today is `review undo`.
- A stated pair already touched by a constraint is refused, even if a newer record in one
  transaction is unbound.
- No machine-made merge can be separated until M2.4.
- `same_event` is allowed by the schema and written by nothing in M2.2.

## M2.3 as built

Accepted as built by the owner on 2026-11-07, with these limits. Scope and acceptance tests are in
[plan.md](../plan.md) (C1 to C21), and the rules in D-046. Tests are
in `tests/scenarios/test_confirmations.py`, `test_confirmation_migration.py`,
`test_decision_order.py` and `tests/unit/test_constraints.py`. The benchmark is
`tests/benchmarks/measure_reconciliation.py --confirmed`.

**Known limits of M2.3:**

- External-ID and same-document items can be neither rejected nor confirmed.
- Two alike rows of one file are always separate transactions (D-008).
- Superseding needs an open item holding the transactions, replaces one decision at a time, and only
  by a confirmation. A confirmed grouping cannot be split except by undo.
- A conflict is settled only by confirming a partition of all its transactions in one decision.
- A decision does not transfer to a re-export, so overlapping re-exports can raise repeat reviews.
- A partition, like a rejection, makes every later import of the account recompute the touched group
  quadratically. A plain confirmation does not.
- `review decisions` says "1 pairs". The wording is unchanged from M2.2.

## M2.9 as built

Accepted as built by the owner on 2026-11-08, with these limits. Scope and acceptance tests are in [plan.md](../plan.md)
(Q1 to Q17), the rules and implementation choices in D-052. Tests are in
`tests/scenarios/test_pending_posted.py`, `test_pending_posted_order.py` and
`test_pending_posted_migration.py`, with rule tests in `tests/unit/test_cross_document.py` and
`test_constraints.py`. The benchmark is `measure_reconciliation.py --pending`.

**Known limits of M2.9:**

- Every account is stale after upgrading until `reconcile`.
- Without a reliable ID, a changed amount is only a candidate, and unalike descriptions still count
  twice with no flag. Many alike descriptions in one block make discovery quadratic.
- Within one document, only a D-021 flag, which needs equal amounts, lets a pending and a posted row
  be confirmed together, and only as single rows.
- Stale pending is a disclosure at a fixed 10 days. Nothing is removed or acted on.

## M2.8 as built

Accepted as built by the owner on 2026-11-08, with these limits. Scope and acceptance tests are in
[plan.md](../plan.md) (K1 to K17), the rules and implementation choices in D-051. Tests are in
`tests/scenarios/test_coverage_declarations.py`, `test_coverage_declaration_order.py` and
`test_coverage_declaration_migration.py`. The benchmark is `measure_reconciliation.py --declared`.

**Known limits of M2.8:**

- Only `complete` and `unknown` can be declared, one document at a time.
- Coverage a document's metadata states can only be withdrawn, never strengthened or narrowed.
- `v1` covers only the effective coverage, so declaring and undoing back to the same coverage gives
  the token it had.
- The README's runnable example has no overlapping files to show this, so the commands are in its
  reference section.

## M2.7 as built

Accepted as built by the owner on 2026-11-08, with these limits. Scope and acceptance tests are in
[plan.md](../plan.md) (U1 to U19), the rules and implementation choices in D-050. Tests are in
`tests/scenarios/test_resolutions.py`, `test_resolution_order.py` and `test_resolution_migration.py`.
The benchmark is `tests/benchmarks/measure_reconciliation.py --resolved`.

**Known limits of M2.7:**

- A completion supplies only what the parser could not read, never a status or an ID, and cannot
  clear a value. A row with an unreadable status keeps `unknown`.
- A resolution cannot be superseded: undo it, then resolve again. Undoing a completion waits for every
  decision and correction binding it that is not undone.
- A completed record never merges automatically, so an identical row elsewhere stays a possible
  duplicate until confirmed.
- Same-document checks run only at import, so a completed record is never flagged against rows of its
  own file.
- One record at a time.

## M3.4 as built

Built and accepted by the owner on 2026-11-08 as built, with no changes, including the
implementation choices and points for review in D-056. M3 closes with it. Scope and acceptance tests are in [plan.md](plan.md)
(T1 to T12), the rules, implementation choices and points for review in D-056. Tests are in
`tests/scenarios/test_income_and_spending.py`, with T11 in both import-order tests. The benchmark
is `measure_reconciliation.py --income`, in [benchmarks.md](benchmarks.md). 23 deliberate breaks:
19 caught by the test aimed at each rule, and 4 survivors closed by new tests and then caught.
Breaks and benchmark output are in `build/m3.4-breaks/` and `build/m3.4-bench/`.

**Known limits of M3.4, as accepted:**

- Income and spending count only what a person classified and confirmed. Unconfirmed transfer
  kinds and unclassified transactions are disclosed as a bound, never counted.
- No reporting periods, which stay in M4 with D-013.
- A loan payment is never split into principal and interest.
- Every write fails above 32,766 transactions bound by transfers, in M3.2 and M3.3 code, for review.

## M3.3 as built

Built and accepted by the owner on 2026-11-08 as built, with no changes, including the
implementation choices and points for review in D-055. Scope and acceptance tests are in
[plan.md](plan.md) (O1 to O14), and the rules in D-055. Tests are in
`tests/scenarios/test_one_sided_transfers.py`, `test_one_sided_transfer_order.py` and
`test_one_sided_transfer_migration.py`, with the token cases in `tests/unit/test_review_revision.py`.
The benchmark is `measure_reconciliation.py --one-sided`. The full suite on the last M3.3 code,
`88bd319`, passed 1721 tests with exit code 0, and again gating the commit recording this.
Breaks and benchmark output are in `build/m3.3-breaks/` and `build/m3.3-bench/`.

**Known limits of M3.3, as accepted:**

- Only a person states a one-sided transfer, naming a registered counterpart, one transaction at a
  time, and only on a transaction with a transfer kind applied.
- Coverage warnings are about one-sided transfers only. Warnings by reporting period wait for M3.4.
- Card payments stay out of spending only once M3.4 reports spending. M3.3 warns in `totals`.
- Fees netted into one side and transfers split over several transactions are not matched, and not
  planned.
- Every write rewrites every one-sided outcome, at a cost of one-sided transfers times equal
  opposite amounts in their counterparts.
- An import summary reports no unsettled matches or one-sided transfers. `totals` does.

## M3.2 as built

Built and accepted by the owner on 2026-11-08 as built, with no changes, including the plan itself,
the implementation choices and points for review in D-054. Scope and acceptance tests are in
[plan.md](../plan.md)
(X1 to X14), the rules, implementation choices and points for review in D-054. Tests are in
`tests/scenarios/test_transfers.py`, `test_transfer_order.py` and `test_transfer_migration.py`, and
the receiving-account direction in `test_classifications.py`. The benchmark is
`measure_reconciliation.py --transfers`. The full suite on the last M3.2 code, `7d62447`, passed 1625 tests with exit code 0, and again
on `f19bd1d` at the start of the review session. Breaks and benchmark output are in
`build/m3.2-breaks/` and `build/m3.2-bench/`.

**Known limits of M3.2:**

- Only a person matches, one pair at a time, and only a candidate, which needs a transfer-kind type
  stated on one side first. An unclassified transfer raises nothing.
- Matching does not classify the other side, so "By financial type" lists it as unclassified until
  classified.
- Exact offsetting amounts only. Fees apart from the principal, a transfer split over several
  transactions, and one-sided transfers wait for M3.3.
- A match binds the records of both transactions when made, and is never superseded. A match that
  stops applying is settled only by undo.
- An import summary does not report matches the import leaves unsettled. `totals` does.
- `totals` lists matched transfers beside account movement. It is not income or spending, which wait
  for M3.4.

The full list of limitations is in [status.md](../status.md).

## M3.1 as built

Built and accepted by the owner on 2026-11-08 as built, with no changes, including the implementation choices and points for review in D-053. Scope and acceptance tests are in [plan.md](../plan.md)
(F1 to F14), the rules, implementation choices and points for review in D-053. Tests are in
`tests/scenarios/test_classifications.py`, `test_classification_order.py` and
`test_classification_migration.py`. The benchmark is `measure_reconciliation.py --classified`.
The suite gating the last M3.1 commit, `735e010`, passed 1512 tests with exit code 0. Breaks,
walkthrough and benchmark output are in `build/m3.1-breaks/`, `build/m3.1-walk/` and
`build/m3.1-bench/`.

**Known limits of M3.1:**

- Only a person classifies, one transaction at a time. No layout or rule suggests a type (D-014).
- Each type but `transfer` fits one direction whatever the account, so a payment received on a card,
  loan or investment account can only be a `transfer`, and interest earned only `income`.
- A classification binds the records of its transaction when made. A re-export that does not merge
  is unclassified, and a split leaves every part unclassified.
- Disagreeing classifications, a changed basis, or a correction's undo turning the amount against
  the type leave the transaction unclassified, with no command but undo to settle it.
- A classified transaction can be superseded only while one classification applies there.
- `totals` lists types beside account movement. It is not income or spending: transfers are not
  matched across accounts until M3.2, and reports wait for M3.4.
- `transactions` does not show types. `review transaction show` and `review classifications` do.
- Lines read "1 transactions", as `review decisions` reads "1 pairs".

The full list of limitations is in [status.md](../status.md).

## M2.6 as built

Accepted as built by the owner on 2026-11-08, including the rules and implementation choices in
D-049, with these limits. Scope and acceptance tests are in [plan.md](../plan.md) (V1 to V18), the
rules and implementation choices in D-049. Tests are in `tests/scenarios/test_corrections.py`,
`test_correction_order.py` and `test_correction_migration.py`. The benchmark is
`tests/benchmarks/measure_reconciliation.py --corrected`.

**Known limits of M2.6:**

- Only amount, transaction date, posting date and description can be corrected. No value can be
  cleared, and unresolved records cannot be corrected (M2.7).
- A correction binds the records of its transaction when made. A re-export that does not merge is
  not corrected, and one made after a merge binds more records, so a later split gives it
  `basis_changed` where an earlier correction would not.
- An unsettled field has no command of its own: undo corrections until one applies.
- A correction of a transaction can be superseded only while it alone applies there.
- `review separate` cannot split the records a correction binds: undo the correction first.
- Every correction and reconcile rewrites the account's derived correction rows, linear in
  corrections.
- `transactions` now escapes descriptions. Other older displays print source descriptions as before.

## M2.5 as built

Accepted as built by the owner on 2026-11-08, including the rules and implementation choices in
D-048, with these limits. Scope and acceptance tests are in [plan.md](../plan.md) (N1 to N18), the
rules in D-048. Tests are in `tests/scenarios/test_supersession.py` and `test_chain_migration.py`.
The benchmark is `tests/benchmarks/measure_reconciliation.py --superseded`.

**Known limits of M2.5:**

- One decision is superseded at a time. A rejection supersedes nothing, and a separation supersedes
  only a confirmation, a separation included.
- No decision transfers to a new record. A re-export that does not merge is reviewed again, and the
  alike listing only helps. It lists records alike in every parsed value, so a re-export with a
  changed description or date is not listed.
- The listing names only decided records in the same item, and stops at 50.
- Superseding a confirmation by a separation is done from the transaction. A confirmed core is not
  listed by `review merges`, which lists automatic joins only. `review decision show` gives the
  transaction a confirmed pair is now in.
- Pair numbers for `--keep` are read from `review decision show`. A separation's follow record IDs.
- Migration 0008 makes every account holding a chain of two or more stale, whether or not its ledger
  differed, until `reconcile`.
- An order test covers superseding separations exhaustively for four files. There is no new
  property test.

## M2.4 as built

Accepted as built by the owner on 2026-11-07, including the rules and implementation choices in
D-047, with these limits. Scope and acceptance tests are in [plan.md](../plan.md) (P1 to P22), the
rules and the choices made where they left one in D-047. Tests are in
`tests/scenarios/test_separations.py`, `test_separation_migration.py`, `test_decision_order.py` and
`tests/unit/test_constraints.py`. The benchmark is `tests/benchmarks/measure_reconciliation.py
--separated`.

**Known limits of M2.4:**

- Every record of the transaction must be named, at most 50. A confirmed core cannot be split
  except by undoing its confirmation. Superseding a confirmation by a separation is M2.5.
- A transaction in an open decision conflict is refused, and settled through the conflict. That
  refusal and the post-derivation conflict check are tested by injecting a conflict, because
  reaching one through imports takes four documents and two layouts.
- A separation binds the records it names. A re-export is withheld and raised as a conflict, so
  overlapping exports can bring repeat reviews.
- A separation touches its candidate group as a partition does, so every later import recomputes
  that group quadratically, and each separated record adds a unit to it.
- Pair numbers of a separation follow record IDs. `--keep` numbers are read from
  `review decision show`, which lists every record pair, up to 1,225 for 50 records.
- A kept group of several records is counted in both the confirmed and the separated `totals`
  lines. Neither line says the counts are disjoint.
- The README's runnable example cannot show separation, because its fixtures never merge (F3). The
  commands are in its reference section only.

## Boundary notes from M2 planning and M2.1

- The planning session's own lapses, before it read this file: it read one memory file under
  `~/.claude`, and listed and searched the parent directory.
- Harness-managed, not the session's own action: oversized outputs were saved under `~/.claude`.
  They were not opened. Harness-managed artifacts are not permission to inspect external files.
- The owner restated the rule: start every command from this repository, do not read external
  memory, do not list or search parent or sibling directories, and do not write external
  scratchpad files. The narrow exception for synthetic pytest temporary artifacts stays.

## Boundary notes from M2.2

- The session's own lapses, before it read this file: it read one memory file under `~/.claude`,
  and listed the parent directory. Both were reported to the owner at the time.
- Harness-managed, not the session's own action: oversized outputs were saved under `~/.claude`,
  and background task output under the system temporary folder. They were not opened.
- Benchmark and break temporary files used `build/tmp`. pytest's own temporary folders stay under the
  documented exception.

## Boundary notes from the M2.2 review and M2.3 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index to
  the session's context, unasked. It was not acted on. One oversized output was saved under
  `~/.claude`, and was not opened.
- pytest and break temporary files used `build/tmp`.

- The M2.3 work stayed inside this repository. Benchmarks, breaks and the walkthrough used `build/`
  and `build/tmp`. Harness-managed background task output went to the system temporary folder and
  was not opened.

## Boundary notes from the M2.3 review session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index to
  the session's context, unasked. It was not acted on. Oversized outputs were saved under
  `~/.claude`. Two of them were the session's own reads of this repository's files and were read
  back. The rest were not opened.
- pytest temporary files used `build/tmp`.

## Boundary notes from the M2.4 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: background task output went to the system
  temporary folder and was not opened. Break results were read from `build/m2.4-breaks/` only.
  Oversized outputs saved under `~/.claude` were not opened.
- A walkthrough command that began with `rm -rf` of a `build/` folder was blocked by the harness's
  safety check, unrun. The folder did not exist, and the walkthrough used a new folder instead.
- Walkthroughs, breaks, the benchmark and a throwaway worktree used `build/`, with `TMPDIR` set to
  `build/tmp`. The worktree was removed with `git worktree remove`.

## Boundary notes from the M2.4 review session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index to
  the session's context, unasked. It was not acted on. One oversized output, the session's own read
  of this file, was saved under `~/.claude` and not opened. This file was read directly instead.
- pytest temporary files used `build/tmp`.

## Boundary notes from the M2.5 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: background task output went to the system temporary
  folder and was not opened. Break results were read from `build/m2.5-breaks/` only.
- Probes, breaks, the walkthrough and the benchmark used `build/`, with `TMPDIR` set to `build/tmp`.
  The break worktree was removed with `git worktree remove`.

## Boundary notes from the M2.5 review session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index and
  the parent folder's git status to the session's context, unasked, and started the shell in the
  parent folder. None of it was acted on. The session's first command changed into this repository.
- pytest temporary files used `build/tmp`.

## Boundary notes from the M2.6 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: background task output went to the system temporary
  folder and was not opened. Break results were read from `build/m2.6-breaks/` only.
- Breaks, the walkthrough and the benchmark used `build/`, with `TMPDIR` set to `build/tmp`. The break
  worktree was removed with `git worktree remove`.

## Boundary notes from the M2.6 review session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index and
  the parent folder's git status to the session's context, unasked, and started the shell in the
  parent folder. None of it was acted on. The session's first command changed into this repository.
  One oversized output, the session's own read of this file, was saved under `~/.claude` and read
  back.
- pytest temporary files used `build/tmp`.

## Boundary notes from the M3.2 review and M3.3 session

- `ebc2ab4`, which adds the one-sided order test and benchmark, was gated as `pytest ... | tail -1
  && git commit`, so the commit followed `tail`, not pytest: the pitfall the handoff names. Its
  output shows 69 passed, and every later gate, including the full suite, passed on that code, so
  nothing broken was committed. History is not rewritten.
- Commit 2's first full-suite gate failed on one test listing every ledger table. It was fixed, that
  test rerun alone, and the full gate rerun before committing `ead542c`.

## Boundary notes from the M3.1 review and M3.2 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index and
  the parent folder's git status to the session's context, unasked, and started the shell in the
  parent folder. None of it was acted on. Each command started in this repository. Background task
  output went to the system temporary folder and was not opened. Break results were read from
  `build/m3.2-breaks/` only.
- The breaks, benchmark and pytest temporary files used `build/`, with `TMPDIR` set to `build/tmp`.
- One commit, `1d1267d`, was gated through `pytest | tail`, so on `tail`'s exit code. The gate
  printed 407 passed, and the full suite had exit code 0 just before with nothing changed between.
  Every later commit was chained on pytest's own exit code.

## Boundary notes from the M3.1 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index and
  the parent folder's git status to the session's context, unasked, and started the shell in the
  parent folder. None of it was acted on. The session's first command changed into this repository.
  One oversized output, the session's own read of this file, was saved under `~/.claude` and not
  opened. This file was read directly instead. Background task output went to the system temporary
  folder and was not opened. Break results were read from `build/m3.1-breaks/` only.
- The walkthrough, breaks and benchmark used `build/`, with `TMPDIR` set to `build/tmp`. The break
  worktree was created and removed with `git worktree`.
- One commit, `dadf4ad`, was made in a command after its gating suite rather than chained to it. The
  suite had exit code 0 and nothing changed between them. Every later commit was chained.

## Boundary notes from the M2.7 to M2.9 review

- The owner accepted all three with "I approve", taken as acceptance of the slices only. It was not
  taken as approval to push, which stays separate.
- pytest temporary files used `build/tmp`.

## Boundary notes from the M2.9 work

- As for M2.7. Break worktrees were created and removed with `git worktree`, one with `--force` after
  a hand-applied break. A throwaway check of the `d5` digest is in `build/m2.9-check/`.

## Boundary notes from the M2.8 work

- As for M2.7. The harness's safety check refused one `rm -rf` of a `build/` probe folder's contents.
  Nothing was removed, and a new folder was used instead. The empty `build/m2.8-probe/` is left for
  the owner to remove if wanted.

## Boundary notes from the M2.7 session

- The session read nothing outside this repository, and listed no parent or sibling directory.
- Harness-managed, not the session's own action: the harness attached a user-level memory index and
  the parent folder's git status to the session's context, unasked, and started the shell in the
  parent folder. None of it was acted on. Background task output went to the system temporary
  folder and was not opened. Break results were read from `build/m2.7-breaks/` only.
- Breaks, the walkthrough and the benchmark used `build/`, with `TMPDIR` set to `build/tmp`. The break
  worktree was removed with `git worktree remove`.

## Recommended M2 scope

See "M2 plan" in [plan.md](../plan.md). M2.5 to M2.9 are provisional, and each needs approval.
Still open: whether grouped review of long runs
belongs in M2, and F2's stored marker if any new command shows legacy creation timestamps.


## Where each slice starts in git

Run `git log -1`: the commit recording this handoff. M3.4's acceptance and M3's close are recorded after `7248d20`, which records M3.4 as built. M3.4 starts after `288fb32`, which records D-056's approval. M3.3's acceptance and D-056 are recorded after `c85c099`, which records M3.3 as built. M3.3 starts after `6bd89a5`, which records D-055's approval, itself after `37882b5`, which records M3.2's acceptance and proposes D-055. M3.2's acceptance is recorded after `f19bd1d`. M3.2 starts after `0a08cd5`, which proposes D-054, itself after `dd961a4`, which records M3.1's acceptance. M3.1 starts after `c25913f`, which records D-053's approval, itself after `08e4225`, which proposed it. M2.6's acceptance is recorded after `4aac5c3`. M2.6 starts after `8384fb6`, which records its plan's approval, itself after `0032c9c`, which records M2.5's acceptance. M2.5 starts after `d1feb30`, which records its plan's approval, itself after `7551e18`, which records M2.4's acceptance. M2.4 starts after `97f7296`, which records M2.3's acceptance. M2.3 starts after `66ecb06`, which records M2.2's acceptance. M2.2 starts after `1caeb52`, and M2.1 after `643e1b1`. In M1, slice 3 starts after `66fda56` and slice 4 after `cda368a`

## Remote state, in full

**Remote state.** The owner intentionally pushed `feature/m1-foundation` twice: `c75aee0` (end
of slice 1) on 2026-11-05, which set upstream tracking, and `643e1b1` (all of M1) on 2026-11-06
at 00:27:10. The owner confirmed that the second push was theirs and intentional, and no
investigation is needed. The 43 commits it added hold code, documentation and the three
synthetic fixture CSVs.

The owner pushed `feature/m2-review` themselves, and reported at the M2.3 review that they did so
after M2.3. The only push recorded in this clone is of `673c025`, the M2.2 handoff commit, on
2026-11-07 at 15:48:44 -0500, which set upstream tracking. This clone's ref is therefore 8 commits
behind `0d3b707`, which does not show an M2.3 push. A push from another clone would not appear here.
Nothing was investigated and nothing was pushed from here. **Unverified:** the remote's live state
and the repository's visibility, because GitHub was not contacted. Local tracking refs only record
what was last pushed from here.

## Known limitations

- Only two invented layouts exist. It must not be used with real financial data.
- Only a person classifies, one transaction at a time, and a payment received on a card, loan or
  investment account can only be a `transfer`. See "Known limits of M3.1".
- Coverage cannot be changed after import (M2.8, provisional).
- Only candidate pairs can be rejected, and only candidate items and conflicts confirmed. See
  "Known limits of M2.3".
- A separation names every record of one transaction, and splits a confirmed core only by
  superseding its confirmation. See "Known limits of M2.5".
- A pending and a posted row with different amounts and no ID are raised for review if their
  descriptions are alike, and count twice with no flag if not (D-052).
- The revision covers only inputs that exist today (D-040). Corrections joined it in M2.6. Corrected
  coverage must join it later.
- Corrections cover amount, dates and description only, and disagreeing ones use the source value
  until undone. See "Known limits of M2.6".
- Group recomputation is quadratic in a touched group. See [status.md](../status.md).
- Similarity has documented misses and false positives (D-032).
- Identity timestamps from before migration 0004 can be fallback values (F2).
- A39 acceptance covers the documented fixtures only, in which nothing merges (F3).
- Reconciliation cost is quadratic in fully overlapping files and in distinct spellings
  per block. See [status.md](../status.md).
- The original file is not kept (M5). The database is not encrypted (M5).
- Setup is verified on this Mac and Python 3.12.6 only. Dependency pins have no hashes.
- A file's summary counts are as of its import. Only the run and account lines are final.
- The full list is in [status.md](../status.md).

## M6 slices

M6 is D-059, complete on 2026-11-09.

| Slice | Commit | Layouts | Breaks |
|---|---|---|---|
| D-059 | `64a4791` | The plan, J1 to J8 | |
| M6.1 | `729e44b` | `capital_one_card_v1`, `capital_one_bank_v1` | 18 applied, 18 caught |
| M6.2 | `15f5958` | `us_bank_v1`, and a fix to `capital_one_bank_v1` | 13 applied, 13 caught |
| M6.3 | `8e70069` | `amex_card_v1` | 8 applied, 8 caught |
| M6.4 | `3c19a70` | `bfsfcu_v1`, and one shared Debit/Credit agreement rule | 14 applied, 14 caught |

## M7 slices

M7 is D-060, complete on 2026-11-09.

| Slice | Commit | What | Breaks |
|---|---|---|---|
| D-060 | `b78ab14` | The M7 plan, D1 to D14 and I1 to I11 | |
| M7.1 | `9a9eafe` | pypdf, fenced from running `jbig2dec`, and `pf pdf text` | 13 on the final code, all caught, and 3 on the logging fence |
| D-061 | `7e4f506` | Capital One bank: format confirmed, account number checked | 7 applied, 7 caught |
| M7.2 | `2626591` | `us_bank_card_activity_pdf_v1` | 16 applied, 13 caught, 2 dead code deleted, 1 gap closed |
| M7.3 | `2665756` | CSV and PDF counting once, on D-006 unchanged | 8 applied, 6 caught here, 2 equivalent here and caught by unit tests |

**Not built:** M7.4, since the printout holds one card and each entry names it. M7.5, since the
owner holds no Capital One card PDF. No U.S. Bank card CSV layout, since the owner holds no such
export: `us_bank_v1` is not that card's format.

## M8 slices

M8 is D-062, complete on 2026-11-09, verified by the owner in a browser.

| Slice | Commit | What | Breaks |
|---|---|---|---|
| D-062 | `c530b8c` | The M8 plan, UA1 to UD4 | |
| M8.1 | `6bf46c2` | One builder per report in `reports/report_text.py`, the CLI printing its lines | 13 applied, 13 caught, 1 gap closed |
| M8.2 | `b31b2a1` | `pf ui` on 127.0.0.1, its protections, totals and monthly pages | 27 applied, 24 caught, 3 gaps closed |
| M8.3 | `719f89f` | Import results, transactions, review queue and item pages | 12 applied, 11 caught, 1 gap closed |

## M5 commits, moved from the handoff on 2026-11-09

M5.1 is `0f01eaa`, M5.2 `46c6d20`, its second amendment `c314c21`, M5.3 `67d2457`, its acceptance
`c8bdb4a`, point 7's amendment `fc76cd2`, M5.4 `5e6e05e`, its docs `7a0d446`, M5.5 `4548b12`, its
docs `df53e65`, and M5's acceptance the commit after it.
