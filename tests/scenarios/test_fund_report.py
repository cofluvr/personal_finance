"""pf report funds and its page, using synthetic data only (GC1 and GC2, D-070 points 4 and 8).
GC3 is in test_backups.py and GC4 is the --funds benchmark row."""

import re
import tempfile
from pathlib import Path

import pytest
from local_ui_client import UiClient, page_text, parsed_page
from test_consumptions import ConsumptionLedger
from test_income_report import biweekly_ledger
from test_local_ui import cli_output

AS_OF = "2026-04-10"


class ReportLedger(ConsumptionLedger):
    def funds_report(self, as_of=AS_OF):
        code, out, err = self.run("report", "funds", "--as-of", as_of)
        assert (code, err) == (0, ""), err
        return out

    def lines_from(self, out, heading):
        """The indented lines after a heading line, up to the next unindented one."""
        found, inside = [], False
        for line in out.splitlines():
            if line.startswith(heading):
                inside = True
                continue
            if inside and not line.startswith("  "):
                break
            if inside:
                found.append(line.strip())
        return found


@pytest.fixture
def ledger(tmp_path, capsys):
    """March planned at 1,000.00 with 400.00 spent, so 600.00 is unused once it closes. In April:
    333.33 of tax-eligible side income under a 25% tax reserve. Savings observed at 5,000.00 holds
    600.00 of a 1,200.00 reserve due in September. A goal of 1,000.00 by December, and a monthly
    goal of 50.00."""
    ledger = ReportLedger(tmp_path, capsys)
    ledger.set_plan_ok(allowance="1000.00")
    ledger.pay("d1.csv", "2026-03-03", amount="-400.00", text="SYNTHETIC SHOP")
    ledger.add_typed_account("Savings", "savings")
    ledger.observe("Savings", "2026-03-01", "5000.00")
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        due="2026-09-01")
    ledger.assign_ok(ledger.reserve, "Savings", "600.00")
    ledger.car = ledger.add_fund_ok(name="Car", kind="goal", target="1000.00", by="2026-12")
    ledger.fun = ledger.add_fund_ok(name="Fun", kind="goal", monthly="50.00")
    ledger.deposit("g1.csv", "2026-04-05", amount="333.33", text="SYNTHETIC GIG")
    ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="monthly:5",
                  anchor="2026-04-05", amount="333.33", tax_eligible=True)
    ledger.tax = ledger.add_fund_ok(name="Tax", kind="tax", percent="25", as_of="2026-04-01")
    return ledger


def prioritized(ledger, *fund_ids):
    code, _, err = ledger.run("fund", "priority", *fund_ids, "--revision",
                              re.search(r"Priority revision: (fu1-\S+)",
                                        ledger.funds_shown(AS_OF))[1])
    assert code == 0, err


class TestExtraByPriority:  # GC1
    def test_the_extra_goes_down_the_list_each_fund_to_its_need(self, ledger):
        prioritized(ledger, ledger.fun, ledger.reserve, ledger.car)
        out = ledger.funds_report()
        # 333.33 side income less ceil(333.33 × 25%) = 83.34 accrued, plus 600.00 unused in March.
        assert ledger.lines_from(out, "Extra in 2026-04") == [
            "Extra paychecks received, actual: 0.00",
            "Side income received, actual: 333.33, less its tax reserve accrual 83.34, a "
            "planning reserve, not a calculated tax liability",
            "Unused capacity of 2026-03, planned: 600.00",
            "Extra to allocate, planned: 849.99",
            f"1. Fun ({ledger.fun}): no target, takes none, planned 0.00",
            f"2. Insurance ({ledger.reserve}): needs 600.00, planned 600.00",
            f"3. Car ({ledger.car}): needs 1000.00, planned 249.99",
            "Unallocated extra, planned: 0.00",
        ]

    def test_what_no_fund_needs_is_left_unallocated(self, ledger):
        prioritized(ledger, ledger.reserve)
        lines = ledger.lines_from(ledger.funds_report(), "Extra in 2026-04")
        assert lines[-2:] == [f"1. Insurance ({ledger.reserve}): needs 600.00, planned 600.00",
                              "Unallocated extra, planned: 249.99"]

    def test_with_no_list_all_of_it_is_unallocated(self, ledger):
        lines = ledger.lines_from(ledger.funds_report(), "Extra in 2026-04")
        assert lines[-2:] == ["No priority list: run fund priority to order the funds",
                              "Unallocated extra, planned: 849.99"]

    def test_nothing_is_assigned_and_no_ledger_table_changes(self, ledger):
        prioritized(ledger, ledger.reserve, ledger.car)
        before = (ledger.fund_tables(), ledger.evidence())
        ledger.funds_report()
        assert (ledger.fund_tables(), ledger.evidence()) == before

    def test_each_target_s_month_at_the_planned_rate(self, ledger):
        out = ledger.funds_report()
        reached = re.findall(r"Target reached at the planned rate: (.+)", out)
        # Insurance: 600.00 over April to September, 100.00 a month, so September. Car: 1,000.00
        # over nine months, 112.00 a month, so December. Fun has none, and Tax holds an amount.
        assert reached == ["2026-09", "2026-12", "no target", "a held amount, no planned rate"]

    def test_every_figure_is_labelled(self, ledger):
        for line in ledger.funds_report().splitlines():
            if re.search(r"\d+\.\d\d", line) and "revision" not in line:
                assert re.search(r"planned|actual|required|assigned|observed|liability|"
                                 r"outstanding|paid", line, re.IGNORECASE), line


class TestPage:  # GC2
    def test_the_page_and_the_command_agree_line_for_line(self, ledger):
        prioritized(ledger, ledger.reserve, ledger.car)
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            for as_of in (AS_OF, "2026-03-20", "2026-09-30"):
                assert page_text(client.get(f"/funds?as_of={as_of}").body) == cli_output(
                    ledger.capsys, "report", "funds", "--db", ledger.db, "--as-of", as_of)
            assert client.get("/funds?as_of=2026-13-01").status == 400
            assert client.request("POST", "/funds").status in (403, 405)
        finally:
            client.close()

    def test_names_on_the_page_are_text(self, ledger):
        ledger.add_fund_ok(name='<b>Boat&"</b>', kind="goal", target="10.00", by="2026-12",
                           as_of=AS_OF)
        client = UiClient(ledger.path)
        client.sign_in()
        try:
            page = parsed_page(client.get(f"/funds?as_of={AS_OF}").body)
            assert not {"b"} & set(page.tags)
            assert any('<b>Boat&"</b>' in line for line in page.report_lines)
        finally:
            client.close()


def test_a_third_paycheck_is_extra(capsys):  # GC1, point 4
    with tempfile.TemporaryDirectory() as folder:
        ledger = biweekly_ledger(Path(folder), capsys, third=True)
        ledger.__class__ = ReportLedger
        assert ledger.run("setting", "set", "household_timezone", "America/Chicago",
                          "--revision", ledger.setting_token())[0] == 0
        lines = ledger.lines_from(ledger.funds_report("2026-01-31"), "Extra in 2026-01")
    assert lines[0] == "Extra paychecks received, actual: 2500.00"
    assert lines[3] == "Extra to allocate, planned: 2500.00"


def test_an_undone_fund_is_counted_not_shown_and_names_are_escaped(ledger):
    boat = ledger.add_fund_ok(name="Boat\x1b[2J", kind="goal", target="10.00", by="2026-12",
                              as_of=AS_OF)
    prioritized(ledger, boat)
    out = ledger.funds_report()
    assert "\x1b" not in out and "Boat\\x1b[2J" in out
    prioritized(ledger)
    assert ledger.undo_fund(boat)[0] == 0
    out = ledger.funds_report()
    assert f"Fund {boat}" not in out
    assert "Undone funds, not shown: 1. Run funds." in out


def test_a_month_over_target_offers_no_capacity(ledger):
    ledger.pay("d2.csv", "2026-03-04", amount="-700.00", text="SYNTHETIC SHOP")
    lines = ledger.lines_from(ledger.funds_report(), "Extra in 2026-04")
    assert lines[2] == "Unused capacity of 2026-03, planned: 0.00"


def test_only_this_month_s_side_income_accrual_is_taken_from_the_extra(tmp_path, capsys):
    """A tax reserve from March over side income in March and April and a tax-eligible salary
    in April: the extra loses April's side accrual only, while the reserve accrues all three."""
    ledger = ReportLedger(tmp_path, capsys)
    for name, day, amount, text in (("g1.csv", "2026-03-05", "333.33", "SYNTHETIC GIG"),
                                    ("g2.csv", "2026-04-05", "333.33", "SYNTHETIC GIG"),
                                    ("p1.csv", "2026-04-02", "1000.00", "SYNTHETIC PAYROLL")):
        ledger.deposit(name, day, amount=amount, text=text)
    ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="monthly:5",
                  anchor="2026-03-05", amount="333.33", tax_eligible=True)
    ledger.add_ok(name="Pay", kind="salary", match="synthetic payroll", cadence="monthly:2",
                  anchor="2026-04-02", amount="1000.00", tax_eligible=True)
    ledger.add_fund_ok(name="Tax", kind="tax", percent="25", as_of="2026-03-01")
    out = ledger.funds_report()
    assert ("Side income received, actual: 333.33, less its tax reserve accrual 83.34"
            in out)
    assert "accrued 416.68 from 3 received occurrences" in out
