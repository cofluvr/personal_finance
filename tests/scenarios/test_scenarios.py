"""Scenarios and their inputs, end to end, using synthetic data only (XA1, XA2, D-074 points 1 and
2, the M18.1 slice plan). The migration is test_scenario_migration.py and the projection
test_scenario_compare.py."""

import re

import pytest
from planning_digest import evidence_digest
from test_safe_to_spend import AS_OF, SafeLedger

from personal_finance.planning import scenarios

TOKEN = r"sc1-[0-9a-f]{16}"
SCENARIO_TABLES = ("scenario", "scenario_event", "scenario_input", "scenario_input_event",
                   "scenario_promotion", "scenario_promotion_event", "scenario_promotion_entry")


class ScenarioLedger(SafeLedger):
    def scenario_add(self, name="Move", include_uncertain=False):
        words = ["scenario", "add", "--name", name]
        if include_uncertain:
            words.append("--include-uncertain")
        code, out, err = self.run(*words)
        assert (code, err) == (0, ""), err
        return re.search(r"Scenario (\S+) recorded", out)[1]

    def scenario_shown(self, scenario_id):
        code, out, err = self.run("scenario", "show", scenario_id)
        assert (code, err) == (0, ""), err
        return out

    def scenario_token(self, scenario_id, kind="Input"):
        return re.search(rf"^{kind} revision: ({TOKEN})$", self.scenario_shown(scenario_id),
                         re.MULTILINE)[1]

    def input_undo_token(self, scenario_id, input_id):
        return re.search(rf"Input {input_id}: .*\n    Undo revision: ({TOKEN})",
                         self.scenario_shown(scenario_id))[1]

    def input_add(self, scenario_id, *words, revision=None):
        return self.run("scenario", "input", "add", scenario_id, *words, "--revision",
                        revision or self.scenario_token(scenario_id))

    def input_ok(self, scenario_id, *words):
        code, out, err = self.input_add(scenario_id, *words)
        assert (code, err) == (0, ""), err
        return re.search(r"Input (\S+) recorded", out)[1]

    def input_undo(self, scenario_id, input_id, revision=None):
        return self.run("scenario", "input", "undo", scenario_id, input_id, "--revision",
                        revision or self.input_undo_token(scenario_id, input_id))

    def scenario_undo(self, scenario_id, revision=None):
        return self.run("scenario", "undo", scenario_id, "--revision",
                        revision or self.scenario_token(scenario_id, "Undo"))

    def input_row(self, input_id):
        conn = self.conn()
        try:
            conn.row_factory = lambda cursor, row: {
                column[0]: value for column, value in zip(cursor.description, row)}
            return conn.execute("SELECT * FROM scenario_input WHERE id = ?",
                                (input_id,)).fetchone()
        finally:
            conn.close()

    def state_of(self, scenario_id, input_id):
        return re.search(rf"Input {input_id}: (.+?):",
                         self.scenario_shown(scenario_id))[1]

    def digest(self):
        conn = self.conn()
        try:
            return evidence_digest(conn)
        finally:
            conn.close()


@pytest.fixture
def ledger(tmp_path, capsys):
    """test_safe_to_spend's household: a biweekly salary, Power at 85.00 fixed on the 5th, a
    mortgage with terms and a 1,500.00 May allowance. Also a reserve for insurance and an empty
    scenario."""
    ledger = ScenarioLedger(tmp_path, capsys)
    assert ledger.set_setting()[0] == 0
    ledger.salary = ledger.add_ok()
    ledger.observe("A", "2026-05-01", "5000.00")
    ledger.liquid_ok("A")
    ledger.power = ledger.ob_add_ok()
    ledger.add_typed_account("Mortgage", "loan")
    ledger.add_terms_ok("Mortgage")
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        cadence="annual:06-10", as_of=AS_OF)
    ledger.scenario = ledger.scenario_add()
    return ledger


# Each kind as typed, and the columns it is stored with.
KINDS = {
    "income": (("--kind", "income", "--amount", "3000.00", "--from", "2026-06-01", "--to",
                "2026-12-31", "--cadence", "monthly:1"),
               {"amount_cents": 300000, "to_date": "2026-12-31", "cadence": "monthly:1",
                "uncertain": 0, "gross": 0}),
    "gross income": (("--kind", "income", "--amount", "4000.00", "--from", "2026-06-01",
                      "--cadence", "biweekly", "--anchor", "2026-06-05", "--gross",
                      "--take-home-percent", "72.5"),
                     {"gross": 1, "take_home_basis_points": 7250, "anchor": "2026-06-05"}),
    "bonus": (("--kind", "bonus", "--amount", "2000.00", "--from", "2026-12-15"),
              {"cadence": "once", "uncertain": 1}),
    "confirmed bonus": (("--kind", "bonus", "--amount", "2000.00", "--from", "2026-12-15",
                         "--confirmed"), {"uncertain": 0}),
    "expense": (("--kind", "expense", "--amount", "40.00", "--from", "2026-06-01", "--cadence",
                 "monthly:20", "--uncertain"), {"uncertain": 1, "replaces_id": None}),
    "annual expense": (("--kind", "annual_expense", "--amount", "900.00", "--from",
                        "2026-06-01", "--cadence", "annual:09-01"), {"cadence": "annual:09-01"}),
    "purchase": (("--kind", "purchase", "--amount", "1800.00", "--from", "2026-08-01"),
                 {"cadence": "once", "amount_cents": 180000}),
    "home purchase": (("--kind", "home_purchase", "--price", "300000.00", "--down-payment",
                       "60000.00", "--closing-costs", "6000.00", "--loan-rate", "6",
                       "--loan-months", "360", "--ownership-costs", "400.00", "--from",
                       "2026-09-10"),
                      {"amount_cents": 30000000, "down_payment_cents": 6000000,
                       "closing_costs_cents": 600000, "ownership_costs_cents": 40000,
                       "loan_rate_millionths": 6000000, "loan_months": 360}),
    "loan payoff": (("--kind", "loan_payoff", "--amount", "5000.00", "--loan", "Mortgage",
                     "--from", "2026-07-01"), {"amount_cents": 500000}),
    "borrowing": (("--kind", "borrowing", "--amount", "10000.00", "--loan-rate", "9.5",
                   "--loan-months", "48", "--from", "2026-07-01"),
                  {"loan_rate_millionths": 9500000, "loan_months": 48}),
}


class TestInputs:  # XA1, point 2
    @pytest.mark.parametrize("name", KINDS)
    def test_each_kind_is_stored_with_its_distinctions(self, ledger, name):
        words, columns = KINDS[name]
        input_id = ledger.input_ok(ledger.scenario, *words)
        row = ledger.input_row(input_id)
        assert {column: row[column] for column in columns} == columns
        assert row["scenario_id"] == ledger.scenario
        shown = ledger.scenario_shown(ledger.scenario)
        assert f"Input {input_id}: " in shown

    def test_replacements_name_their_entry(self, ledger):
        income = ledger.input_ok(ledger.scenario, "--kind", "income", "--amount", "2800.00",
                                 "--from", "2026-06-01", "--cadence", "biweekly", "--anchor",
                                 "2026-06-05", "--replaces", ledger.salary)
        expense = ledger.input_ok(ledger.scenario, "--kind", "expense", "--amount", "60.00",
                                  "--from", "2026-06-01", "--cadence", "monthly:5",
                                  "--replaces", ledger.power)
        annual = ledger.input_ok(ledger.scenario, "--kind", "annual_expense", "--amount",
                                 "1500.00", "--from", "2026-06-01", "--cadence", "annual:06-10",
                                 "--replaces", ledger.reserve)
        assert [(ledger.input_row(each)["replaces_kind"], ledger.input_row(each)["replaces_id"])
                for each in (income, expense, annual)] == [
            ("income_source", ledger.salary), ("recurring_obligation", ledger.power),
            ("fund", ledger.reserve)]
        assert f"replaces income source {ledger.salary}" in ledger.scenario_shown(ledger.scenario)

    def test_a_payoff_is_on_its_loan_s_terms(self, ledger):
        input_id = ledger.input_ok(ledger.scenario, *KINDS["loan payoff"][0])
        conn = ledger.conn()
        (terms_id,) = conn.execute("SELECT id FROM loan_terms").fetchone()
        conn.close()
        assert ledger.input_row(input_id)["loan_terms_id"] == terms_id

    def test_promotion_target_on_an_additional_income(self, ledger):
        input_id = ledger.input_ok(ledger.scenario, "--kind", "income", "--amount", "500.00",
                                   "--from", "2026-06-01", "--cadence", "monthly:15",
                                   "--account", "A", "--match", "synthetic tutoring")
        row = ledger.input_row(input_id)
        assert row["match_text"] == "synthetic tutoring" and row["account_id"]


REFUSALS = [
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence", "monthly:1",
      "--gross"), scenarios.GROSS_NEEDS_PERCENT),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence", "monthly:1",
      "--take-home-percent", "70"), scenarios.PERCENT_NEEDS_GROSS),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence", "monthly:1",
      "--gross", "--take-home-percent", "0.99"), scenarios.TAKE_HOME_RANGE),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence", "monthly:1",
      "--gross", "--take-home-percent", "100.01"), scenarios.TAKE_HOME_RANGE),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--to", "2026-05-31",
      "--cadence", "monthly:1"), scenarios.TO_BEFORE_FROM),
    (("--kind", "purchase", "--amount", "100.00", "--from", "2026-06-01", "--cadence",
      "monthly:1"), scenarios.OPTION_NOT_TAKEN.format(option="--cadence", kind="purchase")),
    (("--kind", "purchase", "--amount", "100.00", "--from", "2026-06-01", "--to", "2026-07-01"),
     scenarios.OPTION_NOT_TAKEN.format(option="--to", kind="purchase")),
    (("--kind", "income", "--price", "100.00", "--amount", "1.00", "--from", "2026-06-01",
      "--cadence", "monthly:1"), scenarios.OPTION_NOT_TAKEN.format(option="--price",
                                                                    kind="income")),
    (("--kind", "expense", "--amount", "10.00", "--from", "2026-06-01", "--gross",
      "--take-home-percent", "50", "--cadence", "monthly:1"),
     scenarios.OPTION_NOT_TAKEN.format(option="--gross", kind="expense")),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01"),
     scenarios.OPTION_REQUIRED.format(kind="income", option="--cadence")),
    (("--kind", "home_purchase", "--price", "100.00", "--from", "2026-06-01"),
     scenarios.OPTION_REQUIRED.format(kind="home_purchase", option="--down-payment")),
    (("--kind", "rent", "--amount", "1.00", "--from", "2026-06-01"), scenarios.KIND_UNKNOWN),
    (("--kind", "annual_expense", "--amount", "100.00", "--from", "2026-06-01", "--cadence",
      "monthly:1"), scenarios.ANNUAL_ONLY),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence",
      "biweekly"), scenarios.ANCHOR_REQUIRED),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence",
      "monthly:1", "--anchor", "2026-06-01"), scenarios.ANCHOR_NOT_TAKEN),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence",
      "quarterly:5", "--anchor", "2026-06-06"), scenarios.ANCHOR_OFF_CADENCE),
    (("--kind", "income", "--amount", "-1.00", "--from", "2026-06-01", "--cadence",
      "monthly:1"), scenarios.AMOUNT_INVALID.format(option="--amount")),
    (("--kind", "bonus", "--amount", "1.00", "--from", "2026-06-01", "--uncertain",
      "--confirmed"), scenarios.UNCERTAIN_AND_CONFIRMED),
    (("--kind", "home_purchase", "--price", "100.00", "--down-payment", "100.01",
      "--closing-costs", "0", "--loan-rate", "5", "--loan-months", "12", "--ownership-costs",
      "0", "--from", "2026-06-01"), scenarios.DOWN_PAYMENT_ABOVE_PRICE),
    (("--kind", "borrowing", "--amount", "100.00", "--loan-rate", "5", "--loan-months", "601",
      "--from", "2026-06-01"), scenarios.LOAN_MONTHS_INVALID),
    (("--kind", "loan_payoff", "--amount", "100.00", "--loan", "A", "--from", "2026-06-01"),
     scenarios.NO_LOAN_TERMS.format(account="A")),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-01", "--cadence",
      "monthly:1", "--account", "A"), scenarios.ACCOUNT_AND_MATCH),
    (("--kind", "income", "--amount", "100.00", "--from", "2026-06-31", "--cadence",
      "monthly:1"), "--from must be a date written YYYY-MM-DD. Nothing was changed."),
]


class TestRefusals:  # XA1, the M18.1 slice plan point 2
    @pytest.mark.parametrize("words, message", REFUSALS)
    def test_each_refusal_changes_nothing(self, ledger, words, message):
        before = ledger.dump(SCENARIO_TABLES)
        code, _, err = ledger.input_add(ledger.scenario, *words)
        assert (code, err.strip()) == (2, f"Error: {message}")
        assert ledger.dump(SCENARIO_TABLES) == before

    def test_a_replacement_of_the_wrong_kind(self, ledger):
        code, _, err = ledger.input_add(ledger.scenario, "--kind", "expense", "--amount", "1.00",
                                        "--from", "2026-06-01", "--cadence", "monthly:5",
                                        "--replaces", ledger.salary)
        assert code == 2 and scenarios.REPLACED_WRONG_KIND.format(
            kind="expense", expected="a recurring obligation", entry=ledger.salary) in err

    def test_an_annual_expense_replaces_a_reserve_only(self, ledger):
        goal = ledger.add_fund_ok(name="Car", monthly="100.00", as_of=AS_OF)
        code, _, err = ledger.input_add(ledger.scenario, "--kind", "annual_expense", "--amount",
                                        "1.00", "--from", "2026-06-01", "--cadence",
                                        "annual:06-10", "--replaces", goal)
        assert code == 2 and scenarios.REPLACED_NOT_RESERVE.format(entry=goal) in err

    def test_a_replacement_of_an_entry_not_applying(self, ledger):
        assert ledger.ob_undo(ledger.power)[0] == 0
        code, _, err = ledger.input_add(ledger.scenario, "--kind", "expense", "--amount", "1.00",
                                        "--from", "2026-06-01", "--cadence", "monthly:5",
                                        "--replaces", ledger.power)
        assert code == 2 and scenarios.REPLACED_NOT_APPLYING.format(entry=ledger.power) in err

    def test_a_replacement_promotes_onto_its_entry_so_takes_no_account(self, ledger):
        code, _, err = ledger.input_add(ledger.scenario, "--kind", "expense", "--amount", "1.00",
                                        "--from", "2026-06-01", "--cadence", "monthly:5",
                                        "--replaces", ledger.power, "--account", "A",
                                        "--match", "x")
        assert code == 2 and scenarios.ACCOUNT_ON_REPLACEMENT in err

    def test_a_stale_sc1(self, ledger):
        stale = ledger.scenario_token(ledger.scenario)
        ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        before = ledger.dump(SCENARIO_TABLES)
        code, _, err = ledger.input_add(ledger.scenario, *KINDS["bonus"][0], revision=stale)
        assert code == 2 and scenarios.STALE_SCENARIO_REVISION in err
        assert ledger.dump(SCENARIO_TABLES) == before

    def test_a_token_for_one_operation_never_authorizes_another(self, ledger):
        undo = ledger.scenario_token(ledger.scenario, "Undo")
        code, _, err = ledger.input_add(ledger.scenario, *KINDS["purchase"][0], revision=undo)
        assert code == 2 and scenarios.STALE_SCENARIO_REVISION in err
        add = ledger.scenario_token(ledger.scenario)
        code, _, err = ledger.scenario_undo(ledger.scenario, revision=add)
        assert code == 2 and scenarios.STALE_SCENARIO_REVISION in err

    def test_a_blank_name(self, ledger):
        code, _, err = ledger.run("scenario", "add", "--name", " ")
        assert code == 2 and scenarios.NAME_BLANK in err


class TestUndo:  # XA1, the M18.1 slice plan points 1 and 5
    def test_undo_an_input_then_the_scenario(self, ledger):
        input_id = ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        assert ledger.input_undo(ledger.scenario, input_id)[0] == 0
        assert ledger.state_of(ledger.scenario, input_id) == "undone"
        assert "Undo revision" not in ledger.scenario_shown(ledger.scenario).split(
            f"Input {input_id}")[1].split("\n")[1]
        assert ledger.scenario_undo(ledger.scenario)[0] == 0
        shown = ledger.scenario_shown(ledger.scenario)
        assert "Status: undone" in shown and "Input revision" not in shown
        assert ledger.input_row(input_id) is not None

    def test_an_undone_input_or_scenario_is_refused(self, ledger):
        input_id = ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        token = ledger.input_undo_token(ledger.scenario, input_id)
        assert ledger.input_undo(ledger.scenario, input_id, revision=token)[0] == 0
        code, _, err = ledger.input_undo(ledger.scenario, input_id, revision=token)
        assert code == 2 and scenarios.INPUT_NOT_ACTIVE in err
        add = ledger.scenario_token(ledger.scenario)
        assert ledger.scenario_undo(ledger.scenario)[0] == 0
        code, _, err = ledger.input_add(ledger.scenario, *KINDS["purchase"][0], revision=add)
        assert code == 2 and scenarios.SCENARIO_NOT_ACTIVE in err

    def test_an_input_of_another_scenario_is_not_found(self, ledger):
        other = ledger.scenario_add("Other")
        input_id = ledger.input_ok(other, *KINDS["purchase"][0])
        token = ledger.input_undo_token(other, input_id)
        code, _, err = ledger.input_undo(ledger.scenario, input_id, revision=token)
        assert code == 2 and scenarios.INPUT_NOT_FOUND in err

    def test_an_input_s_undo_token_names_that_input(self, ledger):
        first = ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        second = ledger.input_ok(ledger.scenario, *KINDS["bonus"][0])
        token = ledger.input_undo_token(ledger.scenario, first)
        code, _, err = ledger.input_undo(ledger.scenario, second, revision=token)
        assert code == 2 and scenarios.STALE_SCENARIO_REVISION in err

    def test_an_unknown_scenario(self, ledger):
        code, _, err = ledger.run("scenario", "show", "nope")
        assert code == 2 and "scenario not found" in err

    def test_scenarios_lists_each(self, ledger):
        ledger.input_ok(ledger.scenario, *KINDS["purchase"][0])
        ledger.input_ok(ledger.scenario, *KINDS["bonus"][0])
        uncertain = ledger.scenario_add("Hopeful", include_uncertain=True)
        out = ledger.run("scenarios")[1]
        assert (f"Scenario {ledger.scenario}: Move, active, 1 of 2 inputs counted, uncertain "
                "inputs left out") in out
        assert f"Scenario {uncertain}: Hopeful, active, 0 of 0 inputs counted" in out


class TestTargetChanged:  # XA2, point 1
    def replacing(self, ledger, *words):
        input_id = ledger.input_ok(ledger.scenario, *words)
        assert ledger.state_of(ledger.scenario, input_id) == "counted"
        return input_id

    def test_an_undone_source(self, ledger):
        input_id = self.replacing(ledger, "--kind", "income", "--amount", "2800.00", "--from",
                                  "2026-06-01", "--cadence", "monthly:1", "--replaces",
                                  ledger.salary)
        token = ledger.input_undo_token(ledger.scenario, input_id)
        assert ledger.undo(ledger.salary)[0] == 0
        assert ledger.state_of(ledger.scenario, input_id) == "target_changed, left out"
        # The state is in sc1, so a token shown before the change is stale.
        code, _, err = ledger.input_undo(ledger.scenario, input_id, revision=token)
        assert code == 2 and scenarios.STALE_SCENARIO_REVISION in err
        assert ledger.input_undo(ledger.scenario, input_id)[0] == 0

    def test_a_superseded_obligation(self, ledger):
        input_id = self.replacing(ledger, "--kind", "expense", "--amount", "60.00", "--from",
                                  "2026-06-01", "--cadence", "monthly:5", "--replaces",
                                  ledger.power)
        assert ledger.ob_add_ok(name="Power 2", supersedes=ledger.power, cadence=None,
                                anchor=None, amount=None, obligation_class=None)
        assert ledger.state_of(ledger.scenario, input_id) == "target_changed, left out"

    def test_an_undone_reserve(self, ledger):
        input_id = self.replacing(ledger, "--kind", "annual_expense", "--amount", "1500.00",
                                  "--from", "2026-06-01", "--cadence", "annual:06-10",
                                  "--replaces", ledger.reserve)
        assert ledger.run("fund", "undo", ledger.reserve, "--revision",
                          ledger.fund_token(ledger.reserve, "Undo"))[0] == 0
        assert ledger.state_of(ledger.scenario, input_id) == "target_changed, left out"

    def test_undone_loan_terms(self, ledger):
        input_id = self.replacing(ledger, *KINDS["loan payoff"][0])
        assert ledger.run("loan", "terms", "undo", "--account", "Mortgage", "--revision",
                          ledger.loan_token("Mortgage", "Undo"))[0] == 0
        assert ledger.state_of(ledger.scenario, input_id) == "target_changed, left out"

    def test_it_never_moves_to_the_superseding_entry(self, ledger):
        input_id = self.replacing(ledger, "--kind", "expense", "--amount", "60.00", "--from",
                                  "2026-06-01", "--cadence", "monthly:5", "--replaces",
                                  ledger.power)
        ledger.ob_add_ok(name="Power 2", supersedes=ledger.power, cadence=None, anchor=None,
                         amount=None, obligation_class=None)
        assert ledger.input_row(input_id)["replaces_id"] == ledger.power


class TestActualHistory:  # XC2, point 7
    def test_no_scenario_command_changes_the_evidence(self, ledger):
        before = ledger.digest()
        input_id = ledger.input_ok(ledger.scenario, *KINDS["home purchase"][0])
        ledger.input_ok(ledger.scenario, *KINDS["income"][0])
        assert ledger.digest() == before
        assert ledger.input_undo(ledger.scenario, input_id)[0] == 0
        assert ledger.scenario_undo(ledger.scenario)[0] == 0
        assert ledger.digest() == before
