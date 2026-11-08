# Session Handoff: M3.4 Built, Awaiting Review

For a fresh session. Written 2026-11-08. **M1, M2 and M3.1 to M3.3 are complete and accepted.** The
owner approved M3.4, income and spending (D-056), on 2026-11-08 with the lead engineer's
recommendations, including points A to C. **M3.4 is built and awaits review**: the implementation
choices and points for review are at the end of D-056, and the limits in "M3.4 as built" below.
Once M3.4 is accepted, M3 closes (D-056, point C).

Earlier history (what each slice built, every test run, the "as built" limits of M2, and session
boundary notes) is in [archive/handoff-history.md](archive/handoff-history.md). Read it only when a
task needs a specific section.

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
| Branch | `feature/m2-review`, created from `643e1b1`. Tracks `origin/feature/m2-review` |
| Latest commit | Run `git log -1`: it records M3.4 as built. M3.4 starts after `288fb32`, which records D-056's approval. Earlier markers are in the archive |
| Latest gating run | Full suite, 1742 passed, exit code 0, gating the commit recording M3.4 as built |
| Python | 3.12.6, project `.venv` already present |
| Runtime dependencies | None |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Entry point | `bin/pf`, using this checkout's `.venv`. An installed `pf` script also works |
| Data | Synthetic only. Keep databases outside the repository |
| Remote | The owner pushes branches themselves. Nothing has been pushed from here since `673c025`, and GitHub's live state is unverified. Details in the archive |

## Read first

1. This file.
2. [decisions.md](decisions.md): the index, the rules in brief, and D-056 in full.
3. [plan.md](plan.md): milestones and the M3 plan.
4. [status.md](status.md): what exists, and the known limitations.

Then only what the task needs:

- For changes to M3.4 (D-056): `reports/totals.py`, `run_totals`, `print_income_and_spending`
  and `describe_income_and_spending` in `cli.py`, and `tests/scenarios/test_income_and_spending.py`.
- For the transfer-effects variable limit: `transaction_facts` in `reconcile/transfer_effects.py`,
  and the `--income` shape in `tests/benchmarks/measure_reconciliation.py`.
- For changes to M3.2 or M3.3: `reconcile/transfer_effects.py`, `reconcile/transfers.py`,
  `reconcile/coverage_in_effect.py`, `reports/transfer_evidence.py`, their scenario tests, and
  "M3.2 as built" or "M3.3 as built" in the archive.
- Any other decision by its heading in [decisions-d001-d052.md](decisions-d001-d052.md).
- [layouts.md](layouts.md) when a task touches parsing or layouts. [benchmarks.md](benchmarks.md)
  when it touches performance. [archive/plan-m1-m2.md](archive/plan-m1-m2.md) for the M1 and M2
  acceptance criteria.

## M3.4 as built

Built 2026-11-08, awaiting the owner's review. Scope and acceptance tests are in [plan.md](plan.md)
(T1 to T12), the rules, implementation choices and points for review in D-056. Tests are in
`tests/scenarios/test_income_and_spending.py`, with T11 in both import-order tests. The benchmark
is `measure_reconciliation.py --income`, in [benchmarks.md](benchmarks.md). 23 deliberate breaks:
19 caught by the test aimed at each rule, and 4 survivors closed by new tests and then caught.
Breaks and benchmark output are in `build/m3.4-breaks/` and `build/m3.4-bench/`.

**Known limits of M3.4:**

- Income and spending count only what a person classified and confirmed. Unconfirmed transfer
  kinds and unclassified transactions are disclosed as a bound, never counted.
- No reporting periods, which stay in M4 with D-013.
- A loan payment is never split into principal and interest.
- Every write fails above 32,766 transactions bound by transfers, in M3.2 and M3.3 code, for review.

## Lessons for new work

Pitfalls that recurred across M1 to M3.4:

- **Migration tests** that build a ledger at the latest version and set it back break when a newer
  migration adds tables. Each migration's tests stop at their own version or drop newer tables.
- **Order dependence.** `pair_up`'s first transaction follows content hashes, and generated IDs are
  random, so tests name files rather than assume an order. A test that failed at random once took the
  credit for four surviving breaks.
- **Deliberate breaks,** run as in "Testing for review". Check which test caught each break, not
  only that one did. Removing a loop's only line is a syntax error, not a catch: use `pass`. A
  replacement that renames a function is a bad break. A break that matches nothing must stop the
  script, not run on unchanged code.
- **Tests that pass for the wrong reason.** Give each schema refusal a control insert that succeeds.
  Pass test helper arguments by keyword. Count the tests actually run: a nested function or a test
  class imported by name changes the count.
- **Renaming a test** breaks `docs/m1-acceptance.md` if a criterion names it. Gate such a commit on
  `tests/unit/test_acceptance_matrix.py` too: `7a07bf4` missed it in M3.4.
- **Benchmarks** must be able to reach the cost they claim to measure. Three documents, not two, are
  needed for a confirmation to link anything.
- **Shell.** zsh has no `PIPESTATUS`, so `pytest | tail && git commit` gates on `tail`: it
  happened in M3.2 at `1d1267d` and again in M3.3 at `ebc2ab4`, both on passing suites. Never pipe a
  gate: redirect to a file and chain the commit to pytest itself. An unquoted `--include=*.py` fails, and
  `echo ====` is read as a command. `mktemp -d` ignores
  `TMPDIR` here. The harness refuses `rm -rf` of a `build/` folder, so use a new folder.

## Open follow-ups

**F2. Legacy identity timestamps. Partly done.** An ID retired before migration 0004 has no stored
`created_at`, so a revival uses its first record's link time (D-029), and `trace` labels it as
approximate. Nothing marks `ledger_transaction.created_at` itself as a fallback. **A stored marker is
a prerequisite before any UI or export presents legacy creation timestamps.**

**F3. Merge-heavy benchmark. Backlog.** See "Backlog benchmarks" in [plan.md](plan.md).

F1 and F4 are fixed, and recorded in the archive.

## Qualifications on M2.1, binding later slices

1. **Revision tokens:** decision commands must validate account, item ID and revision token
   together. A matching token alone does not identify a decision target.
2. **Stale accounts:** before accepting a decision, the workflow must ensure the displayed evidence
   is current. Never silently reconcile changed evidence and then accept an old token.
3. **Output escaping:** keep the escaping, and the tests for embedded newlines and terminal control
   characters.

## Commit hygiene

- Gate every commit on pytest's own exit code, chained as in `pytest -q && git commit`. A pipe such
  as `pytest | tail` hides that exit code. `bd095bf` is a broken commit made when they were not
  chained, and history is not rewritten to remove it.
- While a slice is in progress, gate each commit on the test files for the code it changes and the
  scenario files that exercise it. Gate the last commit before stopping for review on the full
  suite, about 3.5 minutes. If a gate fails, rerun only the failing tests with `pytest --lf` while
  fixing, then rerun the gate itself before committing.

## Testing for review

Set by the owner on 2026-11-08 to cut test time, which reached about two hours a milestone in M3.1
(62 breaks of about 50s each, then all 62 again on the final code). The bar is unchanged: every break
must be caught by a relevant test, or be shown to be a test gap, closed, or equivalent code.

1. **Fewer, targeted breaks.** About 20 to 25 a slice, aimed at refusals, money and direction rules,
   token inputs, and the new invariants and migrations. Skip wording, messages and paths that only
   save work.
2. **Narrow first.** Run each break against the one or two test files that cover the broken code,
   with the most relevant file first. Widen to the slice's wider set only for a break that survives
   there, before calling it a gap.
3. **Stop at the first failure.** Run breaks with `pytest -x -q --tb=no`. One relevant failure is a
   catch. Record which test failed, and treat a catch by an unrelated test as a survivor.
4. **Rerun only what needs it.** On the final code, rerun only the breaks that survived, those whose
   target code changed since, and those that did not apply. A caught break on unchanged code stays
   caught.
5. **The unbroken control** still runs once, on the same narrow files, before any break.
6. **No repeat runs** of a test file to look for flakiness, unless the work touches random or
   order-dependent tests.
7. **Parallel worktrees** only if a break run still takes more than about 15 minutes: run breaks in
   two to four worktrees under `build/`, each with its own `TMPDIR`. No new dependency for it.

Report the counts: applied, caught, survived and why, and rerun.

## Keeping these docs small

Every session reads the "Read first" list, so its cost grows with them. At the end of a task:

- Replace this file's state, rather than appending to it. Move the finished milestone's "as built"
  section and anything only historical to [archive/handoff-history.md](archive/handoff-history.md).
- Record each fact in one place: rules in decisions, current limits in status, measurements in
  benchmarks, history in git and the archive. Link rather than restate.
- When a decision is accepted and a newer one is written, move its full text to
  [decisions-d001-d052.md](decisions-d001-d052.md) and keep its index line.
- Report test runs and break results in the commit message or the session report, and here only the
  latest gating run.
- Write session boundary notes only when something went wrong.

## Awaiting the owner

- Review of M3.4 as built, including the implementation choices and the points for review at the
  end of D-056, notably the 32,766-variable limit in M3.2 and M3.3's transfer effects.
- Pushing. Not authorized from here.

## Permissions

| Permission | Status | Next session |
|---|---|---|
| Local commits on `feature/m2-review` | Approved through M3.4 | **Must be renewed** for anything further |
| M1, M2 and M3.1 to M3.3 | Accepted as built | None |
| M3.4 | Plan D-056 approved 2026-11-08. Built, awaiting review | Owner accepts or asks for changes |
| Pushing | Not approved. Earlier pushes were the owner's own | **Explicit approval for each push** |
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

Read docs/handoff.md first, then only the files and sections its "Read first" list names for
this task. Open the archive and other decisions only when the task needs them. Confirm the
branch is feature/m2-review, the working tree is clean, and run the test suite with a real exit
code before changing anything. Do not contact GitHub.

M3.4 review outcome (D-056, income and spending, including its implementation choices and its
points for review, among them the 32,766-variable limit in transfer effects):
[PASTE IT HERE: accepted, or the changes you want]

Task: record the outcome in D-056 and the handoff. If changes are wanted, make them as small gated
commits and stop for review again. If accepted, M3 closes: record that, and propose a plan for the
next milestone as its own decision, and stop for approval before building any of it. Do not reopen
D-042 to D-056 unless you find a concrete contradiction.

Follow the working principles in docs/handoff.md, and its "Keeping these docs small" rules when
you update the docs. Pushing needs my explicit approval each time. No network, no new
dependencies, no security changes. Synthetic data only. Use build/ for walkthroughs, breaks and
benchmarks, with TMPDIR set to build/tmp. Gate commits on pytest's own exit code, as in its
"Commit hygiene", and run deliberate breaks as in its "Testing for review". A test that fails on
unbroken code proves nothing about a deliberate break. Check which test caught each break, and
that a benchmark shape can reach the cost it claims to measure.
```
