"""Summaries and error paths stay free of financial details (A18, D-037).

M1 has no application logging, so these tests check what could replace it: terminal
output, Python logging, and any file a run leaves behind.
"""

import ast
import logging
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from personal_finance import cli
from personal_finance.cli import BUSY_EXPLANATION, UNEXPECTED_ERROR, main
from personal_finance.db.migrate import connect
from personal_finance.ingest import pipeline

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "personal_finance"

MERCHANT = "SENTINELMERCHANT"
AMOUNT = "98765.43"
EXTERNAL_ID = "SENTINELID7"
SENTINELS = (MERCHANT, AMOUNT, EXTERNAL_ID, "SENTINELCELL", "SENTINELHEADER")

CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
GOOD_ROW = f"{EXTERNAL_ID},2026-01-09,2026-01-10,{MERCHANT},-{AMOUNT},POSTED\n"
UNRESOLVED_ROWS = f"X-1,2026-01-11,,{MERCHANT},SENTINELCELL{AMOUNT},\nSENTINELCELL,{AMOUNT}\n"
NEAR_ROW = f",2026-01-10,2026-01-10,{MERCHANT},-{AMOUNT},POSTED\n"
SUPPORT_SUFFIXES = ("", "-wal", "-shm", "-journal")


def assert_clean(text):
    for sentinel in SENTINELS:
        assert sentinel not in text
    assert "Traceback" not in text


@pytest.fixture
def workspace(tmp_path):
    """A ledger and synthetic files whose contents carry the sentinels."""
    folder = tmp_path / "work"
    folder.mkdir()
    (folder / "good.csv").write_text(CHECKING_HEADER + GOOD_ROW + UNRESOLVED_ROWS)
    (folder / "near.csv").write_text(CHECKING_HEADER + NEAR_ROW)
    (folder / "bad.csv").write_text(f"SENTINELHEADER,{AMOUNT}\n{MERCHANT}\n")
    (folder / "binary.csv").write_bytes(b"\xff\xfe" + MERCHANT.encode())
    (folder / "quotes.csv").write_text(f'{CHECKING_HEADER}"{MERCHANT}\n')
    return folder


FILES = ("good.csv", "near.csv", "bad.csv", "binary.csv", "quotes.csv", "missing.csv")


def setup_commands(db):
    return [
        ["init", "--db", db],
        ["account", "add", "--db", db, "--name", "Checking", "--type", "checking"],
    ]


def import_command(db, folder):
    return ["import", "--db", db, "--account", "Checking", "--layout", "synthetic_checking_v1",
            *[str(folder / name) for name in FILES]]


def quiet_commands(db):
    """Commands that must not show financial details."""
    return [["reconcile", "--db", db], ["documents", "--db", db], ["review", "list", "--db", db]]


class TestOutput:
    def test_import_and_summary_commands_expose_nothing(self, workspace, capsys, caplog):
        caplog.set_level(logging.DEBUG)
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            assert main(command) == 0
        assert main(import_command(db, workspace)) == 1
        captured = capsys.readouterr()
        assert "good.csv: imported" in captured.out
        assert "failed (malformed_csv)" in captured.out
        assert_clean(captured.out + captured.err)

        for command in quiet_commands(db):
            assert main(command) == 0
            captured = capsys.readouterr()
            assert_clean(captured.out + captured.err)
        assert caplog.records == []

    def test_totals_shows_aggregates_but_no_description_or_identifier(self, workspace, capsys):
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            main(command)
        main(import_command(db, workspace))
        capsys.readouterr()

        assert main(["totals", "--db", db]) == 0
        out = capsys.readouterr().out
        assert MERCHANT not in out and EXTERNAL_ID not in out and "SENTINELCELL" not in out

    def test_transactions_and_trace_show_data_by_design(self, workspace, capsys):
        """These commands exist to display selected data, so this is not a leak."""
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            main(command)
        main(import_command(db, workspace))
        capsys.readouterr()

        assert main(["transactions", "--db", db]) == 0
        out = capsys.readouterr().out
        assert MERCHANT in out and AMOUNT in out

        transaction_id = out.split()[0]
        assert main(["trace", "--db", db, transaction_id]) == 0
        assert MERCHANT in capsys.readouterr().out

    def test_review_show_shows_data_by_design_and_only_when_asked(self, workspace, capsys):
        """An explicit request for one item, under the same terms as trace (D-037)."""
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            main(command)
        main(import_command(db, workspace))
        capsys.readouterr()

        assert main(["review", "list", "--db", db]) == 0
        listing = capsys.readouterr().out
        assert_clean(listing)
        items = re.findall(r"^Item ([^:]+): (\S+)", listing, re.MULTILINE)
        assert {kind for _, kind in items} == {"possible_duplicate:", "unresolved_record:"}

        shown = ""
        for item, _ in items:
            assert main(["review", "show", "--db", db, item]) == 0
            shown += capsys.readouterr().out
        assert MERCHANT in shown and AMOUNT in shown and "SENTINELCELL" in shown

    def test_a_refused_review_show_repeats_nothing_it_was_given(self, workspace, capsys):
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            main(command)
        capsys.readouterr()

        assert main(["review", "show", "--db", db, MERCHANT]) == 2
        captured = capsys.readouterr()
        assert_clean(captured.out + captured.err)

    def test_the_ledger_holds_the_sentinels_so_these_checks_mean_something(
        self, workspace, capsys
    ):
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            main(command)
        main(import_command(db, workspace))
        conn = connect(Path(db))
        assert conn.execute(
            "SELECT COUNT(*) FROM source_record WHERE raw_json LIKE ?", (f"%{MERCHANT}%",)
        ).fetchone()[0] >= 2

    def test_failed_attempts_store_only_a_code(self, workspace, capsys):
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            main(command)
        main(import_command(db, workspace))
        conn = connect(Path(db))
        rows = conn.execute(
            "SELECT file_name, failure_code FROM import_attempt WHERE outcome = 'failed'"
        ).fetchall()
        assert len(rows) == 4
        assert_clean(repr(rows))


def run_process(arguments, folder, *, code=None):
    """Run the application for real, with its home and working directory in the test folder."""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(folder),
        "TMPDIR": str(folder),
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    start = ["-c", code] if code else ["-m", "personal_finance"]
    return subprocess.run(
        [sys.executable, "-P", *start, *arguments],
        cwd=folder, env=environment, capture_output=True, text=True, timeout=60,
    )


def unexpected_files(folder, requested=()):
    allowed = {f"ledger.db{suffix}" for suffix in SUPPORT_SUFFIXES}
    allowed.update(FILES, requested)
    return sorted(
        str(path.relative_to(folder)) for path in folder.rglob("*")
        if path.is_file() and path.name not in allowed
    )


class TestFilesLeftBehind:
    def test_a_full_session_leaves_only_the_ledger_and_its_support_files(self, workspace):
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            assert run_process(command, workspace).returncode == 0

        result = run_process(import_command(db, workspace), workspace)
        assert result.returncode == 1
        assert_clean(result.stdout + result.stderr)

        for command in quiet_commands(db):
            result = run_process(command, workspace)
            assert result.returncode == 0
            assert_clean(result.stdout + result.stderr)

        assert unexpected_files(workspace) == []

    def test_an_unexpected_error_leaves_no_traceback_or_dump(self, workspace):
        db = str(workspace / "ledger.db")
        for command in setup_commands(db):
            run_process(command, workspace)

        crash = (
            "import sys\n"
            "from personal_finance import cli\n"
            "def crash(*args, **kwargs):\n"
            f"    raise ValueError('{MERCHANT} {AMOUNT}')\n"
            "cli.account_movement = crash\n"
            "sys.exit(cli.main(sys.argv[1:]))\n"
        )
        result = run_process(["totals", "--db", db], workspace, code=crash)

        assert result.returncode == 2
        assert result.stdout == ""
        assert result.stderr.strip() == f"Error: {UNEXPECTED_ERROR}"
        assert unexpected_files(workspace) == []

    def test_the_file_check_notices_a_stray_log(self, workspace):
        (workspace / "debug.log").write_text("stray")
        assert unexpected_files(workspace) == ["debug.log"]

    def test_an_explicitly_requested_output_is_allowed(self, workspace):
        (workspace / "export.txt").write_text("requested")
        assert unexpected_files(workspace, requested=["export.txt"]) == []


def test_a_reader_closing_the_output_is_neither_an_error_nor_a_success(tmp_path):
    rows = "".join(f"01/10/2026,SYNTHETIC ROW {number},1.00,\n" for number in range(3000))
    (tmp_path / "big.csv").write_text(f"Date,Description,Debit,Credit\n{rows}")
    db = str(tmp_path / "ledger.db")
    for command in setup_commands(db):
        run_process(command, tmp_path)
    run_process(["import", "--db", db, "--account", "Checking", "--layout", "synthetic_card_v1",
                 str(tmp_path / "big.csv")], tmp_path)

    process = subprocess.Popen(
        [sys.executable, "-P", "-m", "personal_finance", "transactions", "--db", db],
        cwd=tmp_path, env={"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert "SYNTHETIC ROW" in process.stdout.readline()
    process.stdout.close()
    errors = process.stderr.read()
    process.stderr.close()

    assert process.wait(timeout=60) == 141
    assert errors == ""


@pytest.fixture
def db(tmp_path, capsys):
    path = str(tmp_path / "ledger.db")
    for command in setup_commands(path):
        assert main(command) == 0
    capsys.readouterr()
    return path


def raises(error):
    def fail(*args, **kwargs):
        raise error
    return fail


def sensitive():
    return ValueError(f"{MERCHANT} {AMOUNT} {EXTERNAL_ID}")


class TestCliBoundary:
    @pytest.mark.parametrize(
        "command",
        [["totals"], ["documents"], ["review", "list"], ["transactions"], ["reconcile"]],
        ids=" ".join,
    )
    def test_an_unexpected_error_is_a_fixed_failure(self, db, capsys, caplog, monkeypatch, command):
        caplog.set_level(logging.DEBUG)
        monkeypatch.setattr(cli, "open_ledger", raises(sensitive()))

        assert main([*command, "--db", db]) == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == f"Error: {UNEXPECTED_ERROR}"
        assert_clean(captured.err + caplog.text)

    def test_an_unexpected_error_in_review_show_is_a_fixed_failure(
        self, db, capsys, caplog, monkeypatch
    ):
        caplog.set_level(logging.DEBUG)
        monkeypatch.setattr(cli, "load_review_evidence", raises(sensitive()))

        assert main(["review", "show", "--db", db, "some-item"]) == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == f"Error: {UNEXPECTED_ERROR}"
        assert_clean(captured.err + caplog.text)

    def test_a_failure_after_files_commit_is_not_reported_as_success(
        self, db, workspace, capsys, monkeypatch
    ):
        monkeypatch.setattr(cli, "account_movement", raises(sensitive()))
        command = ["import", "--db", db, "--account", "Checking", "--layout",
                   "synthetic_checking_v1", str(workspace / "good.csv")]

        assert main(command) == 2

        captured = capsys.readouterr()
        assert "may not have finished" in captured.err
        assert "This account after the run" not in captured.out
        assert_clean(captured.out + captured.err)

    def test_an_error_while_importing_a_file_stays_a_failed_file(
        self, db, workspace, capsys, caplog, monkeypatch
    ):
        caplog.set_level(logging.DEBUG)
        monkeypatch.setattr(pipeline, "reconcile_account", raises(sensitive()))
        command = ["import", "--db", db, "--account", "Checking", "--layout",
                   "synthetic_checking_v1", str(workspace / "good.csv")]

        assert main(command) == 1

        captured = capsys.readouterr()
        assert "failed (internal_error)" in captured.out
        assert_clean(captured.out + captured.err + caplog.text)
        conn = connect(Path(db))
        assert conn.execute("SELECT COUNT(*) FROM source_record").fetchone() == (0,)

    def test_a_corrupt_ledger_is_a_failure_without_details(self, tmp_path, capsys):
        path = tmp_path / "ledger.db"
        path.write_text(f"{MERCHANT} {AMOUNT} " * 500)

        assert main(["totals", "--db", str(path)]) == 2

        captured = capsys.readouterr()
        assert captured.out == ""
        assert_clean(captured.err)

    def test_cancelling_is_not_an_application_error(self, db, capsys, monkeypatch):
        monkeypatch.setattr(cli, "open_ledger", raises(KeyboardInterrupt()))

        with pytest.raises(KeyboardInterrupt):
            main(["totals", "--db", db])

        assert UNEXPECTED_ERROR not in capsys.readouterr().err

    def test_cancelling_an_import_keeps_nothing_from_that_file(
        self, db, workspace, capsys, monkeypatch
    ):
        monkeypatch.setattr(pipeline, "reconcile_account", raises(KeyboardInterrupt()))
        command = ["import", "--db", db, "--account", "Checking", "--layout",
                   "synthetic_checking_v1", str(workspace / "good.csv")]

        with pytest.raises(KeyboardInterrupt):
            main(command)

        assert connect(Path(db)).execute("SELECT COUNT(*) FROM source_record").fetchone() == (0,)

    def test_an_expected_error_keeps_its_useful_message(self, db, capsys):
        assert main(["totals", "--db", db, "--account", "Nope"]) == 2
        assert capsys.readouterr().err.strip() == "Error: account not found: Nope"

    def test_a_busy_ledger_keeps_its_explanation(self, db, capsys, monkeypatch):
        monkeypatch.setattr(
            cli, "open_ledger", raises(sqlite3.OperationalError("database is locked"))
        )
        assert main(["totals", "--db", db]) == 2
        assert capsys.readouterr().err.strip() == f"Error: {BUSY_EXPLANATION}"

    def test_a_database_error_does_not_quote_its_message(self, db, capsys, monkeypatch):
        monkeypatch.setattr(
            cli, "open_ledger", raises(sqlite3.OperationalError(f"near {MERCHANT}: syntax error"))
        )
        assert main(["totals", "--db", db]) == 2
        assert capsys.readouterr().err.strip() == "Error: database error"

    def test_a_usage_error_is_left_to_the_argument_parser(self, capsys):
        with pytest.raises(SystemExit) as exit_info:
            main(["totals"])
        assert exit_info.value.code == 2
        assert UNEXPECTED_ERROR not in capsys.readouterr().err


def source_trees():
    for path in sorted(SOURCE.rglob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


# The PDF reader imports logging only to silence pypdf, whose warnings can quote a file (D-060).
SILENCING_PYPDF = ("pdf_reader.py", "logging")


def test_source_rule_no_logging_or_diagnostic_modules():
    """Supplements the behaviour above. It does not replace it."""
    banned = {"logging", "traceback", "faulthandler", "cgitb"}
    found = []
    for path, tree in source_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            found += [(path.name, name) for name in names if name.split(".")[0] in banned]
    assert found == [SILENCING_PYPDF]


def test_the_pdf_reader_uses_logging_only_to_silence_pypdf():
    """Its one logger is pypdf's, given a handler that writes nothing and kept from the root, so
    no record from it is ever written. Any other use of logging fails here."""
    tree = ast.parse((SOURCE / "ingest" / "pdf_reader.py").read_text(encoding="utf-8"))
    uses = sorted(ast.unparse(node) for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                  and node.value.id in ("logging", "_pypdf_log"))
    assert uses == ["_pypdf_log.addHandler", "_pypdf_log.propagate", "logging.NullHandler",
                    "logging.getLogger"]
    pypdf_log = logging.getLogger("pypdf")
    assert pypdf_log.propagate is False
    assert any(type(handler) is logging.NullHandler for handler in pypdf_log.handlers)
    assert "logging.getLogger('pypdf')" in ast.unparse(tree)


def test_source_rule_only_the_cli_prints():
    found = [
        path.name
        for path, tree in source_trees()
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"
        and path.name != "cli.py"
    ]
    assert found == []
