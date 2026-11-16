"""pf report budget, one month against its plan, using synthetic data only (BB3 to BB6, D-069
points 3 to 5). BB1 and BB2 are tests/unit/test_budget_pace.py."""

import re
import tempfile
from pathlib import Path

import pytest
from local_ui_client import UiClient, page_text, parsed_page
from test_budget_plans import BudgetLedger
from test_decisions import BUDGET_TABLES, INCOME_TABLES, OBLIGATION_TABLES
from test_income_report import biweekly_ledger
from test_local_ui import cli_output

from personal_finance.db.backups import logical_digest
from personal_finance.db.migrate import connect

AS_OF = "2026-03-15"
# Every figure line names one of these, so no planning figure goes unlabelled (G1).
LABELS = ("planned", "actual", "budget pace")


class ReportLedger(BudgetLedger):
    def report(self, *words, as_of=AS_OF, month="2026-03"):
        code, out, err = self.run("report", "budget", "--as-of", as_of, "--month", month, *words)
        assert (code, err) == (0, ""), err
        return out

    def figure(self, out, label):
        """The amount on the line starting with label."""
        line = next(line for line in out.splitlines() if line.strip().startswith(label))
        return line.rsplit(" ", 1)[1]

    def pending(self, name, day, amount, text="SYNTHETIC SHOP"):
        row = f"{name.removesuffix('.csv')},{day},,{text},{amount},PENDING"
        self.load_path(self.write(name, "Transaction ID,Transaction Date,Posted Date,"
                                        "Description,Amount,Status\n", [row]),
                       layout="synthetic_checking_v1")

    def share_and_default(self):
        show = self.run("household", "share", "show")[1]
        assert self.run("household", "share", "set", "--part", "Alex=50", "--part", "Bea=50",
                        "--revision", re.search(r"Revision: (h1-\S+)", show)[1])[0] == 0
        show = self.run("household", "account", "show", "--account", "A")[1]
        assert self.run("household", "account", "set", "--account", "A", "--shared",
                        "--revision", re.search(r"Revision: (a1-\S+)", show)[1])[0] == 0


@pytest.fixture
def ledger(tmp_path, capsys):
    ledger = ReportLedger(tmp_path, capsys)
    ledger.set_plan_ok(allowance="1000.00", members=("Alex=600", "Bea=400"),
                       categories=("Dining=100",))
    return ledger


@pytest.fixture
def spent(ledger):
    """March: 40.00 discretionary, 20.00 unclassified, 100.00 transfer kind, 10.00 pending
    unclassified, a fixed bill reached by its obligation, and a paycheck."""
    ledger.pay("d1.csv", "2026-03-03", amount="-40.00", text="SYNTHETIC SHOP")
    ledger.unclassified = ledger.pay("u1.csv", "2026-03-04", amount="-20.00",
                                     text="SYNTHETIC MYSTERY", financial_type=None)
    ledger.pay("t1.csv", "2026-03-05", amount="-100.00", text="SYNTHETIC MOVE",
               financial_type="transfer")
    ledger.pending("n1.csv", "2026-03-06", "-10.00")
    ledger.pay("b1.csv", "2026-03-05")
    ledger.ob_add_ok(anchor="2026-03-05")
    ledger.deposit("p1.csv", "2026-03-02")
    return ledger


class TestActual:  # BB3
    def test_each_kind_of_spending_on_its_own_line(self, spent):
        out = spent.report()
        assert "  Discretionary spending, actual: 1, 40.00" in out
        assert "  Possible spending, unclassified, actual, counted until classified: 2, 30.00" in out
        assert ("  Possible spending, unconfirmed transfer kinds, actual, counted until "
                "classified: 1, 100.00") in out
        assert "  Of which pending, actual: 1, 10.00" in out
        assert "  Fixed spending, actual, apart from the target: 1, 85.00" in out
        assert "  Spent against the target, actual: 170.00" in out
        assert "  Remaining capacity, budget pace, provisional: 830.00" in out
        # The paycheck and the cafe card row of February are never inputs.
        assert "2500.00" not in out.split("Baseline income")[0]

    def test_classifying_moves_spending_exactly(self, spent):
        before = spent.report()
        spent.classify_ok(spent.unclassified, "purchase")
        after = spent.report()
        assert "  Discretionary spending, actual: 2, 60.00" in after
        assert "unclassified, actual, counted until classified: 1, 10.00" in after
        assert spent.figure(before, "Spent against") == spent.figure(after, "Spent against")

    def test_money_in_is_out_of_the_budget(self, ledger):
        ledger.pay("in.csv", "2026-03-03", amount="15.00", text="SYNTHETIC IN",
                   financial_type=None)
        out = ledger.report()
        assert "  Spent against the target, actual: 0.00" in out
        assert "  Remaining capacity, budget pace: 1000.00" in out

    def test_a_confirmed_transfer_is_out_of_the_budget(self, ledger):
        ledger.add_account("S", "savings")
        moved = ledger.pay("t1.csv", "2026-03-05", amount="-100.00", text="SYNTHETIC MOVE",
                           financial_type="transfer")
        assert "unconfirmed transfer kinds, actual, counted until classified: 1, 100.00" in (
            ledger.report())
        ledger.one_sided_ok(moved, "S")
        out = ledger.report()
        assert "unconfirmed transfer kinds, actual, counted until classified: 0, 0.00" in out
        assert "  Spent against the target, actual: 0.00" in out

    def test_a_refund_reduces_its_category_and_the_actual(self, ledger):
        ledger.run("category", "add", "Takeout", "--parent", "Dining")
        meal = ledger.pay("m1.csv", "2026-03-03", amount="-80.00", text="SYNTHETIC MEAL")
        back = ledger.pay("r1.csv", "2026-03-04", amount="5.00", text="SYNTHETIC MEAL BACK",
                          financial_type="refund")
        late = ledger.pay("m2.csv", "2026-03-05", amount="-30.00", text="SYNTHETIC TAKEOUT")
        ledger.categorize_ok(meal, "Dining")
        ledger.categorize_ok(back, "Dining")
        ledger.categorize_ok(late, "Takeout")
        out = ledger.report()
        assert "  Discretionary spending, actual: 3, 105.00" in out
        assert ("  Category Dining: allowance, planned 100.00, spent, actual 105.00, budget pace "
                "over by 5.00") in out


class TestMembers:  # BB4
    def test_members_and_unattributed_add_to_the_household(self, spent):
        spent.share_and_default()
        spent.add_account("B")
        spent.pay("x1.csv", "2026-03-07", amount="-7.01", text="SYNTHETIC ODD", account="B")
        household = spent.report()
        alex, bea = spent.report("--member", "Alex"), spent.report("--member", "Bea")
        cents = [int(spent.figure(out, "Spent against").replace(".", ""))
                 for out in (household, alex, bea)]
        unattributed = int(spent.figure(alex, "Unattributed").replace(".", ""))
        assert unattributed == int(spent.figure(bea, "Unattributed").replace(".", "")) == 701
        assert cents[1] + cents[2] + unattributed == cents[0]
        assert "  Target, planned: 600.00" in alex and "  Target, planned: 400.00" in bea
        assert "Remaining capacity, budget pace, provisional" in alex
        assert "or not yet attributed to a member" in alex

    def test_a_member_with_nothing_unclassified_or_unattributed_is_not_provisional(self, ledger):
        ledger.share_and_default()
        ledger.pay("d1.csv", "2026-03-03", amount="-40.01", text="SYNTHETIC SHOP")
        out = ledger.report("--member", "Bea")
        assert "  Discretionary spending, actual: 1, 20.00" in out
        assert "  Remaining capacity, budget pace: 380.00" in out
        assert "  Discretionary spending, actual: 1, 20.01" in ledger.report("--member", "Alex")

    def test_unattributed_spending_alone_makes_a_member_provisional(self, ledger):
        ledger.share_and_default()
        ledger.add_account("B")
        ledger.pay("x1.csv", "2026-03-07", amount="-7.00", text="SYNTHETIC ODD", account="B")
        out = ledger.report("--member", "Alex")
        assert "  Unattributed, actual, counted against the household only: 1, 7.00" in out
        assert "  Remaining capacity, budget pace, provisional: 600.00" in out
        assert "  Remaining capacity, budget pace: 993.00" in ledger.report()

    def test_an_unknown_member(self, ledger):
        code, _, err = ledger.run("report", "budget", "--as-of", AS_OF, "--member", "Cy")
        assert (code, err.strip()) == (2, "Error: household member not found. Run household "
                                          "members.")

    def test_a_plan_that_does_not_divide_has_no_member_target(self, ledger):
        ledger.set_plan_ok(from_month="2026-04", allowance="10.00")
        out = ledger.report("--member", "Alex", month="2026-04", as_of="2026-04-02")
        assert "  Target: none, the plan does not divide the allowance among members" in out
        assert "Remaining capacity" not in out


class TestMonths:  # BB5
    def test_a_third_paycheck_changes_nothing(self, capsys):
        outputs = []
        for third in (True, False):
            with tempfile.TemporaryDirectory() as folder:
                ledger = biweekly_ledger(Path(folder), capsys, third)
                ledger.__class__ = ReportLedger
                for name in ("Alex", "Bea"):
                    assert ledger.run("household", "member", "add", name)[0] == 0
                ledger.set_plan_ok(from_month="2026-01", allowance="1000.00", as_of="2026-01-01")
                ledger.pay("d1.csv", "2026-01-20", amount="-12.00", text="SYNTHETIC SHOP")
                outputs.append([ledger.report(month=month, as_of=as_of)
                                for month in ("2026-01", "2026-02", "2026-03")
                                for as_of in ("2026-01-31", "2026-02-14", "2026-04-01")])
        assert outputs[0] == outputs[1]
        assert "Baseline income, planned, context only: 5000.00" in outputs[0][0]

    def test_a_closed_month_shows_unused_capacity_planned(self, spent):
        out = spent.report(as_of="2026-04-01")
        assert "  Unused capacity, planned, to savings (not a bank transfer): 830.00" in out
        assert "Revised daily" not in out
        assert "Disclosure: target corrected" not in out

    def test_a_closed_month_over_target_has_no_unused_capacity(self, ledger):
        ledger.pay("d1.csv", "2026-03-03", amount="-1200.00", text="SYNTHETIC BIG")
        out = ledger.report(as_of="2026-04-01")
        assert "  Over target by 200.00, budget pace" in out
        assert "  Unused capacity, planned, to savings (not a bank transfer): 0.00" in out

    def test_a_corrected_closed_month_is_disclosed(self, ledger):
        ledger.set_plan_ok(from_month="2026-01", allowance="900.00", correct=True)
        for month in ("2026-01", "2026-02"):
            assert "  Disclosure: target corrected after the month closed" in ledger.report(
                month=month, as_of="2026-03-15")
        assert "Disclosure" not in ledger.report(month="2026-03", as_of="2026-04-15")

    def test_a_future_month_shows_the_plan_only(self, spent):
        out = spent.report(month="2026-04")
        assert "  A future month: the plan only." in out
        assert "Discretionary spending" not in out
        assert "  Target, planned: 1000.00" in out

    def test_a_month_with_no_plan(self, ledger):
        out = ledger.report(month="2026-02")
        assert "No budget plan applies to this month." in out
        assert "Target" not in out

    def test_pace_and_allowances_of_the_current_month(self, spent):
        out = spent.report()
        assert "  Days remaining, including today: 17 of 31" in out
        assert "  Revised daily allowance, budget pace: 48.82" in out
        assert "  Revised weekly allowance, budget pace: 341.76" in out
        assert "  Pace to date, budget pace: 483.87, below pace by 313.87" in out

    def test_over_target_lists_the_largest_five(self, ledger):
        for number in range(7):
            ledger.pay(f"d{number}.csv", f"2026-03-0{number + 1}", amount=f"-{200 + number}.00",
                       text=f"SYNTHETIC BIG {number}")
        out = ledger.report()
        assert "  Over target by 421.00, budget pace" in out
        listed = re.findall(r"SYNTHETIC BIG (\d)", out)
        assert listed == ["6", "5", "4", "3", "2"]
        assert "  Revised daily allowance, budget pace: 0.00" in out
        assert "  Equivalent days of original allowance, budget pace: " in out


class TestReadOnlyAndPage:  # BB6
    def test_it_writes_nothing_and_labels_every_figure(self, spent):
        conn = spent.conn()
        before = logical_digest(conn)
        conn.close()
        for words in ((), ("--member", "Alex")):
            for as_of in ("2026-03-15", "2026-04-01", "2026-02-01"):
                out = spent.report(*words, as_of=as_of)
                for line in out.splitlines():
                    if re.search(r"\d+\.\d\d", line) and "Transaction " not in line:
                        assert any(label in line for label in LABELS), line
        conn = spent.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_the_page_equals_the_command(self, spent):
        spent.share_and_default()
        conn = spent.conn()
        members = conn.execute("SELECT id, name FROM household_member ORDER BY id").fetchall()
        conn.close()
        client = UiClient(spent.path)
        client.sign_in()
        try:
            for member in (None, *members):
                for month, as_of in (("2026-03", AS_OF), ("2026-02", AS_OF),
                                     ("2026-04", AS_OF), (None, "2026-03-20")):
                    query = "&".join(part for part in (
                        f"as_of={as_of}", month and f"month={month}",
                        member and f"member={member[0]}") if part)
                    words = [*(["--month", month] if month else []),
                             *(["--member", member[1]] if member else [])]
                    assert page_text(client.get(f"/budget?{query}").body) == cli_output(
                        spent.capsys, "report", "budget", "--db", spent.db, "--as-of", as_of,
                        *words), query
            assert client.get("/budget?member=99&as_of=2026-03-01").status == 400
            assert client.get("/budget?month=2026-13&as_of=2026-03-01").status == 400
        finally:
            client.close()

    def test_names_on_the_page_are_text(self, ledger):
        assert ledger.run("category", "add", '<b>Eat&"</b>')[0] == 0
        ledger.set_plan_ok(from_month="2026-04", allowance="10.00",
                           categories=('<b>Eat&"</b>=5',))
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            page = parsed_page(client.get("/budget?as_of=2026-04-02").body)
            assert not {"b"} & set(page.tags)
            assert any('<b>Eat&"</b>' in line for line in page.report_lines)
        finally:
            client.close()


def test_totals_monthly_and_household_ignore_the_planning_tables(spent):  # G6 point 3
    spent.share_and_default()
    shown = [spent.run(*words) for words in (("totals",), ("report", "monthly"),
                                              ("report", "household"))]
    conn = connect(spent.path)
    for table in (*BUDGET_TABLES, *OBLIGATION_TABLES, *INCOME_TABLES):
        conn.execute(f"DROP TABLE {table}")
    conn.commit()
    conn.close()
    assert [spent.run(*words) for words in (("totals",), ("report", "monthly"),
                                             ("report", "household"))] == shown
