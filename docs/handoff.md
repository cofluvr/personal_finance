# Session Handoff: After M1

For a fresh session. Written 2026-11-06. **M1 is complete and accepted: the owner gave final
sign-off on 2026-11-06.** Its limitations and deferred benchmarks still stand. Do not start
M2 until the owner says so. See [m1-acceptance.md](m1-acceptance.md).
Slice 4's design decisions are D-036 to D-039.

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `feature/m1-foundation`. Partly pushed: see below |
| Latest commit | Run `git log -1`. Slice 3 starts after `66fda56`, slice 4 after `cda368a` |
| Python | 3.12.6, project `.venv` already present |
| Runtime dependencies | None |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Entry point | `bin/pf`, using this checkout's `.venv`. An installed `pf` script also works |
| Data | Synthetic only. Keep databases outside the repository |

**Remote state.** The owner intentionally pushed `c75aee0` (end of slice 1) to
`origin/feature/m1-foundation` on 2026-11-05, which also set upstream tracking. The
local reflog records this as the last push, and later commits are ahead of it
locally. **Unverified:** the remote's current state and the repository's visibility,
because GitHub was not contacted. Tracked content at that commit was documentation,
code and tests, with no CSV, PDF or database files.

Read first: this file, [decisions.md](decisions.md), [plan.md](plan.md),
[layouts.md](layouts.md), [status.md](status.md), [m1-acceptance.md](m1-acceptance.md).
Then the code in
`src/personal_finance/ingest/pipeline.py`, `reconcile/cross_document.py`,
`reconcile/apply.py` and `db/migrations/`.

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

## Tests actually executed

| Check | Result |
|---|---|
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
- Coverage cannot be changed after import (M2).
- Users cannot undo merges or resolve review items (M2).
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

## Awaiting the owner

- Authorization to start M2. The owner will begin M2 planning in a fresh session.
- Pushing. Not authorized. Nothing since `c75aee0` has been pushed.

## Recommended M2 scope

Slices in this order, each stopping for review. Details stay in [plan.md](plan.md).

1. **Decision storage and review queue:** stable-ID decisions (D-009), `review show`, and
   confirm, reject and undo for possible-duplicate groups, including machine-made merges.
2. **Survival across imports:** decisions take precedence over `derive()` (D-029), and survive
   re-imports or are flagged. Undo restores totals.
3. **Unresolved rows and corrections:** resolving unresolved records, and correction
   overrides stored apart from base columns.
4. **Coverage correction:** the history workflow promised by D-022.
5. **Pending to posted:** matching under D-016, including tip and description changes.

Open before M2: whether grouped review of long runs belongs here, and F2's stored marker if
any new command shows legacy creation timestamps.

## Permission approvals to renew

| Permission | Status | Next session |
|---|---|---|
| Local commits on `feature/m1-foundation` | Approved by the owner, and remains approved | Confirm in the kickoff prompt |
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
You are the lead engineer on personal_finance. Work only inside this repository.

Read docs/handoff.md first, then the files it lists. Confirm the branch is
feature/m1-foundation, the working tree is clean, and run the test suite with a
real exit code before changing anything. Do not contact GitHub.

Task: plan M2 slice 1 only, following "Recommended M2 scope" in the handoff. Propose
a short plan with a recommendation for each open point, identify only blocking
questions, and wait for my approval before editing.

Local commits on feature/m1-foundation are approved after I authorize implementation.
Pushing needs my explicit approval each time. No network, no new dependencies, no
security changes, and no access outside this repository, including memory and
scratchpad files. Synthetic data only. Use build/ for walkthroughs and breaks.

Gate commits on pytest's own exit code. Check new tests with targeted deliberate
breaks. Keep unit-labelled counts distinct (D-036). Report actual results, and stop
for review when the slice is complete.
```
