# Session Handoff: M2.3 Awaiting Review

For a fresh session. Written 2026-11-07. **M1 is complete and accepted**, and its limitations and
deferred benchmarks still stand. See [m1-acceptance.md](m1-acceptance.md).

**M2.1 and M2.2 are accepted.** The owner accepted M2.2 as built on 2026-11-07, including the
choices at the end of D-045, with no changes. **M2.3 is implemented and awaits the owner's review.
Do not start M2.4.** M2.4 to M2.9 are provisional, and each needs its own approval. M2.1's decisions
are D-040 and D-041, M2.2's rules are D-042 to D-045, with D-045 overriding the others where they
differ, and M2.3's are D-046.

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `feature/m2-review`, created from `643e1b1`. Local only, with no upstream |
| Latest commit | Run `git log -1`: the commit recording this handoff, whose parent is `f9baed0`. M2.3 starts after `66ecb06`, which records M2.2's acceptance. M2.2 starts after `1caeb52`, and M2.1 after `643e1b1`. In M1, slice 3 starts after `66fda56` and slice 4 after `cda368a` |
| Python | 3.12.6, project `.venv` already present |
| Runtime dependencies | None |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Entry point | `bin/pf`, using this checkout's `.venv`. An installed `pf` script also works |
| Data | Synthetic only. Keep databases outside the repository |

**Remote state.** The owner intentionally pushed `feature/m1-foundation` twice: `c75aee0` (end
of slice 1) on 2026-11-05, which set upstream tracking, and `643e1b1` (all of M1) on 2026-11-06
at 00:27:10. The owner confirmed that the second push was theirs and intentional, and no
investigation is needed. The 43 commits it added hold code, documentation and the three
synthetic fixture CSVs. `feature/m2-review` has never been pushed. **Unverified:** the remote's
live state and the repository's visibility, because GitHub was not contacted. Local tracking
refs only record what was last pushed from here.

Read first: this file, [decisions.md](decisions.md), [plan.md](plan.md),
[layouts.md](layouts.md), [status.md](status.md), [m1-acceptance.md](m1-acceptance.md).
Then the code in
`src/personal_finance/ingest/pipeline.py`, `reconcile/cross_document.py`,
`reconcile/apply.py`, `reconcile/decisions.py`, `reports/review_evidence.py`,
`reports/decision_evidence.py` and `db/migrations/`.

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

## Tests actually executed

| Check | Result |
|---|---|
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
- Users cannot separate machine-made merges yet (M2.4).
- A pending and a posted row with different amounts and no ID count twice with no flag.
- The revision covers only inputs that exist today (D-040). Corrections must join it later.
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

Scope and acceptance tests are in [plan.md](plan.md) (C1 to C21), and the rules in D-046. Tests are
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

## Awaiting the owner

- Review of M2.3.
- Pushing. Not authorized. `feature/m2-review` is local only.

## Recommended M2 scope

See "M2 plan" in [plan.md](plan.md). M2.3 to M2.9 are provisional, and each needs approval.
Still open: whether grouped review of long runs
belongs in M2, and F2's stored marker if any new command shows legacy creation timestamps.

## Permission approvals to renew

| Permission | Status | Next session |
|---|---|---|
| Local commits on `feature/m2-review` | Approved for M2.2's review outcome and for M2.3 | **Must be renewed** for anything further |
| M2.2 | Accepted as built, 2026-11-07 | None |
| M2.3 | Implemented. Stopped for review | Owner reviews |
| M2.4 | Provisional, not approved | Needs its own plan and approval |
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

M2.3 review outcome:
[PASTE IT HERE: accepted, or the changes you want]

Task: record the review outcome, making any changes it asks for first as small gated commits.
Do not reopen D-042 to D-046 unless you find a concrete contradiction. Then propose a plan for
M2.4, separating machine-made merges, against D-029, D-042, D-045 and D-046, and wait for my
approval before implementing it.

Pushing needs my explicit approval each time. No network, no new dependencies, no security
changes. Synthetic data only. Use build/ for walkthroughs, breaks and benchmarks, with TMPDIR set
to build/tmp. Gate commits on pytest's own exit code, and a test that fails on unbroken code proves
nothing about a deliberate break. Check which test caught each break, and that a benchmark shape
can reach the cost it claims to measure.
```
