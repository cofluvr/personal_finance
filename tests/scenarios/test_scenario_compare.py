"""scenario compare and the scenario pages, end to end, using synthetic data only (XB1, XB2, XB4,
D-074 points 3 to 5). The projection's arithmetic by hand is tests/unit/test_scenario_projection.py.
"""

import re

import pytest
from local_ui_client import page_text
from test_local_ui import unchanged_state
from test_local_ui_transaction_writes import all_post_forms, assert_browser_equals_cli
from test_local_ui_writes import Browser
from test_scenarios import KINDS, ScenarioLedger
from test_safe_to_spend import AS_OF

from personal_finance.cli import SCENARIO_MONTHS_INVALID
from personal_finance.ui import writes

SECTIONS = ("Monthly cash flow: ", "Liquidity at month end: ", "Daily allowance: ",
            "Weekly allowance: ", "Debt at month end (projection, not a forecast): ",
            "Net worth at month end (projection, not a forecast, scenario assets apart): ",
            "Scenario assets at month end: ", "Goals: ", "Loans at the horizon's end",
            "Cash shortfalls", "Unmet goals:", "Assumptions:", "Missing inputs:")
FIGURE = re.compile(r"^  (\d{4}-\d{2}): (\S+) \| (\S+) \| (\S+)$")


class CompareLedger(ScenarioLedger):
    def compared(self, scenario_id, *words, as_of=AS_OF):
        code, out, err = self.run("scenario", "compare", scenario_id, "--as-of", as_of, *words)
        assert (code, err) == (0, ""), err
        return out

    def section(self, out, title):
        """A monthly section's rows as (month, baseline, scenario, difference)."""
        lines = out.split(f"\n{title}: baseline | scenario | difference\n")[1].splitlines()
        rows = []
        for line in lines:
            found = FIGURE.match(line)
            if not found:
                break
            rows.append(found.groups())
        return rows


@pytest.fixture
def ledger(tmp_path, capsys):
    """test_scenarios' household with a 1,500.00 allowance from May, a buffer of 500.00, and an
    empty scenario."""
    ledger = CompareLedger(tmp_path, capsys)
    assert ledger.set_setting()[0] == 0
    ledger.salary = ledger.add_ok()
    ledger.observe("A", "2026-05-01", "5000.00")
    ledger.liquid_ok("A")
    ledger.power = ledger.ob_add_ok()
    ledger.budget_plan_ok(from_month="2026-05", allowance="1500.00", as_of=AS_OF)
    ledger.set_buffer("500.00")
    ledger.scenario = ledger.scenario_add()
    return ledger


class TestBaseline:  # XB1
    def test_no_inputs_is_the_baseline_line_for_line(self, ledger):
        out = ledger.compared(ledger.scenario)
        assert "  none: the scenario is the baseline" in out
        for title in ("Monthly cash flow", "Liquidity at month end", "Daily allowance",
                      "Weekly allowance"):
            rows = ledger.section(out, title)
            assert len(rows) == 24
            assert all(base == other and change == "0.00" for _, base, other, change in rows)
        assert "  baseline: none\n  scenario: none" in out

    def test_replacing_the_salary_counts_only_the_new_amount_in_range(self, ledger):
        ledger.input_ok(ledger.scenario, "--kind", "income", "--amount", "2600.00", "--from",
                        "2026-07-01", "--to", "2026-08-31", "--cadence", "biweekly", "--anchor",
                        "2026-07-03", "--replaces", ledger.salary)
        rows = ledger.section(ledger.compared(ledger.scenario, "--months", "6"),
                              "Monthly cash flow")
        # Paydays on alternate Fridays: 3, 17 and 31 July, 14 and 28 August, each 100.00 more.
        assert [change for _, _, _, change in rows] == ["0.00", "0.00", "+300.00", "+200.00",
                                                        "0.00", "0.00"]

    def test_a_look_alike_addition_counts_and_is_flagged(self, ledger):
        input_id = ledger.input_ok(ledger.scenario, "--kind", "expense", "--amount", "85.50",
                                   "--from", "2026-06-01", "--cadence", "monthly:5")
        out = ledger.compared(ledger.scenario, "--months", "3")
        assert (f"  Input {input_id}: counted: " in out
                and f"    possibly_already_planned: looks like {ledger.power}, counted as typed"
                in out)
        assert [change for _, _, _, change in ledger.section(out, "Monthly cash flow")] == [
            "0.00", "-85.50", "-85.50"]


class TestDefaults:  # XB2
    def test_uncertain_inputs_count_only_where_included(self, ledger):
        hopeful = ledger.scenario_add("Hopeful", include_uncertain=True)
        for scenario_id in (ledger.scenario, hopeful):
            ledger.input_ok(scenario_id, "--kind", "bonus", "--amount", "1000.00", "--from",
                            "2026-06-15")
        cautious = ledger.compared(ledger.scenario, "--months", "3")
        assert "left out: uncertain: bonus" in cautious
        assert all(change == "0.00" for _, _, _, change in
                   ledger.section(cautious, "Monthly cash flow"))
        included = ledger.compared(hopeful, "--months", "3")
        assert "Uncertain inputs: included" in included
        assert [change for _, _, _, change in ledger.section(included, "Monthly cash flow")] == [
            "0.00", "+1000.00", "0.00"]

    def test_every_output_is_present_with_assumptions_and_missing_inputs(self, ledger):
        out = ledger.compared(ledger.scenario, "--months", "2")
        positions = [out.index(title) for title in SECTIONS]
        assert positions == sorted(positions)
        assert "  discretionary spending at the budget target in full, never underspent" in out
        assert "  no account is valued: net worth is not projected" not in out

    def test_missing_inputs_are_named(self, tmp_path, capsys):
        bare = CompareLedger(tmp_path, capsys)
        assert bare.set_setting()[0] == 0
        scenario_id = bare.scenario_add()
        out = bare.compared(scenario_id, "--months", "1")
        for missing in ("no liquidity account is designated: the starting balance is 0",
                        "no checking buffer is set: the protected amount is 0",
                        "no account is valued: net worth is not projected",
                        "no budget plan in effect for 1 months, from 2026-05"):
            assert f"  {missing}" in out

    def test_discretionary_projects_at_the_target(self, ledger):
        out = ledger.compared(ledger.scenario, "--months", "3")
        # June has 30 days: 1,500.00 ÷ 30 a day.
        assert ledger.section(out, "Daily allowance")[1][1] == "50.00"

    def test_a_target_changed_input_is_disclosed_and_left_out(self, ledger):
        ledger.input_ok(ledger.scenario, "--kind", "expense", "--amount", "10.00", "--from",
                        "2026-06-01", "--cadence", "monthly:5", "--replaces", ledger.power)
        assert ledger.ob_undo(ledger.power)[0] == 0
        out = ledger.compared(ledger.scenario, "--months", "3")
        assert "target_changed, left out: the entry it replaces no longer applies" in out
        assert all(change == "0.00" for _, _, _, change in
                   ledger.section(out, "Monthly cash flow"))

    @pytest.mark.parametrize("months", ["0", "121", "x", "-1"])
    def test_the_horizon_is_1_to_120(self, ledger, months):
        code, _, err = ledger.run("scenario", "compare", ledger.scenario, "--as-of", AS_OF,
                                  "--months", months)
        assert code == 2 and SCENARIO_MONTHS_INVALID in err

    def test_no_timezone_refuses(self, tmp_path, capsys):
        bare = CompareLedger(tmp_path, capsys)
        scenario_id = bare.scenario_add()
        code, _, err = bare.run("scenario", "compare", scenario_id)
        assert code == 2 and "timezone" in err

    def test_scenario_assets_never_reach_actual_net_worth(self, ledger):
        before = ledger.run("report", "net-worth", "--as-of", AS_OF)
        ledger.input_ok(ledger.scenario, *KINDS["home purchase"][0])
        out = ledger.compared(ledger.scenario, "--months", "6")
        assert ledger.section(out, "Scenario assets at month end")[-1][2] == "300000.00"
        assert ledger.run("report", "net-worth", "--as-of", AS_OF) == before


class TestPages:  # XB4, point 5
    def test_each_page_is_its_command_line_for_line(self, ledger):
        ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        browser = Browser(ledger.path)
        try:
            for page, words in (
                    ("/scenarios", ("scenarios",)),
                    (f"/scenario?id={ledger.scenario}", ("scenario", "show", ledger.scenario)),
                    (f"/scenario/compare?id={ledger.scenario}&months=4&as_of={AS_OF}",
                     ("scenario", "compare", ledger.scenario, "--months", "4", "--as-of",
                      AS_OF))):
                response = browser.get(page)
                assert response.status == 200, response.text
                assert page_text(response.body) == ledger.run(*words)[1], page
        finally:
            browser.close()

    def test_a_get_writes_nothing(self, ledger):
        before = unchanged_state(ledger.path)
        browser = Browser(ledger.path)
        try:
            for page in ("/scenarios", f"/scenario?id={ledger.scenario}",
                         f"/scenario/compare?id={ledger.scenario}&as_of={AS_OF}"):
                assert browser.get(page).status == 200
        finally:
            browser.close()
        assert unchanged_state(ledger.path) == before

    def test_every_kind_has_its_form(self, ledger):
        browser = Browser(ledger.path)
        try:
            forms = all_post_forms(browser.get(f"/scenario?id={ledger.scenario}").body)
        finally:
            browser.close()
        actions = {form["action"] for form in forms}
        assert {f"/scenario/input/{kind}" for kind in (
            "income", "bonus", "expense", "annual_expense", "purchase", "home_purchase",
            "loan_payoff", "borrowing")} | {"/scenario/undo"} <= actions

    def test_adding_a_scenario_from_the_browser_equals_the_cli(self, ledger, tmp_path, capsys):
        def forms(browser):
            (found,) = [form["fields"] for form in all_post_forms(browser.get("/scenarios").body)
                        if form["action"] == "/scenario/add"]
            return {"/scenario/add": found}

        assert_browser_equals_cli(ledger, tmp_path, capsys, "/scenario/add",
                                  {"scenario_name": "Kids", "include_uncertain": "yes"},
                                  ["scenario", "add", "--name", "Kids", "--include-uncertain"],
                                  forms)

    def test_an_input_from_the_browser_equals_the_cli(self, ledger, tmp_path, capsys):
        def forms(browser):
            (found,) = [form["fields"] for form in all_post_forms(
                browser.get(f"/scenario?id={ledger.scenario}").body)
                        if form["action"] == "/scenario/input/income"]
            return {"/scenario/input/income": found}

        token = ledger.scenario_token(ledger.scenario)
        assert_browser_equals_cli(
            ledger, tmp_path, capsys, "/scenario/input/income",
            {"from_date": "2026-06-01", "input_amount": "4000.00", "cadence": "monthly:1",
             "gross": "yes", "take_home_percent": "70", "uncertain": "yes"},
            ["scenario", "input", "add", ledger.scenario, "--kind", "income", "--from",
             "2026-06-01", "--amount", "4000.00", "--cadence", "monthly:1", "--gross",
             "--take-home-percent", "70", "--uncertain", "--revision", token], forms)

    def test_undoing_an_input_then_the_scenario_from_the_browser(self, ledger):
        input_id = ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        browser = Browser(ledger.path)
        try:
            page = f"/scenario?id={ledger.scenario}"
            (undo,) = [form["fields"] for form in all_post_forms(browser.get(page).body)
                       if form["action"] == "/scenario/input-undo"]
            assert undo["input"] == input_id
            assert browser.post("/scenario/input-undo", undo).status == 303
            (whole,) = [form["fields"] for form in all_post_forms(browser.get(page).body)
                        if form["action"] == "/scenario/undo"]
            assert browser.post("/scenario/undo", whole).status == 303
            assert not [form for form in all_post_forms(browser.get(page).body)
                        if form["action"].startswith("/scenario/")]
        finally:
            browser.close()
        assert "Status: undone" in ledger.scenario_shown(ledger.scenario)

    def test_a_refused_input_shows_the_cli_s_message(self, ledger):
        browser = Browser(ledger.path)
        try:
            (form,) = [form["fields"] for form in all_post_forms(
                browser.get(f"/scenario?id={ledger.scenario}").body)
                       if form["action"] == "/scenario/input/income"]
            response = browser.post("/scenario/input/income",
                                    {**form, "from_date": "2026-06-01", "input_amount": "1.00",
                                     "cadence": "monthly:1", "gross": "yes",
                                     "uncertain": ""})
        finally:
            browser.close()
        assert response.status == 409 and "--gross needs --take-home-percent" in response.text

    def test_a_flag_takes_yes_or_nothing(self):
        route = writes.WRITE_ROUTES["/scenario/add"]
        (flag,) = [field for field in route.typed if field.kind == writes.FLAG]
        assert writes.acceptable(flag, "yes") and writes.acceptable(flag, "")
        for value in ("on", "true", "1", "--db=x", "YES"):
            assert not writes.acceptable(flag, value)
        assert writes.command_words("/scenario/add", {"scenario_name": "--db=x",
                                                      "include_uncertain": "yes"},
                                    "/ledger.db") == [
            "scenario", "add", "--db=/ledger.db", "--name=--db=x", "--include-uncertain"]
