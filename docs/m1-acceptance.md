# M1 Acceptance Matrix

Each criterion in [plan.md](plan.md) is listed with the tests that support it. One test can
support several criteria. `tests/unit/test_acceptance_matrix.py` fails if a criterion is
missing here or a named test does not exist. It does not judge whether a test is sufficient.

- **Passed:** the named tests pass, and the rule is proven end to end for synthetic data.
- **Deferred:** planned for a named later milestone.
- **Unverified:** not executed. Nothing should be inferred about it.

## Criteria

| ID | Status | Tests | Limit |
|---|---|---|---|
| A1 | Passed | `a1_a38_repeat_imports_change_nothing`, `identical_file_changes_nothing` | |
| A2 | Passed | `a2_a_reordered_export_adds_no_transactions`, `a2_with_reliable_ids` | |
| A3 | Passed | `a3_overlapping_periods_count_the_overlap_once` | CSV to CSV. CSV to PDF is M7 |
| A4 | Passed | `a4_identical_purchases_survive_an_overlapping_file`, `identical_purchases_in_one_file_stay_distinct` | |
| A5a | Passed | `a5a_two_against_three_with_complete_coverage`, `two_rows_against_three_give_exactly_three_transactions` | |
| A5b | Passed | `a5b_all_records_stay_separate_in_one_item`, `totals_do_not_present_an_exact_adjustment` | |
| A6 | Passed | `a6_a_near_match_is_kept_counted_and_listed` | |
| A7 | Passed | `a7_a_conflicting_amount_is_flagged` | |
| A8 | Passed | `a8_the_same_rows_in_two_accounts_never_match` | |
| A9 | Passed | `unresolved_rows_create_no_transactions`, `a_blank_amount_is_null_not_zero` | |
| A10 | Passed | `zero_stays_zero_and_a_missing_date_stays_missing`, `zero_is_distinct_from_missing` | |
| A11 | Passed | `sub_cent_precision_is_rejected_not_rounded`, `malformed_amounts_are_rejected`, `unresolved_rows_are_queued_with_their_reasons` | |
| A12 | Passed | `a_thousand_dimes_total_exactly`, `the_two_layouts_agree_on_the_sign_of_money_out` | |
| A13 | Passed | `every_transaction_traces_to_its_source`, `row_numbers_lead_back_to_the_original_cells` | |
| A14 | Passed | `a_bad_file_does_not_stop_the_others`, `wrong_layout_fails_and_leaves_nothing` | |
| A15 | Passed | `simultaneous_imports_count_each_file_once` | |
| A16 | Passed | `a16_every_order_gives_the_same_outcome`, `a16_every_order_gives_the_same_outcome_on_the_hard_paths`, `a16_every_arrival_order_of_a_splitting_id_group_agrees` | |
| A17 | Passed | `file_outcomes_reconcile_to_files_attempted`, `rows_read_are_valid_plus_unresolved`, `units_hold_for_any_run_including_splits_and_repeats`, `a_split_shows_records_accepted_are_not_transactions_created`, `account_review_totals_are_final_state_not_sums_of_files`, `an_unreadable_file_has_no_row_count`, `rolled_back_rows_are_not_committed_or_added_to_rows_read`, `unresolved_records_stay_disclosed_for_the_account` | |
| A18 | Passed | `import_and_summary_commands_expose_nothing`, `a_full_session_leaves_only_the_ledger_and_its_support_files`, `an_unexpected_error_leaves_no_traceback_or_dump`, `source_rule_no_logging_or_diagnostic_modules` | M1 has no logs, so this proves their absence and clean output, not a redacting logger |
| A19 | Passed | `socket_connect_is_blocked`, `name_lookup_is_blocked`, `high_level_clients_are_blocked` | Python sockets in the test process only, not subprocesses or native code |
| A20 | Passed | `a20_a_reliable_id_needs_no_coverage` | |
| A21 | Passed | `a21_an_unreliable_id_is_not_identity` | |
| A22 | Passed | `a22_a_single_day_overlap_stays_flagged_when_declared` | |
| A23 | Passed | `rows_never_become_coverage`, `inferred_is_not_an_accepted_evidence_type` | |
| A24 | Passed | `a24_different_date_bases_are_flagged` | |
| A25 | Passed | `totals_use_account_movement_terms`, `totals_never_claim_income_or_spending`, `summaries_do_not_use_the_retired_vocabulary` | |
| A26 | Passed | `a_declaration_is_recorded_as_user_supplied`, `a_declaration_must_be_complete_and_explicit` | |
| A27 | Passed | `a27_rows_without_a_counterpart_are_not_flagged` | |
| A28 | Passed | `a28_overlapping_items_count_distinct_transactions_and_show_no_adjustment` | |
| A29 | Passed | `a_repeated_external_id_stays_visible_and_counted` | |
| A30 | Passed | `pending_and_posted_versions_stay_visible_and_counted` | Flagging only. Reconciling them is M2 |
| A31 | Passed | `a_failure_at_any_step_leaves_no_partial_data`, `a_process_crash_mid_import_leaves_no_partial_data` | |
| A32 | Passed | `a32_a_user_declared_end_date_is_confident` | |
| A33 | Passed | `a33_a_metadata_end_date_is_not_assumed_complete`, `a33_contrast_a_passed_end_date_is_confident` | |
| A34 | Passed | `a34_a_conflicting_date_or_status_is_flagged`, `a34_an_id_repeated_within_a_document_is_flagged` | |
| A35 | Passed | `a35_an_unresolved_row_keeps_the_match_possible`, `a35_contrast_an_unrelated_unresolved_row_changes_nothing` | |
| A36 | Passed | `a36_every_source_stays_linked_and_evidence_is_unchanged` | |
| A37 | Passed | `a37_a_failure_at_any_stage_leaves_no_partial_state`, `a37_a_process_crash_during_matching_leaves_no_partial_state` | |
| A38 | Passed | `a1_a38_repeat_imports_change_nothing` | |
| A39 | Passed | `a39_work_grows_in_step_with_rows_for_these_shapes`, `a39_dense_data_does_no_all_pairs_work`, `a39_dense_groups_store_members_rather_than_pairs` | Documented fixtures only, in which nothing merges. Timing benchmarks are not test assertions. See F3 |
| A40 | Passed | `identical_content_for_another_account_is_refused`, `a_rejected_account_association_preserves_the_existing_import` | |
| A41 | Passed | `complete_coverage_does_not_hide_unresolved_rows`, `complete_coverage_does_not_create_a_transaction_for_a_bad_row` | |
| A42 | Passed | `a42_unrelated_purchases_create_nothing` | |
| A43 | Passed | `a43_a_variation_is_flagged_and_never_merged` | |
| A44 | Passed | `a44_an_id_match_needs_no_similar_description`, `similarity_never_merges_even_under_complete_coverage` | |
| A45 | Passed | `a45_a_reliable_id_is_confident_on_a_single_day_overlap` | |
| A46 | Passed | `a46_unknown_status_stays_unknown_in_its_source` | |

## Completion conditions

From "M1 acceptance criteria" in [plan.md](plan.md).

| Condition | Status | Evidence |
|---|---|---|
| All tests pass | Passed | See "Tests actually executed" in [handoff.md](handoff.md) |
| A new-setup run works from the README | **Unverified** | The README walkthrough and a source checkout passed using existing environments. Installing from `requirements-dev.txt` in a clean environment needs network access and was not performed |
| The decision log records the database, parser and deduplication rules | Passed | D-001, D-018, D-005 to D-008 and D-026 to D-033 |

## Deferred and unverified

| Item | Status | Where |
|---|---|---|
| Clean install from `requirements-dev.txt` | Unverified | Needs one approved network run |
| `pip install` of the package and its `pf` script | Unverified | Needs setuptools. Only checked statically |
| Merge-heavy performance (F3) | Deferred | Backlog in [plan.md](plan.md) |
| Pending and posted reconciliation, resolving review items, undoing merges | Deferred | M2 |
| Correcting coverage after import | Deferred | M2 |
| CSV-to-PDF matching | Deferred | M7 |
| Remote state and repository visibility | Unverified | GitHub was not contacted |
