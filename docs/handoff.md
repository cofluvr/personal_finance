# Session Handoff: After M1 Slice 3

For a fresh session. Written 2026-11-05. Slices 1 and 2 are provisionally accepted.
**Slice 3 is accepted by the owner.** One follow-up, F1 below, is open and awaits the
owner's approval. Do not start slice 4 until the owner says so. Slice 3's design
decisions are D-026 to D-035.

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `feature/m1-foundation`. Partly pushed: see below |
| Latest commit | Run `git log -1`. Slice 3 starts after `66fda56` |
| Python | 3.12.6, project `.venv` already present |
| Runtime dependencies | None |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Data | Synthetic only. Keep databases outside the repository |

**Remote state.** The owner intentionally pushed `c75aee0` (end of slice 1) to
`origin/feature/m1-foundation` on 2026-11-05, which also set upstream tracking. The
local reflog records this as the last push, and later commits are ahead of it
locally. **Unverified:** the remote's current state and the repository's visibility,
because GitHub was not contacted. Tracked content at that commit was documentation,
code and tests, with no CSV, PDF or database files.

Read first: this file, [decisions.md](decisions.md), [plan.md](plan.md),
[layouts.md](layouts.md), [status.md](status.md). Then the code in
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

## Tests actually executed

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` at the final code commit, `143f57c` | **641 passed** |
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

Not executed: a fresh install from `requirements-dev.txt`, because it needs network
access. Deliberate-break checks are not part of the suite, so repeat them for new
code. The slice 3 script and results are in `build/slice3-breaks/`, which is ignored and
may not survive.

## Known limitations

- Only two invented layouts exist. It must not be used with real financial data.
- Coverage cannot be changed after import (M2).
- Users cannot undo merges or resolve review items (M2).
- Similarity has documented misses and false positives (D-032).
- An account can read as current while a merged transaction lacks a primary source (F1).
- Identity timestamps from before migration 0004 can be fallback values (F2).
- A39 acceptance covers the documented fixtures only, in which nothing merges (F3).
- Reconciliation cost is quadratic in fully overlapping files and in distinct spellings
  per block. See [status.md](status.md).
- The original file is not kept (M5). The database is not encrypted (M5).
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

## Open follow-ups

**F1. Marked current without primary-source metadata. Open, needs the owner's approval.**
Confirmed on a temporary ledger. Migration 0004 leaves `primary_source_record_id` NULL on
a transaction merged before it, and does not touch `account_reconciliation`. The
fingerprint still matches, so `is_current` returns True, `accounts_not_current` returns 0,
a repeat import does not catch up, and `totals` says nothing. Only `trace` shows the
problem, and running `reconcile` by hand fixes it. No test covers this. It can only affect
a ledger that had merges at schema version 3.

Proposed correction, not applied: treat an account as not current while any of its
transactions has a NULL primary source, in both `is_current` and `accounts_not_current`.
That needs no migration, and the existing catch-up paths then work. Add two tests: a
migrated account reads as not current and a repeat import repairs it, and `totals`
discloses it until then. The alternative, a migration clearing those markers, adds a
schema step to express a rule that belongs in the check.

**F2. Legacy identity timestamps. Partly done.** An ID retired before migration 0004 has
no stored `created_at`, so a revival uses its first record's link time (D-029). `trace`
now labels this as approximate, for every event of that ID, inferred from the first
identity event being `revived`. Remaining work, when a surface needs it: nothing marks
`ledger_transaction.created_at` itself as a fallback, and no command shows it today. Any
future UI or export of that column must first add a stored marker.

**F3. Merge-heavy benchmark. Backlog.** See "Backlog benchmarks" in [plan.md](plan.md).

## Commit hygiene

- `bd095bf` is a broken intermediate commit: `tests/scenarios/test_overlapping_files.py`
  fails to load there. `7f7ea36` fixes it. The commit ran because the test and commit
  commands were not chained. History is not rewritten to remove it.
- Run the relevant tests successfully before committing, and a failed test must stop the
  commit command. Gate on pytest's own exit code, as in `pytest -q && git commit`. A pipe
  such as `pytest | tail` hides that exit code.

## Slice 4 planning notes

Define import-summary units explicitly, and report each in its own unit:

| Unit | Counts |
|---|---|
| Files | Attempted, succeeded, failed |
| Source rows | Rows read |
| Records | Valid, unresolved |
| Ledger effect | New logical transactions, confidently matched source records |
| Review | Review groups, distinct affected transactions |

Do not force counts with different units into one reconciliation sum. Only sums within
one unit are meaningful, such as valid plus unresolved equalling rows read.
**A17 in [plan.md](plan.md) currently says new, duplicate, flagged and failed counts add up
to the rows read, which mixes these units.** Propose new wording for the owner to approve
as part of slice 4 planning.

Verify the entry point and setup using the existing local `.venv`, without downloading
anything. A clean installation from `requirements-dev.txt` needs network access and stays
unverified until separately authorized. Say so plainly rather than implying it was tested.

## Awaiting the owner

- Approval, or a change, of the F1 correction.
- Pushing. Not authorized. Nothing since `c75aee0` has been pushed.

Next, when the owner approves: slice 4 in [plan.md](plan.md). Pending-to-posted
reconciliation and resolving review items remain M2, and transfers remain M3.

## Permission approvals to renew

| Permission | Status | Next session |
|---|---|---|
| Local commits on `feature/m1-foundation` | Approved by the owner, and remains approved | Confirm in the kickoff prompt |
| Pushing | Not approved. The earlier push was the owner's own | **Explicit approval for each push** |
| Installing dependencies | Was approved for pytest and Hypothesis only | Ask for anything new. None is expected |
| Network access | Was approved for that install and for reading Claude Code docs | Ask for any use. Slice 3 needs none |

Never approved, and not to be assumed:

- Rewriting history.
- Modifying the parent repository.
- Reading parent or sibling directories, unrelated project memory, or any file
  outside `personal_finance/`, including user-level configuration.
- Reading real statements, databases, backups or credentials.
- Applying the security proposal.

## Kickoff prompt

```text
You are the lead engineer on personal_finance. Work only inside this folder.

Read docs/handoff.md first, then the files it lists. Confirm the branch is
feature/m1-foundation and run the test suite before changing anything.

Task: M1 slice 4 only: complete import summaries, log checks, a pf entry point and
setup documentation. Follow "Slice 4 planning notes" in the handoff. Report the status of
follow-up F1 first. Propose a plan and wait for my approval before writing code.

Local commits on feature/m1-foundation are approved after I authorize implementation.
Pushing needs my explicit approval each time. No network, no new dependencies, and no
access outside this folder. Synthetic data only. The security proposal stays unapplied.

Run relevant tests successfully before committing, and a failed test must stop the
commit command. Report actual results. Use deliberate breaks in a throwaway copy under
build/ to check that new tests can fail. Stop for review when slice 4 is complete.
```
