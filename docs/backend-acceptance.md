# Backend Acceptance Matrix

M21's matrix (D-077 point 1, ZA1). Each box of [PRD-backend.md](PRD-backend.md) §21 is listed with
the tests that close it, and with one end-to-end test of its own in
`tests/acceptance/test_full_year.py`. That test runs on one synthetic household built through the
CLI alone, from import to snapshot, so no box is closed only by pieces.
`tests/unit/test_backend_acceptance.py` fails if a box is missing here or a named test does not
exist. Like [m1-acceptance.md](m1-acceptance.md), it does not judge whether a test is sufficient.

- **Passed:** the named tests pass, and the box is shown end to end on synthetic data.
- **Owner:** needs a check only the owner can make, named in the last column.

## PRD §21

| Box | Status | Tests | End to end | Limit |
|---|---|---|---|---|
| B1 Reimporting identical files changes no totals | Passed | `a1_a38_repeat_imports_change_nothing`, `identical_file_changes_nothing`, `reimporting_changes_nothing`, `a_restored_ledger_shows_everything_alike_over_generated_ledgers` | `b1_reimporting_every_file_changes_no_report` | Full scale is M21.2's `--everything` |
| B2 Overlapping CSV and PDF records count once when confidently matched | Passed | `one_periods_csv_and_pdf_count_each_row_once`, `a_csv_spanning_two_printouts_counts_each_row_once`, `either_import_order_gives_the_same_ledger`, `the_pdf_changes_no_report_of_the_csv_alone` | `b2_a_months_pdf_beside_its_csv_counts_once` | One PDF layout, unverified on a real file until point F |
| B3 Legitimate repeated purchases remain distinct | Passed | `a4_identical_purchases_survive_an_overlapping_file`, `identical_purchases_in_one_file_stay_distinct`, `identical_rows_in_one_file_are_separate_transactions`, `identical_entries_stay_separate_and_trace_to_their_rows` | `b3_two_identical_coffees_stay_two` | |
| B4 Pending-to-posted reconciliation avoids double counting | Passed | `a_pending_and_a_posted_row_with_one_id_merge`, `a_changed_amount_is_counted_once_at_the_posted_amount`, `confirming_counts_it_once_at_the_posted_amount_and_undo_restores_both` | `b4_a_pending_row_then_its_posted_row_count_once` | |
| B5 Confirmed internal transfers affect neither income nor spending | Passed | `every_transaction_is_in_one_group_adding_to_movement`, `undo_keeps_it_on_record_and_frees_both_sides` | `b5_a_matched_transfer_is_neither_income_nor_spending` | |
| B6 Credit-card payments do not duplicate purchases | Passed | `a_matched_payment_does_not_duplicate_the_purchase`, `a_one_sided_payment_is_out_of_spending_and_still_warns` | `b6_paying_the_card_does_not_count_its_purchases_again` | |
| B7 Ambiguous matches remain visible and reversible | Passed | `a5b_all_records_stay_separate_in_one_item`, `a6_a_near_match_is_kept_counted_and_listed`, `undo_keeps_it_on_record_and_frees_both_sides` | `b7_a_possible_duplicate_is_listed_decided_and_undone` | |
| B8 All transaction splits reconcile exactly | Passed | `parts_are_exact_close_and_independent_of_order`, `members_and_unattributed_add_to_the_household_which_equals_totals`, `side_by_side_divides_the_odd_cent_and_nets_a_full_refund_to_zero` | `b8_household_parts_and_the_snapshot_reconcile_to_the_cent` | |
| B9 Annual reservations and purchases are not double-counted | Passed | `a_purchase_counts_once_and_leaves_discretionary_by_its_portion`, `a_purchase_within_the_assignment_leaves_discretionary_entirely`, `a_bill_or_loan_payment_made_is_not_reserved` | `b9_a_reserve_purchase_counts_once` | |
| B10 Third paychecks do not increase normal spending targets | Passed | `a_third_paycheck_leaves_every_baseline_line_alike_and_shows_once`, `a_third_paycheck_changes_nothing`, `the_extra_reaches_liquidity_only_as_money_received` | `b10_a_third_paycheck_leaves_the_budget_alike` | |
| B11 Goal allocations cannot silently exceed available funds | Passed | `a_lower_observation_over_assigns_by_exactly_the_difference`, `two_assignments_shown_against_one_observation`, `beyond_the_latest_observation` | `b11_an_over_assignment_is_refused_or_shown` | |
| B12 Graduated payments follow the configured schedule | Passed | `a_six_step_schedule_at_every_step`, `the_amount_due_is_the_period_in_effect_that_day`, `each_state_from_confirmed_transfers_only` | `b12_a_graduated_loan_is_due_its_step_each_period` | The owner's loan documents (D-071) are an input still to come |
| B13 Reports disclose incomplete data and material review issues | Passed | `open_review_items_in_the_month_of_their_transactions`, `uncategorized_spending_is_disclosed_with_its_amount`, `a_shortfall_shows_the_rows_and_safe_to_spend_0`, `every_section_is_present_and_valid` | `b13_an_open_item_and_an_unresolved_row_are_disclosed` | |
| B14 Backups restore records, rules, corrections, and goals | Passed | `a_restored_ledger_shows_everything_alike_over_generated_ledgers`, `a_restored_real_ledger_shows_everything_alike_with_its_originals`, `an_intact_backup_passes_and_nothing_is_written` | `b14_a_restored_household_shows_everything_alike` | Full-scale restore is M21.2's `--everything` |
| B15 Core operation succeeds without internet access | Owner | `no_module_reaches_the_network_or_runs_a_program`, `socket_connect_is_blocked`, `name_lookup_is_blocked` | `b15_the_whole_household_runs_with_the_network_blocked` | Owner: once with the network interface down (D-077 point 1) |

## Shared-contract §6

Every item is decided. [decisions.md](decisions.md)'s "Not yet decided" section is empty (ZA2).

| §6 item | Decided by |
|---|---|
| Database and encryption approach | D-001, D-002 and D-058 |
| Parser strategy | D-018, D-059 and D-060 |
| Deduplication confidence rules | D-005 to D-008, D-026 to D-033 |
| Transfer-matching rules | D-011, D-054 and D-055 |
| Safe-to-spend calculation details | D-072, accepted with M16 |
| Loan projection assumptions | D-071 point 5, accepted with M15 |
| Pairing protocol | D-076 and [sync-protocol.md](sync-protocol.md), built in M20 for review |
| Snapshot compatibility policy | D-075 point 5, accepted with M19 |
| Backup and recovery design | D-058 points 7 and 8 |
| Resource benchmarks | D-034, D-057 and G9, with figures in [benchmarks.md](benchmarks.md) |

## Shared-contract §10, the definition of done

For Phase 1B (M10 to M16: rules, household, income, budgets, funds, loans, safe to spend) and
Phase 1C (M17 to M20: the UI, scenarios, snapshots, sync).

| Item | Phase 1B | Phase 1C |
|---|---|---|
| Reproducible setup | [INSTALL in README.md](../README.md), the clean install of [m1-acceptance.md](m1-acceptance.md); `test_entry_point.py` copies the checkout with only declared dependencies | The same; segno is declared and pinned by hash (D-076) |
| Automated tests | The gating suite; the latest gating run is in [handoff.md](handoff.md) | The same, with the sync suites |
| A synthetic-data demonstration | `test_full_year.py`, B1 to B15 | The same, which ends with a snapshot; the sync runbook's commands under `build/s20/walk1/` |
| Documented assumptions | D-068 to D-072, each with its "How implemented" | D-073 to D-076, each with its "How implemented"; [sync-protocol.md](sync-protocol.md) |
| Migrations | 0021 to 0032, each with its G10 tests | 0033 to 0036, each with its G10 tests |
| Backup and recovery instructions | [real-data-readiness.md](real-data-readiness.md), `pf backup` | The same; a restored ledger pairs again ([sync-runbook.md](sync-runbook.md)) |
| Security and privacy notes | "Network and dependencies" in [status.md](status.md) | The same, and `docs/security-audit.md` (M21.3) |
| Known limitations | [status.md](status.md) | [status.md](status.md) |
| User acceptance checks | **Owner:** the real ledger's migrations 21 to 32, and the inputs D-064 to D-072 list | **Owner:** the real-browser check of M17, migrations 33 to 36, and one real-phone delivery once the iOS app reaches I3 |
