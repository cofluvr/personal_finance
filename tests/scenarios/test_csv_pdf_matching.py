"""The same activity in a CSV and a PDF counts once (M7.3, D-060 point 4, I1 to I6).

The PDF is `us_bank_card_activity_pdf_v1`. U.S. Bank's card CSV has no layout yet, since its header
was not supplied, so the CSV here is a test-only layout of the fields the owner's rows showed: the
date, the description, a signed amount with a charge positive, and the account. Matching is D-006's
exact rule, unchanged: no layout or rule is added for it.
"""

import pytest
from ledger_view import semantic_view
from test_us_bank_activity_pdf import HEADER, LAST4, POSTED, account_line, add_account, entry

from personal_finance.cli import main
from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import (
    SYNTHETIC_CHECKING_V1,
    US_BANK_CARD_ACTIVITY_PDF_V1,
    Layout,
    ParsedRow,
    _amount,
    _date,
    _finish,
)
from personal_finance.ingest.pipeline import import_files
from personal_finance.reports.totals import account_movement
from synthetic_pdf import pdf_bytes


def _parse_card_csv_row(cells):
    problems = []
    amount = _amount(cells["Amount"], problems)
    row = ParsedRow(
        posting_date=_date(cells["Date"], "%m/%d/%Y", problems),
        amount_cents=None if amount is None else -amount,
        description=cells["Description"].strip() or None,
    )
    return _finish(row, problems)


# Test-only (layouts.md): the owner's CSV rows' fields under an invented header.
CARD_CSV = Layout(
    layout_id="test_us_bank_card_csv",
    parser_version="1",
    columns=("Date", "Description", "Amount", "Account"),
    parse_row=_parse_card_csv_row,
    pending_in_complete_coverage={"posting": False, "transaction": False},
)

# (date, description, amount as printed): the same activity in both formats.
OCTOBER = [
    ("10/30/2026", "SYNTHETIC GROCER 01", "216.40"),
    ("10/27/2026", "SYNTHETIC GROCER 01", "-83.10"),
    ("10/20/2026", "Rewards Redeemed for Statement Credit", "-14.00"),
    ("10/09/2026", "SYNTHETIC HARDWARE", "41.75"),
    ("10/02/2026", "Internet Payment Thank You", "-125.00"),
]
NOVEMBER = [
    ("11/18/2026", "SYNTHETIC FUEL 07", "38.20"),
    ("11/04/2026", "SYNTHETIC GROCER 01", "12.66"),
]
OCTOBER_PERIOD = ("2026-10-01", "2026-10-31")
NOVEMBER_PERIOD = ("2026-11-01", "2026-11-30")


def csv_text(rows):
    lines = ["Date,Description,Amount,Account"]
    lines += [f'{day},"{description}",{amount},"Credit Card ...{LAST4}"'
              for day, description, amount in rows]
    return "\n".join(lines) + "\n"


def printout(rows, extra_lines=()):
    lines = [HEADER, POSTED]
    for day, description, amount in rows:
        printed = f"-${amount[1:]}" if amount.startswith("-") else f"${amount}"
        lines += [entry(day, description, printed), account_line()]
    return pdf_bytes([lines + list(extra_lines)])


@pytest.fixture
def card(conn):
    return add_account(conn, "card", "credit_card", LAST4)


def load(conn, tmp_path, name, content, layout, period=None, basis="posting"):
    path = tmp_path / name
    path.write_bytes(content)
    declared = declare_complete(*period, basis) if period else None
    (result,) = import_files(conn, [path], account_id="card", layout=layout,
                             declared_coverage=declared)
    assert result.outcome == "imported", result
    return result


def load_csv(conn, tmp_path, rows, period=OCTOBER_PERIOD, name="activity.csv", basis="posting"):
    return load(conn, tmp_path, name, csv_text(rows).encode(), CARD_CSV, period, basis)


def load_pdf(conn, tmp_path, rows, period=OCTOBER_PERIOD, name="activity.pdf", extra_lines=()):
    return load(conn, tmp_path, name, printout(rows, extra_lines), US_BANK_CARD_ACTIVITY_PDF_V1,
                period)


def cents(rows):
    return sum(-round(float(amount) * 100) for _, _, amount in rows)


class TestCountedOnce:  # I1
    def test_one_periods_csv_and_pdf_count_each_row_once(self, conn, card, tmp_path):
        load_csv(conn, tmp_path, OCTOBER)
        load_pdf(conn, tmp_path, OCTOBER)
        movement = account_movement(conn, "card")
        assert (movement.transactions, movement.net_cents) == (len(OCTOBER), cents(OCTOBER))
        assert movement.candidate_groups == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM transaction_source WHERE link_rule = 'exact_coverage_pair'"
        ).fetchone()[0] == 2 * len(OCTOBER)

    def test_either_import_order_gives_the_same_ledger(self, tmp_path):
        views = []
        for order in (("csv", "pdf"), ("pdf", "csv")):
            folder = tmp_path / "-".join(order)
            folder.mkdir()
            create_database(folder / "ledger.db")
            conn = connect(folder / "ledger.db")
            add_account(conn, "card", "credit_card", LAST4)
            for kind in order:
                (load_csv if kind == "csv" else load_pdf)(conn, folder, OCTOBER)
            views.append(semantic_view(conn))
            assert account_movement(conn, "card").transactions == len(OCTOBER)
            conn.close()
        assert views[0] == views[1]

    def test_the_pdf_changes_no_report_of_the_csv_alone(self, conn, card, tmp_path, db_path,
                                                          capsys):  # I6
        def reports():
            capsys.readouterr()
            for words in (["totals"], ["report", "monthly"]):
                assert main([*words, "--db", str(db_path), "--account", "card"]) == 0
            return capsys.readouterr().out

        load_csv(conn, tmp_path, OCTOBER)
        conn.commit()
        movement, printed = account_movement(conn, "card"), reports()
        load_pdf(conn, tmp_path, OCTOBER)
        conn.commit()
        assert account_movement(conn, "card") == movement
        assert reports() == printed


class TestPossibleDuplicates:  # I2: each missing condition keeps both, counted and disclosed
    def assert_both_kept(self, conn, rows):
        movement = account_movement(conn, "card")
        assert movement.transactions == 2 * len(rows)
        assert movement.transactions_in_candidate_groups == 2 * len(rows)

    def test_without_a_declaration_on_the_pdf(self, conn, card, tmp_path):
        load_csv(conn, tmp_path, OCTOBER)
        load_pdf(conn, tmp_path, OCTOBER, period=None)
        self.assert_both_kept(conn, OCTOBER)

    def test_with_coverage_on_another_basis(self, conn, card, tmp_path):
        load_csv(conn, tmp_path, OCTOBER, basis="transaction")
        load_pdf(conn, tmp_path, OCTOBER)
        self.assert_both_kept(conn, OCTOBER)

    def test_for_a_row_outside_one_interval(self, conn, card, tmp_path):
        load_csv(conn, tmp_path, OCTOBER, period=("2026-10-05", "2026-10-31"))
        load_pdf(conn, tmp_path, OCTOBER)
        movement = account_movement(conn, "card")
        assert movement.transactions == len(OCTOBER) + 1
        assert movement.transactions_in_candidate_groups == 2

    def test_with_an_unresolved_row_in_the_pdf(self, conn, card, tmp_path):
        result = load_pdf(conn, tmp_path, OCTOBER, extra_lines=[((40, "Pending"),)])
        assert result.unresolved_records == 1
        load_csv(conn, tmp_path, OCTOBER)
        self.assert_both_kept(conn, OCTOBER)


class TestAcrossStatements:  # I3
    def test_a_csv_spanning_two_printouts_counts_each_row_once(self, conn, card, tmp_path):
        load_pdf(conn, tmp_path, OCTOBER, name="october.pdf")
        load_pdf(conn, tmp_path, NOVEMBER, period=NOVEMBER_PERIOD, name="november.pdf")
        load_csv(conn, tmp_path, NOVEMBER + OCTOBER, period=("2026-10-01", "2026-11-30"))
        movement = account_movement(conn, "card")
        both = NOVEMBER + OCTOBER
        assert (movement.transactions, movement.net_cents) == (len(both), cents(both))
        assert movement.candidate_groups == 0


class TestIdenticalRows:  # I4
    TWICE = [("10/14/2026", "SYNTHETIC COFFEE", "4.50")] * 2

    def test_two_against_two_give_two(self, conn, card, tmp_path):
        load_csv(conn, tmp_path, self.TWICE)
        load_pdf(conn, tmp_path, self.TWICE)
        assert account_movement(conn, "card").transactions == 2

    def test_two_against_one_give_two(self, conn, card, tmp_path):
        load_csv(conn, tmp_path, self.TWICE)
        load_pdf(conn, tmp_path, self.TWICE[:1])
        movement = account_movement(conn, "card")
        assert (movement.transactions, movement.net_cents) == (2, -900)


class TestOneSideWithAnId:  # I5: D-026's limitation, as kept
    def test_an_id_bearing_row_is_only_a_possible_duplicate_of_a_pdf_row(self, conn, card,
                                                                          tmp_path):
        checking = ("# coverage-kind: complete\n# coverage-start: 2026-10-01\n"
                    "# coverage-end: 2026-10-31\n# coverage-basis: posting\n"
                    "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                    "SYN-1,,2026-10-09,SYNTHETIC HARDWARE,-41.75,POSTED\n")
        load(conn, tmp_path, "with_id.csv", checking.encode(), SYNTHETIC_CHECKING_V1)
        load_pdf(conn, tmp_path, OCTOBER[3:4])
        movement = account_movement(conn, "card")
        assert (movement.transactions, movement.transactions_in_candidate_groups) == (2, 2)
        assert movement.net_cents == 2 * -4175
