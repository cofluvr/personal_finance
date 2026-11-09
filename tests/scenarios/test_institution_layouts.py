"""M6's institution layouts, J1 to J7 of D-059, each on its invented fixture.

Every layout here is unverified until a real file of it reconciles with its statement (D-059
point F). These tests show each layout does what layouts.md says, not that the export matches.
"""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from personal_finance.cli import main
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import (
    CAPITAL_ONE_BANK_V1,
    CAPITAL_ONE_CARD_V1,
    LAYOUTS,
    US_BANK_V1,
    Layout,
)
from personal_finance.ingest.pipeline import import_files
from personal_finance.reports.totals import account_movement

STATEMENTS = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "statements"


@dataclass(frozen=True)
class LayoutCase:
    layout: Layout
    fixture: str
    # (transaction date, posting date, cents, description) for each data row, in order.
    expected_rows: tuple[tuple[str | None, str | None, int, str], ...]
    # Cell overrides on the first data row, and the reason each leaves.
    unresolved_rows: tuple[tuple[dict[str, str], str], ...]
    # Two overlapping exports: data rows [0, first_ends) and [second_starts, end), each
    # declared complete over its interval on the basis given.
    first_ends: int
    second_starts: int
    first_interval: tuple[str, str]
    second_interval: tuple[str, str]
    overlap_basis: str
    unoffered_bases: tuple[str, ...] = field(default=())

    @property
    def id(self) -> str:
        return self.layout.layout_id

    def text(self) -> str:
        return (STATEMENTS / self.fixture).read_text(encoding="utf-8")

    def lines(self) -> list[str]:
        return self.text().splitlines()

    def first_row_cells(self) -> dict[str, str]:
        header, first = list(csv.reader(io.StringIO(self.text())))[:2]
        return dict(zip(header, first))


CASES = (
    LayoutCase(
        layout=CAPITAL_ONE_CARD_V1,
        fixture="capital_one_card.csv",
        expected_rows=(
            ("2026-01-03", "2026-01-05", -475, "SYNTHETIC COFFEE HOUSE"),
            ("2026-01-03", "2026-01-05", -475, "SYNTHETIC COFFEE HOUSE"),
            ("2026-01-09", "2026-01-10", -6218, "SYNTHETIC GROCER #0000"),
            ("2026-01-14", "2026-01-15", -3840, "SYNTHETIC FUEL STOP 000"),
            ("2026-01-20", "2026-01-20", 25000, "CAPITAL ONE AUTOPAY PYMT"),
            ("2026-01-24", "2026-01-26", 1218, "SYNTHETIC GROCER #0000"),
            ("2026-01-28", "2026-01-29", -1599, "SYNTHETIC STREAMING SVC"),
        ),
        unresolved_rows=(
            ({"Debit": ""}, "missing_amount"),
            ({"Debit": "4.7x"}, "invalid_amount"),
            ({"Debit": "-4.75"}, "invalid_amount"),
            ({"Credit": "4.75"}, "conflicting_amount"),
            ({"Transaction Date": "", "Posted Date": ""}, "missing_date"),
            ({"Posted Date": "01/05/2026"}, "invalid_date"),
            ({"Transaction Date": "2026-02-30"}, "invalid_date"),
        ),
        first_ends=5,
        second_starts=3,
        first_interval=("2026-01-01", "2026-01-20"),
        second_interval=("2026-01-12", "2026-01-31"),
        overlap_basis="posting",
    ),
    LayoutCase(
        layout=CAPITAL_ONE_BANK_V1,
        fixture="capital_one_bank.csv",
        expected_rows=(
            ("2026-01-02", None, 185000, "Deposit from SYNTHETIC EMPLOYER PAYROLL"),
            ("2026-01-06", None, -2350, "Debit Card Purchase - SYNTHETIC MARKET"),
            ("2026-01-06", None, -2350, "Debit Card Purchase - SYNTHETIC MARKET"),
            ("2026-01-20", None, -25000, "Withdrawal to SYNTHETIC CARD PAYMENT"),
            ("2026-01-31", None, 42, "Monthly Interest Paid"),
        ),
        unresolved_rows=(
            ({"Transaction Amount": ""}, "missing_amount"),
            ({"Transaction Amount": "1850.0.0"}, "invalid_amount"),
            ({"Transaction Amount": "-1850.00"}, "invalid_amount"),
            ({"Transaction Type": ""}, "invalid_direction"),
            ({"Transaction Type": "Transfer"}, "invalid_direction"),
            ({"Transaction Date": ""}, "missing_date"),
            ({"Transaction Date": "2026-01-02"}, "invalid_date"),
        ),
        first_ends=4,
        second_starts=1,
        first_interval=("2026-01-01", "2026-01-20"),
        second_interval=("2026-01-05", "2026-01-31"),
        overlap_basis="transaction",
        unoffered_bases=("posting",),
    ),
    LayoutCase(
        layout=US_BANK_V1,
        fixture="us_bank.csv",
        expected_rows=(
            (None, "2026-01-02", 210000, "ELECTRONIC DEPOSIT SYNTHETIC EMPLOYER"),
            (None, "2026-01-05", -3127, "DEBIT PURCHASE -VISA SYNTHETIC MART 000"),
            (None, "2026-01-05", -3127, "DEBIT PURCHASE -VISA SYNTHETIC MART 000"),
            (None, "2026-01-12", -8810, "WEB AUTHORIZED PMT SYNTHETIC UTILITY"),
            (None, "2026-01-21", -495, "MONTHLY MAINTENANCE FEE"),
            (None, "2026-01-29", 1500, "ELECTRONIC DEPOSIT SYNTHETIC REFUND"),
        ),
        unresolved_rows=(
            ({"Amount": ""}, "missing_amount"),
            ({"Amount": "21OO.00"}, "invalid_amount"),
            ({"Amount": "-2100.00"}, "conflicting_amount"),
            ({"Transaction": "DEBIT"}, "conflicting_amount"),
            ({"Transaction": ""}, "invalid_direction"),
            ({"Transaction": "TRANSFER"}, "invalid_direction"),
            ({"Date": ""}, "missing_date"),
            ({"Date": "01/02/2026"}, "invalid_date"),
        ),
        first_ends=5,
        second_starts=1,
        first_interval=("2026-01-01", "2026-01-21"),
        second_interval=("2026-01-04", "2026-01-31"),
        overlap_basis="posting",
        unoffered_bases=("transaction",),
    ),
)

pytestmark = pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)


@pytest.fixture
def account(conn):
    conn.execute(
        "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'acct', 'checking')"
    )
    return "acct"


def import_text(conn, tmp_path, case, name, text, declared=None):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    (result,) = import_files(
        conn, [path], account_id="acct", layout=case.layout, declared_coverage=declared
    )
    return result


def stored_documents(conn):
    return conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0]


def header_variants(columns):
    yield columns[:-1]
    yield ("Renamed",) + columns[1:]
    yield (columns[1], columns[0]) + columns[2:]
    yield columns + ("Extra",)


class TestJ1Header:
    def test_the_exact_header_is_accepted(self, conn, account, tmp_path, case):
        result = import_text(conn, tmp_path, case, "statement.csv", case.text())
        assert result.outcome != "failed", result
        assert tuple(next(csv.reader([case.lines()[0]]))) == case.layout.columns

    def test_any_other_header_fails_importing_nothing(self, conn, account, tmp_path, case):
        body = case.lines()[1:]
        for number, columns in enumerate(header_variants(case.layout.columns)):
            text = "\n".join([",".join(f'"{column}"' for column in columns), *body]) + "\n"
            result = import_text(conn, tmp_path, case, f"variant{number}.csv", text)
            assert result.failure_code == "header_mismatch", columns
        assert stored_documents(conn) == 0


class TestJ2Rows:
    def test_every_row_parses_as_expected(self, case):
        rows = list(csv.DictReader(io.StringIO(case.text())))
        parsed = [case.layout.parse_row(row) for row in rows]
        assert [row.reason_code for row in parsed] == [None] * len(rows)
        assert [
            (row.transaction_date, row.posting_date, row.amount_cents, row.description)
            for row in parsed
        ] == list(case.expected_rows)
        assert {(row.settlement_status, row.external_id) for row in parsed} == {("unknown", None)}

    def test_money_out_is_negative_and_money_in_positive(self, case):
        amounts = [cents for _, _, cents, _ in case.expected_rows]
        assert min(amounts) < 0 < max(amounts)


class TestJ3Unresolved:
    def test_each_bad_cell_leaves_the_row_unresolved(self, case):
        for overrides, reason in case.unresolved_rows:
            row = case.layout.parse_row({**case.first_row_cells(), **overrides})
            assert row.reason_code == reason, overrides
            if reason in ("missing_date", "invalid_date"):
                assert row.amount_cents == case.expected_rows[0][2], overrides
            else:
                assert row.amount_cents is None, overrides

    def test_an_unresolved_row_keeps_its_cells(self, conn, account, tmp_path, case):
        overrides, reason = case.unresolved_rows[0]
        cells = {**case.first_row_cells(), **overrides}
        line = ",".join(f'"{cells[column]}"' for column in case.layout.columns)
        text = "\n".join([case.lines()[0], line]) + "\n"
        result = import_text(conn, tmp_path, case, "bad.csv", text)
        assert result.outcome != "failed", result
        raw, parse_reason = conn.execute(
            """SELECT record.raw_json, parse.reason_code FROM source_record record
               JOIN record_parse parse ON parse.source_record_id = record.id"""
        ).fetchone()
        assert parse_reason == reason
        assert raw == "[" + ",".join(f'"{cells[column]}"' for column in case.layout.columns) + "]"


class TestJ4IdenticalRows:
    def test_identical_rows_in_one_file_are_separate_transactions(
        self, conn, account, tmp_path, case
    ):
        import_text(conn, tmp_path, case, "statement.csv", case.text())
        assert len(set(case.expected_rows)) < len(case.expected_rows)
        assert account_movement(conn, "acct").transactions == len(case.expected_rows)

    def test_every_transaction_traces_to_its_document_and_row(
        self, conn, account, tmp_path, case
    ):
        import_text(conn, tmp_path, case, "statement.csv", case.text())
        traced = conn.execute(
            """SELECT record.record_index FROM transaction_source source
               JOIN source_record record ON record.id = source.source_record_id
               ORDER BY record.record_index"""
        ).fetchall()
        assert [index for (index,) in traced] == list(range(1, len(case.expected_rows) + 1))


class TestJ5Overlap:
    def test_reimporting_changes_nothing(self, conn, account, tmp_path, case):
        import_text(conn, tmp_path, case, "statement.csv", case.text())
        before = account_movement(conn, "acct")
        import_text(conn, tmp_path, case, "statement.csv", case.text())
        assert account_movement(conn, "acct") == before
        assert stored_documents(conn) == 1

    def test_an_overlapping_export_counts_shared_rows_once(self, conn, account, tmp_path, case):
        header, *rows = case.lines()
        first = "\n".join([header, *rows[: case.first_ends]]) + "\n"
        second = "\n".join([header, *rows[case.second_starts :]]) + "\n"
        assert case.second_starts < case.first_ends
        import_text(conn, tmp_path, case, "first.csv", first,
                    declare_complete(*case.first_interval, case.overlap_basis))
        import_text(conn, tmp_path, case, "second.csv", second,
                    declare_complete(*case.second_interval, case.overlap_basis))
        movement = account_movement(conn, "acct")
        assert movement.transactions == len(case.expected_rows)
        assert movement.net_cents == sum(cents for _, _, cents, _ in case.expected_rows)


class TestJ6Coverage:
    def test_a_declaration_on_an_offered_basis_is_accepted(self, conn, account, tmp_path, case):
        for number, basis in enumerate(case.layout.pending_in_complete_coverage):
            text = case.text() + "\n" * number
            declared = declare_complete("2026-01-01", "2026-01-31", basis)
            result = import_text(conn, tmp_path, case, f"{basis}.csv", text, declared)
            assert result.outcome != "failed", result
            assert result.coverage.evidence == "user_declared"

    def test_a_declaration_on_another_basis_fails(self, conn, account, tmp_path, case):
        for basis in case.unoffered_bases:
            declared = declare_complete("2026-01-01", "2026-01-31", basis)
            result = import_text(conn, tmp_path, case, "statement.csv", case.text(), declared)
            assert result.failure_code == "coverage_basis_unavailable"
        assert stored_documents(conn) == 0

    def test_a_metadata_line_is_not_read_as_coverage(self, conn, account, tmp_path, case):
        text = "# coverage-kind: complete\n" + case.text()
        result = import_text(conn, tmp_path, case, "statement.csv", text)
        assert result.failure_code == "header_mismatch"


class TestJ7Interpretation:
    def test_the_stored_interpretation_declares_no_ids(self, conn, account, tmp_path, case):
        import_text(conn, tmp_path, case, "statement.csv", case.text())
        assert conn.execute(
            """SELECT layout_id, external_id_namespace, external_id_guarantee
               FROM document_interpretation"""
        ).fetchall() == [(case.id, None, "none")]

    def test_pf_import_offers_the_layout(self, tmp_path, capsys, case):
        db = str(tmp_path / "ledger.db")
        assert LAYOUTS[case.id] is case.layout
        assert main(["init", "--db", db]) == 0
        assert main(["account", "add", "--db", db, "--name", "Acct", "--type", "checking"]) == 0
        statement = str(STATEMENTS / case.fixture)
        assert main(["import", "--db", db, "--account", "Acct", "--layout", case.id,
                     statement]) == 0
        capsys.readouterr()
        assert main(["documents", "--db", db]) == 0
        assert f"{case.fixture}: {len(case.expected_rows)} records, account Acct, layout {case.id}" \
            in capsys.readouterr().out
