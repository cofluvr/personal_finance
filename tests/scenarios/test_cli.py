"""The commands a person runs, in process, using only synthetic data."""

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from personal_finance import cli
from personal_finance.cli import main
from personal_finance.db.migrate import (
    connect,
    create_database,
    load_migrations,
)
from personal_finance.ingest import pipeline
from personal_finance.reconcile.apply import ReconcileResult

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
    assert "Source rows read: 4 (4 valid, 0 unresolved)" in out
    assert "coverage complete 2026-01-01 to 2026-01-31, posting basis (document_metadata)" in out
    assert "Files attempted: 1 (1 imported, 0 already imported, 0 failed)" in out
    assert "Cross-document duplicates are not checked yet" not in out
    assert "Open review groups: 0, covering 0 distinct affected transactions." in out


def test_repeat_import_summary(db, capsys):
    import_checking(db, CHECKING)
    capsys.readouterr()
    assert import_checking(db, CHECKING) == 0
    assert "already imported, nothing changed" in capsys.readouterr().out


def test_a_failed_file_gives_a_failing_exit_code_and_the_others_still_import(db, capsys):
    assert import_checking(db, CARD, CHECKING) == 1
    out = capsys.readouterr().out
    assert "card_jan_no_metadata.csv: failed (header_mismatch)" in out
    assert "Files attempted: 2 (1 imported, 0 already imported, 1 failed)" in out


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
    assert "Files attempted: 1 (0 imported, 0 already imported, 1 failed)" in out


def test_a_coverage_conflict_explains_the_way_to_declare_and_changes_nothing(db, capsys):
    import_card(db)
    capsys.readouterr()
    main(["totals", "--db", db])
    totals_before = capsys.readouterr().out
    main(["documents", "--db", db])
    documents_before = capsys.readouterr().out

    assert import_card(db, *declaration()) == 1

    out = capsys.readouterr().out
    assert "failed (coverage_conflict)" in out
    assert "differs from the coverage the document already has" in out
    assert "Existing data is unchanged" in out
    assert "review coverage declare" in out
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


def test_account_movement_never_claims_income_or_spending(db, capsys):
    """D-010 binds account movement. Income and spending are their own section (D-056)."""
    import_checking(db, CHECKING)
    import_card(db)
    capsys.readouterr()
    main(["totals", "--db", db])
    out = capsys.readouterr().out
    lowered = out.split("Income and spending, as you classified and matched them:")[0].lower()
    assert "income" not in lowered
    assert "spending" not in lowered
    assert "expense" not in lowered
    # Nothing is classified, so nothing is income or spending.
    assert "  Income: 0 transactions, 0.00\n  Spending: 0 transactions, 0.00\n" in out


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


def test_totals_disclose_what_matching_does_not_guarantee(db, capsys):
    main(["totals", "--db", db])
    out = capsys.readouterr().out
    assert "Rows matched confidently are counted once" in out
    assert "Other duplicates can go undetected" in out
    assert "not checked yet" not in out


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
    assert "1 possible-duplicate groups cover 2 distinct transactions, all counted in full" in out
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


def card_file(tmp_path, name, *rows):
    path = tmp_path / name
    path.write_text("Date,Description,Debit,Credit\n" + "".join(f"{row}\n" for row in rows))
    return path


def import_card_file(db, path, *extra):
    return main(["import", "--db", db, "--account", "Card", "--layout", "synthetic_card_v1",
                 *extra, str(path)])


def daily_rows(days):
    return [f"01/{day:02d}/2026,SYNTHETIC CAFE,5.00," for day in days]


def test_a28_overlapping_items_count_distinct_transactions_and_show_no_adjustment(
    db, tmp_path, capsys
):
    days = range(1, 31)
    import_card_file(db, card_file(tmp_path, "a.csv", *daily_rows(days)))
    import_card_file(db, card_file(tmp_path, "b.csv", *reversed(daily_rows(days))))
    capsys.readouterr()

    main(["totals", "--db", db])
    out = capsys.readouterr().out
    line = next(text for text in out.splitlines() if "possible-duplicate groups" in text)

    assert "cover 60 distinct transactions" in line
    assert "no exact adjustment can be stated" in line
    assert "150.00" not in line and "300.00" not in line

    conn = connect(Path(db))
    memberships = conn.execute(
        """SELECT COUNT(*) FROM review_issue_subject subject
           JOIN review_issue issue ON issue.id = subject.review_issue_id
           WHERE issue.rule = 'cross_document_candidates'"""
    ).fetchone()[0]
    conn.close()
    assert memberships > 60


def test_an_issue_in_two_kinds_of_item_counts_its_transaction_once(db, tmp_path, capsys):
    header = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
    row = "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED\n"
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text(header + row + row)
    second.write_text(header + row)
    import_checking(db, first)
    import_checking(db, second)
    capsys.readouterr()

    main(["totals", "--db", db])
    out = capsys.readouterr().out
    assert "2 possible-duplicate groups cover 3 distinct transactions" in out


def test_review_list_shows_reasons_dates_and_members_without_contents(db, tmp_path, capsys):
    import_card_file(db, card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,"))
    import_card_file(db, card_file(tmp_path, "b.csv", "01/11/2026,SYNTHETIC CAFE,5.00,"))
    capsys.readouterr()

    main(["review", "list", "--db", db])
    out = capsys.readouterr().out

    assert "cross_document_candidates, 2 transactions" in out
    assert "2026-01-10 to 2026-01-11, reasons: similar_description" in out
    assert out.count("  Transaction ") == 2
    assert "SYNTHETIC CAFE" not in out
    assert "5.00" not in out


def test_import_reports_matches(db, tmp_path, capsys):
    declared = declaration()
    import_card_file(db, card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,"), *declared)
    capsys.readouterr()
    second = card_file(
        tmp_path, "b.csv", "01/10/2026,SYNTHETIC CAFE,5.00,", "01/12/2026,SYNTHETIC CAFE,7.00,"
    )
    import_card_file(db, second, *declared)
    out = capsys.readouterr().out
    assert "Source rows read: 2 (2 valid, 0 unresolved)" in out
    assert "Confidently consolidated records: 1" in out
    assert "Net change in live logical transactions: +1" in out


def merged_trace_setup(db, tmp_path):
    declared = declaration()
    import_card_file(db, card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,"), *declared)
    import_card_file(
        db,
        card_file(tmp_path, "b.csv", "01/10/2026,SYNTHETIC CAFE,5.00,", "01/12/2026,OTHER,7.00,"),
        *declared,
    )
    conn = connect(Path(db))
    (retired, survivor) = conn.execute(
        "SELECT from_transaction_id, to_transaction_id FROM transaction_link_history"
    ).fetchone()
    return conn, retired, survivor


def test_trace_separates_current_sources_from_history(db, tmp_path, capsys):
    conn, retired, survivor = merged_trace_setup(db, tmp_path)
    conn.close()
    capsys.readouterr()

    assert main(["trace", "--db", db, survivor]) == 0
    out = capsys.readouterr().out

    current, history = out.split("Historical moves (not current membership):")
    assert current.count("Source ") >= 2
    assert "Current sources:" in current
    assert "Source status: posted" in current
    assert "merged: record" in history
    assert f"from {retired} to {survivor}" in history


def test_trace_names_the_primary_source_and_explains_the_selection(db, tmp_path, capsys):
    header = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text(header + "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,\n")
    second.write_text(header + "S-1,2026-01-09,2026-01-10,FULLER NAME,-5.00,POSTED\n")
    import_checking(db, first)
    import_checking(db, second)
    conn = connect(Path(db))
    transaction_id, primary = conn.execute(
        "SELECT id, primary_source_record_id FROM ledger_transaction"
    ).fetchone()
    conn.close()
    capsys.readouterr()

    main(["trace", "--db", db, transaction_id])
    out = capsys.readouterr().out

    assert "Description: FULLER NAME" in out
    assert out.count("Role: primary, supplies the displayed values") == 1
    assert "Role: alternative, not selected on: settlement status" in out
    assert "'SYNTHETIC CAFE'" in out, "the alternative's evidence stays visible"
    assert "Source status: unknown" in out
    assert f"Displayed values come from record {primary}, chosen by, in order:" in out
    assert "1. read from the source, then completed by hand" in out
    assert "5. lowest document hash, then row number" in out


def test_trace_explains_a_primary_that_was_never_recorded(db, tmp_path, capsys):
    conn, _, survivor = merged_trace_setup(db, tmp_path)
    conn.execute("UPDATE ledger_transaction SET primary_source_record_id = NULL WHERE id = ?", (survivor,))
    conn.close()
    capsys.readouterr()

    main(["trace", "--db", db, survivor])
    out = capsys.readouterr().out
    assert "Displayed values: source not recorded. Run reconcile" in out

    main(["reconcile", "--db", db])
    capsys.readouterr()
    main(["trace", "--db", db, survivor])
    assert "Role: primary" in capsys.readouterr().out


def test_trace_shows_identity_history_apart_from_current_sources(db, tmp_path, capsys):
    conn, retired, _ = merged_trace_setup(db, tmp_path)
    conn.close()
    capsys.readouterr()

    main(["trace", "--db", db, retired])
    out = capsys.readouterr().out
    assert "Identity history:" in out
    assert "retired (exact_coverage_pair), first created" in out


def test_trace_of_a_retired_id_names_its_current_transaction(db, tmp_path, capsys):
    conn, retired, survivor = merged_trace_setup(db, tmp_path)
    conn.close()
    capsys.readouterr()

    assert main(["trace", "--db", db, retired]) == 0
    out = capsys.readouterr().out
    assert f"Transaction {retired} is retired" in out
    assert f"Transaction {survivor}: record" in out


def test_trace_of_a_retired_id_lists_every_resulting_transaction(db, tmp_path, capsys):
    conn, _, survivor = merged_trace_setup(db, tmp_path)
    other = conn.execute(
        "SELECT id FROM ledger_transaction WHERE id <> ?", (survivor,)
    ).fetchone()[0]
    for transaction_id in (survivor, other):
        record = conn.execute(
            "SELECT source_record_id FROM transaction_source WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO transaction_link_history (source_record_id, from_transaction_id,
                                                     to_transaction_id, action, reason,
                                                     rules_fingerprint)
               VALUES (?, 'old-id', ?, 'split', 'evidence_changed', ?)""",
            (record, transaction_id, "a" * 64),
        )
    conn.close()
    capsys.readouterr()

    assert main(["trace", "--db", db, "old-id"]) == 0
    out = capsys.readouterr().out
    assert f"Transaction {survivor}: record" in out
    assert f"Transaction {other}: record" in out


def test_trace_of_an_unknown_id_is_an_error(db, capsys):
    assert main(["trace", "--db", db, "never-existed"]) == 2
    assert "transaction not found" in capsys.readouterr().err


def test_reconcile_catches_up_an_account_without_a_new_file(db, tmp_path, monkeypatch, capsys):
    declared = declaration()
    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "reconcile_account", lambda *args, **kwargs: ReconcileResult(None, 0))
        import_card_file(db, card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,"), *declared)
        import_card_file(
            db,
            card_file(tmp_path, "b.csv", "01/10/2026,SYNTHETIC CAFE,5.00,", "01/12/2026,X,7.00,"),
            *declared,
        )
    capsys.readouterr()

    main(["totals", "--db", db])
    assert "1 accounts have not been reconciled" in capsys.readouterr().out

    assert main(["reconcile", "--db", db]) == 0
    assert "source memberships changed: 1." in capsys.readouterr().out

    main(["totals", "--db", db])
    out = capsys.readouterr().out
    assert "Transactions: 2" in out
    assert "have not been reconciled" not in out


def test_repeat_import_says_when_it_reconciled(db, tmp_path, monkeypatch, capsys):
    path = card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,")
    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "reconcile_account", lambda *args, **kwargs: ReconcileResult(None, 0))
        import_card_file(db, path)
    capsys.readouterr()

    import_card_file(db, path)
    assert "already imported; account reconciled under current rules" in capsys.readouterr().out
    import_card_file(db, path)
    assert "already imported, nothing changed" in capsys.readouterr().out


def old_ledger(tmp_path, versions=2):
    """A ledger created by earlier code, on an earlier schema."""
    old = tmp_path / "old_migrations"
    old.mkdir()
    for migration in load_migrations()[:versions]:
        shutil.copy(migration.path, old / migration.path.name)
    path = tmp_path / "old.db"
    create_database(path, old)
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "name, extra",
    [
        (["documents"], []),
        (["transactions"], []),
        (["review", "list"], []),
        (["review", "show"], ["some-id"]),
        (["totals"], []),
        (["trace"], ["some-id"]),
    ],
)
def test_read_commands_explain_an_old_schema_and_change_nothing(tmp_path, capsys, name, extra):
    path = old_ledger(tmp_path)
    before = digest(path)

    assert main([*name, "--db", str(path), *extra]) == 2

    error = capsys.readouterr().err
    assert "schema version 2" in error
    assert "Nothing was changed" in error
    assert "migrate --db" in error
    assert digest(path) == before


def test_write_commands_also_refuse_an_old_schema(tmp_path, capsys):
    path = old_ledger(tmp_path)
    before = digest(path)

    assert main(["account", "add", "--db", str(path), "--name", "X", "--type", "checking"]) == 2
    assert main(["reconcile", "--db", str(path)]) == 2
    assert main(["import", "--db", str(path), "--account", "X", "--layout", "synthetic_card_v1",
                 str(CARD)]) == 2

    assert "migrate --db" in capsys.readouterr().err
    assert digest(path) == before


def test_a_newer_schema_is_refused_without_change(db, capsys):
    conn = connect(Path(db))
    conn.execute("PRAGMA user_version = 9999")
    conn.close()
    before = digest(Path(db))

    assert main(["totals", "--db", db]) == 2
    assert "newer than this code" in capsys.readouterr().err
    assert digest(Path(db)) == before


@pytest.mark.parametrize("command", [["documents"], ["transactions"], ["totals"]])
def test_read_commands_leave_a_current_ledger_byte_identical(db, capsys, command):
    import_card(db)
    before = digest(Path(db))
    assert main([*command, "--db", db]) == 0
    assert digest(Path(db)) == before


def test_read_commands_open_the_ledger_read_only(db, monkeypatch):
    opened = []

    def recording_connect(path, *, read_only=False):
        opened.append(read_only)
        return connect(path, read_only=read_only)

    monkeypatch.setattr(cli, "connect", recording_connect)
    main(["totals", "--db", db])
    main(["documents", "--db", db])
    assert opened == [True, True]


def test_a_read_only_connection_cannot_write(db):
    conn = connect(Path(db), read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO import_run (id) VALUES ('x')")
    conn.close()


def test_migrate_upgrades_and_says_grouping_is_unchanged(tmp_path, capsys):
    path = old_ledger(tmp_path)

    assert main(["migrate", "--db", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"Upgraded from schema version 2 to {len(load_migrations())}" in out
    assert "Transaction grouping was not changed. Run reconcile" in out

    assert main(["migrate", "--db", str(path)]) == 0
    assert "Already at schema version" in capsys.readouterr().out


def test_migrate_refuses_a_missing_ledger(tmp_path, capsys):
    assert main(["migrate", "--db", str(tmp_path / "missing.db")]) == 2
    assert "database not found" in capsys.readouterr().err
    assert not (tmp_path / "missing.db").exists()


def test_a_failed_migration_reports_where_the_ledger_stands(tmp_path, monkeypatch, capsys):
    path = old_ledger(tmp_path)

    def failing(conn):
        raise sqlite3.IntegrityError("injected")

    monkeypatch.setattr(cli, "migrate", failing)
    assert main(["migrate", "--db", str(path)]) == 2
    error = capsys.readouterr().err
    assert "migration failed at schema version 2" in error
    assert "Run migrate again" in error


def impatient_connect(path, *, read_only=False):
    conn = connect(path, read_only=read_only)
    conn.execute("PRAGMA busy_timeout = 50")
    return conn


def test_a_busy_import_is_reported_as_a_failure_with_what_to_do(db, tmp_path, monkeypatch, capsys):
    path = card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,")
    monkeypatch.setattr(cli, "connect", impatient_connect)
    holder = connect(Path(db))
    holder.execute("BEGIN IMMEDIATE")

    code = import_card_file(db, path)
    holder.execute("ROLLBACK")

    captured = capsys.readouterr()
    assert code == 2
    assert "database is busy" in captured.err
    assert "changed nothing" in captured.err
    assert "run this command again" in captured.err
    assert "imported" not in captured.out

    assert import_card_file(db, path) == 0
    assert "Source rows read: 1 (1 valid, 0 unresolved)" in capsys.readouterr().out


def test_a_file_blocked_at_commit_is_reported_and_the_exit_code_shows_it(
    db, tmp_path, monkeypatch, capsys
):
    path = card_file(tmp_path, "a.csv", "01/10/2026,SYNTHETIC CAFE,5.00,")
    monkeypatch.setattr(cli, "connect", impatient_connect)
    reader = connect(Path(db), read_only=True)
    original = pipeline.reconcile_account

    def reader_arrives_during_reconciliation(*args, **kwargs):
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM account").fetchone()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "reconcile_account", reader_arrives_during_reconciliation)

    code = import_card_file(db, path)
    reader.execute("ROLLBACK")
    reader.close()

    out = capsys.readouterr().out
    assert code == 1
    assert "failed (database_busy)" in out
    assert "nothing from it was kept" in out
    assert "import the file again" in out
    assert "Files attempted: 1 (0 imported, 0 already imported, 1 failed)" in out

    conn = connect(Path(db))
    assert conn.execute("SELECT COUNT(*) FROM source_document").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone() == (0,)
    conn.close()
    monkeypatch.undo()
    assert import_card_file(db, path) == 0


def test_a_busy_reconcile_changes_nothing_and_says_so(db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect", impatient_connect)
    holder = connect(Path(db))
    holder.execute("BEGIN IMMEDIATE")

    code = main(["reconcile", "--db", db])
    holder.execute("ROLLBACK")

    assert code == 2
    assert "changed nothing" in capsys.readouterr().err


def test_a_busy_migration_says_busy_and_can_be_retried(tmp_path, monkeypatch, capsys):
    path = old_ledger(tmp_path)
    before = digest(path)
    monkeypatch.setattr(cli, "connect", impatient_connect)
    holder = connect(path)
    holder.execute("BEGIN IMMEDIATE")

    code = main(["migrate", "--db", str(path)])
    holder.execute("ROLLBACK")
    holder.close()

    error = capsys.readouterr().err
    assert code == 2
    assert "database is busy" in error
    assert "migration failed" not in error
    assert digest(path) == before
    assert main(["migrate", "--db", str(path)]) == 0


def test_trace_does_not_present_a_fallback_timestamp_as_exact(db, tmp_path, capsys):
    header = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
    rows = (
        "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,\n",
        "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED\n",
        "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED\n",
    )
    files = []
    for number, row in enumerate(rows):
        path = tmp_path / f"{number}.csv"
        path.write_text(header + row)
        files.append(path)
    import_checking(db, files[0])
    import_checking(db, files[1])

    conn = connect(Path(db))
    retired = conn.execute("SELECT from_transaction_id FROM transaction_link_history").fetchone()[0]
    # Stand in for an ID retired before migration 0004, which left no identity record.
    conn.executescript(
        """DROP TRIGGER transaction_identity_history_no_delete;
           DELETE FROM transaction_identity_history;"""
    )
    conn.close()
    import_checking(db, files[2])
    capsys.readouterr()

    main(["trace", "--db", db, retired])
    out = capsys.readouterr().out
    assert "first created approximately, from its link time, not an exact record:" in out
    assert "), first created 2" not in out
