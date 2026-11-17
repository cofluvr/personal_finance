# Session Handoff: M14.1 Built, Awaiting Review

For a fresh session. Written 2026-11-16. **M1 to M13 are complete and accepted:** the owner
approved M13.1 and M13.2 on 2026-11-16, as built. `main` holds M1 to M9 at `19ee858`. M10 to
M14.1 are on `feature/m10-rules`, not merged and not pushed.

**M14.1 is built, for the owner's review,** under D-070: migration 0027 (`3fbcc7a`), then funds,
assignments and the priority list (`9465cfb`), with `fu1` and `fa1`. Its departures and choices
are in "How M14.1 was implemented" under D-070: `fund preview` beyond D-070's list, no
supersession of a fund, no undo of a fund holding an assignment, one emergency fund and one tax
reserve at a time, a fund's start no earlier than this month (so the tax reserve cannot start
before it), accrual from `received` occurrences only, two states of its own (`in progress`, `not
started`), and an assignment checking its account is current.

**Latest results:** the full-suite gate, slow tests included, 3,389 passed in 0:10:14, chained to
this handoff's commit. G6 for M14.1: 124,060 of 124,128 runs identical, the other 68 the two ledgers
a failed-migration test stamps at 27, which the old code refused as newer, with no token version
moved. Breaks: 25 applied, 24 caught on the first run, one gap closed (tax accrued on income not
tax-eligible) and caught on the rerun.

**M10 to M13 are not yet on the real ledger.** It stays at version 20 until the owner makes a
verified backup and runs `pf migrate`: 21, then 22 and 23 (D-065 point 7), then 24 and 25 for
M12, then 26 for M13, then 27 once M14 is accepted (G10: one milestone at a time). After 26, the
owner sets the household timezone with `pf setting set` before any command that needs today.

The owner's members, share and defaults are entered with the `household` commands, which nothing
here has run on real data. No security control changed, no dependency was added, and the UI stays
read-only. Every fixture is invented. Point F with the owner on their already-imported files is
still open.

Earlier history (what each slice built, every test run, the "as built" limits of M2, and session
boundary notes) is in [archive/handoff-history.md](archive/handoff-history.md). Read it only when a
task needs a specific section.

Standing rules (session rules, working principles, commit hygiene, testing for review, lessons,
keeping the docs small) are in [CLAUDE.md](../CLAUDE.md), loaded automatically. Do not restate
them here.

## Next task

Rewritten by each session for the next. The kickoff prompt carries only the owner's notes.

- **First, the owner's review of M14.1.** Its departures and choices are listed above and under
  D-070. A change the owner asks for is the next task, before anything else.
- **Then M14.2, consumption and the tax reserve,** under D-070 points 5 to 7, once the owner
  approves it and renews commit permission. GB1 to GB4 move into [plan.md](plan.md) when it
  starts.
- **Read first:** D-070 points 5 to 7 and GB1 to GB4, and D-067's G5 and G6, in
  [decisions-m12-m21.md](decisions-m12-m21.md); "How M14.1 was implemented"; D-063's stated model
  as `reconcile/stated_fields.py` holds it, with categorizations (`reconcile/categorizations.py`,
  `reports/categorization_evidence.py`) as the model `review consume` copies; how M11 added `a1`
  and `s1` to `r`, `t`, `d` and `c` while keeping every digest (D-065); `planning/funds.py` and
  `reports/fund_standing.py`; `reports/budget_report.py` for "paid from reserves".
- **Warnings:** M14.2 adds migration 0028, so every older migration test's set-back grows again:
  `drop_fund_tables` now runs first in `drop_budget_tables`. It moves `r`, `t`, `d` and `c` once,
  to `r13`, `t11`, `d10` and `c6` (G5), leaving the new input out of each token while no
  consumption reaches, so G6's compare takes `r12:r13,t10:t11,d9:d10,c5:c6` as token bumps. The
  tax reserve's `fund release` belongs to M14.2 and joins `fu1`. Before changing `src/`, keep the
  suite's ledgers with `--basetemp` from a `git archive` export of the latest commit, for G6;
  this session's scripts are `build/m14/g6/` (`capture.py --funds`, `compare.py`,
  `migrate_copies.py` from 26). In `cli.py`, alias any imported name that may already exist
  (`change_terms` clashed in M14.1).
- **Done when:** the slice the owner approves is built, gated on the full suite, with 20 to 25
  breaks reported. Stop for review there unless the owner's notes extend the scope.

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `main` holds everything through M9 at `19ee858`. M10 to M14.1 are on `feature/m10-rules`, created from `main` at `19ee858`, not pushed |
| Latest commit | Run `git log -1`. M9's acceptance is `19ee858`. On `feature/m10-rules`: M10 `a294d64` to `871cdad`, the M11 plan and approvals to `b61d85d`, one commit per M11 slice, the review's changes `e9745ec`, the types and categories refusal fix `b47b308`, M11's acceptance record `aacbe47`, M12.1's approved slice plan `181c8cf`, and M12.1 itself. M14.1: migration 0027 `3fbcc7a`, the slice `9465cfb`, then its records. Earlier commits are in the archive |
| Latest gating run | The full suite, slow tests included, on M14.1 with its records: 3,389 passed in 0:10:14, exit code 0, chained to this handoff's commit |
| Python | 3.12.6, project `.venv` already present |
| macOS | Golden Gate 27.2, as stated by the owner |
| Owner's data folder | `/Users/michaelbattaile/Documents/commoncents_data`, outside this repository. It holds the owner's statements, which no session reads, lists or runs a command against. Its `ledger/` is no longer the real ledger's folder, and the owner has restored statements into the image. Backups go on an encrypted disk image whose file the owner keeps in `~/CommonCents_LocalBackups`, mounted at `/Volumes/CommonCentsBackup` (D-058 point 7, as amended). Never read, list or search that volume either. That folder is the owner's too: never read, list or search it |
| Real ledger's image | `~/CommonCents.sparsebundle`, mounted by the owner only when needed at `/Volumes/CommonCents`, with the ledger folder `/Volumes/CommonCents/ledger` (`0700`, the owner's). It holds the owner's statements: never read, list or search it. Run diskutil, hdiutil or `stat` on it only with the owner's approval each time. Checked 2026-11-09: encrypted as an image file (`image-encrypted` true), its APFS volume not (`Encryption` false), ownership honoured, so the gate accepts it. The owner ran the readiness checklist on it on 2026-11-09, so the real ledger lives at `/Volumes/CommonCents/ledger/ledger.db` |
| Runtime dependencies | pypdf 6.21.2, pinned by hash in `requirements.txt`, already in `.venv` (D-060 point 1, as amended) |
| Dev dependencies | pinned in `requirements-dev.txt` (pytest 9.2.0, Hypothesis 6.170.14) |
| Entry point | `bin/pf`, using this checkout's `.venv`. An installed `pf` script also works |
| Data | Synthetic only. Keep databases outside the repository. Institution fixtures in `tests/fixtures/synthetic/statements` are invented |
| Remote | The owner pushes branches themselves. Nothing has been pushed from here since `673c025`, and GitHub's live state is unverified. Details in the archive |

## Read first

1. This file.
2. [decisions.md](decisions.md): the index, the rules in brief, and D-065 (accepted) and D-066 in
   full. Every earlier decision is accepted, and their full text is in
   [decisions-d001-d052.md](decisions-d001-d052.md). Moving D-065's full text there is housekeeping
   not yet done.
3. [plan.md](plan.md): milestones, and each milestone's slices and acceptance criteria.
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
- For changes to M9: D-063 in the full text and its "How M9.n was implemented", its criteria in
  [plan.md](plan.md), `reconcile/stated_fields.py`, `reconcile/statements.py`,
  `reports/stated_evidence.py`, the
  category modules beside them, migrations 0019 and 0020, `reports/totals.py`, `reports/monthly.py`,
  `reports/report_text.py`, and `tests/scenarios/test_categories.py`, `test_categorizations.py` and
  `test_spending_by_category.py`. A change to types or categories changes both: run
  `test_classifications.py` too. A byte for byte comparison follows "How M9.3 was implemented":
  keep the suite's ledgers with `--basetemp` under `build/`, migrate copies, and cap per-ID shows.
- For changes to M11: D-065 and its "How M11.n was implemented", its criteria in
  [plan.md](plan.md), `reconcile/household_effects.py` (`allocate_cents` and every attribution),
  `reconcile/household.py`, `reconcile/allocation_effects.py`, `reconcile/allocations.py`, the
  `write_value` hook in `reconcile/statements.py`, `reports/household_evidence.py`,
  `reports/allocation_evidence.py`, `reports/household.py`, migrations 0022 and 0023, and
  `tests/scenarios/test_household.py`, `test_allocations.py` and `test_household_report.py`.
  Allocations share the stated model with types and categories, so run `test_categorizations.py`
  and `test_classifications.py` too.
- For M12 to M21: D-067's guardrails G1 to G13 in [decisions-m12-m21.md](decisions-m12-m21.md)
  first, then the milestone's own decision, D-068 to D-077, and the decisions it names. Each
  milestone's criteria move into [plan.md](plan.md) when it starts.
- For changes to M13: D-069 with "How M13.1 was implemented" and "How M13.2 was implemented",
  BA1 to BB6 in [plan.md](plan.md), `planning/settings.py`, `budgets.py`, `budget_pace.py`,
  `reports/budget_report.py`, the budget lines in `reports/report_text.py`, `current_utc_time`,
  `household_today` and the setting and budget handlers in `cli.py`, `answer_budget` in
  `ui/server.py`, migration 0026, and `tests/scenarios/test_budget_plans.py`,
  `test_budget_report.py`, `test_budget_migration.py` and `tests/unit/test_budget_pace.py`. The
  test ledger `BudgetLedger` names its helpers `plan_preview*`: `IncomeLedger` already has
  `preview`. G6's scripts are `build/m13/g6/` (`capture.py --budget`, `compare.py`), and the
  breaks `build/m13/breaks/`.
- For M14: D-070 first, then M13's notes above. Unused capacity from `report budget`'s closed
  months is what M14's priority order takes.
- For changes to M14.1: D-070 with "How M14.1 was implemented", GA1 to GA5 in [plan.md](plan.md),
  `planning/funds.py`, `reports/fund_standing.py`, the fund handlers in `cli.py`, migration 0027,
  and `tests/scenarios/test_funds.py`, `test_fund_migration.py` and
  `tests/unit/test_fund_required.py`. The test ledger is `FundLedger` (on `ObligationLedger`).
  G6's scripts are `build/m14/g6/`, and the breaks `build/m14/breaks/`.
- For changes to M12.2 or M12.3: "How M12.2 was implemented" and "How M12.3 was implemented"
  under D-068, `planning/schedules.py`, `entries.py`, `obligation_effects.py`, `obligations.py`,
  `obligation_proposals.py`, `reports/obligation_evidence.py`, `obligation_spending.py`,
  `income_report.py`, the Recurring lines in `reports/report_text.py` and `review_evidence.py`,
  migration 0025, and `tests/scenarios/test_obligations.py`, `test_obligation_migration.py` and
  `test_income_report.py`. G6's scripts are `build/m12_2/g6/` (`capture.py --obligations`,
  `compare.py` strips Recurring sections, `migrate_copies.py` from 24). Pass the compare its
  ledger roots as the capture saw them, relative.
- For changes to M12.1: D-068 with its "M12.1 slice plan" and "How M12.1 was
  implemented", IA1 to IA7 and IB1 to IB5 in [plan.md](plan.md), `planning/income_effects.py`,
  `planning/income_sources.py`, `planning/income_proposals.py`, `reports/income_evidence.py`,
  migration 0024, the `income` handlers in `cli.py`, `write_transfer_effects`, and
  `tests/scenarios/test_income_sources.py`, `planning_digest.py` (`evidence_digest`) and
  `tests/unit/test_income_schedules.py`, `test_token_registry.py` and `test_planning_rules.py`.
  Sources read types, transfers and corrections, so run `test_classifications.py` too. G6's scripts
  for this slice are `build/m12/capture.py`, `compare.py` and `migrate_copies.py`, with `--income`.
- For changes to M10: D-064 and its "How M10.n was implemented", its criteria in
  [plan.md](plan.md), `reconcile/category_rule_effects.py`, `reconcile/category_rules.py`,
  `reports/category_rule_evidence.py`, migration 0021, the `category rule` handlers in `cli.py`,
  and `tests/scenarios/test_category_rules.py`. Rules read the derived types, transfers,
  corrections and person's categories, so run `test_categorizations.py` too.
- **A new migration** breaks every older migration test's set-back: `drop_category_tables` in
  `test_decisions.py` drops 0026 to 0019 through `drop_category_rule_tables`,
  `drop_household_tables`, `drop_allocation_tables`, `drop_income_tables`,
  `drop_obligation_tables` and `drop_budget_tables`, and grows with each later migration's tables.
  Also add the tables to `tests/unit/test_migrations.py`, `planning_digest.py`'s
  `PLANNING_TABLES`,
  `test_review_show.py`'s and `test_backups.py`'s `LEDGER_TABLES`, and the hand-added migrations of
  `test_pending_posted_migration.py`.
- For changes to M8: D-062 in the full text and its criteria in [plan.md](plan.md), `ui/server.py`,
  `reports/report_text.py`, `run_ui`, `explained_error` and the six report handlers in `cli.py`,
  `tests/scenarios/local_ui_client.py`, `test_local_ui.py`, `test_local_ui_review.py`,
  `test_report_text.py`, and `tests/unit/test_no_network_imports.py`. A new page renders a
  builder's lines and gets a parity test against its command. Showing `trace` or any decision
  history needs F2 first. D-037, D-040, D-043 and D-058 points 3 and 9 in the full text when a
  point names them.
- For M7: D-060, its acceptance criteria in [plan.md](plan.md), [layouts.md](layouts.md),
  `ingest/` (`pdf_reader.py`, `pdf_documents.py`, `layouts.py`, `csv_reader.py`, `pipeline.py`), `tests/unit/test_pdf_reader.py`, `tests/synthetic_pdf.py`,
  `tests/scenarios/test_us_bank_activity_pdf.py`, `tests/scenarios/test_csv_pdf_matching.py`,
  `reconcile/cross_document.py`
  (`_match_exact` and `_coverage_gap`), and `tests/unit/test_no_network_imports.py`. D-005, D-006,
  D-020, D-024, D-026 and D-027 in the full text when a point names them.
- For changes to M6: D-059, D-061 for `capital_one_bank_v1`'s account number check, [layouts.md](layouts.md), `ingest/layouts.py`,
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

## Open follow-ups

**F2. Legacy identity timestamps. Partly done.** An ID retired before migration 0004 has no stored
`created_at`, so a revival uses its first record's link time (D-029), and `trace` labels it as
approximate. Nothing marks `ledger_transaction.created_at` itself as a fallback. **A stored marker is
a prerequisite before any UI or export presents legacy creation timestamps.**

**F3. Merge-heavy benchmark. Backlog.** See "Backlog benchmarks" in [plan.md](plan.md).

F1 and F4 are fixed, and recorded in the archive.

## Awaiting the owner

- Point F for `us_bank_card_activity_pdf_v1`, by the PDF section of
  [layout-verification.md](layout-verification.md).
- Point F per layout, by [layout-verification.md](layout-verification.md), and its results. The
  owner's layouts are already imported into the real ledger, so point F reuses those files in a
  throwaway ledger, with the owner, at the final review.
- [real-data-readiness.md](real-data-readiness.md) names the backup volume `CommonCentsBackups`.
  The owner's is `/Volumes/CommonCentsBackup`. A doc fix, not made.
- **The review of M14.1,** with its departures listed under D-070. Then renewed commit permission
  for M14.2.
- Whether the tax reserve may start in a closed month (a correction flag, as D-069's), if the
  owner wants it accruing from the start of the year.
- The household timezone, the monthly allowance, members' parts and any category allowances
  (D-069's inputs), and the bills to confirm first (D-068's), entered by the owner on the real
  ledger once it reaches 26.
- M14's inputs (D-070): goals, the emergency minimum, annual expenses, the tax percentage, the
  priority and current assignments, entered by the owner once the real ledger reaches 27.
- A delivery deadline, if any (D-066).
- Each milestone's own inputs, listed in its decision, when it starts.
- On the real ledger, a verified backup, then `pf migrate` to version 21 for M10, verified, then
  22 and 23 for M11, then the owner's members, the 50/50 share and each account's default,
  entered by the owner, then 24 and 25 for M12, then 26 for M13, then 27 once M14 is accepted.
- Merging `feature/m10-rules` into `main`. Needs the owner's approval.
- Pushing. Not authorized from here.

## Permissions

| Permission | Status | Next session |
|---|---|---|
| Local commits | Approved on 2026-11-16 for M14.1 on `feature/m10-rules`. Used for `3fbcc7a`, `9465cfb` and this handoff's commit | **Must be renewed** for any later change |
| M11 | Accepted on 2026-11-10. Not yet on the real ledger | The real-ledger migrations 21, 22 and 23, each after a verified backup |
| M12 to M21 | Plans approved on 2026-11-10 (D-066 to D-077), including M17's and M20's security changes. M12 and M13 accepted on 2026-11-16. M14.1 built on 2026-11-16 | M14.1's review. M17's browser writes and M20 need the owner's approval in a session whose kickoff allows a security change, a dependency and network. Installing `segno` still needs its pinned version and hash, and W1's check |
| M1 to M5 | Accepted. Readiness checklist run by the owner on 2026-11-09 | None |
| M6 | Complete, recorded by the owner on 2026-11-09 | Point F results. A layout correction needs approval |
| M7 | Complete, recorded by the owner on 2026-11-09 | Point F for `us_bank_card_activity_pdf_v1`. A layout correction needs approval |
| M8 | Complete, verified by the owner in a browser on 2026-11-09 | Decisions from the browser (M8.4) need a new approval, as a security change |
| M9 | Accepted on 2026-11-09, verified on the real ledger | None |
| M10 | Accepted on 2026-11-10. Not yet verified on the real ledger | The owner's backup and `pf migrate` to 21. Merging into `main` needs approval |
| Pushing | Not approved. Earlier pushes were the owner's own | **Explicit approval for each push** |
| Installing dependencies | Approved for the declared dependencies and build requirements, and on 2026-11-09 for pypdf 6.21.2 | Ask for anything new, an upgrade of pypdf included |
| Network access | Approved for the clean-install dependencies, and on 2026-11-09 for pypdf's release list and install. Used, and now closed | Ask for any use |

Never approved, and not to be assumed: see [CLAUDE.md](../CLAUDE.md).

## Kickoff prompt

Start the session inside `personal_finance/`. Standing rules load from CLAUDE.md, and the task is
under "Next task" above, so the prompt carries only what changed since this file was written:

```text
Do the next task in docs/handoff.md.

Owner notes:
- <review outcomes, e.g. "M12.2 and M12.3 reviewed and approved">
- <permissions renewed, e.g. "local commits approved for M13 on feature/m10-rules">
- <scope change or stopping point, if any>
```
