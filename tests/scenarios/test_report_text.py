"""One builder per report, printed by the CLI and rendered by the UI alike (UA1, UA2, D-062 point 6).

M8.1 moved each report command's output into a builder, and its output was compared byte for byte
with the output before the move, on every ledger the suite builds. These tests keep it that way:
each command prints its builder's lines and nothing else, and the builders print nothing, open no
ledger and need only a read-only connection.
"""

import ast
from pathlib import Path

from test_decisions import CAFE, Ledger

from personal_finance import cli
from personal_finance.db.migrate import connect
from personal_finance.ingest import pipeline
from personal_finance.reconcile.apply import ReconcileResult
from personal_finance.reports import report_text
from personal_finance.reports.report_text import (
    ReportLine,
    document_list_lines,
    monthly_report_lines,
    review_item_report,
    review_queue_lines,
    totals_report_lines,
    transaction_list_lines,
)

BUILDER_OF_HANDLER = {
    "run_totals": "totals_report_lines",
    "run_report_monthly": "monthly_report_lines",
    "run_documents": "document_list_lines",
    "run_transactions": "transaction_list_lines",
    "run_review_list": "review_queue_lines",
    "run_review_show": "review_item_report",
}


def called_names(node) -> set[str]:
    return {call.func.id for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}


def module_tree(module):
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def ledger_with_an_item(tmp_path, capsys):
    ledger = Ledger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    ledger.card("b.csv", CAFE)
    (item,) = ledger.items()
    return ledger, item


def test_each_report_command_prints_its_builders_lines_and_nothing_else():
    handlers = {node.name: node for node in module_tree(cli).body
                if isinstance(node, ast.FunctionDef) and node.name in BUILDER_OF_HANDLER}
    assert set(handlers) == set(BUILDER_OF_HANDLER)
    for name, builder in BUILDER_OF_HANDLER.items():
        calls = called_names(handlers[name])
        assert {builder, "print_report", "open_ledger"} <= calls, name
        assert "print" not in calls, name


def test_the_builders_print_nothing_and_open_no_ledger():
    tree = module_tree(report_text)
    assert not called_names(tree) & {"print", "open", "open_ledger", "connect"}
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "personal_finance.cli" not in imported


def test_the_builders_need_only_a_read_only_connection(tmp_path, capsys):
    ledger, item = ledger_with_an_item(tmp_path, capsys)
    before = ledger.path.read_bytes()
    conn = connect(ledger.path, read_only=True)
    (account_id,) = conn.execute("SELECT id FROM account").fetchone()

    reports = [
        totals_report_lines(conn, None), totals_report_lines(conn, account_id),
        monthly_report_lines(conn, None, None, None),
        monthly_report_lines(conn, account_id, "2026-01", "2026-01"),
        document_list_lines(conn), transaction_list_lines(conn), review_queue_lines(conn),
        review_item_report(conn, item).lines,
    ]
    conn.close()

    for lines in reports:
        assert lines and all(type(line) is ReportLine and isinstance(line.text, str)
                             for line in lines)
    assert ledger.path.read_bytes() == before
    assert capsys.readouterr() == ("", "")


def test_the_cli_prints_exactly_the_builders_lines(tmp_path, capsys):
    ledger, item = ledger_with_an_item(tmp_path, capsys)
    conn = connect(ledger.path, read_only=True)
    (account_id,) = conn.execute("SELECT id FROM account").fetchone()
    expected = {
        ("totals",): totals_report_lines(conn, None),
        ("totals", "--account", account_id): totals_report_lines(conn, account_id),
        ("report", "monthly", "--from", "2026-01"): monthly_report_lines(conn, None, "2026-01",
                                                                         None),
        ("documents",): document_list_lines(conn),
        ("transactions",): transaction_list_lines(conn),
        ("review", "list"): review_queue_lines(conn),
        ("review", "show", item): review_item_report(conn, item).lines,
    }
    conn.close()

    for command, lines in expected.items():
        code, out, err = ledger.run(*command)
        assert (code, err) == (0, ""), command
        assert out == "".join(f"{line.text}\n" for line in lines), command


def test_the_queue_links_each_item_line_to_its_item(tmp_path, capsys):
    ledger, item = ledger_with_an_item(tmp_path, capsys)
    with connect(ledger.path, read_only=True) as conn:
        lines = review_queue_lines(conn)
    linked = [line for line in lines if line.linked_review_item_id]
    assert [line.linked_review_item_id for line in linked] == [item]
    assert linked[0].text.startswith(f"Item {item}: ")


def test_an_unknown_item_has_no_report(tmp_path, capsys):
    ledger, _ = ledger_with_an_item(tmp_path, capsys)
    with connect(ledger.path, read_only=True) as conn:
        assert review_item_report(conn, "no-such-item") is None


def test_an_items_report_carries_what_deciding_it_needs(tmp_path, capsys):
    ledger, item = ledger_with_an_item(tmp_path, capsys)
    with connect(ledger.path, read_only=True) as conn:
        report = review_item_report(conn, item)
        (account_id,) = conn.execute("SELECT id FROM account").fetchone()
    assert (report.item_id, report.kind, report.account_id) == (item, "possible_duplicate",
                                                                account_id)
    assert report.revision == ledger.revision(item)


def test_a_report_for_one_account_discloses_only_its_own_staleness(tmp_path, capsys, monkeypatch):
    """Another account left unreconciled is disclosed for the ledger, not for this account."""
    ledger = Ledger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    ledger.add_account("B")
    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "reconcile_account",
                      lambda *args, **kwargs: ReconcileResult(None, 0))
        ledger.card("b.csv", CAFE, account="B")

    stale = "1 accounts have not been reconciled"
    for command in (("totals",), ("report", "monthly")):
        assert stale in ledger.run(*command)[1], command
        assert stale not in ledger.run(*command, "--account", "A")[1], command
        assert stale in ledger.run(*command, "--account", "B")[1], command
