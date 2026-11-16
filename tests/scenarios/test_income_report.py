"""pf report income, by month, using synthetic data only (IC1 to IC4, D-068 points 3 and 8)."""

import re
import tempfile
from pathlib import Path

import pytest
from local_ui_client import UiClient, page_text, parsed_page
from test_decisions import INCOME_TABLES, OBLIGATION_TABLES
from test_local_ui import account_ids, cli_output
from test_obligations import ObligationLedger

from personal_finance.db.backups import logical_digest
from personal_finance.db.migrate import connect

AS_OF = "2026-03-31"
# Every figure line names one of these, so no planning figure goes unlabelled (G1).
LABELS = ("planned", "actual", "expected")


@pytest.fixture
def ledger(tmp_path, capsys):
    return ObligationLedger(tmp_path, capsys)


def report(ledger, *words, as_of=AS_OF):
    code, out, err = ledger.run("report", "income", "--as-of", as_of, *words)
    assert (code, err) == (0, ""), err
    return out


def month_block(out, month):
    lines = out.splitlines()
    start = lines.index(f"Month {month}")
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("Month ")), len(lines))
    return lines[start:end]


def biweekly_ledger(folder, capsys, third):
    """Biweekly pay from Friday 2026-01-02: January holds three pay dates, the 2nd, 16th and 30th.
    With third, the 30th is paid too."""
    ledger = ObligationLedger(folder, capsys)
    days = ["2026-01-02", "2026-01-16", "2026-02-13", "2026-02-27", "2026-03-13", "2026-03-27"]
    if third:
        days.append("2026-01-30")
    for number, day in enumerate(sorted(days)):
        ledger.deposit(f"p{number}.csv", day)
    ledger.add_ok()
    return ledger


class TestThreePaychecks:  # IC1
    def test_a_third_paycheck_leaves_every_baseline_line_alike_and_shows_once(self, capsys):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            with_third = report(biweekly_ledger(Path(one), capsys, third=True))
            without = report(biweekly_ledger(Path(two), capsys, third=False))
        for month in ("2026-01", "2026-02", "2026-03"):
            baseline = [line for line in month_block(with_third, month) if "aseline" in line]
            assert baseline == [line for line in month_block(without, month)
                                if "aseline" in line], month
            assert any("Baseline, planned: 2, 5000.00" in line for line in baseline)
        extra = [line for line in with_third.splitlines() if "to goals (M14)" in line]
        assert extra == ["    Extra, actual received: 1, 2500.00: to goals (M14)"]
        assert "    Extra, expected: 0, missed: 1" in month_block(without, "2026-01")
        assert "  Extra income, actual received: 2500.00, of which side 0.00" in month_block(
            with_third, "2026-01")

    def test_an_early_payment_across_a_month_end_is_not_a_third(self, ledger):
        # Semimonthly on the 1st and 15th: the 2026-02-01 pay arrives on 2026-01-31.
        for name, day in (("p1.csv", "2026-01-01"), ("p2.csv", "2026-01-15"),
                          ("p3.csv", "2026-01-31"), ("p4.csv", "2026-02-15")):
            ledger.deposit(name, day)
        ledger.add_ok(cadence="semimonthly:1,15", anchor="2026-01-01")
        out = report(ledger)
        assert "    Baseline, actual received: 2, 5000.00" in month_block(out, "2026-01")
        assert "    Baseline, actual received: 2, 5000.00" in month_block(out, "2026-02")
        assert "to goals" not in out

    def test_a_late_payment_the_other_way(self, ledger):
        # Monthly on the 31st: January's pay arrives on 2026-02-02, February's on 2026-02-27.
        for name, day in (("p1.csv", "2026-02-02"), ("p2.csv", "2026-02-27")):
            ledger.deposit(name, day)
        ledger.add_ok(cadence="monthly:31", anchor="2026-01-31")
        out = report(ledger)
        assert "    Baseline, actual received: 1, 2500.00" in month_block(out, "2026-01")
        assert "    Baseline, actual received: 1, 2500.00" in month_block(out, "2026-02")
        assert "to goals" not in out

    def test_2026_s_three_paycheck_months_for_a_friday_anchor(self, ledger):
        ledger.deposit("p1.csv", "2026-01-02")
        ledger.add_ok()
        out = report(ledger, "--from", "2026-01", "--to", "2026-12", as_of="2026-12-31")
        # By hand: Fridays every 14 days from 2026-01-02 give three in January and July.
        extra_months = [month for month in (f"2026-{number:02d}" for number in range(1, 13))
                        if any(line.startswith("    Extra,") for line in month_block(out, month))]
        assert extra_months == ["2026-01", "2026-07"]


class TestSideIncome:  # IC2
    def test_side_income_is_never_baseline_and_is_extra_when_received(self, ledger):
        ledger.deposit("s1.csv", "2026-02-10", amount="300.00", text="SYNTHETIC GIG")
        ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="monthly:10",
                      anchor="2026-02-10", amount="300.00")
        out = report(ledger)
        assert "aseline, planned: 0" not in out
        assert "Baseline, planned" not in "\n".join(month_block(out, "2026-02"))
        assert "    Side, actual received: 1, 300.00: to goals (M14)" in month_block(
            out, "2026-02")
        assert "  Baseline income, planned: 0.00" in month_block(out, "2026-02")
        assert "  Extra income, actual received: 300.00, of which side 300.00" in month_block(
            out, "2026-02")
        assert "    Side, expected: 0, missed: 1" in month_block(out, "2026-03")


@pytest.fixture
def full(ledger):
    """Pay, a side gig, a fixed and a discretionary obligation, a conflict, a possible paycheck
    and a payment out of range."""
    for name, day in (("p1.csv", "2026-01-02"), ("p2.csv", "2026-01-16"),
                      ("p3.csv", "2026-01-30"), ("p4.csv", "2026-02-13")):
        ledger.deposit(name, day)
    ledger.deposit("maybe.csv", "2026-02-27", financial_type=None)
    ledger.add_ok(name='<b>Pay&amp;"</b>')
    for name, day, amount in (("b1.csv", "2026-01-05", "-85.00"),
                              ("b2.csv", "2026-02-05", "-140.00")):
        ledger.pay(name, day, amount=amount)
    ledger.ob_add_ok()
    ledger.pay("g1.csv", "2026-01-12", amount="-40.00", text="SYNTHETIC GYM")
    ledger.ob_add_ok(name="Gym", match="synthetic gym", cadence="monthly:12",
                     anchor="2026-01-12", amount="40.00", obligation_class="discretionary")
    ledger.ob_add_ok(name="Gym too", match="gym", cadence="monthly:12", anchor="2026-01-12",
                     amount="40.00", obligation_class="discretionary")
    return ledger


class TestReport:  # IC3
    def test_obligations_due_and_paid_by_class_and_disclosures(self, full):
        out = report(full)
        january = month_block(out, "2026-01")
        assert "  Fixed obligations due, planned: 1, 85.00" in january
        assert "  Fixed obligations paid, actual: 1, 85.00" in january
        assert "  Discretionary obligations due, planned: 2, 80.00" in january
        assert "  Discretionary obligations paid, actual: 0, 0.00" in january
        assert "  Disclosure: 2 payments two obligations reach, counted as discretionary" in (
            january)
        february = month_block(out, "2026-02")
        assert "  Fixed obligations paid, actual: 1, 140.00" in february
        assert "  Disclosure: 1 payments outside their obligation's range" in february
        assert ("  Possible paychecks, unclassified, actual, never counted: 1, 2500.00"
                in february)
        assert "  Fixed obligations expected: 0, missed: 1" in month_block(out, "2026-03")

    def test_every_figure_is_labelled(self, full):
        for line in report(full).splitlines():
            if re.search(r"\d+\.\d\d", line) and not line.startswith(("Income and", "Month")):
                assert any(label in line for label in LABELS), line

    def test_it_opens_read_only_and_changes_no_digest(self, full):
        conn = full.conn()
        before = logical_digest(conn)
        conn.close()
        report(full)
        report(full, "--account", "A", "--from", "2026-02")
        conn = full.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_an_as_of_is_required_and_months_are_checked(self, full):
        with pytest.raises(SystemExit) as refused:
            full.run("report", "income")
        assert refused.value.code == 2
        code, _, err = full.run("report", "income", "--as-of", "2026-3-1")
        assert code == 2 and "--as-of must be a date" in err
        code, _, err = full.run("report", "income", "--as-of", AS_OF, "--from", "2026-03",
                                "--to", "2026-01")
        assert code == 2 and "--from is after --to" in err

    def test_one_account_shows_only_its_own(self, full):
        full.add_account("B")
        out = report(full, "--account", "B")
        assert "Pay" not in out and "Fixed obligations due, planned: 0, 0.00" in out


MONTH_RANGES = [(None, None), ("2026-01", "2026-01"), ("2026-02", None)]


def assert_income_pages_equal_the_cli(ledger):
    client = UiClient(ledger.path)
    client.sign_in()
    try:
        for account_id in (None, *account_ids(ledger.path)):
            for first, last in MONTH_RANGES:
                query = "&".join(part for part in (
                    f"as_of={AS_OF}", account_id and f"account={account_id}",
                    first and f"from={first}", last and f"to={last}") if part)
                words = [*(["--account", account_id] if account_id else []),
                         *(["--from", first] if first else []),
                         *(["--to", last] if last else [])]
                assert page_text(client.get(f"/income?{query}").body) == cli_output(
                    ledger.capsys, "report", "income", "--db", ledger.db, "--as-of", AS_OF,
                    *words), query
    finally:
        client.close()


class TestPage:  # IC3
    def test_the_page_equals_the_command_and_names_are_text(self, full):
        assert_income_pages_equal_the_cli(full)
        client = UiClient(full.path)
        client.sign_in()
        try:
            page = parsed_page(client.get(f"/income?as_of={AS_OF}").body)
            assert not {"b"} & set(page.tags)
            assert any('<b>Pay&amp;"</b>' in line for line in page.report_lines)
            assert client.get("/income").status == 200
            assert client.get("/income?as_of=2026-13-01").status == 400
        finally:
            client.close()


def test_totals_and_monthly_ignore_the_planning_tables(full):  # G6 point 3, IC4
    shown = [full.run(*words) for words in (("totals",), ("report", "monthly"),
                                             ("totals", "--account", "A"))]
    conn = connect(full.path)
    for table in (*OBLIGATION_TABLES, *INCOME_TABLES):
        conn.execute(f"DROP TABLE {table}")
    conn.close()
    conn = connect(full.path)
    # Recreated empty from the migrations' own text, so the version stays current.
    from personal_finance.db.migrate import load_migrations
    for migration in load_migrations()[23:25]:
        conn.executescript(migration.path.read_text())
    conn.close()
    assert [full.run(*words) for words in (("totals",), ("report", "monthly"),
                                           ("totals", "--account", "A"))] == shown
