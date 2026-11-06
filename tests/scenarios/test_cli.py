"""The commands a person runs, in process, using only synthetic data."""

from pathlib import Path

import pytest

from personal_finance.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"
CHECKING = FIXTURES / "checking_jan_complete.csv"
CARD = FIXTURES / "card_jan_no_metadata.csv"
PROBLEMS = FIXTURES / "checking_problem_rows.csv"


@pytest.fixture
def db(tmp_path, capsys):
    path = tmp_path / "ledger.db"
    assert main(["init", "--db", str(path)]) == 0
    assert main(["account", "add", "--db", str(path), "--name", "Checking", "--type", "checking"]) == 0
    assert main(["account", "add", "--db", str(path), "--name", "Card", "--type", "credit_card"]) == 0
    capsys.readouterr()
    return str(path)


def import_checking(db, *files):
    return main(["import", "--db", db, "--account", "Checking",
                 "--layout", "synthetic_checking_v1", *map(str, files)])


def import_card(db, *extra):
    return main(["import", "--db", db, "--account", "Card", "--layout", "synthetic_card_v1",
                 *extra, str(CARD)])


def declaration(start="2026-01-01", end="2026-01-31", basis="posting"):
    return ["--declare-complete-coverage", "--coverage-start", start, "--coverage-end", end,
            "--coverage-basis", basis]


def test_init_refuses_to_overwrite(tmp_path, capsys):
    path = tmp_path / "ledger.db"
    path.write_text("existing work")
    assert main(["init", "--db", str(path)]) == 2
    assert path.read_text() == "existing work"
    assert "refusing to overwrite" in capsys.readouterr().err


def test_a_missing_database_is_an_error_not_a_new_ledger(tmp_path, capsys):
    path = tmp_path / "missing.db"
    assert main(["totals", "--db", str(path)]) == 2
    assert not path.exists()
    assert "database not found" in capsys.readouterr().err


def test_an_unknown_account_is_refused(db, capsys):
    code = main(["import", "--db", db, "--account", "Nope", "--layout", "synthetic_card_v1", str(CARD)])
    assert code == 2
    assert "account not found" in capsys.readouterr().err


def test_a_duplicate_account_name_is_refused(db, capsys):
    assert main(["account", "add", "--db", db, "--name", "Card", "--type", "checking"]) == 2


def test_import_summary(db, capsys):
    assert import_checking(db, CHECKING) == 0
    out = capsys.readouterr().out
    assert "imported 4 rows: 4 transactions, 0 unresolved, 0 possible-duplicate groups" in out
    assert "coverage complete 2026-01-01 to 2026-01-31, posting basis (document_metadata)" in out
    assert "Files: 1 imported, 0 already imported, 0 failed" in out
    assert "Cross-document duplicates are not checked yet" in out


def test_repeat_import_summary(db, capsys):
    import_checking(db, CHECKING)
    capsys.readouterr()
    assert import_checking(db, CHECKING) == 0
    assert "already imported, nothing changed" in capsys.readouterr().out


def test_a_failed_file_gives_a_failing_exit_code_and_the_others_still_import(db, capsys):
    assert import_checking(db, CARD, CHECKING) == 1
    out = capsys.readouterr().out
    assert "card_jan_no_metadata.csv: failed (header_mismatch)" in out
    assert "Files: 1 imported, 0 already imported, 1 failed" in out


def test_a_file_for_another_account_is_rejected_not_skipped(db, capsys):
    import_card(db)
    capsys.readouterr()

    code = main(["import", "--db", db, "--account", "Checking", "--layout", "synthetic_card_v1",
                 str(CARD)])

    out = capsys.readouterr().out
    assert code == 1
    assert "failed (account_mismatch)" in out
    assert "already imported for a different account" in out
    assert "was not linked to the requested account" in out
    assert "existing import is unchanged" in out
    assert "nothing changed" not in out
    assert "Files: 0 imported, 0 already imported, 1 failed" in out


def test_a_coverage_conflict_explains_the_limitation_and_changes_nothing(db, capsys):
    import_card(db)
    capsys.readouterr()
    main(["totals", "--db", db])
    totals_before = capsys.readouterr().out
    main(["documents", "--db", db])
    documents_before = capsys.readouterr().out

    assert import_card(db, *declaration()) == 1

    out = capsys.readouterr().out
    assert "failed (coverage_conflict)" in out
    assert "Coverage is fixed when a document is first imported" in out
    assert "Existing data is unchanged" in out
    assert "M2" in out
    assert "delete" not in out.lower()
    assert "sql" not in out.lower()
    main(["totals", "--db", db])
    assert capsys.readouterr().out == totals_before
    main(["documents", "--db", db])
    assert capsys.readouterr().out == documents_before


def test_totals_use_account_movement_terms(db, capsys):
    import_checking(db, CHECKING)
    capsys.readouterr()
    assert main(["totals", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "Account inflows: 2500.00" in out
    assert "Account outflows: 209.05" in out
    assert "Net account movement: 2290.95" in out
    assert "Transactions: 4, of which pending: 1" in out


def test_totals_never_claim_income_or_spending(db, capsys):
    import_checking(db, CHECKING)
    import_card(db)
    capsys.readouterr()
    main(["totals", "--db", db])
    lowered = capsys.readouterr().out.lower()
    assert "income" not in lowered
    assert "spending" not in lowered
    assert "expense" not in lowered


def test_totals_for_one_account(db, capsys):
    import_checking(db, CHECKING)
    import_card(db)
    capsys.readouterr()
    assert main(["totals", "--db", db, "--account", "Card"]) == 0
    out = capsys.readouterr().out
    assert "Account inflows: 30.00" in out
    assert "Account outflows: 43.00" in out


def test_totals_on_an_empty_ledger_are_zero(db, capsys):
    assert main(["totals", "--db", db]) == 0
    assert "Net account movement: 0.00" in capsys.readouterr().out


def test_totals_disclose_that_overlaps_are_not_checked(db, capsys):
    main(["totals", "--db", db])
    assert "Cross-document duplicates are not checked yet" in capsys.readouterr().out


def test_totals_disclose_unresolved_rows(db, capsys):
    import_checking(db, PROBLEMS)
    capsys.readouterr()
    main(["totals", "--db", db])
    assert "4 unresolved records are not included" in capsys.readouterr().out


def test_totals_do_not_present_an_exact_adjustment(db, tmp_path, capsys):
    path = tmp_path / "x.csv"
    path.write_text(
        "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
        "SYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\n"
        "SYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\n"
    )
    import_checking(db, path)
    capsys.readouterr()
    main(["totals", "--db", db])
    out = capsys.readouterr().out
    assert "1 possible-duplicate groups cover 2 transactions, all counted in full" in out
    assert "Totals may be overstated, and no exact adjustment can be stated" in out


def test_declared_coverage_is_shown_as_user_supplied(db, capsys):
    assert import_card(db, *declaration()) == 0
    capsys.readouterr()
    main(["documents", "--db", db])
    out = capsys.readouterr().out
    assert "coverage complete 2026-01-01 to 2026-01-31, posting basis, evidence user_declared" in out
    assert "pending excluded" in out


def test_documents_show_unknown_coverage(db, capsys):
    import_card(db)
    capsys.readouterr()
    main(["documents", "--db", db])
    assert "coverage unknown" in capsys.readouterr().out


def test_documents_state_pending_treatment_per_basis(db, tmp_path, capsys):
    path = tmp_path / "x.csv"
    path.write_text(
        "# coverage-kind: complete\n# coverage-start: 2026-01-01\n# coverage-end: 2026-01-31\n"
        "# coverage-basis: transaction\n"
        "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
    )
    import_checking(db, path)
    capsys.readouterr()
    main(["documents", "--db", db])
    assert "pending included" in capsys.readouterr().out


@pytest.mark.parametrize(
    "options",
    [
        ["--declare-complete-coverage"],
        ["--declare-complete-coverage", "--coverage-start", "2026-01-01"],
        ["--declare-complete-coverage", "--coverage-start", "2026-01-01",
         "--coverage-end", "2026-01-31"],
        ["--coverage-start", "2026-01-01", "--coverage-end", "2026-01-31",
         "--coverage-basis", "posting"],
        ["--coverage-start", "2026-01-01"],
    ],
)
def test_a_declaration_must_be_complete_and_explicit(db, capsys, options):
    assert import_card(db, *options) == 2
    assert "coverage" in capsys.readouterr().err
    main(["documents", "--db", db])
    assert "No documents." in capsys.readouterr().out


def test_an_invalid_declared_interval_is_refused(db, capsys):
    assert import_card(db, *declaration("2026-02-01", "2026-01-01")) == 2
    assert "invalid_coverage_declaration" in capsys.readouterr().err


def test_a_declaration_applies_to_exactly_one_file(db, capsys):
    code = main(["import", "--db", db, "--account", "Card", "--layout", "synthetic_card_v1",
                 *declaration(), str(CARD), str(CHECKING)])
    assert code == 2
    assert "exactly one file" in capsys.readouterr().err


def test_review_list_shows_reasons_without_row_contents(db, capsys):
    import_checking(db, PROBLEMS)
    capsys.readouterr()
    main(["review", "list", "--db", db])
    out = capsys.readouterr().out
    assert "unresolved_record: missing_amount, checking_problem_rows.csv row 1" in out
    assert "unresolved_record: wrong_column_count, checking_problem_rows.csv row 6" in out
    assert "Open review items: 4" in out
    assert "SYNTHETIC" not in out
    assert "10.005" not in out


def test_trace_leads_from_a_transaction_to_its_source(db, capsys):
    import_checking(db, CHECKING)
    capsys.readouterr()
    main(["transactions", "--db", db])
    line = next(l for l in capsys.readouterr().out.splitlines() if "SYNTHETIC GROCER" in l)
    assert main(["trace", "--db", db, line.split()[0]]) == 0
    out = capsys.readouterr().out
    assert "Source checking_jan_complete.csv, row 2" in out
    assert "Amount: -82.15" in out
    assert "Link rule: new_record" in out
    assert "'SYN-1002'" in out


def test_trace_shows_missing_values_as_missing(db, capsys):
    import_checking(db, CHECKING)
    capsys.readouterr()
    main(["transactions", "--db", db])
    line = next(l for l in capsys.readouterr().out.splitlines() if "SYNTHETIC CAFE" in l)
    main(["trace", "--db", db, line.split()[0]])
    assert "Posting date: missing" in capsys.readouterr().out


def test_trace_of_an_unknown_transaction_is_an_error(db, capsys):
    assert main(["trace", "--db", db, "nope"]) == 2


def test_import_output_contains_no_row_contents(db, tmp_path, capsys):
    path = tmp_path / "x.csv"
    path.write_text(
        "Date,Description,Debit,Credit\n"
        "01/05/2026,SENTINEL-MERCHANT,98765.43,\n"
        "01/06/2026,SENTINEL-MERCHANT,not-a-number,\n"
    )
    main(["import", "--db", db, "--account", "Card", "--layout", "synthetic_card_v1", str(path)])
    captured = capsys.readouterr()
    assert "SENTINEL" not in captured.out + captured.err
    assert "98765" not in captured.out + captured.err


def test_a_failed_file_reports_only_a_code(db, tmp_path, capsys):
    path = tmp_path / "x.csv"
    path.write_text("SENTINEL-HEADER,98765.43\n")
    main(["import", "--db", db, "--account", "Card", "--layout", "synthetic_card_v1", str(path)])
    captured = capsys.readouterr()
    assert "SENTINEL" not in captured.out + captured.err
    assert "header_mismatch" in captured.out
