"""Import summaries keep their units apart (A17, D-036), using only synthetic data."""

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_import_order import CHECKING_HEADER, File, card_file, checking_file

from personal_finance.cli import main
from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest import pipeline
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile.apply import ReconcileResult
from personal_finance.reports.import_summary import summarize_run
from personal_finance.reports.totals import account_movement

CARD_HEADER = "Date,Description,Debit,Credit\n"
CAFE = "01/10/2026,SYNTHETIC CAFE,4.00,"
UNKNOWN = "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,"
POSTED_ONE = "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"
POSTED_TWO = "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED"
OTHER = "S-9,2026-01-20,2026-01-21,SYNTHETIC GROCER,-9.00,POSTED"
COVERED = "# coverage-kind: complete\n# coverage-start: 2026-01-01\n# coverage-end: 2026-01-31\n"
COVERED += "# coverage-basis: posting\n# generated-on: 2026-02-05\n"


@pytest.fixture
def db(tmp_path, capsys):
    path = tmp_path / "ledger.db"
    assert main(["init", "--db", str(path)]) == 0
    assert main(["account", "add", "--db", str(path), "--name", "Checking", "--type", "checking"]) == 0
    assert main(["account", "add", "--db", str(path), "--name", "Card", "--type", "credit_card"]) == 0
    capsys.readouterr()
    return str(path)


def write(tmp_path, name, header, *rows):
    path = tmp_path / name
    path.write_text(header + "".join(f"{row}\n" for row in rows))
    return path


def checking(tmp_path, name, *rows):
    return write(tmp_path, name, CHECKING_HEADER, *rows)


def card(tmp_path, name, *rows):
    return write(tmp_path, name, CARD_HEADER, *rows)


def run(db, capsys, account, *files, extra=()):
    layout = {"Checking": "synthetic_checking_v1", "Card": "synthetic_card_v1"}[account]
    code = main(["import", "--db", db, "--account", account, "--layout", layout, *extra,
                 *map(str, files)])
    return code, capsys.readouterr().out


def section(out, heading):
    """The indented lines under one heading of the output."""
    lines = out.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith(heading))
    body = []
    for line in lines[start + 1:]:
        if not line.startswith("  "):
            break
        body.append(line.strip())
    return body


def declaration():
    return ["--declare-complete-coverage", "--coverage-start", "2026-01-01", "--coverage-end",
            "2026-01-31", "--coverage-basis", "posting"]


class TestFiles:
    def test_file_outcomes_reconcile_to_files_attempted(self, db, tmp_path, capsys):
        good = checking(tmp_path, "good.csv", POSTED_ONE)
        bad = tmp_path / "bad.csv"
        bad.write_text("not,the,header\n")
        code, out = run(db, capsys, "Checking", good, good, bad, tmp_path / "missing.csv")

        assert code == 1
        assert "Files attempted: 4 (1 imported, 1 already imported, 2 failed)" in out

    def test_a_run_with_no_failure_exits_zero(self, db, tmp_path, capsys):
        good = checking(tmp_path, "good.csv", POSTED_ONE)
        assert run(db, capsys, "Checking", good, good)[0] == 0


class TestRows:
    def test_rows_read_are_valid_plus_unresolved(self, db, tmp_path, capsys):
        path = card(tmp_path, "a.csv", CAFE, "01/11/2026,SYNTHETIC CAFE,,", "too few cells")
        out = run(db, capsys, "Card", path)[1]
        assert "Source rows read: 3 (1 valid, 2 unresolved)" in section(out, "a.csv")
        assert "Source rows read: 3 (1 valid, 2 unresolved)" in section(out, "Run summary")

    def test_blank_lines_are_not_rows_but_whitespace_is(self, db, tmp_path, capsys):
        path = card(tmp_path, "a.csv", CAFE, "", "", "   ", ",,,")
        assert "Source rows read: 3 (1 valid, 2 unresolved)" in run(db, capsys, "Card", path)[1]

    def test_a_header_only_file_really_has_no_rows(self, db, tmp_path, capsys):
        out = run(db, capsys, "Card", card(tmp_path, "a.csv"))[1]
        assert "Source rows read: 0 (0 valid, 0 unresolved)" in section(out, "a.csv")

    def test_an_already_imported_file_reports_no_row_counts(self, db, tmp_path, capsys):
        path = card(tmp_path, "a.csv", CAFE)
        run(db, capsys, "Card", path)
        out = run(db, capsys, "Card", path)[1]
        assert "a.csv: already imported, nothing changed" in out
        assert "Source rows: none, because no file was newly imported" in out
        assert "Source rows read" not in out

    def test_stored_records_match_the_reported_rows(self, db, tmp_path, capsys):
        path = card(tmp_path, "a.csv", CAFE, "01/11/2026,SYNTHETIC CAFE,,")
        run(db, capsys, "Card", path)
        conn = connect(Path(db))
        assert conn.execute(
            "SELECT status, COUNT(*) FROM record_parse GROUP BY status ORDER BY status"
        ).fetchall() == [("parsed", 1), ("unresolved", 1)]


class TestFailedFiles:
    def test_an_unreadable_file_has_no_row_count(self, db, tmp_path, capsys):
        out = run(db, capsys, "Card", tmp_path / "missing.csv")[1]
        assert section(out, "missing.csv") == ["Source rows: unavailable"]
        assert "Failed files with row counts unavailable: 1" in out
        assert "Source rows: none, because no file was newly imported" in out
        assert "0 read" not in out

    def test_a_file_that_cannot_be_parsed_has_no_row_count(self, db, tmp_path, capsys):
        path = tmp_path / "bad.csv"
        path.write_text("not,the,header\n1,2,3\n")
        assert "Source rows: unavailable" in section(run(db, capsys, "Card", path)[1], "bad.csv")

    def test_a_file_parsed_then_refused_has_a_known_attempted_count(self, db, tmp_path, capsys):
        path = write(tmp_path, "a.csv", COVERED + CHECKING_HEADER, POSTED_ONE, "bad row")
        code, out = run(db, capsys, "Checking", path, extra=declaration())

        assert code == 1
        assert "a.csv: failed (coverage_conflict)" in out
        assert "Source rows: 2 read, then rolled back. None were kept." in section(out, "a.csv")
        assert "Failed files: 2 rows read, then rolled back. None were kept." in out
        assert "Unresolved records, not included in totals: 0" in out

    def test_rolled_back_rows_are_not_committed_or_added_to_rows_read(self, db, tmp_path, capsys):
        good = checking(tmp_path, "good.csv", POSTED_ONE)
        original = pipeline.reconcile_account

        def fail_on_the_second_file(conn, account_id, rules, trigger_document_id=None):
            name = conn.execute(
                "SELECT file_name FROM source_document WHERE id = ?", (trigger_document_id,)
            ).fetchone()[0]
            if name == "fails.csv":
                raise RuntimeError("synthetic failure")
            return original(conn, account_id, rules, trigger_document_id=trigger_document_id)

        failing = checking(tmp_path, "fails.csv", POSTED_TWO.replace("S-1", "S-2"), "S-3,,,,,")
        pipeline_patch = pytest.MonkeyPatch()
        pipeline_patch.setattr(pipeline, "reconcile_account", fail_on_the_second_file)
        try:
            code, out = run(db, capsys, "Checking", good, failing)
        finally:
            pipeline_patch.undo()

        summary = section(out, "Run summary")
        assert code == 1
        assert "Source rows read: 1 (1 valid, 0 unresolved)" in summary
        assert "Failed files: 2 rows read, then rolled back. None were kept." in summary
        assert "Net change in live logical transactions: +1" in summary
        assert "failed (internal_error)" in out
        conn = connect(Path(db))
        assert conn.execute("SELECT COUNT(*) FROM source_record").fetchone() == (1,)

    def test_a_file_already_imported_elsewhere_is_not_reread(self, db, tmp_path, capsys):
        path = card(tmp_path, "a.csv", CAFE)
        run(db, capsys, "Card", path)
        out = run(db, capsys, "Checking", path.with_name("a.csv"))[1]
        assert "failed" in out
        assert "Source rows: unavailable" in section(out, "a.csv")


class TestLedgerEffect:
    def test_a_split_shows_records_accepted_are_not_transactions_created(self, db, tmp_path, capsys):
        run(db, capsys, "Checking", checking(tmp_path, "a.csv", UNKNOWN))
        run(db, capsys, "Checking", checking(tmp_path, "b.csv", POSTED_ONE))
        out = run(db, capsys, "Checking", checking(tmp_path, "c.csv", POSTED_TWO))[1]

        file_lines = section(out, "c.csv")
        assert "Source rows read: 1 (1 valid, 0 unresolved)" in file_lines
        assert "Final logical transactions for those valid records: 1" in file_lines
        assert "Confidently consolidated records: 0" in file_lines
        assert "Net change in live logical transactions: +2" in file_lines
        assert "Source memberships changed: 1" in file_lines
        assert account_movement(connect(Path(db))).transactions == 3

    def test_a_full_overlap_accepts_records_and_adds_no_transactions(self, db, tmp_path, capsys):
        run(db, capsys, "Checking", checking(tmp_path, "a.csv", POSTED_ONE))
        again = checking(tmp_path, "b.csv", POSTED_ONE, "")
        out = run(db, capsys, "Checking", again)[1]

        file_lines = section(out, "b.csv")
        assert "Source rows read: 1 (1 valid, 0 unresolved)" in file_lines
        assert "Confidently consolidated records: 1" in file_lines
        assert "Net change in live logical transactions: +0" in file_lines
        assert "Source memberships changed: 1" in file_lines

    def test_the_run_reads_final_state_after_a_later_file_consolidates_an_earlier_one(
        self, db, tmp_path, capsys
    ):
        first = checking(tmp_path, "a.csv", POSTED_ONE)
        second = checking(tmp_path, "b.csv", POSTED_ONE, OTHER)
        out = run(db, capsys, "Checking", first, second)[1]

        assert "Each file's counts describe the moment it was imported." in out
        assert "Confidently consolidated records: 0" in section(out, "a.csv")
        assert "Confidently consolidated records: 1" in section(out, "b.csv")
        summary = section(out, "Run summary")
        assert "Source rows read: 3 (3 valid, 0 unresolved)" in summary
        assert "Final logical transactions for those valid records: 2" in summary
        assert "Confidently consolidated records: 2" in summary
        assert "Net change in live logical transactions: +2" in summary

    def test_a_repeat_import_that_reconciles_reports_its_effect(
        self, db, tmp_path, capsys, monkeypatch
    ):
        first = checking(tmp_path, "a.csv", POSTED_ONE)
        second = checking(tmp_path, "b.csv", POSTED_ONE, OTHER)
        with monkeypatch.context() as patch:
            patch.setattr(pipeline, "reconcile_account", lambda *a, **k: ReconcileResult(None, 0))
            run(db, capsys, "Checking", first, second)

        out = run(db, capsys, "Checking", first)[1]

        assert "a.csv: already imported; account reconciled under current rules" in out
        assert "Net change in live logical transactions: -1" in section(out, "a.csv")
        assert "Source memberships changed: 1" in section(out, "a.csv")
        assert "Net change in live logical transactions: -1" in section(out, "Run summary")
        assert "Source memberships changed: 1" in section(out, "Run summary")


class TestReview:
    def test_account_review_totals_are_final_state_not_sums_of_files(self, db, tmp_path, capsys):
        files = [
            card(tmp_path, "a.csv", CAFE),
            card(tmp_path, "b.csv", CAFE, "01/11/2026,FILLER ONE,1.00,"),
            card(tmp_path, "c.csv", CAFE, "01/12/2026,FILLER TWO,1.00,"),
        ]
        out = run(db, capsys, "Card", *files)[1]

        touching = [
            int(line.rsplit(" ", 1)[1]) for line in out.splitlines()
            if "Open review groups touching this file" in line
        ]
        movement = account_movement(connect(Path(db)))
        assert sum(touching) > movement.candidate_groups
        assert (
            f"Open review groups: {movement.candidate_groups}, covering "
            f"{movement.transactions_in_candidate_groups} distinct affected transactions."
        ) in section(out, "This account after the run")

    def test_unresolved_records_stay_disclosed_for_the_account(self, db, tmp_path, capsys):
        run(db, capsys, "Card", card(tmp_path, "a.csv", "too few cells"))
        out = run(db, capsys, "Card", card(tmp_path, "b.csv", CAFE))[1]
        assert "Source rows read: 1 (1 valid, 0 unresolved)" in out
        assert "Unresolved records, not included in totals: 1" in out

    def test_final_state_covers_only_the_account_imported_into(self, db, tmp_path, capsys):
        problem = checking(tmp_path, "a.csv", UNKNOWN, "too few cells")
        run(db, capsys, "Checking", problem)
        run(db, capsys, "Checking", checking(tmp_path, "b.csv", POSTED_ONE))
        run(db, capsys, "Checking", checking(tmp_path, "c.csv", POSTED_TWO))

        out = run(db, capsys, "Card", card(tmp_path, "d.csv", CAFE))[1]

        assert section(out, "This account after the run") == [
            "Open review groups: 0, covering 0 distinct affected transactions.",
            "Unresolved records, not included in totals: 0",
        ]

    def test_summaries_do_not_use_the_retired_vocabulary(self, db, tmp_path, capsys):
        files = [card(tmp_path, "a.csv", CAFE), card(tmp_path, "b.csv", CAFE, "too few cells")]
        lowered = run(db, capsys, "Card", *files, tmp_path / "missing.csv")[1].lower()
        for word in ("flag", "created", "new transaction", "income", "spending"):
            assert word not in lowered


def checked_import(conn, tmp, name, file, declared):
    path = tmp / name
    path.write_text(file.content, encoding="utf-8")
    return import_files(conn, [path], account_id="acct", layout=file.layout,
                        declared_coverage=declared)[0]


def assert_units_hold(conn, results, live_before):
    summary = summarize_run(conn, results)
    assert summary.files_attempted == (
        summary.files_imported + summary.files_already_imported + summary.files_failed
    )
    assert summary.rows_read == summary.valid_records + summary.unresolved_records
    for result in results:
        if result.outcome == "imported":
            assert result.rows_read == result.valid_records + result.unresolved_records
            stored = conn.execute(
                """SELECT COUNT(*), COUNT(CASE WHEN parse.status = 'parsed' THEN 1 END)
                   FROM source_record record
                   JOIN record_parse parse ON parse.source_record_id = record.id
                   WHERE record.source_document_id = ?""",
                (result.source_document_id,),
            ).fetchone()
            assert stored == (result.rows_read, result.valid_records)
        else:
            assert result.rows_read is None and result.valid_records is None
    live = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
    assert summary.net_transactions == live - live_before
    assert summary.final_transactions <= summary.valid_records
    assert summary.consolidated_records <= summary.valid_records


BROKEN = File("not,the,header\n", SYNTHETIC_CHECKING_V1)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    files=st.lists(st.one_of(checking_file(), st.just(BROKEN)), min_size=1, max_size=5),
    repeats=st.lists(st.integers(0, 4), max_size=3),
)
def test_units_hold_for_any_run_including_splits_and_repeats(files, repeats):
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        create_database(tmp / "ledger.db")
        conn = connect(tmp / "ledger.db")
        conn.execute("INSERT INTO account (id, display_name, account_type) "
                     "VALUES ('acct', 'A', 'checking')")
        order = list(enumerate(files)) + [
            (index % len(files), files[index % len(files)]) for index in repeats
        ]
        results = []
        for number, file in order:
            results.append(checked_import(conn, tmp, f"{number}.csv", file, file.declared))
        assert_units_hold(conn, results, 0)
        conn.close()


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(files=st.lists(card_file(), min_size=2, max_size=4))
def test_one_multi_file_run_of_card_files_keeps_its_units(files):
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        create_database(tmp / "ledger.db")
        conn = connect(tmp / "ledger.db")
        conn.execute("INSERT INTO account (id, display_name, account_type) "
                     "VALUES ('acct', 'A', 'credit_card')")
        paths = []
        for number, file in enumerate(files):
            paths.append(tmp / f"{number}.csv")
            paths[-1].write_text(file.content, encoding="utf-8")
        results = import_files(conn, paths, account_id="acct", layout=SYNTHETIC_CARD_V1)
        assert_units_hold(conn, results, 0)
        conn.close()
