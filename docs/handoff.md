# Session Handoff: M1 Slice 3

For a fresh session. Written 2026-11-05. Slices 1 and 2 are provisionally accepted.
**Slice 3 has not started.**

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `feature/m1-foundation`. Partly pushed: see below |
| Latest code commit | `c5c0991`. Run `git log -1` for the latest commit, which may be this handoff |
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
`src/personal_finance/ingest/pipeline.py`, `reconcile/same_document.py` and
`db/migrations/`.

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

## Tests actually executed

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest` at `c5c0991` | **411 passed** |
| Scenario tests repeated 5 times, including concurrency | All passed (at 406 tests, before the last 5 were added) |
| Deliberate breaks in a throwaway copy, slice 1 | 26 distinct breaks, all caught after fixing two test gaps |
| Deliberate breaks in a throwaway copy, slice 2 | 50 distinct breaks, all caught after adding tests for three survivors |
| README example, in zsh and `sh` | Totals correct. The final `trace` line was run separately, not in this script |

Not executed: a fresh install from `requirements-dev.txt`, because it needs network
access. Deliberate-break checks are not part of the suite, so repeat them for new
code.

## Known limitations

- **Overlapping files that are not byte-identical are counted twice** until slice 3.
- Only two invented layouts exist. It must not be used with real financial data.
- Coverage cannot be changed after import (M2).
- Merges cannot be undone, and `transaction_source` has no history (M2).
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

| External-ID matching | A differing description alone does not conflict for a reliable ID, and both are preserved. Conflicts in amount, status or a date present on both records are flagged | D-006 |
| Unresolved rows | Exact matches stay possible duplicates when an unresolved row could affect the count. Reliable ID matches are not affected | D-024 |

## Slice 3 scope

Implement cross-document transaction deduplication only.

Required behavior:

- Match only within the same account.
- Use reliable identifiers and explicit coverage evidence (D-005 to D-008).
- Preserve legitimate identical purchases.
- Retain ambiguous candidates and disclose their effect on totals.
- Preserve all source provenance.
- Do not guess a single exact duplicate adjustment for ambiguous candidate groups.

Out of scope: pending-to-posted reconciliation (M2), transfer classification (M3),
resolving review items (M2), undoing merges (M2), real layouts, PDFs, the UI.

When done, remove the cross-document notice from `import` and `totals`, and replace
it with accurate disclosure.

## Slice 3 acceptance criteria

Full wording is in [plan.md](plan.md).

| Required test | Plan IDs |
|---|---|
| Reordered exports with complete coverage | A2, A3 |
| Complete versus partial or unknown coverage | A5a, A5b, A24 |
| Inclusive end-date matching under explicit declarations | A32, with A33 and A22 as the contrast |
| Two identical purchases versus three under justified coverage | A4, A5a |
| Identical-looking purchases that remain ambiguous | A5b, A6, A22, A35 |
| External IDs with compatible fields | A20, with A21 for unreliable IDs |
| External IDs with conflicting amounts or other material fields | A7, A34 |
| Different accounts never matching | A8 |
| Repeated imports | A1, A38 |
| Different import orders | A16 |
| Provenance retained after merging | A36 |
| Failures leaving no partial merge state | A37 |
| Candidate discovery on a large synthetic dataset | A39 |
| Only plausible candidates enter review | A27 |
| No exact adjustment for ambiguous groups | A28 |

Import-order tests compare financial outcomes, source associations and unresolved
candidate relationships. They must not require identical generated IDs or display
order.

For A39, no time target exists yet (PRD §20). Propose one from a measurement, and
report the row count, timing and how timing grows with size.

## Design questions to settle first

Propose these with a recommendation and wait for approval before coding:

1. **Order independence.** Evidence accumulates as documents arrive, so a third
   document can change what earlier ones mean. Decide between matching incrementally
   and re-evaluating an account's candidates after each import, and how stable
   transaction IDs survive either way.
2. **Which values a merged transaction shows.** Sources can differ in description.
   The choice must not depend on import order, and it must not change totals.
3. **Review item lifecycle.** Decide how a group grows or is replaced when a new
   document joins it, without duplicating items on re-import.
4. **Disclosure wording.** Decide what summaries show about candidate groups,
   without implying an exact adjustment.

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

Task: M1 slice 3, cross-document transaction deduplication only.

Start by proposing answers to the design questions in the handoff, with a
recommendation each, and wait for my approval before writing code.

Local commits on feature/m1-foundation are approved. Pushing needs my explicit
approval each time. No network, no new dependencies, and no access outside this
folder.
Synthetic data only. The security proposal stays unapplied.

Run tests and report actual results. Use deliberate breaks in a throwaway copy to
check that new tests can fail. Stop for review when slice 3 is complete.
```
