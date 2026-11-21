"""Promoting a scenario and undoing it, end to end, using synthetic data only (XC1, XC2, D-074
points 6 and 7, the M18.3 slice plan)."""

import re

import pytest
from test_scenario_compare import CompareLedger
from test_scenarios import KINDS, SCENARIO_TABLES
from test_safe_to_spend import AS_OF

from personal_finance.planning import funds, promotions

TOKEN = r"sp1-[0-9a-f]{16}"
PLANNING = ("income_source", "income_source_terms", "income_source_event",
            "transaction_income_source", "recurring_obligation", "recurring_obligation_terms",
            "recurring_obligation_event", "transaction_obligation", "fund", "fund_terms",
            "fund_event", *SCENARIO_TABLES)


class PromotionLedger(CompareLedger):
    def promotion_token(self, scenario_id, kind="Promotion"):
        return re.search(rf"^{kind} revision: ({TOKEN})$", self.scenario_shown(scenario_id),
                         re.MULTILINE)[1]

    def promote(self, scenario_id, revision=None, as_of=AS_OF):
        return self.run("scenario", "promote", scenario_id, "--as-of", as_of, "--revision",
                        revision or self.promotion_token(scenario_id))

    def promote_ok(self, scenario_id):
        code, out, err = self.promote(scenario_id)
        assert (code, err) == (0, ""), err
        return out

    def unpromote(self, scenario_id, revision=None):
        return self.run("scenario", "promotion", "undo", scenario_id, "--revision",
                        revision or self.promotion_token(scenario_id, "Promotion undo"))

    def count(self, table):
        conn = self.conn()
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def entry_ids(self):
        conn = self.conn()
        try:
            return ([row[0] for row in conn.execute("SELECT id FROM income_source")],
                    [row[0] for row in conn.execute("SELECT id FROM recurring_obligation")],
                    [row[0] for row in conn.execute("SELECT id FROM fund")])
        finally:
            conn.close()

    def plan_shown(self, entry_ids):
        """Every show of the entries given, and the plan's figures."""
        sources, duties, reserves = entry_ids
        return ([self.show(source) for source in sources]
                + [self.ob_show(duty) for duty in duties]
                + [self.fund_shown(fund) for fund in reserves]
                + [self.run("safe-to-spend", "--as-of", AS_OF, "--explain")])


@pytest.fixture
def ledger(tmp_path, capsys):
    """test_scenario_compare's household with a reserve for insurance, annual on 10 June, and a
    scenario holding one of each promotable input."""
    ledger = PromotionLedger(tmp_path, capsys)
    assert ledger.set_setting()[0] == 0
    ledger.salary = ledger.add_ok()
    ledger.observe("A", "2026-05-01", "5000.00")
    ledger.liquid_ok("A")
    ledger.power = ledger.ob_add_ok()
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        cadence="annual:06-10", as_of=AS_OF)
    ledger.budget_plan_ok(from_month="2026-05", allowance="1500.00", as_of=AS_OF)
    ledger.scenario = ledger.scenario_add()
    ledger.inputs = {
        "raise": ledger.input_ok(ledger.scenario, "--kind", "income", "--amount", "2600.00",
                                 "--from", "2026-07-01", "--to", "2026-08-31", "--cadence",
                                 "biweekly", "--anchor", "2026-07-03", "--replaces",
                                 ledger.salary),
        "power": ledger.input_ok(ledger.scenario, "--kind", "expense", "--amount", "60.00",
                                 "--from", "2026-06-01", "--cadence", "monthly:5",
                                 "--replaces", ledger.power),
        "insurance": ledger.input_ok(ledger.scenario, "--kind", "annual_expense", "--amount",
                                     "1500.00", "--from", "2026-06-01", "--cadence",
                                     "annual:06-10", "--replaces", ledger.reserve),
        "tutoring": ledger.input_ok(ledger.scenario, "--kind", "income", "--amount", "500.00",
                                    "--from", "2026-06-01", "--cadence", "monthly:15",
                                    "--account", "A", "--match", "synthetic tutoring"),
        "gym": ledger.input_ok(ledger.scenario, "--kind", "expense", "--amount", "40.00",
                               "--from", "2026-06-01", "--cadence", "monthly:20", "--account",
                               "A", "--match", "synthetic gym"),
        "sofa": ledger.input_ok(ledger.scenario, "--kind", "purchase", "--amount", "1800.00",
                                "--from", "2026-08-01"),
        "taxes": ledger.input_ok(ledger.scenario, "--kind", "annual_expense", "--amount",
                                 "900.00", "--from", "2026-06-01", "--cadence", "annual:09-01"),
    }
    return ledger


NOT_PROMOTABLE = {
    "bonus": (KINDS["confirmed bonus"][0], promotions.NO_ONE_TIME_INCOME),
    "maybe": (("--kind", "expense", "--amount", "5.00", "--from", "2026-06-01", "--cadence",
               "monthly:2", "--uncertain"), promotions.UNCERTAIN_INPUT),
    "home": (KINDS["home purchase"][0], promotions.NEEDS_AN_ACCOUNT),
    "borrow": (KINDS["borrowing"][0], promotions.NEEDS_AN_ACCOUNT),
    "nowhere": (("--kind", "income", "--amount", "5.00", "--from", "2026-06-01", "--cadence",
                 "monthly:2"), promotions.NO_ACCOUNT_GIVEN),
    "ending": (("--kind", "expense", "--amount", "5.00", "--from", "2026-06-01", "--to",
                "2026-07-01", "--cadence", "monthly:2", "--account", "A", "--match", "x"),
               promotions.NO_END_DATE),
}


class TestPromote:  # XC1, point 6
    def test_it_makes_exactly_the_mapped_entries(self, ledger):
        not_promotable = {name: ledger.input_ok(ledger.scenario, *words)
                          for name, (words, _) in NOT_PROMOTABLE.items()}
        shown = ledger.scenario_shown(ledger.scenario)
        for name, (_, reason) in NOT_PROMOTABLE.items():
            assert f"  Input {not_promotable[name]}: not promotable: {reason}" in shown
        assert (f"  Input {ledger.inputs['raise']}: becomes a new terms row on income source "
                f"{ledger.salary}") in shown
        counts = {table: ledger.count(table) for table in PLANNING}
        out = ledger.promote_ok(ledger.scenario)
        made = re.findall(r"^  (\S+) ", out, re.MULTILINE)
        assert sorted(made) == sorted(["income_source_terms"] * 2 + ["recurring_obligation_terms",
                                       "fund_terms", "income_source", "recurring_obligation",
                                       "fund", "fund"])
        grown = {table: ledger.count(table) - counts[table] for table in PLANNING}
        assert {table: change for table, change in grown.items() if change} == {
            "income_source_terms": 3, "income_source": 1, "income_source_event": 1,
            "recurring_obligation_terms": 2, "recurring_obligation": 1,
            "recurring_obligation_event": 1, "fund_terms": 3, "fund": 2, "fund_event": 2,
            "scenario_promotion": 1, "scenario_promotion_event": 1,
            "scenario_promotion_entry": 8}
        # The raise from 1 July, and the salary's own terms again from 1 September.
        source = ledger.show(ledger.salary)
        assert "2026-07-01" in source and "2600.00" in source and "2026-09-01" in source

    def test_it_is_one_transaction(self, ledger):
        ledger.input_ok(ledger.scenario, "--kind", "purchase", "--amount", "10.00", "--from",
                        "2026-05-01")
        before = ledger.dump(PLANNING)
        code, _, err = ledger.promote(ledger.scenario)
        assert code == 2 and "--due must be no earlier than --effective-from" in err
        assert ledger.dump(PLANNING) == before

    def test_a_stale_sp1_is_refused(self, ledger):
        stale = ledger.promotion_token(ledger.scenario)
        ledger.input_ok(ledger.scenario, *KINDS["confirmed bonus"][0])
        code, _, err = ledger.promote(ledger.scenario, revision=stale)
        assert code == 2 and promotions.STALE_PROMOTION_REVISION in err

    def test_a_replaced_entry_changed_since_is_refused(self, ledger):
        stale = ledger.promotion_token(ledger.scenario)
        assert ledger.ob_terms(ledger.power, "2026-06-15", "--amount", "90.00",
                               as_of=AS_OF)[0] == 0
        before = ledger.dump(PLANNING)
        code, _, err = ledger.promote(ledger.scenario, revision=stale)
        assert code == 2 and promotions.STALE_PROMOTION_REVISION in err
        assert ledger.dump(PLANNING) == before

    def test_promoting_twice_or_nothing_is_refused(self, ledger, tmp_path, capsys):
        ledger.promote_ok(ledger.scenario)
        add = ledger.scenario_shown(ledger.scenario)
        assert "Promotion revision" not in add
        empty = ledger.scenario_add("Empty")
        ledger.input_ok(empty, *KINDS["confirmed bonus"][0])
        assert "Promotion revision" not in ledger.scenario_shown(empty)
        conn = ledger.conn()
        from personal_finance.planning.scenarios import find_scenario

        with pytest.raises(Exception, match="nothing in this scenario is promotable"):
            promotions.promote(conn, empty, AS_OF,
                               promotions.promotion_revision(conn, find_scenario(conn, empty)))
        scenario = find_scenario(conn, ledger.scenario)
        with pytest.raises(Exception, match="promoted already"):
            promotions.promote(conn, ledger.scenario, AS_OF,
                               promotions.promotion_revision(conn, scenario))
        conn.close()


class TestWhatIsMade:  # XC1, point 6's table
    def test_a_target_changed_input_is_listed_and_left_out(self, ledger):
        assert ledger.ob_undo(ledger.power)[0] == 0
        shown = ledger.scenario_shown(ledger.scenario)
        assert (f"  Input {ledger.inputs['power']}: not promotable: "
                f"{promotions.TARGET_GONE}") in shown
        out = ledger.promote_ok(ledger.scenario)
        assert "recurring_obligation_terms" not in out
        conn = ledger.conn()
        try:
            assert conn.execute("SELECT COUNT(*) FROM recurring_obligation_terms "
                                "WHERE chain_id = ?", (ledger.power,)).fetchone()[0] == 1
        finally:
            conn.close()

    def test_a_promoted_income_on_a_salary_cadence_is_salary(self, ledger):
        out = ledger.promote_ok(ledger.scenario)
        made = re.search(r"^  income_source (\S+),", out, re.MULTILINE)[1]
        assert ", salary, account A, description contains synthetic tutoring" in ledger.show(made)

    def test_a_purchase_is_a_reserve_due_on_its_date(self, ledger):
        out = ledger.promote_ok(ledger.scenario)
        made = [ledger.fund_shown(fund) for fund in re.findall(r"^  fund (\S+),", out,
                                                                re.MULTILINE)]
        assert any("2026-08-01" in shown and "1800.00" in shown for shown in made)

    def test_a_gross_replacement_promotes_its_take_home_amount(self, ledger):
        scenario_id = ledger.scenario_add("Gross")
        ledger.input_ok(scenario_id, "--kind", "income", "--amount", "4000.00", "--from",
                        "2026-07-01", "--cadence", "biweekly", "--anchor", "2026-07-03",
                        "--gross", "--take-home-percent", "65", "--replaces", ledger.salary)
        ledger.promote_ok(scenario_id)
        assert "Terms from 2026-07-01: biweekly, anchor 2026-07-03, expected 2600.00" in \
            ledger.show(ledger.salary)

    def test_an_undone_scenario_is_never_promoted(self, ledger):
        from personal_finance.planning.scenarios import SCENARIO_NOT_ACTIVE, find_scenario

        assert ledger.scenario_undo(ledger.scenario)[0] == 0
        assert "Promotion revision" not in ledger.scenario_shown(ledger.scenario)
        conn = ledger.conn()
        try:
            token = promotions.promotion_revision(conn, find_scenario(conn, ledger.scenario))
            with pytest.raises(Exception, match=SCENARIO_NOT_ACTIVE.split(".")[0]):
                promotions.promote(conn, ledger.scenario, AS_OF, token)
        finally:
            conn.close()


class TestUndo:  # XC1
    def test_undo_gives_back_every_entry_s_show_and_token(self, ledger):
        existing = ledger.entry_ids()
        before = ledger.plan_shown(existing)
        ledger.promote_ok(ledger.scenario)
        assert ledger.plan_shown(existing) != before
        code, out, err = ledger.unpromote(ledger.scenario)
        assert (code, err) == (0, ""), err
        assert ledger.plan_shown(existing) == before
        # The entries the promotion made stay on record, undone.
        sources, duties, reserves = ledger.entry_ids()
        made = (set(sources) - set(existing[0]), set(duties) - set(existing[1]),
                set(reserves) - set(existing[2]))
        assert [len(each) for each in made] == [1, 1, 2]
        for shown in ([ledger.show(each) for each in made[0]]
                      + [ledger.ob_show(each) for each in made[1]]
                      + [ledger.fund_shown(each) for each in made[2]]):
            assert "Status: undone" in shown

    def test_undo_rewrites_what_each_payment_is(self, ledger):
        ledger.pay("power.csv", "2026-06-05")
        scenario_id = ledger.scenario_add("Cheaper power")
        ledger.input_ok(scenario_id, "--kind", "expense", "--amount", "60.00", "--from",
                        "2026-06-01", "--cadence", "monthly:5", "--replaces", ledger.power)
        before = ledger.dump(("transaction_obligation",))
        ledger.promote_ok(scenario_id)
        assert ledger.dump(("transaction_obligation",)) != before
        assert ledger.unpromote(scenario_id)[0] == 0
        assert ledger.dump(("transaction_obligation",)) == before

    def test_undo_refuses_after_a_later_terms_row(self, ledger):
        ledger.promote_ok(ledger.scenario)
        code, _, err = ledger.run("income", "terms", ledger.salary, "--effective-from",
                                  "2026-10-01", "--amount", "2700.00", "--as-of", AS_OF,
                                  "--revision", ledger.token(ledger.salary, "Terms"))
        assert (code, err) == (0, ""), err
        before = ledger.dump(PLANNING)
        code, _, err = ledger.unpromote(ledger.scenario)
        assert code == 2 and "a later terms row from 2026-10-01" in err
        assert ledger.dump(PLANNING) == before

    def test_undo_refuses_after_a_made_entry_is_superseded(self, ledger):
        out = ledger.promote_ok(ledger.scenario)
        made = re.search(r"^  recurring_obligation (\S+),", out, re.MULTILINE)[1]
        ledger.ob_add_ok(name="Gym 2", match="synthetic gym two", supersedes=made, cadence=None,
                         anchor=None, amount=None, obligation_class=None)
        code, _, err = ledger.unpromote(ledger.scenario)
        assert code == 2 and f"obligation {made} has changed since" in err

    def test_undo_refuses_while_a_made_reserve_holds_money(self, ledger):
        out = ledger.promote_ok(ledger.scenario)
        made = re.findall(r"^  fund (\S+),", out, re.MULTILINE)[0]
        ledger.assign_ok(made, "A", "100.00", as_of=AS_OF)
        code, _, err = ledger.unpromote(ledger.scenario)
        assert code == 2 and funds.UNDO_ASSIGNED.format(accounts="A") in err
        assert ledger.count("scenario_promotion_event") == 1

    def test_a_stale_undo_token_and_undoing_twice(self, ledger):
        ledger.promote_ok(ledger.scenario)
        token = ledger.promotion_token(ledger.scenario, "Promotion undo")
        assert ledger.unpromote(ledger.scenario, revision=token)[0] == 0
        code, _, err = ledger.unpromote(ledger.scenario, revision=token)
        assert code == 2 and promotions.NOT_PROMOTED in err

    def test_promoting_again_on_a_withdrawn_date_is_refused_clearly(self, ledger):
        ledger.promote_ok(ledger.scenario)
        assert ledger.unpromote(ledger.scenario)[0] == 0
        code, _, err = ledger.promote(ledger.scenario)
        assert code == 2 and "an undone promotion's terms row holds" in err


class TestActualHistory:  # XC2, point 7
    def test_promote_and_its_undo_change_no_evidence(self, ledger):
        before = ledger.digest()
        ledger.promote_ok(ledger.scenario)
        assert ledger.digest() == before
        assert ledger.unpromote(ledger.scenario)[0] == 0
        assert ledger.digest() == before
