"""PRD §21, box by box, end to end on one synthetic household (ZA1, D-077 point 1, the M21.1 slice
plan point 2). Synthetic data only.

Every test starts from the same household, built through the CLI by test_snapshot.py's
household(): two members sharing checking account A 50/50, a salary and a power bill, a card, a
mortgage with terms, an insurance reserve, a budget plan and a checking buffer. Each test then
does what its box is about and checks it from the commands' own output, ending where it can with
a snapshot that verifies: from import to snapshot, so that no box is closed only by pieces. B2's
CSV layout is test-only (layouts.md), so that one file is imported by import_files. The suite's
socket guard is on throughout, which is B15.
"""

import json
import re
from datetime import date

import pytest
from test_backups import assert_restored_alike
from test_csv_pdf_matching import CARD_CSV, OCTOBER, csv_text, printout
from test_decisions import CAFE, FIRST_HALF, SECOND_HALF, Ledger
from test_snapshot import SnapshotLedger, household
from test_us_bank_activity_pdf import LAST4

from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import US_BANK_CARD_ACTIVITY_PDF_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.snapshot import builder, validate
from personal_finance.snapshot.files import verified

pytestmark = pytest.mark.slow

AS_OF = "2026-05-04"


class Household(SnapshotLedger):
    def snapshot_now(self) -> dict:
        """The household's snapshot as of AS_OF, verified by M19's rules."""
        conn = self.conn()
        try:
            data = builder.build_snapshot(conn, date.fromisoformat(AS_OF), 90,
                                          "5b1f0a52-8f0e-4c55-9d7a-2f6b9e1c3d40",
                                          "2026-05-04T17:00:00.000Z")
        finally:
            conn.close()
        return verified(data)

    def ok(self, *words) -> str:
        code, out, err = self.run(*words)
        assert (code, err) == (0, ""), (words, err)
        return out

    def as_review_ledger(self) -> Ledger:
        """The same ledger with the review helpers of test_decisions.py's Ledger, which the
        income and obligation ledgers' show and undo override."""
        view = Ledger.__new__(Ledger)
        view.__dict__ = self.__dict__
        return view

    def reports(self) -> list[str]:
        return [self.ok(*words) for words in (
            ("totals",), ("report", "monthly"), ("report", "household"),
            ("transactions",), ("review", "list"))]


@pytest.fixture
def home(tmp_path, capsys):
    return household(Household(tmp_path, capsys))


def amount_of(out: str, label: str) -> str:
    return re.search(rf"{re.escape(label)}: (-?[0-9.]+)", out)[1]


def test_b1_reimporting_every_file_changes_no_report(home):
    before = home.reports()
    snapshot_before = home.snapshot_now()["content"]
    paths = sorted(home.folder.glob("*.csv"))
    assert len(paths) >= 3
    for path in paths:
        layout = ("synthetic_checking_v1" if path.read_text().startswith("Transaction ID")
                  else "synthetic_card_v1")
        out = home.ok("import", "--account", "A", "--layout", layout, str(path))
        assert "Files attempted: 1 (0 imported, 1 already imported, 0 failed)" in out, path
    assert home.reports() == before
    assert home.snapshot_now()["content"] == snapshot_before


def test_b2_a_months_pdf_beside_its_csv_counts_once(home):
    items_before = sorted(home.items())
    conn = home.conn()
    try:
        conn.execute("INSERT INTO account (id, display_name, account_type, last4) "
                     "VALUES ('usbank', 'U.S. Bank card', 'credit_card', ?)", (LAST4,))
        period = declare_complete("2026-10-01", "2026-10-31", "posting")
        for name, content, layout in (("activity.csv", csv_text(OCTOBER).encode(), CARD_CSV),
                                      ("activity.pdf", printout(OCTOBER),
                                       US_BANK_CARD_ACTIVITY_PDF_V1)):
            path = home.folder / name
            path.write_bytes(content)
            (result,) = import_files(conn, [path], account_id="usbank", layout=layout,
                                     declared_coverage=period)
            assert result.outcome == "imported", result
    finally:
        conn.close()
    out = home.ok("totals", "--account", "U.S. Bank card")
    assert f"Transactions: {len(OCTOBER)}, of which pending: 0" in out
    assert f"Net account movement: {-sum(float(amount) for *_, amount in OCTOBER):.2f}" in out
    assert sorted(home.items()) == items_before
    assert len(home.snapshot_now()["content"]["accounts"]) == 3


def test_b3_two_identical_coffees_stay_two(home):
    before = home.ok("transactions").count("SYNTHETIC CAFE")
    home.card("coffee.csv", CAFE, CAFE)
    assert home.ok("transactions").count("SYNTHETIC CAFE") == before + 2
    assert len(home.items()) == 0
    home.snapshot_now()


def test_b4_a_pending_row_then_its_posted_row_count_once(home):
    before = amount_of(home.ok("totals", "--account", "A"), "Account outflows")
    home.checking("pending.csv", "TX9,2026-05-02,2026-05-02,SYNTHETIC SHOP,-20.00,PENDING")
    home.checking("posted.csv", "TX9,2026-05-02,2026-05-03,SYNTHETIC SHOP,-21.50,POSTED")
    out = home.ok("totals", "--account", "A")
    assert float(amount_of(out, "Account outflows")) == pytest.approx(float(before) + 21.50)
    assert home.ok("transactions").count("SYNTHETIC SHOP") == 1
    home.snapshot_now()


def test_b5_a_matched_transfer_is_neither_income_nor_spending(home):
    def groups():
        out = home.ok("totals")
        return [line for line in out.splitlines() if line.strip().startswith(("income", "purchase",
                                                                              "spending"))]

    before = groups()
    home.add_account("S", "savings")
    out_row = home.deposit("move-out.csv", "2026-05-02", amount="-300.00",
                           text="SYNTHETIC MOVE", financial_type="transfer")
    in_row = home.deposit("move-in.csv", "2026-05-02", amount="300.00", text="SYNTHETIC MOVE",
                          financial_type=None, account="S")
    home.match_ok(out_row, in_row)
    assert groups() == before
    assert "Matched: 1 pairs" in home.ok("totals")
    home.snapshot_now()


def test_b6_paying_the_card_does_not_count_its_purchases_again(home):
    home.add_account("Card", "credit_card")
    home.pay("card-buy.csv", "2026-05-01", amount="-40.00", text="SYNTHETIC BOOKS",
             account="Card")
    spending_before = home.ok("totals")
    payment = home.pay("card-pay.csv", "2026-05-03", amount="-40.00", text="SYNTHETIC CARD PAY",
                       financial_type="card_payment")
    received = home.deposit("card-recv.csv", "2026-05-03", amount="40.00",
                            text="SYNTHETIC PAYMENT THANK YOU", financial_type=None,
                            account="Card")
    home.match_ok(payment, received, counterpart_account="Card")
    after = home.ok("totals")
    purchase = re.compile(r"purchase: \d+ transactions, (-?[0-9.]+)")
    assert purchase.search(after)[1] == purchase.search(spending_before)[1]
    home.snapshot_now()


def test_b7_a_possible_duplicate_is_listed_decided_and_undone(home):
    review = home.as_review_ledger()
    items_before = set(review.items())
    home.card("p1.csv", CAFE, extra=FIRST_HALF)
    home.card("p2.csv", CAFE, extra=SECOND_HALF)
    (item,) = set(review.items()) - items_before
    assert "SYNTHETIC CAFE" in home.ok("review", "show", item)
    totals_open = home.ok("totals")
    code, out, err = review.reject(item, tuple(review.transactions(item)))
    assert (code, err) == (0, ""), err
    assert set(review.items()) == items_before
    decision = re.search(r"Decision (\S+)", out)[1]
    code, _, err = review.undo(decision)
    assert (code, err) == (0, ""), err
    assert len(set(review.items()) - items_before) == 1
    assert home.ok("totals") == totals_open
    home.snapshot_now()


def test_b8_household_parts_and_the_snapshot_reconcile_to_the_cent(home):
    home.pay("odd.csv", "2026-05-02", amount="-0.03", text="SYNTHETIC ODD")
    out = home.ok("report", "household")
    assert "Alex" in out and "Bea" in out
    document = home.snapshot_now()
    assert validate.unreconciled(document["content"]) == []
    parts = [transaction for transaction in document["content"]["transactions"]
             if transaction["amount_cents"] == -3]
    assert parts and sorted(part["amount_cents"] for part in parts[0]["member_parts"]) == [-2, -1]


def test_b9_a_reserve_purchase_counts_once(home):
    home.assign_ok(home.reserve, "A", "600.00", as_of=AS_OF)
    purchase = home.pay("insurer.csv", "2026-05-03", amount="-600.00", text="SYNTHETIC INSURER")
    totals_before, monthly_before = home.ok("totals"), home.ok("report", "monthly")
    home.ok("review", "consume", purchase, "--account", "A", "--fund", home.reserve,
            "--revision", home.transaction_revision(purchase))
    assert (home.ok("totals"), home.ok("report", "monthly")) == (totals_before, monthly_before)
    funds = home.ok("report", "funds", "--as-of", AS_OF)
    assert "Paid from this fund: 600.00 in 1 transaction" in funds
    home.snapshot_now()


def test_b10_a_third_paycheck_leaves_the_budget_alike(home):
    budget_before = home.ok("report", "budget", "--month", "2026-05", "--as-of", AS_OF)
    home.deposit("pay-may-2.csv", "2026-05-02", amount="2500.00")
    home.deposit("pay-may-3.csv", "2026-05-03", amount="2500.00")
    budget_after = home.ok("report", "budget", "--month", "2026-05", "--as-of", AS_OF)
    def planned(out):
        return [line for line in out.splitlines()
                if line.strip().startswith(("Target, planned", "Baseline income",
                                            "Remaining capacity", "Original daily allowance"))]

    assert len(planned(budget_before)) == 4
    assert planned(budget_after) == planned(budget_before)
    home.snapshot_now()


def test_b11_an_over_assignment_is_refused_or_shown(home):
    code, _, err = home.assign(home.reserve, "A", "5000.01", as_of=AS_OF)
    assert code == 2 and "Nothing was changed" in err
    assert "Assigned: 0.00" in home.fund_shown(home.reserve, AS_OF)
    home.assign_ok(home.reserve, "A", "4000.00", as_of=AS_OF)
    home.observe("A", "2026-05-03", "3000.00")
    assert "Over-assigned by 1000.00" in home.ok("funds", "--as-of", AS_OF)
    home.snapshot_now()


def test_b12_a_graduated_loan_is_due_its_step_each_period(home):
    home.add_typed_account("Student", "loan")
    home.add_terms_ok("Student", payment="100.00", effective_from="2026-01-01")
    code, _, err = home.period("payment", "Student", "250.00", "2026-04-01")
    assert (code, err) == (0, ""), err
    shown = home.terms_shown("Student")
    assert "Payment from 2026-01-01, scheduled: 100.00" in shown
    assert "Payment from 2026-04-01, scheduled: 250.00" in shown
    assert "Student" in home.loans_shown(as_of=AS_OF)
    home.snapshot_now()


def test_b13_an_open_item_and_an_unresolved_row_are_disclosed(home):
    home.card("p1.csv", CAFE, extra=FIRST_HALF)
    home.card("p2.csv", CAFE, extra=SECOND_HALF)
    assert len(home.as_review_ledger().items()) == 1
    monthly = home.ok("report", "monthly")
    assert "2026-01: net account movement" in monthly
    assert "  Open review items: 1, holding 2 transactions here" in monthly
    assert "  Not covered for the whole month: A, Mortgage" in monthly
    document = home.snapshot_now()
    assert document["content"]["review"] and document["content"]["warnings"]


def test_b14_a_restored_household_shows_everything_alike(home, tmp_path, capsys):
    shown = assert_restored_alike(home, tmp_path / "backup", tmp_path / "restored.db", capsys)
    assert any(out for code, out, _ in shown.values() if code == 0)


def test_b15_the_whole_household_runs_with_the_network_blocked(home):
    """The suite's socket guard is on for this test as every other: building the household,
    every report and the snapshot needed no network."""
    import socket

    with pytest.raises(RuntimeError, match="network access"):
        socket.create_connection(("127.0.0.1", 9))
    for out in home.reports():
        assert out
    assert json.loads(json.dumps(home.snapshot_now()))["format"] == "commoncents-snapshot"
