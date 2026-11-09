# Session Handoff: M6 Reviewed, M6.4 Waits for Its Header

For a fresh session. Written 2026-11-09. **M1 to M5 are complete and accepted.** The owner directed
M6 on 2026-11-09, to be built unattended overnight: D-059 in [decisions.md](decisions.md). **M6.1 to
M6.3 are built and committed, and await the owner's review. M6.4, BFSFCU, is not built.** Every
layout is **unverified**: no sample reached this repository, so each is written from the lead
engineer's knowledge of the export, on invented fixtures. Read D-059's points A to F first: they are
where the owner's directions met earlier rules, and what was done instead.

| Slice | Commit | Layouts | Breaks |
|---|---|---|---|
| D-059 | `64a4791` | The plan, J1 to J8 | |
| M6.1 | `729e44b` | `capital_one_card_v1`, `capital_one_bank_v1` | 18 applied, 18 caught |
| M6.2 | `15f5958` | `us_bank_v1`, and a fix to `capital_one_bank_v1` | 13 applied, 13 caught |
| M6.3 | `8e70069` | `amex_card_v1` | 8 applied, 8 caught |

**The owner approved D-059's points A to F on 2026-11-09.** Next: M6.4, BFSFCU, once its export's
header and two rows reach this repository (they had not yet), and the owner's point F run per
layout, by [layout-verification.md](layout-verification.md), before any real import.

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
| Latest commit | Run `git log -1`. M5.1 is `0f01eaa`, M5.2 `46c6d20`, its second amendment `c314c21`, M5.3 `67d2457`, its acceptance `c8bdb4a`, point 7's amendment `fc76cd2`, M5.4 `5e6e05e`, its docs `7a0d446`, M5.5 `4548b12`, its docs `df53e65`, and M5's acceptance the commit after it |
| Latest gating run | Full suite, 2237 passed, exit code 0, on M6.3 `8e70069` |
| Python | 3.12.6, project `.venv` already present |
| macOS | Golden Gate 27.2, as stated by the owner |
| Owner's data folder | `/Users/michaelbattaile/Documents/commoncents_data`, outside this repository. It holds the owner's statements, which no session reads, lists or runs a command against. Its `ledger/` is no longer the real ledger's folder, and the owner has restored statements into the image. Backups go on an encrypted disk image whose file the owner keeps in `~/CommonCents_LocalBackups`, mounted at `/Volumes/CommonCentsBackup` (D-058 point 7, as amended). Never read, list or search that volume either. That folder is the owner's too: never read, list or search it |
| Real ledger's image | `~/CommonCents.sparsebundle`, mounted by the owner only when needed at `/Volumes/CommonCents`, with the ledger folder `/Volumes/CommonCents/ledger` (`0700`, the owner's). It holds the owner's statements: never read, list or search it. Run diskutil, hdiutil or `stat` on it only with the owner's approval each time. Checked 2026-11-09: encrypted as an image file (`image-encrypted` true), its APFS volume not (`Encryption` false), ownership honoured, so the gate accepts it. The owner ran the readiness checklist on it on 2026-11-09, so the real ledger lives at `/Volumes/CommonCents/ledger/ledger.db` |
| Runtime dependencies | None |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Entry point | `bin/pf`, using this checkout's `.venv`. An installed `pf` script also works |
| Data | Synthetic only. Keep databases outside the repository. Institution fixtures in `tests/fixtures/synthetic/statements` are invented |
| Remote | The owner pushes branches themselves. Nothing has been pushed from here since `673c025`, and GitHub's live state is unverified. Details in the archive |

## Read first

1. This file.
2. [decisions.md](decisions.md): the index, the rules in brief, and D-058 in full. Every earlier
   decision is accepted, and their full text is in [decisions-d001-d052.md](decisions-d001-d052.md).
3. [plan.md](plan.md): milestones and the M5 plan.
4. [status.md](status.md): what exists, and the known limitations.

Then only what the task needs:

- For changes to M5.1: `db/real_ledger.py`, `run_init`, `open_ledger`, `run_migrate` and
  `run_import` in `cli.py`, migration 0017, `tests/scenarios/test_real_ledger.py`,
  `tests/scenarios/test_real_ledger_migration.py`, and "How M5.1 was implemented" under D-058.
- For changes to M5.2: `db/volume_probes.py`, `refuse_unless_on_encrypted_disk_image`,
  `disk_image_is_encrypted` and `check_real_ledger_on_open` in `db/real_ledger.py`,
  `tests/scenarios/test_encrypted_volume.py`, the recordings in
  `tests/fixtures/synthetic/volume_probes`, and "How M5.2 was implemented" under D-058.
- For changes to M5.3: `db/originals.py`, `reports/storage.py`, the archive step in
  `ingest/pipeline.py`, `run_import`, `run_archive_verify` and `run_storage` in `cli.py`,
  `tests/scenarios/test_originals.py`, and "How M5.3 was implemented" under D-058.
- For changes to M5.4: `db/backups.py`, migration 0018, the `backup` commands and `run_storage`
  in `cli.py`, `tests/scenarios/test_backups.py`, and "How M5.4 was implemented" under D-058.
- For changes to M5.5: `tests/unit/test_no_network_imports.py`, [real-data-readiness.md](real-data-readiness.md),
  "Network and dependencies" in [status.md](status.md), and "How M5.5 was implemented" under D-058.
- For changes to M6: D-059, [layouts.md](layouts.md), `ingest/layouts.py`,
  `tests/scenarios/test_institution_layouts.py` (one `LayoutCase` per layout runs J1 to J7), and
  `tests/fixtures/synthetic/statements`. A new layout is a new `LayoutCase`. A real layout's sample
  reaches this repository only redacted and with the owner's approval (D-019).
- For changes to M4: the M4 slice's code, its scenario tests, and its "How M4.n was implemented"
  under D-057 in [decisions-d001-d052.md](decisions-d001-d052.md). M4.4's benchmark is `--scale` in
  `tests/benchmarks/measure_reconciliation.py`, with figures in [benchmarks.md](benchmarks.md).
- For changes to M3.4 (D-056): `reports/totals.py`, `run_totals`, `print_income_and_spending`
  and `describe_income_and_spending` in `cli.py`, `tests/scenarios/test_income_and_spending.py`,
  and "M3.4 as built" in the archive.
- For changes to M3.2 or M3.3: `reconcile/transfer_effects.py`, `reconcile/transfers.py`,
  `reconcile/coverage_in_effect.py`, `reports/transfer_evidence.py`, their scenario tests, and
  "M3.2 as built" or "M3.3 as built" in the archive.
- Any other decision by its heading in [decisions-d001-d052.md](decisions-d001-d052.md).
- [layouts.md](layouts.md) when a task touches parsing or layouts. [benchmarks.md](benchmarks.md)
  when it touches performance. [archive/plan-m1-m2.md](archive/plan-m1-m2.md) for the M1 and M2
  acceptance criteria.

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
  script, not run on unchanged code. Give every break run a fresh bytecode cache
  (`PYTHONPYCACHEPREFIX`): in M4.2 a break of the same size, written in the same second as the one
  before, ran that one's stale `.pyc` and credited a catch to the wrong break.
- **Closed review items.** D-045 closes an item by removing it. Only D-052's same-document
  pending and posted items stay as `resolved` rows, so a test about resolved items needs that shape.
- **A broader refusal can stand in for the one under test.** In M5.1 the trigger refusing a mark
  on a ledger with an account refused `INSERT OR REPLACE` first, hiding a missing no-replace
  trigger. Test each refusal on a state where it alone applies.
- **Tests that pass for the wrong reason.** Give each schema refusal a control insert that succeeds.
  Pass test helper arguments by keyword. Count the tests actually run: a nested function or a test
  class imported by name changes the count.
- **Renaming a test** breaks `docs/m1-acceptance.md` if a criterion names it. Gate such a commit on
  `tests/unit/test_acceptance_matrix.py` too: `7a07bf4` missed it in M3.4.
- **Check the schema before planning a case.** D-057 planned a `no date` line for transactions
  that migration 0001 already refuses. Read the table's CHECKs before designing for a state.
- **New command groups** need adding to the test `Ledger.run` helper, which inserts `--db` after
  the group's words (`report` was added in M4.3).
- **Name benchmark rows by stable keys.** M4.4's first runs bound records of the wrong account
  through an external ID repeated across accounts, then classified a randomly chosen matched side,
  which the product rightly refused. Key by account and external ID, never by generated ID order.
- **Benchmarks** must be able to reach the cost they claim to measure. Three documents, not two, are
  needed for a confirmation to link anything.
- **Privacy checks against an amount** must leave timestamps out: in M5.4 a gate failed when
  `16.502Z` held `6.50`. Three tests now strip ISO timestamps first.
- **Learn an outside tool's output from a real run before designing on it.** In M5.2 diskutil
  refused a folder, had no `VirtualOrPhysical` key, and reported an image encrypted only as a file
  as not encrypted: all three would have been built wrong from memory.
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

- For M6.4: the header row of a BFSFCU export and two rows in its format, values invented.
- Point F per layout, by [layout-verification.md](layout-verification.md), and its results.
- Acceptance of M6.1 to M6.3 once point F passes for them.
- Pushing. Not authorized from here.

## Permissions

| Permission | Status | Next session |
|---|---|---|
| Local commits on `feature/m2-review` | Approved for D-059 and M6 on 2026-11-09, used for them | **Must be renewed** for changes after the review |
| M1 to M5 | Accepted. Readiness checklist run by the owner on 2026-11-09 | None |
| M6 | D-059 approved with points A to F. M6.1 to M6.3 built. M6.4 approved, waits for its header | Build M6.4 once the header arrives |
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

Next task, from the owner:
[PASTE IT HERE: for example, draft D-059, the M6 plan]

Task: do only what the owner asks. A new milestone, such as M6, needs its own plan as the next
free decision number, and approval before any of it is built. Each slice of it then needs its own
approval. Do not reopen D-042 to D-058 unless you find a concrete contradiction.

Follow the working principles in docs/handoff.md, and its "Keeping these docs small" rules when
you update the docs. Pushing needs my explicit approval each time. No network, no new
dependencies, no security changes. Synthetic data only. Use build/ for walkthroughs, breaks and
benchmarks, with TMPDIR set to build/tmp. Gate commits on pytest's own exit code, as in its
"Commit hygiene", and run deliberate breaks as in its "Testing for review". A test that fails on
unbroken code proves nothing about a deliberate break. Check which test caught each break, and
that a benchmark shape can reach the cost it claims to measure.
```
