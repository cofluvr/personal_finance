"""What safe-to-spend reads that a person states, end to end, using synthetic data only (SA1 to
SA3, D-072 points 2 and 4): liquidity designations, coverage links and the look-alikes they clear,
the emergency fund's restoration and the checking buffer. Migration 0032 is
test_liquidity_migration.py."""

import re

import pytest
from test_decisions import LIQUIDITY_TABLES
from test_loans import LoanLedger

from personal_finance.planning import coverage, fund_restorations, liquidity
from personal_finance.planning.coverage import (
    CHAIN_COVERS_ALREADY,
    NOT_A_RESERVE,
    NOT_A_SCHEDULED_LOAN,
    NOT_COVERING,
    STALE_COVERAGE_REVISION,
    TARGET_COVERED_ALREADY,
)
from personal_finance.planning.fund_restorations import (
    NO_RESTORATION,
    NOT_EMERGENCY,
    RESTORATION_CLOSED_MONTH,
    RESTORATION_NOT_LATER,
)
from personal_finance.planning.funds import STALE_FUND_REVISION
from personal_finance.planning.liquidity import (
    ALREADY_LIQUID,
    NOT_DESIGNATED,
    NOT_LIQUID_TYPE,
    STALE_LIQUIDITY_REVISION,
)
from personal_finance.planning.settings import BUFFER_INVALID

AS_OF = "2026-05-01"
LIQUIDITY_TOKEN = r"lq1-[0-9a-f]{16}"
OBLIGATION_TOKEN = r"ob1-[0-9a-f]{16}"
FUND_TOKEN = r"fu1-[0-9a-f]{16}"
SETTING_TOKEN = r"st1-[0-9a-f]{16}"


class InputsLedger(LoanLedger):
    def liquidity_shown(self):
        code, out, err = self.run("account", "liquidity", "show")
        assert (code, err) == (0, ""), err
        return out

    def liquidity_token(self, account):
        block = self.liquidity_shown().split(f"Account {account} (")[1].split("\nAccount ")[0]
        return re.search(rf"revision: ({LIQUIDITY_TOKEN})", block)[1]

    def liquid(self, account, revision=None, operation="set"):
        return self.run("account", "liquidity", operation, "--account", account, "--revision",
                        revision or self.liquidity_token(account))

    def liquid_ok(self, account, operation="set"):
        code, _, err = self.liquid(account, operation=operation)
        assert (code, err) == (0, ""), err

    def coverage_shown(self, as_of=AS_OF):
        code, out, err = self.run("obligation", "coverage", "--as-of", as_of)
        assert (code, err) == (0, ""), err
        return out

    def coverage_token(self, obligation, kind="Covers"):
        block = self.coverage_shown().split(f"Obligation {obligation} (")[1].split(
            "\nObligation ")[0]
        return re.search(rf"{kind} revision: ({OBLIGATION_TOKEN})", block)[1]

    def covers(self, obligation, *target, revision=None):
        return self.run("obligation", "covers", obligation, *target, "--revision",
                        revision or self.coverage_token(obligation))

    def covers_ok(self, obligation, *target):
        code, _, err = self.covers(obligation, *target)
        assert (code, err) == (0, ""), err

    def uncover(self, obligation, revision=None):
        return self.run("obligation", "uncover", obligation, "--revision",
                        revision or self.coverage_token(obligation, "Uncover"))

    def alikes(self, as_of=AS_OF):
        return re.findall(r"^  Obligation (\S+), due (\S+), and (loan|reserve) .*?, due (\S+),",
                          self.coverage_shown(as_of), re.MULTILINE)

    def restorations_shown(self, fund_id):
        code, out, err = self.run("fund", "restorations", fund_id)
        assert (code, err) == (0, ""), err
        return out

    def restoration_token(self, fund_id, kind="Restoration"):
        return re.search(rf"{kind} revision(?:, for the newest)?: ({FUND_TOKEN})",
                         self.restorations_shown(fund_id))[1]

    def restore(self, fund_id, monthly="200.00", effective_from=AS_OF, as_of=AS_OF,
                revision=None):
        return self.run("fund", "restoration", "--fund", fund_id, "--monthly", monthly,
                        "--effective-from", effective_from, "--as-of", as_of, "--revision",
                        revision or self.restoration_token(fund_id))

    def restore_ok(self, fund_id, **options):
        code, _, err = self.restore(fund_id, **options)
        assert (code, err) == (0, ""), err

    def unrestore(self, fund_id, revision=None):
        return self.run("fund", "restoration-undo", "--fund", fund_id, "--revision",
                        revision or self.restoration_token(fund_id, "Undo"))

    def setting_token(self, key):
        out = self.run("setting", "show")[1]
        return re.search(rf"Setting {key}:.*?\n  Revision: ({SETTING_TOKEN})", out)[1]

    def inputs(self):
        return self.dump(LIQUIDITY_TABLES)

    def refused(self, attempt, message):
        before = (self.inputs(), self.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (self.inputs(), self.evidence()) == before


@pytest.fixture
def ledger(tmp_path, capsys):
    """Checking A, savings S, a card, a mortgage with terms due on the 5th at 1,500.00, a reserve
    of 1,200.00 due 2026-06-10, an emergency fund, and two obligations on A."""
    ledger = InputsLedger(tmp_path, capsys)
    ledger.add_typed_account("S", "savings")
    ledger.add_typed_account("Card", "credit_card")
    ledger.add_typed_account("Mortgage", "loan")
    ledger.add_terms_ok("Mortgage")
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        due="2026-06-10", as_of=AS_OF)
    ledger.emergency = ledger.add_fund_ok(name="Rainy", kind="emergency", minimum="5000.00",
                                          as_of=AS_OF)
    ledger.mortgage_bill = ledger.ob_add_ok(name="Mortgage bill", match="synthetic mortgage",
                                            cadence="monthly:5", anchor="2026-01-05",
                                            amount="1500.00")
    ledger.insurance_bill = ledger.ob_add_ok(name="Insurance bill", match="synthetic insure",
                                             cadence="annual:06-10", anchor="2026-06-10",
                                             amount="1200.00")
    return ledger


class TestLiquidity:  # SA1
    def test_set_show_and_undo(self, ledger):
        assert "Account A (checking, " in ledger.liquidity_shown()
        assert "Card" not in ledger.liquidity_shown()
        ledger.liquid_ok("A")
        assert re.search(r"Account A \(checking, \S+\): liquid, designation",
                         ledger.liquidity_shown())
        assert "Checking and savings accounts: 2, liquid: 1" in ledger.liquidity_shown()
        ledger.liquid_ok("A", operation="undo")
        assert "Checking and savings accounts: 2, liquid: 0" in ledger.liquidity_shown()
        ledger.liquid_ok("A")

    @pytest.mark.parametrize("account", ["Card", "Mortgage"])
    def test_other_account_types_are_refused(self, ledger, account):
        ledger.refused(lambda: ledger.liquid(account, revision="lq1-0000000000000000"),
                       NOT_LIQUID_TYPE.format(account=account))

    def test_refusals_and_a_stale_token(self, ledger):
        token = ledger.liquidity_token("S")
        ledger.liquid_ok("S")
        ledger.refused(lambda: ledger.liquid("S", revision=token),
                       ALREADY_LIQUID.format(account="S"))
        ledger.refused(lambda: ledger.liquid("A", revision="lq1-0000000000000000",
                                             operation="undo"),
                       NOT_DESIGNATED.format(account="A"))
        # The set token of one account never sets another, and an undo never reuses a set token.
        ledger.refused(lambda: ledger.liquid("A", revision=token), STALE_LIQUIDITY_REVISION)
        ledger.refused(lambda: ledger.liquid("S", revision=token, operation="undo"),
                       STALE_LIQUIDITY_REVISION)


    def test_one_account_s_token_never_designates_another_of_its_type(self, ledger):
        ledger.add_typed_account("B", "checking")
        ledger.refused(lambda: ledger.liquid("A", revision=ledger.liquidity_token("B")),
                       STALE_LIQUIDITY_REVISION)


class TestCoverage:  # SA1
    def test_covers_a_loan_and_a_reserve_and_uncovers(self, ledger):
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        ledger.covers_ok(ledger.insurance_bill, "--fund", ledger.reserve)
        out = ledger.coverage_shown()
        assert f"Obligation {ledger.mortgage_bill} (Mortgage bill): covers loan Mortgage" in out
        assert (f"Obligation {ledger.insurance_bill} (Insurance bill): covers reserve Insurance "
                f"({ledger.reserve})") in out
        assert "Links: 2" in out
        assert ledger.uncover(ledger.mortgage_bill)[0] == 0
        assert "Links: 1" in ledger.coverage_shown()

    def test_refusals(self, ledger):
        ledger.add_typed_account("Loan 2", "loan")
        token = ledger.coverage_token(ledger.mortgage_bill)
        ledger.refused(lambda: ledger.covers(ledger.mortgage_bill, "--loan", "Loan 2",
                                             revision=token),
                       NOT_A_SCHEDULED_LOAN.format(account="Loan 2"))
        ledger.add_terms_ok("Card", rate="24.99", payment=None)
        ledger.refused(lambda: ledger.covers(ledger.mortgage_bill, "--loan", "Card",
                                             revision=token),
                       NOT_A_SCHEDULED_LOAN.format(account="Card"))
        ledger.refused(lambda: ledger.covers(ledger.mortgage_bill, "--fund", ledger.emergency,
                                             revision=token),
                       NOT_A_RESERVE.format(fund=ledger.emergency))
        ledger.refused(lambda: ledger.uncover(ledger.mortgage_bill,
                                              revision="ob1-0000000000000000"),
                       NOT_COVERING.format(obligation=ledger.mortgage_bill))

    def test_a_second_link_on_either_side_is_refused(self, ledger):
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        ledger.refused(lambda: ledger.covers(ledger.mortgage_bill, "--fund", ledger.reserve,
                                             revision="ob1-0000000000000000"),
                       CHAIN_COVERS_ALREADY.format(obligation=ledger.mortgage_bill,
                                                   target="loan Mortgage"))
        ledger.refused(lambda: ledger.covers(ledger.insurance_bill, "--loan", "Mortgage"),
                       TARGET_COVERED_ALREADY.format(target="loan Mortgage",
                                                     obligation=ledger.mortgage_bill))

    def test_a_stale_token_for_each_input(self, ledger):
        token = ledger.coverage_token(ledger.mortgage_bill)
        # A link on the chain moves its token, and so does a change of what it says.
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        assert ledger.uncover(ledger.mortgage_bill)[0] == 0
        ledger.refused(lambda: ledger.uncover(ledger.mortgage_bill, revision=token),
                       NOT_COVERING.format(obligation=ledger.mortgage_bill))
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        ledger.refused(lambda: ledger.uncover(ledger.mortgage_bill, revision=token),
                       STALE_COVERAGE_REVISION)
        assert ledger.uncover(ledger.mortgage_bill)[0] == 0
        token = ledger.coverage_token(ledger.mortgage_bill)
        code, _, err = ledger.ob_terms(ledger.mortgage_bill, "2026-06-01", "--amount", "1550.00",
                                       as_of=AS_OF)
        assert code == 0, err
        ledger.refused(lambda: ledger.covers(ledger.mortgage_bill, "--loan", "Mortgage",
                                             revision=token), STALE_COVERAGE_REVISION)
        # One obligation's token never covers for another.
        ledger.refused(lambda: ledger.covers(
            ledger.insurance_bill, "--fund", ledger.reserve,
            revision=ledger.coverage_token(ledger.mortgage_bill)), STALE_COVERAGE_REVISION)
        # A covers token never uncovers.
        ledger.covers_ok(ledger.insurance_bill, "--fund", ledger.reserve)
        ledger.refused(lambda: ledger.uncover(ledger.insurance_bill,
                                              revision=ledger.coverage_token(
                                                  ledger.mortgage_bill)),
                       STALE_COVERAGE_REVISION)

    def test_an_uncover_token_names_what_the_link_covers(self, ledger):
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        token = ledger.coverage_token(ledger.mortgage_bill, "Uncover")
        assert ledger.uncover(ledger.mortgage_bill)[0] == 0
        ledger.covers_ok(ledger.mortgage_bill, "--fund", ledger.reserve)
        ledger.refused(lambda: ledger.uncover(ledger.mortgage_bill, revision=token),
                       STALE_COVERAGE_REVISION)

    def test_a_supersession_keeps_the_link(self, ledger):
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        newer = ledger.ob_add_ok(name="Mortgage bill 2", match="synthetic mortgage", cadence=None,
                                 anchor=None, amount=None, obligation_class=None,
                                 supersedes=ledger.mortgage_bill)
        out = ledger.coverage_shown()
        assert f"Obligation {newer} (Mortgage bill 2): covers loan Mortgage" in out
        assert f"Obligation {ledger.mortgage_bill} (" not in out
        assert ledger.uncover(newer)[0] == 0
        assert "Links: 0" in ledger.coverage_shown()

    def test_an_inert_link_is_shown_and_can_be_taken_away(self, ledger):
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        assert ledger.ob_undo(ledger.mortgage_bill)[0] == 0
        out = ledger.coverage_shown()
        assert "inert: the obligation is undone" in out
        assert ledger.uncover(ledger.mortgage_bill)[0] == 0
        assert "Links: 0" in ledger.coverage_shown()


class TestLookAlikes:  # SA2
    def test_both_pairs_are_found_and_a_link_clears_each(self, ledger):
        assert ledger.alikes() == sorted([
            (ledger.mortgage_bill, "2026-05-05", "loan", "2026-05-05"),
            (ledger.insurance_bill, "2026-06-10", "reserve", "2026-06-10")])
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        assert ledger.alikes() == [(ledger.insurance_bill, "2026-06-10", "reserve",
                                    "2026-06-10")]
        ledger.covers_ok(ledger.insurance_bill, "--fund", ledger.reserve)
        assert ledger.alikes() == []
        assert "Possible double reservations as of 2026-05-01: none" in ledger.coverage_shown()

    def test_a_linked_side_looks_like_nothing_else(self, ledger):
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        # A reserve like the linked bill, and a second bill like the linked loan.
        ledger.add_fund_ok(name="Like the bill", kind="reserve", target="1500.00",
                           due="2026-05-05", as_of=AS_OF)
        other = ledger.ob_add_ok(name="Like the loan", match="synthetic lender",
                                 cadence="monthly:5", anchor="2026-01-05", amount="1500.00")
        found = ledger.alikes()
        assert not [alike for alike in found if alike[0] == ledger.mortgage_bill]
        assert not [alike for alike in found if alike[0] == other and alike[2] == "loan"]
        assert [alike for alike in found if alike[0] == other and alike[2] == "reserve"]

    def test_a_reserve_not_started_looks_like_nothing(self, ledger):
        later = ledger.add_fund_ok(name="Later", kind="reserve", target="1500.00",
                                   due="2026-07-05", effective_from="2026-06-01", as_of=AS_OF)
        assert not [alike for alike in ledger.alikes() if alike[0] == ledger.mortgage_bill
                    and alike[2] == "reserve"]
        # A reserve with no terms row at all, as a ledger written directly can hold.
        conn = ledger.conn()
        conn.execute("INSERT INTO fund (id, name, kind) VALUES ('bare', 'Bare', 'reserve')")
        conn.execute("INSERT INTO fund_event (fund_id, event) VALUES ('bare', 'made')")
        conn.close()
        assert ledger.coverage_shown()
        assert later

    @pytest.mark.parametrize("day, found", [(2, True), (8, True), (1, False), (9, False)])
    def test_the_loan_edges_are_three_days(self, ledger, day, found):
        assert ledger.ob_undo(ledger.mortgage_bill)[0] == 0
        other = ledger.ob_add_ok(name="Loan payment", match="synthetic lender",
                                 cadence=f"monthly:{day}", anchor=f"2026-01-{day:02}",
                                 amount="1500.00")
        assert any(alike[0] == other for alike in ledger.alikes()) is found

    @pytest.mark.parametrize("day, found", [("06-07", True), ("06-13", True), ("06-06", False),
                                            ("06-14", False)])
    def test_the_reserve_edges_are_three_days(self, ledger, day, found):
        assert ledger.ob_undo(ledger.insurance_bill)[0] == 0
        other = ledger.ob_add_ok(name="Premium", match="synthetic premium",
                                 cadence=f"annual:{day}", anchor=f"2026-{day}", amount="1200.00")
        assert any(alike[0] == other for alike in ledger.alikes()) is found

    def test_a_different_amount_or_a_discretionary_class_is_no_look_alike(self, ledger):
        for bill in (ledger.mortgage_bill, ledger.insurance_bill):
            assert ledger.ob_undo(bill)[0] == 0
        ledger.ob_add_ok(name="Near", match="synthetic near", cadence="monthly:5",
                         anchor="2026-01-05", amount="1499.99")
        ledger.ob_add_ok(name="Loose", match="synthetic loose", cadence="monthly:5",
                         anchor="2026-01-05", amount="1500.00", obligation_class="discretionary")
        assert ledger.alikes() == []

    def test_a_range_holding_the_amount_is_a_look_alike(self, ledger):
        assert ledger.ob_undo(ledger.mortgage_bill)[0] == 0
        other = ledger.ob_add_ok(name="Ranged", match="synthetic ranged", cadence="monthly:5",
                                 anchor="2026-01-05", amount=None, amount_range="1400.00..1600.00")
        assert (other, "2026-05-05", "loan", "2026-05-05") in ledger.alikes()


class TestRestoration:  # SA1, point 2
    def test_set_step_back_and_show(self, ledger):
        assert "Restoration: none" in ledger.restorations_shown(ledger.emergency)
        ledger.restore_ok(ledger.emergency)
        ledger.restore_ok(ledger.emergency, monthly="300.00", effective_from="2026-06-01")
        out = ledger.restorations_shown(ledger.emergency)
        assert "from 2026-05-01, planned 200.00 a month while underfunded" in out
        assert "from 2026-06-01, planned 300.00 a month while underfunded" in out
        assert ledger.unrestore(ledger.emergency)[0] == 0
        out = ledger.restorations_shown(ledger.emergency)
        assert "300.00" not in out and "200.00" in out

    def test_refusals(self, ledger):
        token = ledger.restoration_token(ledger.emergency)
        ledger.refused(lambda: ledger.restore(ledger.reserve, revision=token), NOT_EMERGENCY)
        ledger.refused(lambda: ledger.restore(ledger.emergency, effective_from="2026-04-30",
                                              revision=token), RESTORATION_CLOSED_MONTH)
        ledger.refused(lambda: ledger.unrestore(ledger.emergency, revision=token),
                       NO_RESTORATION)
        ledger.restore_ok(ledger.emergency, effective_from="2026-05-10")
        ledger.refused(lambda: ledger.restore(ledger.emergency, effective_from="2026-05-10"),
                       RESTORATION_NOT_LATER.format(latest="2026-05-10"))

    def test_a_stale_token(self, ledger):
        token = ledger.restoration_token(ledger.emergency)
        ledger.restore_ok(ledger.emergency)
        ledger.refused(lambda: ledger.restore(ledger.emergency, effective_from="2026-06-01",
                                              revision=token), STALE_FUND_REVISION)
        undo = ledger.restoration_token(ledger.emergency, "Undo")
        # A change of the fund's terms moves both.
        code, _, err = ledger.terms(ledger.emergency, "2026-05-02", minimum="6000.00")
        assert code == 0, err
        ledger.refused(lambda: ledger.unrestore(ledger.emergency, revision=undo),
                       STALE_FUND_REVISION)

    def test_it_moves_no_existing_fund_token(self, ledger):
        before = ledger.fund_shown(ledger.emergency)
        ledger.restore_ok(ledger.emergency)
        assert ledger.fund_shown(ledger.emergency) == before


class TestBuffer:  # SA1, point 2
    def test_it_is_seeded_and_kept_as_cents(self, ledger):
        assert "Setting checking_buffer_cents: not set" in ledger.run("setting", "show")[1]
        code, _, err = ledger.run("setting", "set", "checking_buffer_cents", "500.00",
                                  "--revision", ledger.setting_token("checking_buffer_cents"))
        assert (code, err) == (0, ""), err
        assert "Setting checking_buffer_cents: 50000, setting" in ledger.run("setting", "show")[1]

    @pytest.mark.parametrize("value", ["0.00", "-5.00", "five", "1.234"])
    def test_an_amount_not_above_zero_is_refused(self, ledger, value):
        code, _, err = ledger.run("setting", "set", "checking_buffer_cents", value, "--revision",
                                  ledger.setting_token("checking_buffer_cents"))
        assert (code, err.strip()) == (
            2, "Error: " + BUFFER_INVALID.format(key="checking_buffer_cents"))


class TestNoLedgerChange:  # SA3, G1
    def test_every_write_leaves_the_evidence_digest(self, ledger):
        before = ledger.evidence()
        ledger.liquid_ok("A")
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        ledger.restore_ok(ledger.emergency)
        assert ledger.run("setting", "set", "checking_buffer_cents", "500.00", "--revision",
                          ledger.setting_token("checking_buffer_cents"))[0] == 0
        assert ledger.evidence() == before
        ledger.liquid_ok("A", operation="undo")
        assert ledger.uncover(ledger.mortgage_bill)[0] == 0
        assert ledger.unrestore(ledger.emergency)[0] == 0
        assert ledger.evidence() == before


class TestRacesAndFaults:  # G3
    def test_a_second_connection_between_show_and_write_is_refused(self, ledger):
        # Undo shown, then another write undoes and sets again: a new designation, so the token
        # shown no longer applies, though the account is liquid either way.
        ledger.liquid_ok("A")
        token = ledger.liquidity_token("A")
        ledger.liquid_ok("A", operation="undo")
        ledger.liquid_ok("A")
        ledger.refused(lambda: ledger.liquid("A", revision=token, operation="undo"),
                       STALE_LIQUIDITY_REVISION)
        # Uncover shown, then the obligation's terms change under it.
        ledger.covers_ok(ledger.mortgage_bill, "--loan", "Mortgage")
        token = ledger.coverage_token(ledger.mortgage_bill, "Uncover")
        assert ledger.ob_terms(ledger.mortgage_bill, "2026-06-01", "--amount", "1550.00",
                               as_of=AS_OF)[0] == 0
        ledger.refused(lambda: ledger.uncover(ledger.mortgage_bill, revision=token),
                       STALE_COVERAGE_REVISION)
        token = ledger.restoration_token(ledger.emergency)
        ledger.restore_ok(ledger.emergency)
        ledger.refused(lambda: ledger.restore(ledger.emergency, effective_from="2026-06-01",
                                              revision=token), STALE_FUND_REVISION)

    @pytest.mark.parametrize("module, helper, attempt", [
        (liquidity, "insert_designation_event", lambda ledger: ledger.liquid("A")),
        (coverage, "insert_coverage_event",
         lambda ledger: ledger.covers(ledger.mortgage_bill, "--loan", "Mortgage")),
        (fund_restorations, "insert_restoration_event",
         lambda ledger: ledger.restore(ledger.emergency))])
    def test_a_fault_after_the_first_insert_leaves_nothing(self, ledger, monkeypatch, module,
                                                           helper, attempt):
        before = ledger.logical()

        def fail(conn, entry_id, event):
            raise RuntimeError("injected")

        monkeypatch.setattr(module, helper, fail)
        code, _, err = attempt(ledger)
        assert code == 2 and "unexpected" in err
        assert ledger.logical() == before
