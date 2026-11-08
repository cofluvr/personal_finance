# Session Handoff: M2.6 Awaiting Review

For a fresh session. Written 2026-11-08. **M1 is complete and accepted**, and its limitations and
deferred benchmarks still stand. See [m1-acceptance.md](m1-acceptance.md).

**M2.1, M2.2, M2.3, M2.4 and M2.5 are accepted.** The owner accepted M2.2 as built on 2026-11-07, including
the choices at the end of D-045, with no changes. The owner accepted M2.3 as built on 2026-11-07,
including the rules and limits recorded in D-046 and "M2.3 as built" below, with no changes. The owner
accepted M2.4 as built on 2026-11-07, including the rules and implementation choices recorded in
D-047 and the limits in "M2.4 as built" below, with no changes. The owner accepted M2.5 as built on
2026-11-08, including the rules and implementation choices recorded in D-048 and the limits in
"M2.5 as built" below, with no changes. The owner approved the M2.6 plan on 2026-11-08, taking every
recommendation in it (D-049). **M2.6 is implemented and awaits the owner's review. Do not start
M2.7.** M2.7 to M2.9 are provisional, and each needs its own approval. M2.1's decisions are D-040 and
D-041, M2.2's rules are D-042 to D-045, with D-045 overriding the others where they differ, M2.3's are
D-046, M2.4's are D-047, M2.5's are D-048, and M2.6's are D-049.

## Working principles

Given by the owner on 2026-11-08, for the entirety of the project:

1. Don't build it until you need it.
2. Extract patterns after the second duplication, not before.
3. Explicit errors beat silent failures: fail fast.
4. Write the obvious solution, and optimize only if needed.
5. Delete aggressively: less code means fewer bugs.
6. Name variables, parameters and API endpoints semantically, with verbose, self-documenting names
   that optimize for comprehension by both humans and LLMs, not brevity.

Much existing code uses short names such as `held`, `bound` and `rows`. Principle 6 applies to new
and changed code. Renaming existing code wholesale is a separate change for the owner to approve.

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `feature/m2-review`, created from `643e1b1`. Tracks `origin/feature/m2-review`. See "Remote state" |
| Latest commit | Run `git log -1`: the commit recording this handoff. M2.6 starts after `8384fb6`, which records its plan's approval, itself after `0032c9c`, which records M2.5's acceptance. M2.5 starts after `d1feb30`, which records its plan's approval, itself after `7551e18`, which records M2.4's acceptance. M2.4 starts after `97f7296`, which records M2.3's acceptance. M2.3 starts after `66ecb06`, which records M2.2's acceptance. M2.2 starts after `1caeb52`, and M2.1 after `643e1b1`. In M1, slice 3 starts after `66fda56` and slice 4 after `cda368a` |
| Python | 3.12.6, project `.venv` already present |
| Runtime dependencies | None |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Entry point | `bin/pf`, using this checkout's `.venv`. An installed `pf` script also works |
| Data | Synthetic only. Keep databases outside the repository |

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

Read first: this file, [decisions.md](decisions.md), [plan.md](plan.md),
[layouts.md](layouts.md), [status.md](status.md), [m1-acceptance.md](m1-acceptance.md).
Then the code in
`src/personal_finance/ingest/pipeline.py`, `reconcile/cross_document.py`,
`reconcile/apply.py`, `reconcile/decisions.py`, `reports/review_evidence.py`,
`reports/decision_evidence.py`, `reconcile/correction_effects.py`, `reconcile/corrections.py`,
`reports/correction_evidence.py` and `db/migrations/`.

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

## Tests actually executed

| Check | Result |
|---|---|
| The suite gating each M2.6 commit, last at `43d5748` | 1275 passed, exit code 0 |
| Targeted deliberate breaks, M2.6 | 34 breaks with an unbroken control passing (255 tests): 32 caught, each by a relevant test, 2 survived, both test gaps, now closed. 2 more were caught only by the `c1` pin, and their inputs were removed as immaterial. A rerun found 1 more survivor, a test gap, now closed, and 1 more input caught only by the pin, removed. On the final code, 33 breaks with the control passing 258: all caught. Script and results in `build/m2.6-breaks/`, ignored and may not survive |
| `tests/scenarios/test_corrections.py` repeated 3 times | 61 passed each time, exit code 0, before the 3 tests breaks added |
| Order test for corrections | Exhaustive: 60 cases, every valid point of every order of four files, all equal, with later records never bound |
| Walkthrough through `bin/pf`, ledger in `build/m2.6-walk2` | Net -6.50 merged, -13.00 separated, -11.00 with corrections of 6.00 and 5.00, -6.50 once undoing the separation made them disagree, disclosed on its own line, -6.00 after undoing the 5.00 one, and -6.50 after both. Stale `c1` and `t2` tokens refused with exit code 2 |
| Correction measurements | See [status.md](status.md). A correction does not derive, and stays below a later import |
| Token pins | `r3-d41e2251fcd3a611`, `r3-74d05de08ff20c6b`, `r3-8f8c8b328e5b7256`, `t1-4ae2352458f9c44c` and `d3-2a1e1dd2ac99de82`, pinned before M2.6, now read `r4-`, `t2-` and `d4-` with the same digests. `c1-e2235f95e29f164e` is new |
| `.venv/bin/python -m pytest -q` at the start of the M2.5 review session, `ceb4f4a` | 1190 passed, exit code 0 |
| The same suite gating the commit recording M2.5's acceptance | 1190 passed, exit code 0 |
| The suite gating each M2.5 commit, last at `59b67ec` | 1190 passed, exit code 0 |
| Targeted deliberate breaks, M2.5 | 31 breaks with an unbroken control passing (379 tests). 25 caught, each by a relevant test, 5 survived and 1 did not apply. 4 survivors were test gaps, now closed, and 1 was a filter that could never fire, removed. On the final code, 30 breaks with the control passing 384: all caught, after the same-file test was given a lookalike so that both rows of one file share an item. Script and results in `build/m2.5-breaks/`, ignored and may not survive |
| The new scenario files repeated 3 times before the final commit | 47 passed each time, exit code 0 |
| Order test for superseding separations | Exhaustive, not a property test: 60 cases, every valid point of every order of four files, all equal |
| Walkthrough through `bin/pf`, ledger in `build/m2.5-walk` | Net movement -13.00, then -6.50 after confirming, -13.00 after a separation superseding it, -19.50 after a re-export listed as alike, and -13.00 after undoing the separation, which restored the confirmation. A stale undo token and undoing the superseded confirmation refused with exit code 2 |
| Superseding measurements | See [status.md](status.md). A superseding separation costs what a partition costs |
| Token pins | `d2-2a1e1dd2ac99de82`, `t1-4ae2352458f9c44c` and `r3-74d05de08ff20c6b` computed on unchanged code before M2.5's changes. The first now reads `d3-` with the same digest, and the others are unchanged |
| `.venv/bin/python -m pytest -q` at the start of the M2.4 review session, `55c008f` | 1143 passed, exit code 0 |
| The suite gating each M2.4 commit, last at `54b6dc2` | 1143 passed, exit code 0 |
| Targeted deliberate breaks, M2.4 | 50 breaks with an unbroken control passing (320 tests). 43 caught, each by a relevant test, and 7 survived. No break failed to apply or caused a syntax error. After 7 new tests, the control passed 328 and all 7 were caught, one only after its test was made independent of ID order. Script and results in `build/m2.4-breaks/`, ignored and may not survive |
| The new scenario files repeated 3 times at `54b6dc2` | 83 passed each time, exit code 0 |
| Separation order property test, instrumented once | 100 examples compared, 12 discarded as invalid. About 6% of valid replays reached a conflict, so conflicts rely on the exhaustive test |
| ID merge property test, instrumented once | 102 of 200 examples reached a reliable-ID merge and 58 an exact pair |
| Item token before and after the shared loading code | `r3-d41e2251fcd3a611` at `3a765fe` and after, from a throwaway worktree in `build/`, since removed. Pinned by a test |
| Separation walkthrough through `bin/pf`, ledger in `build/m2.4-walk` | Totals 6.50, then 13.00 after separating three files into {a,b} and {c}, then 6.50 after undo. Stale token, an unnamed record and undoing twice refused with exit code 2 |
| Separation measurements | See [status.md](status.md). A separation costs what a rejection or partition costs on the same group, plus the units it adds |
| `.venv/bin/python -m pytest -q` at the start of the M2.3 review session, `0d3b707` | 1063 passed, exit code 0 |
| `.venv/bin/python -m pytest` at the start of the M2.3 session, `673c025` | 970 passed, exit code 0 |
| The same suite gating each M2.3 commit, last at `f9baed0` | 1063 passed, exit code 0 |
| Targeted deliberate breaks, M2.3 | 62 breaks, all caught at `f9baed0`, each by a relevant test, with an unbroken control passing. The first run found 2 real bugs and 2 test gaps, removed 1 unreachable path and 2 immaterial token fields, and had 4 mislabelled breaks whose catch was credited to the wrong test. 2 breaks matched nothing after a code change and were corrected and rerun. Script and results in `build/m2.3-breaks/`, ignored and may not survive |
| Order property tests for confirmation, instrumented once | 100 examples compared, 45 discarded as invalid |
| Confirmation walkthrough through `bin/pf`, ledger in `build/m2.3-walk` | Totals 19.50, then 13.00 after a superseding confirmation, then 19.50 after undo, which restored the rejection. Stale token, contradiction and undoing a superseded decision refused with exit code 2 |
| Confirmation measurements | See [status.md](status.md). A partition costs what a rejection costs, and a confirmation far less |
| `.venv/bin/python -m pytest` at the M2.2 code commit, `56e0adc`, gating that commit | 970 passed, exit code 0 |
| The same suite at the start of the M2.2 session, `1caeb52` | 816 passed, exit code 0 |
| Targeted deliberate breaks, M2.2 | 79 breaks, all caught on a final run at `56e0adc`, after closing 7 test gaps and removing 1 redundant check. An earlier run reported 4 false catches, because a flaky test failed at random and took the credit. Script and results in `build/m2.2-breaks/`, ignored and may not survive |
| `tests/scenarios` repeated 3 times at `56e0adc` | 431 passed each time, exit code 0 |
| `tests/scenarios/test_decisions.py` repeated 5 times, after removing an ID-order dependence | 86 passed each time |
| Order test, instrumented once | 150 examples actually compared, about 100 with differing orders or points. About 6% reached a conflict, so conflicts rely mainly on the exhaustive tests |
| README example through `bin/pf`, ledger in `build/` | Exit code 0. Inflows 2530.00, outflows 256.05, net 2273.95, 10 transactions |
| Partial rejection, conflict and undo walkthrough through `bin/pf`, ledger in `build/` | Totals 13.00, then 19.50, then 6.50 after undo. Stale tokens refused with exit code 2 |
| Dense constrained measurements | See [status.md](status.md) |
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
| Reconciliation measurements | See [status.md](status.md) |
| `.venv/bin/python -m pytest` at `c5c0991` | 411 passed |
| Scenario tests repeated 5 times, including concurrency | All passed (at 406 tests, before the last 5 were added) |
| Deliberate breaks in a throwaway copy, slice 1 | 26 distinct breaks, all caught after fixing two test gaps |
| Deliberate breaks in a throwaway copy, slice 2 | 50 distinct breaks, all caught after adding tests for three survivors |
| README example, re-run after slice 3 in zsh | Totals correct, with `trace` and `reconcile` also run |

The commands, versions and substitutions of the clean install are in
[m1-acceptance.md](m1-acceptance.md). The `c33b417` source-checkout run above was not a clean
install: pytest came from the existing `.venv`, used read-only. Deliberate-break checks are not part of the suite, so repeat them for new
code. The slice 3 script and results are in `build/slice3-breaks/`, which is ignored and
may not survive.

## Known limitations

- Only two invented layouts exist. It must not be used with real financial data.
- Coverage cannot be changed after import (M2.8, provisional).
- Only candidate pairs can be rejected, and only candidate items and conflicts confirmed. See
  "Known limits of M2.3".
- A separation names every record of one transaction, and splits a confirmed core only by
  superseding its confirmation. See "Known limits of M2.5".
- A pending and a posted row with different amounts and no ID count twice with no flag.
- The revision covers only inputs that exist today (D-040). Corrections joined it in M2.6. Corrected
  coverage must join it later.
- Corrections cover amount, dates and description only, and disagreeing ones use the source value
  until undone. See "Known limits of M2.6".
- Group recomputation is quadratic in a touched group. See [status.md](status.md).
- Similarity has documented misses and false positives (D-032).
- Identity timestamps from before migration 0004 can be fallback values (F2).
- A39 acceptance covers the documented fixtures only, in which nothing merges (F3).
- Reconciliation cost is quadratic in fully overlapping files and in distinct spellings
  per block. See [status.md](status.md).
- The original file is not kept (M5). The database is not encrypted (M5).
- Setup is verified on this Mac and Python 3.12.6 only. Dependency pins have no hashes.
- A file's summary counts are as of its import. Only the run and account lines are final.
- The full list is in [status.md](status.md).

## Approved decisions

| Decision | Rule | Log |
|---|---|---|
| Coverage correction | Limitation stays until M2. A conflict changes nothing and explains itself. Never recommend deleting the database or editing SQL | D-022 |
| Inclusive end date | A user declaration vouches for the whole end date when generation metadata is absent, under the layout's pending definition. Never assumed for a date range in metadata | D-007 |
| Coverage evidence | Keep user confirmation, validated layout metadata, a non-establishing date range, and unknown or partial coverage distinct | D-005 |
| Coverage versus extraction | Complete coverage does not mean every row parsed. Disclosures stay, and no identities are manufactured | D-024 |
| File and account | A byte-identical file under another account is rejected, never skipped. Existing import preserved. **Verified and tested** | D-022 |
| Candidates | Only plausible candidates enter review. No exact adjustment for ambiguous groups | D-006 |
| One record per document | An initial safeguard, not proof | D-008 |
| Decisions and corrections | Use stable internal IDs. Fingerprints are evidence only | D-009 |
| Transfers (M3) | Suspected transfers never increase safe-to-spend | D-011 |
| Totals wording | Account inflows, account outflows, net account movement | D-010 |
| Repository | Do not move it. Real data needs the M5 gate first | D-019 |
| Security proposal | **Unapplied.** Unverified, and not active protection | D-025 |
| External-ID matching | Validated and account-scoped. A differing description alone does not conflict for a reliable ID, and both are preserved. Conflicts in amount, status or a date present on both records are flagged | D-006 |
| Single-day overlap | ID-less matches stay possible duplicates, including under `user_declared` coverage. An intentional conservative policy, not a mathematical requirement. Does not override a confident reliable-ID match | D-007 |
| Candidate discovery | Needs evidence beyond amount and date: similar merchant or description, a validated identifier, or a documented source-specific relationship. Different descriptions alone are not evidence. The date window is a configurable heuristic. Candidates create review items and never authorize a merge | D-006 |
| Unknown status | Does not conflict with `posted`, for status comparison only. Does not establish identity, and is never filled in as `posted` | D-006 |
| Test-only layout | A synthetic layout with unreliable IDs is allowed in tests for A21. It is not a production layout | [layouts.md](layouts.md) |
| Unresolved rows | Exact matches stay possible duplicates when an unresolved row could plausibly affect the count. Reliable ID matches are not affected | D-024 |
| Identifier guarantees | Stored per document, never reread from Python. The `synthetic_checking_v1` clarification is one-time and synthetic-only | D-026 |
| Metadata coverage | A separate effective interval, with the claimed interval preserved | D-027 |
| Single-day policy | ID-less matching only | D-028 |
| Source movement | Machine-made merges can split. Every record preserved, history append-only, M2 decisions take precedence | D-029 |
| Displayed values | One primary source, no field mixing | D-030 |
| Candidate grouping | Connected groups, bounded by fixed calendar blocks, counted as distinct transactions | D-031 |
| Similarity | Candidate evidence only, with known limits | D-032 |
| Rule versions | Fingerprint of the effective configuration per account | D-033 |
| Performance | Provisional benchmarks for the documented fixtures only. Current locking stays. Not test assertions | D-034 |
| Migration | Explicit, and separate from reconciliation. Read commands stay read-only | D-035 |
| Summary units | Files and source rows are the only partitions. Records accepted are never called transactions created. Account review totals are final state, never sums of per-file snapshots. "Review groups", not "flags" | D-036 |
| Failed files | Row counts are unavailable, or known but rolled back. Never zero, never counted as stored | D-036 |
| Logging | None in M1. The boundary prints a fixed message with exit code 2. Cancellation and a closed pipe are not errors. No dumps on disk | D-037 |
| Entry point | `bin/pf` is verified. `project.scripts` is declared only. A shared-environment clone is a source-checkout check, not a clean install | D-038 |
| Temporary files | pytest temp folders are allowed for synthetic artifacts. Walkthroughs, clones and breaks use `build/` | D-039 |
| Review evidence | `review show` displays data for the one item requested, under `trace`'s terms. Routine output and errors stay clean. Six kinds of evidence stay separate, and missing stays missing | D-037, D-040 |
| Revision token | All material evidence, not membership alone. Deterministic and documented. New inputs join it when they exist, with a version bump | D-040 |
| Later M2 requirements | Corrections and coverage conflicts stay distinguishable. Several overrides on one transaction need a defined effective value | D-041 |
| Rejection | A pair-level assertion. No "reject group", and never an implied "all distinct". Binds source records. Shares one model with confirmation | D-042 |
| Whole-group withholding | An automatic group containing a constrained pair is withheld entirely, with its records separate and counted | D-042 |
| Decision commands | Current account, then account, item ID and token together, under one write lock. Never reconciles for the user. Undo needs the same | D-043 |
| Decision conflicts | Their own `decision_conflict` kind, disclosed on their own line | D-044 |
| Closing an item | By removal. The decision stays in history, and undo can raise a new item | D-045 |
| Rejectable pairs | Direct, undecided candidates only, not two transactions merely sharing a group | D-045 |
| Rejection and the ledger | Must change no totals or memberships, or it refuses atomically | D-045 |
| Undo token | Decision state and everything relevant to regrouping. Undo is never a snapshot restore | D-045 |
| Confirmation | An explicit partition: same within a group, different between groups, nothing about the rest | D-046 |
| A confirmed group | Direct links, one record per document, no two unique IDs, at most 50 transactions | D-046 |
| Confirmed units | Survive new evidence. An automatic merge joins only when valid, else it is withheld | D-046 |
| Settling a conflict | Only by one confirmation's partition. A rejection never settles one | D-046 |
| Superseding | One decision, by a confirmation, naming its token. Every old pair contradicted or kept. Undo restores it or refuses | D-046 |
| Separation | A partition of every record of one transaction, stored as a confirmation targeting it. Groups of several records become confirmed units | D-047 |
| What can be separated | Records joined automatically, including those a confirmed unit absorbed. Not a confirmed core, one record, or a transaction in an open conflict | D-047 |
| Separation and the ledger | May raise totals. Changes only that transaction, raises no conflict, or refuses atomically | D-047 |
| Transaction token | `t1`, over one transaction's material evidence. Item `r3` and undo `d2` unchanged | D-047 |
| Superseding chains | Superseded while anything superseding it is not undone. Only the newest applies and can be undone, one link at a time. 0008 re-derives chain accounts | D-048 |
| New evidence | No decision transfers to a new record. `review show` lists records alike a decided record, binding nothing | D-048 |
| What supersedes what | A confirmation joins apart pairs, a separation splits a confirmation's pairs, a rejection supersedes nothing. One at a time | D-048 |
| Undo token | `d3`, the same fields, so a ledger without chains keeps its digest | D-048 |
| Corrections | Amount, dates and description. Stored apart, applied after derivation, never read by matching. Bind the records of their transaction | D-049 |
| Effective value | Agreeing corrections apply. Disagreeing ones, or one whose records sit in several transactions, leave the source value, disclosed | D-049 |
| Correction chains | D-048's rule. Undo never refuses for contradiction. Confirm and separate refuse to leave a correction unsettled | D-049 |
| Correction tokens | `r4`, `t2` and `d4` add corrections, keeping digests when there are none. `c1` for undo | D-049 |

## Open follow-ups

**F1. Marked current without primary-source metadata. Fixed in `dfe412f`.** Migration 0004
leaves a transaction merged before it with no primary source, while its marker still
matched. `stale_accounts` is now the single definition of current (D-033): the rules must
match and every live transaction must record its primary source. Accounts with no
transactions are never stale. No migration was needed. A repeat import or `reconcile`
catches up, and `totals` discloses the account until then.

**F2. Legacy identity timestamps. Partly done.** An ID retired before migration 0004 has
no stored `created_at`, so a revival uses its first record's link time (D-029). `trace`
now labels this as approximate, for every event of that ID, inferred from the first
identity event being `revived`. Nothing marks `ledger_transaction.created_at` itself as a
fallback, and no command shows it today. **A stored marker is a prerequisite before any UI
or export presents legacy creation timestamps.**

**F3. Merge-heavy benchmark. Backlog.** See "Backlog benchmarks" in [plan.md](plan.md).

**F4. Supersession chains revived a superseded decision. Found at the M2.4 review, fixed in `425c684`.**
In a chain A ← B ← C, where rejection A keeps X and Y apart, confirmation B joins them and supersedes
A, and confirmation C supersedes B keeping its `same_event` pair, `review decisions` listed A as
active once C was made. The ledger held X and Y together while A said they were different events,
and no conflict was raised. `decision_states` followed D-046's wording, under which a decision is
superseded only by an active one. Reproduced in `build/m2.5-probe/`. D-048 amends the rule.

## Commit hygiene

- `bd095bf` is a broken intermediate commit: `tests/scenarios/test_overlapping_files.py`
  fails to load there. `7f7ea36` fixes it. The commit ran because the test and commit
  commands were not chained. History is not rewritten to remove it.
- Run the relevant tests successfully before committing, and a failed test must stop the
  commit command. Gate on pytest's own exit code, as in `pytest -q && git commit`. A pipe
  such as `pytest | tail` hides that exit code.

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

## Qualifications on M2.1, from its acceptance

The owner approved M2.1's three additional choices with these conditions, which bind later
slices:

1. **Revision tokens:** future decision commands must validate account, item ID and revision
   token together. A matching token alone does not identify a decision target.
2. **Stale accounts:** before accepting a decision, the workflow must ensure the displayed
   evidence is current. Never silently reconcile changed evidence and then accept an old token.
3. **Output escaping:** keep the escaping, and the tests for embedded newlines and terminal
   control characters.

## M2.2 as built

Scope and acceptance tests are in [plan.md](plan.md) (S1 to S23). Tests are in
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
  that account pays it. Measured in [status.md](status.md).
- A decision conflict has no action of its own. The only response today is `review undo`.
- A stated pair already touched by a constraint is refused, even if a newer record in one
  transaction is unbound.
- No machine-made merge can be separated until M2.4.
- `same_event` is allowed by the schema and written by nothing in M2.2.

## M2.3 as built

Accepted as built by the owner on 2026-11-07, with these limits. Scope and acceptance tests are in
[plan.md](plan.md) (C1 to C21), and the rules in D-046. Tests are
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

## M2.6 as built

Awaiting the owner's review. Scope and acceptance tests are in [plan.md](plan.md) (V1 to V18), the
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
D-048, with these limits. Scope and acceptance tests are in [plan.md](plan.md) (N1 to N18), the
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
D-047, with these limits. Scope and acceptance tests are in [plan.md](plan.md) (P1 to P22), the
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

## Awaiting the owner

- Review of M2.6.
- Pushing. Not authorized from here. The owner's own push is described under "Remote state".
- Pushing. Not authorized from here. The owner's own push is described under "Remote state".

## Recommended M2 scope

See "M2 plan" in [plan.md](plan.md). M2.5 to M2.9 are provisional, and each needs approval.
Still open: whether grouped review of long runs
belongs in M2, and F2's stored marker if any new command shows legacy creation timestamps.

## Permission approvals to renew

| Permission | Status | Next session |
|---|---|---|
| Local commits on `feature/m2-review` | Approved for M2.2's review outcome, M2.3, M2.3's review outcome, M2.4, M2.4's review outcome, M2.5, M2.5's review outcome and M2.6 | **Must be renewed** for anything further |
| M2.2 | Accepted as built, 2026-11-07 | None |
| M2.3 | Accepted as built, 2026-11-07 | None |
| M2.4 | Accepted as built, 2026-11-07 | None |
| M2.5 | Accepted as built, 2026-11-08 | None |
| M2.6 | Implemented. Stopped for review | Owner reviews |
| M2.7 | Provisional, not approved | Needs its own plan and approval |
| Pushing | Not approved. The earlier push was the owner's own | **Explicit approval for each push** |
| Installing dependencies | Was approved for the declared dependencies and build requirements only | Ask for anything new. None is expected |
| Network access | Was approved for the clean-install dependencies only. Used, and now closed | Ask for any use |

Never approved, and not to be assumed:

- Rewriting history.
- Modifying the parent repository.
- Reading parent or sibling directories, unrelated project memory, or any file
  outside `personal_finance/`, including user-level configuration.
- Reading real statements, databases, backups or credentials.
- Applying the security proposal.

## Kickoff prompt

```text
You are the lead engineer on personal_finance. Work only inside this repository, and start
every command from it. Do not read external memory, list or search parent or sibling
directories, or write external scratchpad files. Synthetic pytest temporary artifacts are the
only exception.

Read docs/handoff.md first, then the files it lists. Confirm the branch is feature/m2-review,
the working tree is clean, and run the test suite with a real exit code before changing
anything. Do not contact GitHub.

M2.6 review outcome:
[PASTE IT HERE: accepted, or the changes you want]

Task: record the review outcome, making any changes it asks for first as small gated commits.
Do not reopen D-042 to D-049 unless you find a concrete contradiction. Then propose a plan for
M2.7, resolving incomplete records, and wait for my approval before implementing it.

Follow the working principles in docs/handoff.md. Pushing needs my explicit approval each time.
No network, no new dependencies, no security changes. Synthetic data only. Use build/ for walkthroughs, breaks and benchmarks, with TMPDIR set
to build/tmp. Gate commits on pytest's own exit code, and a test that fails on unbroken code proves
nothing about a deliberate break. Check which test caught each break, and that a benchmark shape
can reach the cost it claims to measure.
```
