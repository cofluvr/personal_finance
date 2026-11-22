# Session Handoff: M20, M21.1 to M21.3, the iPhone app and snapshot 1.1 built, awaiting review

For a fresh session. Written 2026-11-21. **M1 to M19 are complete and accepted** (M17 to M19 on the
owner's notes of 2026-11-21, M17's real-browser check still the owner's). `feature/m10-rules`, M10
to M21.3 and the app, was merged into `main` on GitHub by the owner on 2026-11-21. The commits
after `28d4959` are local on `feature/m10-rules`, not pushed.

**Built on 2026-11-21, for the owner's review,** each recorded in its decision's "How
implemented":

- **M20 (D-076), pairing and local-network sync.** This is a security change: TLS 1.3 on one
  private address, `/usr/bin/openssl` and `segno`. Its protocol is
  [sync-protocol.md](sync-protocol.md), and the owner's steps [sync-runbook.md](sync-runbook.md).
- **M21.1 to M21.3 (D-077):**
  - [backend-acceptance.md](backend-acceptance.md), with B1 to B15 end to end;
  - `tests/stress/` (crashes, fuzz, stress) and `--everything`;
  - [security-audit.md](security-audit.md).
- **The iPhone app, I1 to I3 (D-079), in `ios/`:** CommonCentsKit and the SwiftUI app
  ([ios/README.md](../ios/README.md)).
- **D-080, snapshot 1.1:** each member's budget pace, on the phone's member view.

**Latest results:**

- **The full suite:** see "Latest gating run" below.
- **Swift:** 28 package tests on the Mac and the iOS 26 simulator, and 9 UI tests. Interop
  against the real server on loopback passes.
- **Crashes:** 484 kill points over 10 commands, every one leaving the before or the after
  state.
- **Fuzz:** every target passes 500 examples at seeds 1 and 2.
- **Stress:** three 60-minute seeds, 4 writers and 2 readers each: 350,387 writes (129,297 accepted) and 696,041 reads; every minute's integrity, foreign-key and reconciliation check passed, no read failed, every refusal was a documented one, and no accepted write reused its target's token. Seeds 1 and 2 ran before the rule's correction and were checked again under it; seed 3 ran on it.
- **`--everything`:** every read below 2.0s on 104,100 transactions (`totals` 1.733s); backup 10.9s, verify 5.9s, restore 11.8s, and all 16 reads byte for byte the same on the restored copy; migration 0036 in 0.018s ([benchmarks.md](benchmarks.md)).

**Nothing from M10 on is on the real ledger.** It stays at version 20 until the owner makes a
verified backup and runs `pf migrate` one milestone at a time (G10): 21 (M10), 22 and 23 (M11),
24 and 25 (M12), 26 (M13), 27 and 28 (M14), 29 to 31 (M15), 32 (M16), 33 (M17), 34 (M18), 35
(M19), then 36 (M20) once it is accepted. After 26, the owner sets the household timezone with
`pf setting set`.

Every fixture is invented. Earlier history is in [archive/handoff-history.md](archive/handoff-history.md).

Standing rules are in [CLAUDE.md](../CLAUDE.md), loaded automatically. Do not restate them here.

## Next task

Rewritten by each session for the next. The kickoff prompt carries only the owner's notes.

- **Stop for the owner's review** of:
  - M20 (a security change);
  - M21.1 to M21.3, with D-025 item by item in [security-audit.md](security-audit.md) §7;
  - the app;
  - D-080.

  A change the owner asks for in any of them comes first, in the order given. Gate each change on
  its files, then on the full suite before stopping. For the app, also run `swift test` and the UI
  tests (commands in [ios/README.md](../ios/README.md)).
- **Then, only if the owner's notes allow:**
  - **I4 with the owner:** putting the app on the phone, and one real-phone delivery (YC2).
  - **M21.4 with the owner:** point F, the migration rehearsal, and the readiness checklist.
  - **Any new milestone** needs its plan as the next free decision number, D-081. Candidates are
    PRD §13's later items: receipt photography, mobile categorization, notifications. Each needs
    a write-capable sync contract first (shared-contract §5).
- **Read first for review changes:**
  - **M20:** D-076's slice plans and "How M20 was implemented", `sync/`, and the `test_sync_*.py`
    files.
  - **M21:** D-077's slice plans and "How M21 was implemented".
  - **The app:** D-079's I1 to I3 slice plan in [decisions-ios.md](decisions-ios.md).
  - **Snapshot 1.1:** D-080 in [decisions.md](decisions.md).
- **Warnings:**
  - **A new migration** joins the set-backs before `drop_sync_tables`.
  - **A snapshot change** needs:
    - a version change and its own `snapshots/vX.Y/` fixture;
    - the app's schema copy and demo snapshot updated, which `test_ios_copies.py` checks;
    - the Swift tests run.
  - **segno** is pinned to 1.6.6, and W1 pins its uses to their functions. Review any upgrade.
  - **Stress tokens recur legitimately** when a state is restored. Read
    `run_stress.py`'s rule before calling one stale.
  - **The suite takes about 23 minutes;** the stress seeds an hour each.
- **Done when:** the owner's review changes are made and gated, and the full suite, `swift test`
  and the UI tests pass.

## Current state

| Item | Value |
|---|---|
| Repository | `personal_finance/`, its own git repo. Open this folder directly |
| Branch | `main` on GitHub holds M10 to M21.3 and the app, merged by the owner on 2026-11-21. Local `main` is at `19ee858`, behind it. Later work is on `feature/m10-rules`, local, not pushed |
| Latest commit | Run `git log -1`. M20 from `af4a9d7` to `3dc0654`; M21 from `ef3a9e6`; the app `a3d209b`; D-080 `73bcfff`. Earlier commits are in the archive |
| Latest gating run | The full suite, slow tests included, on D-080 and the app's last change with M21's records: 4,500 passed in 0:20:44, exit code 0, before the handoff's commit. Swift: `swift test` 28 passed; the UI tests 9 passed |
| Python | 3.12.6, project `.venv` already present |
| Xcode | 27.2 with an iOS 26.3 simulator (iPhone 17 Pro); Swift 6.4 |
| macOS | Golden Gate 27.2, as stated by the owner |
| Owner's data folder | `/Users/michaelbattaile/Documents/commoncents_data`, outside this repository. It holds the owner's statements, which no session reads, lists or runs a command against. Its `ledger/` is no longer the real ledger's folder, and the owner has restored statements into the image. Backups go on an encrypted disk image whose file the owner keeps in `~/CommonCents_LocalBackups`, mounted at `/Volumes/CommonCentsBackup` (D-058 point 7, as amended). Never read, list or search that volume either. That folder is the owner's too: never read, list or search it |
| Real ledger's image | `~/CommonCents.sparsebundle`, mounted by the owner only when needed at `/Volumes/CommonCents`, with the ledger folder `/Volumes/CommonCents/ledger` (`0700`, the owner's). It holds the owner's statements: never read, list or search it. Run diskutil, hdiutil or `stat` on it only with the owner's approval each time. Checked 2026-11-09: encrypted as an image file (`image-encrypted` true), its APFS volume not (`Encryption` false), ownership honoured, so the gate accepts it. The owner ran the readiness checklist on it on 2026-11-09, so the real ledger lives at `/Volumes/CommonCents/ledger/ledger.db` |
| Runtime dependencies | pypdf 6.21.2 (D-060 point 1, as amended) and segno 1.6.6 (D-076), each pinned by hash in `requirements.txt`, already in `.venv` |
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

- For changes to M20:
  - D-076's slice plans and "How M20 was implemented", YA1 to YC2 in [plan.md](plan.md);
  - `sync/` (`identity.py`, `devices.py`, `pairing.py`, `server.py`) and migration 0036;
  - `tests/scenarios/sync_harness.py`, `tests/sync_reference_client.py` and the
    `test_sync_*.py` files;
  - W1's sync and segno tests in `tests/unit/test_no_network_imports.py`.
- For changes to M21:
  - D-077's slice plans and "How M21 was implemented", and ZA1 to ZD1;
  - [backend-acceptance.md](backend-acceptance.md), `tests/acceptance/`, `tests/stress/` and
    [security-audit.md](security-audit.md).
- For changes to the app:
  - D-079's I1 to I3 slice plan, and D-080;
  - `ios/CommonCentsKit` (`SnapshotValidator.swift` mirrors `snapshot/files.py`'s `verified`, and
    `Sync.swift` [sync-protocol.md](sync-protocol.md));
  - `ios/CommonCents`, and `ios/interop/run_interop.py`.
- For changes to the snapshot (M19, D-080):
  - D-075's slice plans, `snapshot/`, and shared-contract §6;
  - the fixtures under `tests/fixtures/synthetic/snapshots/`, of which `v1.1` is current;
  - `tests/unit/test_ios_copies.py`.
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
- For changes to M18: D-074's slice plans and "How M18 was implemented", XA1 to XC2 in
  [plan.md](plan.md), the files named under "Next task", and migration 0034.
- For changes to M19: D-075's slice plans and "How M19 was implemented", VA1 to VB4,
  shared-contract §6, `snapshot/`, `household_by_month` in `reports/household.py`,
  `refuse_unsafe_export_destination` in `db/exports.py`, and migration 0035.
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
- For changes to M14.2: D-070's "How M14.2 was implemented", GB1 to GB4 in [plan.md](plan.md),
  `reconcile/consumption_effects.py`, `consumptions.py`, `reports/consumption_evidence.py`,
  `planning/funds.py` (`consumed_portions`, `reductions_as_of`), `planning/fund_releases.py`,
  `reports/budget_report.py`, migration 0028, `tests/scenarios/test_consumptions.py`,
  `test_consumption_migration.py`, `tests/unit/test_fund_consumed.py`.
- For changes to M14.3: its "How implemented", GC1 to GC4, `reports/fund_report.py`,
  `funds_report_lines` and the fund line builders in `reports/report_text.py`, `/funds` in
  `ui/server.py`, `build_funds` in `test_backups.py`, `tests/scenarios/test_fund_report.py`,
  `--scale --funds`.
- For changes to M15: D-071's "How M15.n was implemented", LA1 to LC4 in [plan.md](plan.md),
  `planning/net_worth.py`, `reports/net_worth_report.py`, `planning/loans.py`,
  `reports/loan_report.py`, `reconcile/breakdown_effects.py`, `breakdowns.py`,
  `reports/breakdown_evidence.py`, the tally in `reports/totals.py` (`LOAN_INTEREST`,
  `divided_by_parts`), migrations 0029 to 0031, and `test_net_worth.py`, `test_loans.py`,
  `test_breakdowns.py`, their migration tests, `tests/unit/test_net_worth_counting.py` and
  `test_loan_math.py`. Test ledgers: `NetWorthLedger`, `LoanLedger`, `BreakdownLedger`.
- For changes to M16: D-072's "How M16.1 was implemented" and "How M16.2 was implemented", SA1
  to SB7 in [plan.md](plan.md), `planning/liquidity.py`, `coverage.py`, `fund_restorations.py`,
  `CHECKING_BUFFER` in `planning/settings.py`, `reports/safe_to_spend.py`,
  `safe_to_spend_lines` and `dashboard_lines` in `reports/report_text.py`, `/dashboard` in
  `ui/server.py`, migration 0032, `build_safe_to_spend_inputs` in `test_backups.py`, and
  `tests/scenarios/test_liquidity_migration.py`, `test_safe_to_spend_inputs.py` and
  `test_safe_to_spend.py`. Test ledgers: `InputsLedger`, `SafeLedger`.
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
  `drop_obligation_tables` and `drop_budget_tables`, and grows with each later migration's tables,
  down to `drop_snapshot_tables` for 0035, through `drop_tag_tables` (0033) and
  `drop_scenario_tables` (0034).
  Also add the tables to `tests/unit/test_migrations.py`, `planning_digest.py`'s
  `PLANNING_TABLES` (planning tables only: scenarios are, snapshot records are not),
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

**F3. Merge-heavy benchmark. Backlog.** See "Backlog benchmarks" in [plan.md](plan.md).

F1, F2 and F4 are closed. F2 closed on 2026-11-21 as not needed: nothing but `pf trace` shows a
creation time, and `test_no_legacy_timestamps_shown.py` keeps it so.

## Awaiting the owner

- **The review of M20, M21.1 to M21.3, the app and D-080.** M20 is a security change.
- **D-025, item by item,** by [security-audit.md](security-audit.md) §7. It is about the
  development agent's own environment.
- **The app on the phone (I4):** signing with your Apple ID, then one real-phone delivery (YC2).
  The steps are in [ios/README.md](../ios/README.md) and [sync-runbook.md](sync-runbook.md).
- **M21.4:**
  - point F per layout, by [layout-verification.md](layout-verification.md), in a throwaway
    ledger with your already-imported files;
  - a migration rehearsal on a restored backup;
  - the readiness checklist run again.
- **M17's real-browser check:** one decision, one tag form, `/visuals`, and any CSP console
  error.
- **The inputs each milestone lists:**
  - M14: goals, the emergency minimum, the tax percentage and the priority;
  - M15: graduated-loan documents, redacted;
  - M16: the checking buffer, liquid accounts and coverage links;
  - M19: the transaction window, and whether institution names may appear.

  Each is entered on the real ledger once it reaches that milestone's version.
- **On the real ledger:** a verified backup, then `pf migrate` one milestone at a time, as above.
- **Pushing** the commits after `28d4959`. Needs your approval.

## Permissions

| Permission | Status | Next session |
|---|---|---|
| Local commits | Approved on 2026-11-21 on `feature/m10-rules` by the owner's notes, with sign-off on everything not excepted. Used for M20, M21, the app and D-080 | Renewed by each kickoff's notes |
| M11 | Accepted on 2026-11-10. Not yet on the real ledger | The real-ledger migrations 21, 22 and 23, each after a verified backup |
| M12 to M21 | Plans approved on 2026-11-10 (D-066 to D-077). M12 to M19 accepted. M20 and M21.1 to M21.3 built on 2026-11-21 under the owner's notes of that day, segno and its one fetch included | The review of M20 and M21. M21.4 with the owner |
| iOS (D-079) | Plan and mock-ups accepted on 2026-11-20. I1 to I3 built on 2026-11-21, with D-080's snapshot 1.1 | The review; I4 with the owner |
| M1 to M5 | Accepted. Readiness checklist run by the owner on 2026-11-09 | None |
| M6 | Complete, recorded by the owner on 2026-11-09 | Point F results. A layout correction needs approval |
| M7 | Complete, recorded by the owner on 2026-11-09 | Point F for `us_bank_card_activity_pdf_v1`. A layout correction needs approval |
| M8 | Complete, verified by the owner in a browser on 2026-11-09 | Decisions from the browser (M8.4) need a new approval, as a security change |
| M9 | Accepted on 2026-11-09, verified on the real ledger | None |
| M10 | Accepted on 2026-11-10. Not yet verified on the real ledger | The owner's backup and `pf migrate` to 21. Merging into `main` needs approval |
| Pushing | Not approved. Earlier pushes were the owner's own | **Explicit approval for each push** |
| Installing dependencies | Approved for the declared dependencies and build requirements, and on 2026-11-09 for pypdf 6.21.2 | Ask for anything new, an upgrade of pypdf included |
| Network access | Used on 2026-11-21 under the owner's notes: segno's download, and one advisory search per dependency (the audit). Now closed | Ask for any use |

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
