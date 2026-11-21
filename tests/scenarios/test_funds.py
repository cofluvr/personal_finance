"""Funds, assignments and the priority list stated by a person, end to end, using synthetic data
only (GA2 to GA5, D-070 points 1 to 4, D-067 G1 to G4 and G7)."""

import re
import tempfile
from pathlib import Path

import pytest
from planning_digest import evidence_digest
from test_decisions import FUND_TABLES
from test_income_report import biweekly_ledger
from test_obligations import ObligationLedger

from personal_finance.db.backups import logical_digest
from personal_finance.planning import funds
from personal_finance.planning.funds import (
    ACCOUNT_NOT_ASSIGNABLE,
    ALREADY_ASSIGNED,
    AMOUNT_INVALID,
    ANCHOR_OFF_CADENCE,
    BEYOND_OBSERVATION,
    BY_BEFORE_START,
    CADENCE_FOR_RESERVE,
    CLOSED_MONTH,
    DUE_BEFORE_START,
    FUND_NOT_ACTIVE,
    FUND_NOT_FOUND,
    KIND_UNKNOWN,
    MONTHS_INVALID,
    NAME_BLANK,
    NAME_TAKEN,
    NO_OBSERVATION,
    NOT_ASSIGNED,
    ONE_ACTIVE,
    PERCENT_INVALID,
    PRIORITY_KIND,
    PRIORITY_REPEATED,
    STALE_ASSIGNMENT_REVISION,
    STALE_FUND_PREVIEW,
    STALE_FUND_REVISION,
    STALE_PRIORITY_REVISION,
    TERMS_FOR_KIND,
    TERMS_NOT_LATER,
    UNDO_ASSIGNED,
)

AS_OF = "2026-03-15"
FUND_TOKEN = r"fu1-[0-9a-f]{16}"
ASSIGNMENT_TOKEN = r"fa1-[0-9a-f]{16}"
NO_TOKEN = "fa1-0000000000000000"


class FundLedger(ObligationLedger):
    def add_typed_account(self, name, account_type):
        assert self.run("account", "add", "--name", name, "--type", account_type)[0] == 0

    def observe(self, account, day, balance, option="--balance"):
        code, _, err = self.run("balance", "record", "--account", account, "--date", day,
                                option, balance)
        assert code == 0, err

    def fund_words(self, name="House", kind="goal", as_of=AS_OF, effective_from=None, **terms):
        words = ["--name", name, "--kind", kind]
        if not terms and kind == "goal":
            terms = {"monthly": "500.00"}
        for option, value in terms.items():
            words += ["--" + option.replace("_", "-"), value]
        if effective_from is not None:
            words += ["--effective-from", effective_from]
        return words + ["--as-of", as_of]

    def fund_preview(self, **options):
        return self.run("fund", "preview", *self.fund_words(**options))

    def fund_preview_revision(self, **options):
        code, out, err = self.fund_preview(**options)
        assert (code, err) == (0, ""), err
        return re.search(rf"Revision: ({FUND_TOKEN})", out)[1]

    def add_fund(self, revision=None, **options):
        return self.run("fund", "add", *self.fund_words(**options), "--revision",
                        revision or self.fund_preview_revision(**options))

    def add_fund_ok(self, **options):
        code, out, err = self.add_fund(**options)
        assert (code, err) == (0, ""), err
        return re.search(r"Fund (\S+) recorded", out)[1]

    def fund_shown(self, fund_id, as_of=AS_OF):
        code, out, err = self.run("fund", "show", fund_id, "--as-of", as_of)
        assert (code, err) == (0, ""), err
        return out

    def fund_token(self, fund_id, kind):
        return re.search(rf"^{kind} revision: ({FUND_TOKEN})", self.fund_shown(fund_id),
                         re.MULTILINE)[1]

    def funds_shown(self, as_of=AS_OF):
        code, out, err = self.run("funds", "--as-of", as_of)
        assert (code, err) == (0, ""), err
        return out

    def assignment_token(self, fund_id, account, as_of=AS_OF):
        out = self.fund_shown(fund_id, as_of)
        block = out.split(f"  Account {account}:")[1].split("\n  Account ")[0]
        return re.search(rf"Assignment revision, to \w+: ({ASSIGNMENT_TOKEN})", block)[1]

    def assign(self, fund_id, account, amount, revision=None, as_of=AS_OF):
        return self.run("fund", "assign", "--fund", fund_id, "--account", account, "--amount",
                        amount, "--as-of", as_of, "--revision",
                        revision or self.assignment_token(fund_id, account, as_of))

    def assign_ok(self, fund_id, account, amount, **options):
        code, _, err = self.assign(fund_id, account, amount, **options)
        assert (code, err) == (0, ""), err

    def unassign(self, fund_id, account, revision=None, as_of=AS_OF):
        return self.run("fund", "unassign", "--fund", fund_id, "--account", account, "--as-of",
                        as_of, "--revision",
                        revision or self.assignment_token(fund_id, account, as_of))

    def terms(self, fund_id, effective_from, revision=None, as_of=AS_OF, **terms):
        words = ["fund", "terms", fund_id, "--effective-from", effective_from, "--as-of", as_of]
        for option, value in terms.items():
            words += ["--" + option.replace("_", "-"), value]
        return self.run(*words, "--revision", revision or self.fund_token(fund_id, "Terms"))

    def undo_fund(self, fund_id, revision=None):
        return self.run("fund", "undo", fund_id, "--revision",
                        revision or self.fund_token(fund_id, "Undo"))

    def priority_token(self):
        return re.search(rf"Priority revision: ({FUND_TOKEN})", self.funds_shown())[1]

    def set_priority(self, *fund_ids, revision=None):
        return self.run("fund", "priority", *fund_ids, "--revision",
                        revision or self.priority_token())

    def fund_tables(self):
        conn = self.conn()
        try:
            return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in FUND_TABLES}
        finally:
            conn.close()

    def evidence(self):
        conn = self.conn()
        try:
            return evidence_digest(conn)
        finally:
            conn.close()

    def logical(self):
        conn = self.conn()
        try:
            return logical_digest(conn)
        finally:
            conn.close()

    def refused(self, attempt, message):
        """The attempt fails with exactly this message, and no table changes."""
        before = (self.fund_tables(), self.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (self.fund_tables(), self.evidence()) == before


@pytest.fixture
def ledger(tmp_path, capsys):
    ledger = FundLedger(tmp_path, capsys)
    ledger.add_typed_account("Savings", "savings")
    ledger.observe("Savings", "2026-03-01", "5000.00")
    return ledger


# GA2: required amounts as the commands show them. The formulas by hand are in
# tests/unit/test_fund_required.py.

class TestRequired:  # GA2
    def test_one_fund_of_each_kind_is_shown_with_its_labels(self, ledger):
        ledger.add_fund_ok(name="House", target="12000", by="2026-12")
        ledger.add_fund_ok(name="Cushion", kind="emergency", minimum="3000")
        ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200",
                           cadence="annual:09-01")
        ledger.add_fund_ok(name="Tax", kind="tax", percent="25")
        out = ledger.funds_shown()
        assert ("  Terms: from 2026-03-15, target 12000.00 by the end of 2026-12, planned\n"
                "  Assigned: 0.00\n"
                "  Outstanding: 12000.00, due 2026-12, 10 months left including it\n"
                "  Planned contribution this month: 1200.00\n"
                "  State: in progress\n") in out
        assert ("  Required held: 3000.00\n  Assigned: 0.00\n"
                "  Restoration recommended, planned: 3000.00\n  State: underfunded\n") in out
        assert ("  Outstanding: 1200.00, due 2026-09-01, 7 months left including it\n"
                "  Planned contribution this month: 171.43\n") in out
        assert ("  Tax reserve, a planning reserve, not a calculated tax liability: accrued 0.00 "
                "from 0 received occurrences, paid 0.00, released 0.00") in out

    def test_a_percentage_goal_is_alike_across_a_third_paycheck(self, capsys):
        outputs = []
        for third in (True, False):
            with tempfile.TemporaryDirectory() as folder:
                ledger = biweekly_ledger(Path(folder), capsys, third)
                ledger.__class__ = FundLedger
                fund = ledger.add_fund_ok(percent_of_income="10", as_of="2026-01-01")
                outputs.append([ledger.funds_shown(as_of).replace(fund, "FUND")
                                for as_of in ("2026-01-31", "2026-02-14", "2026-03-31")])
        assert outputs[0] == outputs[1]
        assert ("  Baseline income this month, planned: 5000.00\n  Assigned: 0.00\n"
                "  Planned contribution this month: 500.00\n") in outputs[0][0]

    def test_emergency_months_read_the_fixed_obligations_planned(self, ledger):
        ledger.pay("b1.csv", "2026-01-05")
        ledger.ob_add_ok()
        ledger.ob_add_ok(name="Fun", match="synthetic fun", obligation_class="discretionary",
                         amount="40.00")
        fund = ledger.add_fund_ok(name="Cushion", kind="emergency", months="3")
        out = ledger.fund_shown(fund)
        assert "  Fixed commitments a month, planned: 85.00\n" in out
        assert "  Required held: 255.00\n" in out

    def test_the_tax_reserve_accrues_received_eligible_income_from_its_start(self, ledger):
        for number, day in enumerate(("2026-01-10", "2026-02-10", "2026-03-10")):
            ledger.deposit(f"g{number}.csv", day, amount="333.33", text="SYNTHETIC GIG")
        ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="monthly:10",
                      anchor="2026-01-10", amount="333.33", tax_eligible=True)
        # A salary received in the same months, not tax-eligible, accrues nothing.
        ledger.deposit("p1.csv", "2026-02-13")
        ledger.add_ok()
        assert (("p1.csv",), "Pay", "received", "2026-02-13") in ledger.outcomes()
        fund = ledger.add_fund_ok(name="Tax", kind="tax", percent="25",
                                  effective_from="2026-02-01", as_of="2026-02-01")
        # 333.33 × 25% is 83.3325, rounded up per occurrence, from February only.
        assert ("accrued 166.68 from 2 received occurrences, paid 0.00, released 0.00"
                in ledger.fund_shown(fund, "2026-03-31"))
        assert "accrued 83.34 from 1 received occurrence," in ledger.fund_shown(fund,
                                                                               "2026-02-28")

    def test_terms_change_from_a_date_keeping_earlier_months(self, ledger):
        fund = ledger.add_fund_ok()
        assert ledger.terms(fund, "2026-04-01", monthly="700.00")[0] == 0
        assert "Planned contribution this month: 500.00" in ledger.fund_shown(fund, "2026-03-31")
        assert "Planned contribution this month: 700.00" in ledger.fund_shown(fund, "2026-04-01")
        out = ledger.fund_shown(fund)
        assert ("  Terms from 2026-03-15: 500.00 a month, planned\n"
                "  Terms from 2026-04-01: 700.00 a month, planned\n") in out

    def test_a_fund_not_yet_started(self, ledger):
        fund = ledger.add_fund_ok(effective_from="2026-05-01")
        assert "  State: not started, its terms apply from 2026-05-01" in ledger.fund_shown(fund)


# GA2's refusals of what was typed, each alone, each changing nothing.

class TestFundRefusals:
    @pytest.mark.parametrize("options, message", [
        ({"name": " "}, NAME_BLANK),
        ({"kind": "pension"}, KIND_UNKNOWN),
        ({"monthly": "5", "percent_of_income": "5"}, TERMS_FOR_KIND["goal"]),
        ({"target": "5"}, TERMS_FOR_KIND["goal"]),
        ({"kind": "emergency", "monthly": "5"}, TERMS_FOR_KIND["emergency"]),
        ({"kind": "reserve", "target": "5"}, TERMS_FOR_KIND["reserve"]),
        ({"kind": "reserve", "target": "5", "due": "2026-09-01", "anchor": "2026-09-01"},
         TERMS_FOR_KIND["reserve"]),
        ({"kind": "tax", "percent_of_income": "5"}, TERMS_FOR_KIND["tax"]),
        ({"monthly": "0"}, AMOUNT_INVALID.format(option="--monthly")),
        ({"monthly": "1.001"}, AMOUNT_INVALID.format(option="--monthly")),
        ({"percent_of_income": "0"}, PERCENT_INVALID.format(option="--percent-of-income")),
        ({"kind": "tax", "percent": "100.01"}, PERCENT_INVALID.format(option="--percent")),
        ({"kind": "tax", "percent": "1.005"}, PERCENT_INVALID.format(option="--percent")),
        ({"kind": "emergency", "months": "0"}, MONTHS_INVALID),
        ({"kind": "emergency", "months": "121"}, MONTHS_INVALID),
        ({"target": "5", "by": "2026-02"}, BY_BEFORE_START),
        ({"kind": "reserve", "target": "5", "due": "2026-03-14"}, DUE_BEFORE_START),
        ({"kind": "reserve", "target": "5", "cadence": "monthly:5"}, CADENCE_FOR_RESERVE),
        ({"kind": "reserve", "target": "5", "cadence": "every:6-months:15"},
         CADENCE_FOR_RESERVE),
        ({"kind": "reserve", "target": "5", "cadence": "annual:09-01", "anchor": "2026-09-01"},
         CADENCE_FOR_RESERVE),
        ({"kind": "reserve", "target": "5", "cadence": "every:6-months:15",
          "anchor": "2026-06-14"}, ANCHOR_OFF_CADENCE),
        ({"effective_from": "2026-02-28"}, CLOSED_MONTH),
    ])
    def test_what_was_typed(self, ledger, options, message):
        ledger.refused(lambda: ledger.fund_preview(**options), message)
        ledger.refused(lambda: ledger.add_fund(revision="fu1-0000000000000000", **options),
                       message)

    def test_a_name_taken_and_a_second_emergency_or_tax_fund(self, ledger):
        house = ledger.add_fund_ok()
        cushion = ledger.add_fund_ok(name="Cushion", kind="emergency", minimum="1")
        tax = ledger.add_fund_ok(name="Tax", kind="tax", percent="20")
        ledger.refused(lambda: ledger.fund_preview(monthly="1.00"),
                       NAME_TAKEN.format(fund=house))
        ledger.refused(lambda: ledger.fund_preview(name="Other", kind="emergency", minimum="1"),
                       ONE_ACTIVE.format(fund=cushion, kind="emergency"))
        ledger.refused(lambda: ledger.fund_preview(name="Other", kind="tax", percent="1"),
                       ONE_ACTIVE.format(fund=tax, kind="tax"))
        # Once undone, each frees its name and its kind.
        assert ledger.undo_fund(house)[0] == 0
        assert ledger.undo_fund(cushion)[0] == 0
        ledger.add_fund_ok()
        ledger.add_fund_ok(name="Other", kind="emergency", minimum="1")

    def test_terms_refusals(self, ledger):
        fund = ledger.add_fund_ok()
        ledger.refused(lambda: ledger.terms(fund, "2026-03-15", monthly="1.00"),
                       TERMS_NOT_LATER.format(latest="2026-03-15"))
        ledger.refused(lambda: ledger.terms(fund, "2026-04-01", monthly="1.00",
                                            as_of="2026-05-01"), CLOSED_MONTH)
        ledger.refused(lambda: ledger.terms(fund, "2026-04-01", minimum="1.00"),
                       TERMS_FOR_KIND["goal"])
        token = ledger.fund_token(fund, "Terms")
        assert ledger.undo_fund(fund)[0] == 0
        ledger.refused(lambda: ledger.terms(fund, "2026-04-01", monthly="1.00", revision=token),
                       FUND_NOT_ACTIVE)
        ledger.refused(lambda: ledger.terms("nope", "2026-04-01", monthly="1.00",
                                            revision=token), FUND_NOT_FOUND)

    def test_undo_refusals(self, ledger):
        fund = ledger.add_fund_ok()
        token = ledger.fund_token(fund, "Undo")
        ledger.assign_ok(fund, "Savings", "10.00")
        ledger.refused(lambda: ledger.undo_fund(fund, revision=token),
                       UNDO_ASSIGNED.format(accounts="Savings"))
        assert ledger.unassign(fund, "Savings")[0] == 0
        assert ledger.undo_fund(fund, revision=token)[0] == 0
        ledger.refused(lambda: ledger.undo_fund(fund, revision=token), FUND_NOT_ACTIVE)
        ledger.refused(lambda: ledger.undo_fund("nope", revision=token), FUND_NOT_FOUND)
        assert "  Status: undone" in ledger.fund_shown(fund)

    def test_names_are_escaped(self, ledger):
        ledger.add_fund_ok(name="Hou\x1b[31mse")
        assert "\x1b" not in ledger.funds_shown()


class TestFundTokens:  # G3 step 4, D-070 point 7
    @pytest.mark.parametrize("change", [
        {"name": "Home"}, {"monthly": "500.01"}, {"percent_of_income": "5"},
        {"effective_from": "2026-04-01"}, {"as_of": "2026-03-16"},
    ])
    def test_the_preview_token_covers_every_field_typed(self, ledger, change):
        revision = ledger.fund_preview_revision()
        ledger.refused(lambda: ledger.add_fund(revision=revision, **change), STALE_FUND_PREVIEW)

    def test_terms_and_undo_tokens_move_with_the_terms(self, ledger):
        fund = ledger.add_fund_ok()
        terms, undo = ledger.fund_token(fund, "Terms"), ledger.fund_token(fund, "Undo")
        assert terms != undo
        ledger.refused(lambda: ledger.undo_fund(fund, revision=terms), STALE_FUND_REVISION)
        # A race: another connection adds terms between show and undo.
        assert ledger.terms(fund, "2026-04-01", monthly="1.00")[0] == 0
        ledger.refused(lambda: ledger.undo_fund(fund, revision=undo), STALE_FUND_REVISION)
        ledger.refused(lambda: ledger.terms(fund, "2026-05-01", monthly="2.00", revision=terms),
                       STALE_FUND_REVISION)

    def test_a_fault_after_the_first_insert_leaves_nothing(self, ledger, monkeypatch):
        revision = ledger.fund_preview_revision()
        before = ledger.logical()

        def fail(conn, fund_id, terms):
            raise RuntimeError("injected")

        monkeypatch.setattr(funds, "insert_terms", fail)
        code, _, err = ledger.add_fund(revision=revision)
        assert code == 2 and "unexpected" in err
        assert ledger.logical() == before


# GA3: the assignability guard and its refusals, each changing nothing.

class TestAssignRefusals:  # GA3
    @pytest.fixture
    def fund(self, ledger):
        return ledger.add_fund_ok()

    def test_an_assignment_is_recorded_and_shown(self, ledger, fund):
        ledger.assign_ok(fund, "Savings", "1200.00")
        out = ledger.fund_shown(fund)
        assert "  Assigned: 1200.00 (Savings 1200.00)\n" in out
        assert ("  Account Savings: balance observed 5000.00 on 2026-03-01, assigned 1200.00, "
                "unassigned 3800.00\n    This fund: 1200.00 assigned\n"
                "    Assignment revision, to unassign: fa1-") in out

    def test_beyond_the_latest_observation(self, ledger, fund):
        other = ledger.add_fund_ok(name="Car", monthly="1.00")
        ledger.assign_ok(other, "Savings", "4000.00")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1000.01"), BEYOND_OBSERVATION.format(
            amount="1000.01", total="5000.01", balance="5000.00", observed_on="2026-03-01",
            unassigned="1000.00"))
        ledger.assign_ok(fund, "Savings", "1000.00")

    def test_the_observation_is_the_latest_on_or_before_as_of(self, ledger, fund):
        ledger.observe("Savings", "2026-03-20", "100.00")
        ledger.assign_ok(fund, "Savings", "5000.00")
        assert ledger.unassign(fund, "Savings")[0] == 0
        ledger.refused(lambda: ledger.assign(fund, "Savings", "100.01", as_of="2026-03-20"),
                       BEYOND_OBSERVATION.format(amount="100.01", total="100.01",
                                                 balance="100.00", observed_on="2026-03-20",
                                                 unassigned="100.00"))

    def test_an_account_with_no_observation(self, ledger, fund):
        ledger.add_typed_account("Spare", "checking")
        ledger.refused(lambda: ledger.assign(fund, "Spare", "1.00", revision=NO_TOKEN),
                       NO_OBSERVATION.format(as_of=AS_OF))
        ledger.observe("Spare", "2026-03-16", "10.00")
        ledger.refused(lambda: ledger.assign(fund, "Spare", "1.00", revision=NO_TOKEN),
                       NO_OBSERVATION.format(as_of=AS_OF))

    @pytest.mark.parametrize("account_type, words", [
        ("credit_card", "credit card"), ("loan", "loan"), ("retirement", "retirement")])
    def test_a_card_loan_or_retirement_account(self, ledger, fund, account_type, words):
        ledger.add_typed_account("Other", account_type)
        ledger.observe("Other", "2026-03-01", "10.00",
                       "--balance" if account_type == "retirement" else "--owed")
        ledger.refused(lambda: ledger.assign(fund, "Other", "1.00", revision=NO_TOKEN),
                       ACCOUNT_NOT_ASSIGNABLE.format(account_type=words))

    def test_a_second_active_assignment(self, ledger, fund):
        ledger.assign_ok(fund, "Savings", "1.00")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00", revision=NO_TOKEN),
                       ALREADY_ASSIGNED)
        # Undo then assign changes it.
        assert ledger.unassign(fund, "Savings")[0] == 0
        ledger.assign_ok(fund, "Savings", "2.00")
        assert "  Assigned: 2.00 (Savings 2.00)\n" in ledger.fund_shown(fund)

    def test_an_unknown_or_undone_fund_and_a_bad_amount(self, ledger, fund):
        token = ledger.assignment_token(fund, "Savings")
        for amount in ("0", "-1.00", "1.001", "x"):
            ledger.refused(lambda: ledger.assign(fund, "Savings", amount, revision=token),
                           AMOUNT_INVALID.format(option="--amount"))
        ledger.refused(lambda: ledger.assign("nope", "Savings", "1.00", revision=token),
                       FUND_NOT_FOUND)
        assert ledger.undo_fund(fund)[0] == 0
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00", revision=token),
                       FUND_NOT_ACTIVE)

    def test_nothing_to_unassign(self, ledger, fund):
        ledger.refused(lambda: ledger.unassign(fund, "Savings",
                                               revision=ledger.assignment_token(fund, "Savings")),
                       NOT_ASSIGNED)

    def test_a_stale_token_for_each_input(self, ledger, fund):
        other = ledger.add_fund_ok(name="Car", monthly="1.00")
        ledger.add_typed_account("Spare", "checking")
        ledger.observe("Spare", "2026-03-01", "50.00")
        # The observation.
        token = ledger.assignment_token(fund, "Savings")
        ledger.observe("Savings", "2026-03-10", "5000.00")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00", revision=token),
                       STALE_ASSIGNMENT_REVISION)
        # The as-of date choosing the observation.
        token = ledger.assignment_token(fund, "Savings", as_of="2026-03-05")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00", revision=token),
                       STALE_ASSIGNMENT_REVISION)
        # The account's assignments, another fund's.
        token = ledger.assignment_token(fund, "Savings")
        ledger.assign_ok(other, "Savings", "1.00")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00", revision=token),
                       STALE_ASSIGNMENT_REVISION)
        # The fund's assignments, on another account.
        token = ledger.assignment_token(fund, "Savings")
        ledger.assign_ok(fund, "Spare", "1.00")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00", revision=token),
                       STALE_ASSIGNMENT_REVISION)
        # The operation: an assign token used to release.
        token = ledger.assignment_token(fund, "Savings")
        ledger.assign_ok(fund, "Savings", "1.00", revision=token)
        ledger.refused(lambda: ledger.unassign(fund, "Savings", revision=token),
                       STALE_ASSIGNMENT_REVISION)

    def test_the_token_names_its_fund_and_account(self, ledger, fund):
        other = ledger.add_fund_ok(name="Car", monthly="1.00")
        ledger.add_typed_account("Spare", "savings")
        ledger.observe("Spare", "2026-03-01", "5000.00")
        assert ledger.assignment_token(fund, "Savings") != ledger.assignment_token(other,
                                                                                   "Savings")
        assert ledger.assignment_token(fund, "Savings") != ledger.assignment_token(fund, "Spare")
        ledger.refused(lambda: ledger.assign(fund, "Savings", "1.00",
                                             revision=ledger.assignment_token(fund, "Spare")),
                       STALE_ASSIGNMENT_REVISION)

    def test_a_fault_after_the_first_insert_leaves_nothing(self, ledger, fund, monkeypatch):
        token = ledger.assignment_token(fund, "Savings")
        before = ledger.logical()

        def fail(conn, assignment_id, event):
            raise RuntimeError("injected")

        monkeypatch.setattr(funds, "insert_assignment_event", fail)
        code, _, err = ledger.assign(fund, "Savings", "1.00", revision=token)
        assert code == 2 and "unexpected" in err
        assert ledger.logical() == before


# GA4: over-assigned, disclosed, never absorbed, and the race.

class TestOverAssigned:  # GA4
    def test_a_lower_observation_over_assigns_by_exactly_the_difference(self, ledger):
        house = ledger.add_fund_ok()
        car = ledger.add_fund_ok(name="Car", monthly="1.00")
        ledger.assign_ok(house, "Savings", "4000.00")
        ledger.assign_ok(car, "Savings", "1000.00")
        ledger.observe("Savings", "2026-03-10", "4499.99")
        listed, shown = ledger.funds_shown(), ledger.fund_shown(house)
        for out in (listed, shown):
            assert ("Over-assigned by 500.01: new assignments here are refused until assignments "
                    "are released or a higher balance is observed") in out
            assert ("  Assignment not backed: Savings holds more in funds than its balance "
                    "observed") in out
        assert listed.count("Assignment not backed") == 2
        # New assignments there are refused, even a cent.
        third = ledger.add_fund_ok(name="Bike", monthly="1.00")
        ledger.refused(lambda: ledger.assign(third, "Savings", "0.01"), BEYOND_OBSERVATION.format(
            amount="0.01", total="5000.01", balance="4499.99", observed_on="2026-03-10",
            unassigned="0.00"))
        # Until a release resolves it.
        assert ledger.unassign(car, "Savings")[0] == 0
        assert "Over-assigned" not in ledger.funds_shown()
        assert "Assignment not backed" not in ledger.funds_shown()
        ledger.assign_ok(third, "Savings", "499.99")

    def test_a_higher_observation_resolves_it(self, ledger):
        house = ledger.add_fund_ok()
        ledger.assign_ok(house, "Savings", "5000.00")
        ledger.observe("Savings", "2026-03-10", "4000.00")
        assert "Over-assigned by 1000.00" in ledger.funds_shown()
        ledger.observe("Savings", "2026-03-12", "6000.00")
        assert "Over-assigned" not in ledger.funds_shown()

    def test_two_assignments_shown_against_one_observation(self, ledger):
        house = ledger.add_fund_ok()
        car = ledger.add_fund_ok(name="Car", monthly="1.00")
        house_token = ledger.assignment_token(house, "Savings")
        car_token = ledger.assignment_token(car, "Savings")
        ledger.assign_ok(house, "Savings", "3000.00", revision=house_token)
        ledger.refused(lambda: ledger.assign(car, "Savings", "3000.00", revision=car_token),
                       STALE_ASSIGNMENT_REVISION)

    @pytest.mark.parametrize("as_of, provisional", [("2026-04-01", False),
                                                    ("2026-04-02", True)])
    def test_an_observation_over_31_days_old_is_provisional(self, ledger, as_of, provisional):
        house = ledger.add_fund_ok()
        ledger.assign_ok(house, "Savings", "10.00")
        out = ledger.funds_shown(as_of)
        assert ("Provisional: the balance of Savings was observed more than 31 days before"
                in out) == provisional
        assert ("Provisional: observed more than 31 days before" in out) == provisional
        assert "  Assigned: 10.00 (Savings 10.00)" in out


# GA5: planning figures assign nothing, and no fund write changes the evidence.

class TestNothingAutomatic:  # GA5
    def test_planned_contributions_and_restoration_assign_nothing(self, ledger):
        house = ledger.add_fund_ok(target="12000", by="2026-12")
        cushion = ledger.add_fund_ok(name="Cushion", kind="emergency", minimum="3000")
        before = ledger.logical()
        for as_of in ("2026-03-15", "2026-06-30", "2027-02-01"):
            ledger.funds_shown(as_of)
            ledger.fund_shown(house, as_of)
            ledger.fund_shown(cushion, as_of)
        assert ledger.logical() == before
        assert ledger.fund_tables()["fund_assignment"] == []

    def test_no_fund_write_changes_the_evidence(self, ledger):
        before = ledger.evidence()
        house = ledger.add_fund_ok()
        cushion = ledger.add_fund_ok(name="Cushion", kind="emergency", minimum="3000")
        assert ledger.terms(house, "2026-04-01", monthly="1.00")[0] == 0
        ledger.assign_ok(house, "Savings", "1.00")
        assert ledger.set_priority(house, cushion)[0] == 0
        assert ledger.unassign(house, "Savings")[0] == 0
        assert ledger.undo_fund(house)[0] == 0
        assert ledger.evidence() == before

    def test_read_commands_write_nothing(self, ledger):
        house = ledger.add_fund_ok()
        before = ledger.logical()
        for words in (("funds", "--as-of", AS_OF), ("fund", "show", house, "--as-of", AS_OF),
                      ("fund", "preview", *ledger.fund_words(name="Other"))):
            assert ledger.run(*words)[0] == 0
        assert ledger.logical() == before


# D-070 point 4: one priority list.

class TestPriority:
    def test_a_list_replaces_the_last_and_skips_an_undone_fund(self, ledger):
        house = ledger.add_fund_ok()
        cushion = ledger.add_fund_ok(name="Cushion", kind="emergency", minimum="3000")
        trip = ledger.add_fund_ok(name="Trip", kind="reserve", target="900", due="2026-08-01")
        assert "planned: none" in ledger.funds_shown()
        assert ledger.set_priority(house, cushion, trip)[0] == 0
        assert (f"planned: 1. House ({house}), 2. Cushion ({cushion}), 3. Trip ({trip})"
                in ledger.funds_shown())
        assert ledger.set_priority(trip, house)[0] == 0
        assert f"planned: 1. Trip ({trip}), 2. House ({house})\n" in ledger.funds_shown()
        assert ledger.undo_fund(trip)[0] == 0
        assert f"planned: 1. House ({house})\n" in ledger.funds_shown()
        assert ledger.set_priority()[0] == 0
        assert "planned: none" in ledger.funds_shown()

    def test_refusals(self, ledger):
        house = ledger.add_fund_ok()
        tax = ledger.add_fund_ok(name="Tax", kind="tax", percent="20")
        token = ledger.priority_token()
        ledger.refused(lambda: ledger.set_priority(house, tax, revision=token),
                       PRIORITY_KIND.format(fund=tax))
        ledger.refused(lambda: ledger.set_priority(house, house, revision=token),
                       PRIORITY_REPEATED.format(fund=house))
        ledger.refused(lambda: ledger.set_priority("nope", revision=token), FUND_NOT_FOUND)
        assert ledger.set_priority(house)[0] == 0
        # A race: the list changed since it was shown.
        ledger.refused(lambda: ledger.set_priority(revision=token), STALE_PRIORITY_REVISION)
