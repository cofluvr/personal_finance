"""Recurring obligations stated by a person, end to end, using synthetic data only (IB1 to IB5,
D-068 points 5 and 6, and "How M12.2 was implemented")."""

import itertools
import random
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from planning_digest import evidence_digest
from test_categorizations import CategoryLedger
from test_decisions import OBLIGATION_TABLES
from test_income_sources import IncomeLedger
from test_supersession import holding

from personal_finance.db.backups import logical_digest
from personal_finance.planning import obligations
from personal_finance.reports.obligation_spending import spending_by_class
from personal_finance.planning.obligations import (
    AMOUNT_INVALID,
    AMOUNT_OR_RANGE,
    ANCHOR_OFF_CADENCE,
    CATEGORY_UNKNOWN,
    DISMISS_NOT_FOUND,
    DISMISSAL_NOT_ACTIVE,
    DISMISSAL_NOT_FOUND,
    NAME_BLANK,
    NAME_TAKEN,
    OBLIGATION_REFUSALS,
    PROPOSAL_NOT_FOUND,
    RANGE_INVALID,
    SAME_MATCHER,
    STALE_DISMISS_REVISION,
    STALE_DISMISSAL_REVISION,
    STALE_OBLIGATION_PREVIEW,
    STALE_OBLIGATION_REVISION,
    SUPERSEDE_ACCOUNT_DIFFERS,
    SUPERSEDE_TERMS_GIVEN,
    TERMS_CADENCE_PAIR,
    TERMS_CLOSED_MONTH,
    TERMS_NOT_LATER,
    TERMS_REQUIRED,
    TEXT_BLANK,
    TOLERANCE_DAYS_RANGE,
)
from personal_finance.reconcile.decisions import STALE_ACCOUNT
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.totals import combined, income_and_spending

POWER = "SYNTHETIC POWER CO"
TOKEN = r"ob1-[0-9a-f]{16}"


class ObligationLedger(IncomeLedger, CategoryLedger):
    def pay(self, name, day, amount="-85.00", text=POWER, financial_type="purchase",
            account="A"):
        """One money-out row in its own file, typed financial_type unless None."""
        return self.deposit(name, day, amount=amount, text=text, financial_type=financial_type,
                            account=account)

    def obligation_words(self, name="Power", match="synthetic power", cadence="monthly:5",
                         anchor="2026-01-05", amount="85.00", amount_range=None,
                         obligation_class="fixed", account="A", category=None,
                         tolerance_days=None, from_proposal=None, supersedes=None):
        words = ["--account", account, "--name", name, "--match", match]
        for option, value in (("--cadence", cadence), ("--anchor", anchor), ("--amount", amount),
                              ("--range", amount_range), ("--class", obligation_class),
                              ("--category", category), ("--tolerance-days", tolerance_days),
                              ("--from-proposal", from_proposal), ("--supersedes", supersedes)):
            if value is not None:
                words += [option, str(value)]
        return words

    def ob_preview(self, **options):
        return self.run("obligation", "preview", *self.obligation_words(**options))

    def ob_preview_ok(self, **options):
        code, out, err = self.ob_preview(**options)
        assert (code, err) == (0, ""), err
        return out

    def ob_preview_revision(self, **options):
        return re.search(rf"Revision: ({TOKEN})", self.ob_preview_ok(**options))[1]

    def ob_add(self, revision=None, **options):
        return self.run("obligation", "add", *self.obligation_words(**options), "--revision",
                        revision or self.ob_preview_revision(**options))

    def ob_add_ok(self, **options):
        code, out, err = self.ob_add(**options)
        assert (code, err) == (0, ""), err
        return re.search(r"Obligation (\S+) recorded", out)[1]

    def ob_show(self, obligation, as_of="2026-12-31"):
        code, out, err = self.run("obligation", "show", obligation, "--as-of", as_of)
        assert code == 0, err
        return out

    def ob_token(self, obligation, kind):
        return re.search(rf"{kind} revision: ({TOKEN})", self.ob_show(obligation))[1]

    def ob_terms(self, obligation, effective_from, *extra, as_of="2026-01-01", revision=None):
        return self.run("obligation", "terms", obligation, "--effective-from", effective_from,
                        *extra, "--as-of", as_of, "--revision",
                        revision or self.ob_token(obligation, "Terms"))

    def ob_undo(self, obligation, revision=None):
        return self.run("obligation", "undo", obligation, "--revision",
                        revision or self.ob_token(obligation, "Undo"))

    def proposals(self):
        code, out, err = self.run("obligation", "proposals")
        assert code == 0, err
        return out

    def proposal_keys(self):
        return re.findall(r"Proposal ([0-9a-f]{16}):", self.proposals())

    def dismiss_token(self, key):
        found = re.search(rf"Proposal {key}:.*?Dismiss revision: ({TOKEN})", self.proposals(),
                          re.S)
        return found[1]

    def dismiss(self, key, revision=None):
        return self.run("obligation", "dismiss", key, "--revision",
                        revision or self.dismiss_token(key))

    def dismissals(self):
        code, out, err = self.run("obligation", "dismissals")
        assert code == 0, err
        return out

    def undo_dismissal(self, dismissal, revision=None):
        if revision is None:
            revision = re.search(rf"Dismissal {dismissal}:.*?Undo revision: ({TOKEN})",
                                 self.dismissals(), re.S)[1]
        return self.run("obligation", "dismissal", "undo", dismissal, "--revision", revision)

    def ob_outcomes(self):
        """Each reached payment as its file names, its obligation's name, state, due date and
        class."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (tuple(sorted(names[transaction_id])), name, state, nominal, obligation_class)
            for transaction_id, name, state, nominal, obligation_class in conn.execute(
                """SELECT derived.transaction_id, obligation.name, derived.state,
                          derived.nominal_date, derived.obligation_class
                   FROM transaction_obligation derived
                   JOIN recurring_obligation obligation
                       ON obligation.id = derived.obligation_id""")
        )
        conn.close()
        return found

    def obligation_tables(self):
        return self.dump(OBLIGATION_TABLES)

    def add_rule_ok(self, category, contains):
        words = ["--category", category, "--description-contains", contains]
        code, out, err = self.run("category", "rule", "preview", *words)
        assert code == 0, err
        revision = re.search(r"Revision: (p1-[0-9a-f]{16})", out)[1]
        code, out, err = self.run("category", "rule", "add", *words, "--preview", revision)
        assert code == 0, err


@pytest.fixture
def ledger(tmp_path, capsys):
    return ObligationLedger(tmp_path, capsys)


@pytest.fixture
def billed(ledger):
    """Three monthly power bills due on the 5th, typed purchase."""
    for name, day in (("b1.csv", "2026-01-05"), ("b2.csv", "2026-02-05"),
                      ("b3.csv", "2026-03-06")):
        ledger.pay(name, day)
    return ledger


# IB1's migration and append-only tables are test_obligation_migration.py.

@pytest.fixture
def history(billed):
    """An obligation with a later terms row, a second one undone, and a dismissal undone."""
    obligation = billed.ob_add_ok()
    assert billed.ob_terms(obligation, "2026-04-01", "--amount", "90.00")[0] == 0
    other = billed.ob_add_ok(name="Other", match="power")
    assert billed.ob_undo(other)[0] == 0
    for name, day in (("w1.csv", "2026-01-10"), ("w2.csv", "2026-02-10"),
                      ("w3.csv", "2026-03-10")):
        billed.pay(name, day, amount="-30.00", text="SYNTHETIC WATER")
    (key,) = billed.proposal_keys()
    assert billed.dismiss(key)[0] == 0
    (dismissal,) = re.findall(r"Dismissal (\S+):", billed.dismissals())
    assert billed.undo_dismissal(dismissal)[0] == 0
    return billed


# IB2: what an obligation reaches, and its states.

class TestReach:  # IB2
    def test_only_money_out_in_spending_whose_description_contains_its_text(self, ledger):
        ledger.add_account("B")
        ledger.pay("bill.csv", "2026-01-05")
        ledger.pay("refund.csv", "2026-01-06", amount="10.00", financial_type="refund")
        ledger.pay("other.csv", "2026-01-06", text="SYNTHETIC GAS CO")
        ledger.pay("untyped.csv", "2026-01-06", financial_type=None)
        ledger.pay("moved.csv", "2026-01-06", financial_type="transfer")
        ledger.pay("elsewhere.csv", "2026-01-05", account="B")
        ledger.pay("fee.csv", "2026-01-07", financial_type="fee")
        ledger.ob_add_ok()
        assert ledger.ob_outcomes() == [
            (("bill.csv",), "Power", "paid", "2026-01-05", "fixed"),
            (("fee.csv",), "Power", "unscheduled", None, "fixed")]

    def test_a_category_narrows_it_by_a_persons_category_else_the_rules(self, ledger):
        mine = ledger.pay("mine.csv", "2026-01-05")
        ledger.categorize_ok(mine, "Utilities and communications")
        ruled = ledger.pay("ruled.csv", "2026-02-05", text="SYNTHETIC POWER CO BILL")
        ledger.pay("plain.csv", "2026-03-05")
        ledger.add_rule_ok("Utilities and communications", "power co bill")
        ledger.ob_add_ok(category="Utilities and communications")
        assert [outcome[0] for outcome in ledger.ob_outcomes()] == [("mine.csv",),
                                                                     ("ruled.csv",)]

    def test_a_category_change_later_rewrites_what_it_reaches(self, ledger):
        bill = ledger.pay("b1.csv", "2026-01-05")
        ledger.ob_add_ok(category="Utilities and communications")
        assert ledger.ob_outcomes() == []
        ledger.categorize_ok(bill, "Utilities and communications")
        assert [outcome[0] for outcome in ledger.ob_outcomes()] == [("b1.csv",)]
        ledger.add_rule_ok("Food", "synthetic power")
        assert [outcome[0] for outcome in ledger.ob_outcomes()] == [("b1.csv",)]

    def test_a_corrected_amount_and_date_are_what_it_reads(self, billed):
        billed.correct_ok(holding(billed, "b2.csv"), "amount", "-99.00")
        billed.ob_add_ok()
        assert billed.ob_outcomes()[1][2] == "amount_out_of_range"

    def test_a_range_plans_its_high_and_pays_within_it(self, billed):
        obligation = billed.ob_add_ok(amount=None, amount_range="60.00..85.00")
        assert all(outcome[2] == "paid" for outcome in billed.ob_outcomes())
        out = billed.ob_show(obligation, as_of="2026-04-01")
        assert "2026-04-05 (fixed): expected, planned 85.00" in out
        assert billed.ob_add(name="Narrow", match="power co", amount=None,
                             amount_range="60.00..84.99")[0] == 0
        assert {outcome[2] for outcome in billed.ob_outcomes()} == {"obligation_conflict"}

    def test_two_obligations_on_one_payment_leave_it_discretionary(self, billed):
        billed.ob_add_ok()
        billed.ob_add_ok(name="Broad", match="power", obligation_class="discretionary")
        assert {outcome[2:] for outcome in billed.ob_outcomes()} == {
            ("obligation_conflict", None, None)}
        conn = billed.conn()
        by_class = spending_by_class(conn)
        conn.close()
        assert by_class.fixed.transactions == 0
        assert by_class.discretionary.out_cents == 3 * 8500
        out = billed.run("review", "transaction", "show", holding(billed, "b1.csv"))[1]
        assert "obligation_conflict" in out and "discretionary" in out

    def test_nothing_before_the_first_due_date_less_the_tolerance(self, ledger):
        ledger.pay("early.csv", "2025-12-05")
        ledger.pay("edge.csv", "2026-01-02")
        ledger.pay("b1.csv", "2026-01-05")
        obligation = ledger.ob_add_ok()
        assert [outcome[0] for outcome in ledger.ob_outcomes()] == [("b1.csv",), ("edge.csv",)]
        assert "Before the first due date, not reached: 1" in ledger.ob_show(obligation)


class TestStates:  # IB2
    def test_each_state_is_produced(self, ledger):
        ledger.pay("b1.csv", "2026-01-05")
        ledger.pay("b2.csv", "2026-02-06", amount="-120.00")
        ledger.pay("extra.csv", "2026-02-20")
        obligation = ledger.ob_add_ok(amount=None, amount_range="80.00..100.00")
        assert ledger.ob_outcomes() == [
            (("b1.csv",), "Power", "paid", "2026-01-05", "fixed"),
            (("b2.csv",), "Power", "amount_out_of_range", "2026-02-05", "fixed"),
            (("extra.csv",), "Power", "unscheduled", None, "fixed")]
        out = ledger.ob_show(obligation, as_of="2026-04-07")
        assert "2026-03-05 (fixed): missed, planned 100.00" in out
        assert "2026-04-05 (fixed): expected, planned 100.00" in out
        assert "2026-05-05 (fixed): expected, planned 100.00" in out
        assert "2026-06-05" not in out

    def test_missed_and_expected_change_no_token(self, billed):
        obligation = billed.ob_add_ok()
        early = billed.ob_show(obligation, as_of="2026-03-01")
        late = billed.ob_show(obligation, as_of="2026-12-31")
        undo = re.compile(rf"Undo revision: {TOKEN}")
        assert undo.search(early)[0] == undo.search(late)[0]

    def test_an_as_of_must_be_a_date(self, billed):
        obligation = billed.ob_add_ok()
        code, _, err = billed.run("obligation", "show", obligation, "--as-of", "2026-2-1")
        assert code == 2 and "--as-of must be a date" in err


@pytest.mark.slow
def test_pairing_is_the_same_in_every_import_order(capsys):  # IB2, exhaustively for four files
    rows = [("b1.csv", "2026-01-05"), ("b2.csv", "2026-01-06"), ("b3.csv", "2026-02-03"),
            ("b4.csv", "2026-02-08")]
    seen = set()
    for order in itertools.permutations(rows):
        with tempfile.TemporaryDirectory() as folder:
            ledger = ObligationLedger(Path(folder), capsys)
            ledger.ob_add_ok()
            for name, day in order:
                ledger.pay(name, day)
            seen.add(tuple(ledger.ob_outcomes()))
    assert seen == {(
        (("b1.csv",), "Power", "paid", "2026-01-05", "fixed"),
        (("b2.csv",), "Power", "unscheduled", None, "fixed"),
        (("b3.csv",), "Power", "paid", "2026-02-05", "fixed"),
        (("b4.csv",), "Power", "unscheduled", None, "fixed"),
    )}


# IB3: fixed and discretionary spending add to D-056's Spending exactly.

def generated_ledger(ledger, seed):
    """Two accounts, four months of bills, groceries, refunds, transfers and corrections, with a
    fixed and a discretionary obligation on each account and one pair that conflicts."""
    chooser = random.Random(seed)
    ledger.add_account("B")
    files = 0
    for account in ("A", "B"):
        for month in range(1, 5):
            for text, amount, financial_type in (
                    (POWER, f"-{chooser.randint(80, 95)}.00", "purchase"),
                    ("SYNTHETIC GYM", "-40.00", "purchase"),
                    ("SYNTHETIC GROCER", f"-{chooser.randint(10, 200)}.25",
                     chooser.choice(["purchase", "fee", "interest"])),
                    ("SYNTHETIC GROCER", f"{chooser.randint(1, 9)}.00", "refund"),
                    ("SYNTHETIC SAVINGS", "-100.00", chooser.choice(["transfer", None]))):
                files += 1
                day = f"2026-{month:02d}-{chooser.randint(3, 7):02d}"
                transaction = ledger.pay(f"g{files}.csv", day, amount=amount, text=text,
                                         financial_type=financial_type, account=account)
                if chooser.random() < 0.15 and financial_type == "purchase":
                    ledger.correct_ok(transaction, "amount", f"-{chooser.randint(1, 300)}.00",
                                      account=account)
        ledger.ob_add_ok(name=f"Power {account}", account=account, amount=None,
                         amount_range="80.00..95.00")
        ledger.ob_add_ok(name=f"Gym {account}", match="synthetic gym", account=account,
                         amount="40.00", obligation_class="discretionary")
    ledger.ob_add_ok(name="Grocer", match="synthetic grocer", account="A", amount=None,
                     amount_range="1.00..300.00")
    ledger.ob_add_ok(name="Grocer too", match="grocer", account="A", amount=None,
                     amount_range="1.00..300.00")
    return ledger


@pytest.mark.slow
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_fixed_and_discretionary_add_to_spending_exactly(ledger, seed):  # IB3
    generated_ledger(ledger, seed)
    conn = ledger.conn()
    try:
        accounts = [None, ledger.account_id("A"), ledger.account_id("B")]
        assert conn.execute("SELECT COUNT(*) FROM transaction_obligation WHERE "
                            "state = 'obligation_conflict'").fetchone()[0] > 0
        for account_id in accounts:
            by_class = spending_by_class(conn, account_id)
            spending = income_and_spending(conn, account_id).spending
            assert combined([by_class.fixed, by_class.discretionary]) == spending
            assert by_class.fixed.transactions > 0 and by_class.discretionary.transactions > 0
            for month in monthly_report(conn, account_id).months:
                by_class = spending_by_class(conn, account_id, month.month)
                assert (combined([by_class.fixed, by_class.discretionary])
                        == month.income_and_spending.spending)
    finally:
        conn.close()


# IB4: proposals and their dismissal.

class TestProposals:  # IB4
    def test_three_monthly_bills_are_proposed_with_a_dismiss_token(self, billed):
        out = billed.proposals()
        assert "description synthetic power co, monthly:5" in out
        assert "--anchor 2026-01-05 --amount 85.00, expected next 2026-04-05" in out
        assert re.search(rf"Dismiss revision: {TOKEN}", out)

    def test_varying_amounts_suggest_a_range(self, ledger):
        for name, day, amount in (("b1.csv", "2026-01-05", "-80.00"),
                                  ("b2.csv", "2026-02-05", "-88.00"),
                                  ("b3.csv", "2026-03-05", "-84.00")):
            ledger.pay(name, day, amount=amount)
        assert "--range 80.00..88.00" in ledger.proposals()

    def test_a_dismissal_holds_across_imports_and_its_undo_brings_it_back(self, billed):
        (key,) = billed.proposal_keys()
        assert billed.dismiss(key)[0] == 0
        assert billed.proposal_keys() == []
        billed.pay("b4.csv", "2026-04-05")
        assert billed.proposal_keys() == []
        (dismissal,) = re.findall(r"Dismissal (\S+): active", billed.dismissals())
        assert billed.undo_dismissal(dismissal)[0] == 0
        assert billed.proposal_keys() == [key]
        assert f"Dismissal {dismissal}: undone" in billed.dismissals()
        assert billed.dismiss(key)[0] == 0
        assert billed.proposal_keys() == []

    def test_a_group_an_obligation_reaches_is_withdrawn(self, billed):
        billed.ob_add_ok()
        assert billed.proposal_keys() == []

    def test_a_stale_dismiss_token_refuses(self, billed):
        (key,) = billed.proposal_keys()
        revision = billed.dismiss_token(key)
        billed.pay("b4.csv", "2026-04-05")
        before = billed.obligation_tables()
        code, _, err = billed.dismiss(key, revision=revision)
        assert (code, err.strip()) == (2, f"Error: {STALE_DISMISS_REVISION}")
        assert billed.obligation_tables() == before

    def test_a_stale_undo_token_and_twice_undone(self, billed):
        (key,) = billed.proposal_keys()
        assert billed.dismiss(key)[0] == 0
        (dismissal,) = re.findall(r"Dismissal (\S+): active", billed.dismissals())
        revision = re.search(rf"Undo revision: ({TOKEN})", billed.dismissals())[1]
        billed.pay("b4.csv", "2026-04-05")
        code, _, err = billed.undo_dismissal(dismissal, revision=revision)
        assert (code, err.strip()) == (2, f"Error: {STALE_DISMISSAL_REVISION}")
        assert billed.undo_dismissal(dismissal)[0] == 0
        code, _, err = billed.undo_dismissal(dismissal, revision=revision)
        assert (code, err.strip()) == (2, f"Error: {DISMISSAL_NOT_ACTIVE}")
        code, _, err = billed.undo_dismissal("nope", revision=revision)
        assert (code, err.strip()) == (2, f"Error: {DISMISSAL_NOT_FOUND}")

    def test_a_token_covers_every_payment_of_the_group(self, billed):
        billed.pay("b4.csv", "2026-04-05")
        (key,) = billed.proposal_keys()
        dismiss, add = billed.dismiss_token(key), billed.ob_preview_revision(from_proposal=key)
        # A payment's date moves within its group: the key, anchor, last date, next date and
        # amounts all stay the same, and what the obligation would reach does too.
        billed.correct_ok(holding(billed, "b2.csv"), "transaction_date", "2026-02-06")
        assert billed.proposal_keys() == [key]
        code, _, err = billed.dismiss(key, revision=dismiss)
        assert (code, err.strip()) == (2, f"Error: {STALE_DISMISS_REVISION}")
        code, _, err = billed.ob_add(revision=add, from_proposal=key)
        assert (code, err.strip()) == (2, f"Error: {STALE_OBLIGATION_PREVIEW}")

    def test_an_unknown_or_dismissed_key_cannot_be_dismissed(self, billed):
        (key,) = billed.proposal_keys()
        revision = billed.dismiss_token(key)
        assert billed.dismiss(key, revision=revision)[0] == 0
        code, _, err = billed.dismiss(key, revision=revision)
        assert (code, err.strip()) == (2, f"Error: {DISMISS_NOT_FOUND}")

    def test_an_add_from_a_changed_proposal_refuses(self, billed):
        (key,) = billed.proposal_keys()
        revision = billed.ob_preview_revision(from_proposal=key)
        billed.pay("b4.csv", "2026-04-05")
        code, _, err = billed.ob_add(revision=revision, from_proposal=key)
        assert (code, err.strip()) == (2, f"Error: {STALE_OBLIGATION_PREVIEW}")

    def test_a_token_covers_the_proposal_even_where_the_reach_is_unchanged(self, billed):
        (key,) = billed.proposal_keys()
        revision = billed.ob_preview_revision(from_proposal=key, match="synthetic power co")
        without_proposal = billed.ob_preview_revision(match="synthetic power co")
        billed.pay("older.csv", "2025-12-05")
        # Before the first due date less the tolerance, so what the obligation reaches is the same.
        assert billed.ob_preview_revision(match="synthetic power co") == without_proposal
        assert billed.proposal_keys() == [key]
        code, _, err = billed.ob_add(revision=revision, from_proposal=key,
                                     match="synthetic power co")
        assert (code, err.strip()) == (2, f"Error: {STALE_OBLIGATION_PREVIEW}")

    def test_an_unknown_proposal_is_refused(self, billed):
        code, _, err = billed.ob_preview(from_proposal="0" * 16)
        assert (code, err.strip()) == (2, f"Error: {PROPOSAL_NOT_FOUND}")


# G3 and the refusals of a write.

class TestRefusals:
    def refused(self, ledger, message, **options):
        before = (ledger.obligation_tables(), ledger.evidence())
        code, _, err = ledger.ob_add(revision=options.pop("revision", "ob1-0000000000000000"),
                                     **options)
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (ledger.obligation_tables(), ledger.evidence()) == before

    @pytest.mark.parametrize(("options", "message"), [
        ({"name": " "}, NAME_BLANK),
        ({"match": "  "}, TEXT_BLANK),
        ({"category": "Nope"}, CATEGORY_UNKNOWN),
        ({"amount": "0"}, AMOUNT_INVALID),
        ({"amount": "-5.00"}, AMOUNT_INVALID),
        ({"amount_range": "60.00..140.00"}, AMOUNT_OR_RANGE),
        ({"amount": None, "amount_range": "90.00..80.00"}, RANGE_INVALID),
        ({"amount": None, "amount_range": "0..80.00"}, RANGE_INVALID),
        ({"amount": None, "amount_range": "80.00"}, RANGE_INVALID),
        ({"anchor": "2026-01-06"}, ANCHOR_OFF_CADENCE),
        ({"cadence": "annual:02-05"}, ANCHOR_OFF_CADENCE),
        ({"tolerance_days": 8}, TOLERANCE_DAYS_RANGE),
        ({"obligation_class": None}, TERMS_REQUIRED),
        ({"amount": None}, TERMS_REQUIRED),
    ])
    def test_what_was_typed(self, billed, options, message):
        self.refused(billed, message, **options)

    def test_a_repeated_name_and_the_same_matcher(self, billed):
        obligation = billed.ob_add_ok()
        self.refused(billed, NAME_TAKEN.format(obligation=obligation), match="power")
        self.refused(billed, SAME_MATCHER.format(obligation=obligation), name="Again",
                     match="SYNTHETIC  power")
        assert billed.ob_add(name="Narrow", category="Utilities and communications")[0] == 0

    def test_a_stale_token(self, billed):
        revision = billed.ob_preview_revision()
        billed.pay("b4.csv", "2026-04-05")
        self.refused(billed, STALE_OBLIGATION_PREVIEW, revision=revision)

    @pytest.mark.parametrize("change", [
        {"name": "Renamed"}, {"match": "power"}, {"amount": "85.01"}, {"tolerance_days": 2},
        {"amount": None, "amount_range": "80.00..85.00"}, {"obligation_class": "discretionary"},
        {"anchor": "2026-02-05"}, {"cadence": "monthly:6", "anchor": "2026-01-06"},
        {"category": "Utilities and communications"},
    ])
    def test_a_token_covers_every_field_typed(self, billed, change):
        revision = billed.ob_preview_revision()
        self.refused(billed, STALE_OBLIGATION_PREVIEW, revision=revision, **change)

    def test_a_token_covers_a_correction_a_classification_and_a_category(self, billed):
        revision = billed.ob_preview_revision()
        billed.correct_ok(holding(billed, "b3.csv"), "amount", "-84.00")
        self.refused(billed, STALE_OBLIGATION_PREVIEW, revision=revision)
        revision = billed.ob_preview_revision()
        transaction = holding(billed, "b2.csv")
        as_fee = billed.classify_ok(transaction, "fee",
                                    supersedes=billed.classification_of(transaction))
        assert billed.ob_preview_revision() == revision
        billed.classify_ok(transaction, "transfer", supersedes=as_fee)
        self.refused(billed, STALE_OBLIGATION_PREVIEW, revision=revision)
        options = {"category": "Utilities and communications"}
        revision = billed.ob_preview_revision(**options)
        billed.categorize_ok(holding(billed, "b1.csv"), "Utilities and communications")
        self.refused(billed, STALE_OBLIGATION_PREVIEW, revision=revision, **options)

    def test_a_stale_account_is_checked_first(self, billed):
        conn = billed.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        assert "adding it will be refused until it is" in billed.ob_preview_ok()
        self.refused(billed, STALE_ACCOUNT, name=" ", amount="0")

    def test_a_race_between_preview_and_add_refuses(self, billed):
        revision = billed.ob_preview_revision()
        # Another connection commits a bill the obligation would reach, between the two.
        billed.pay("b4.csv", "2026-04-05")
        self.refused(billed, STALE_OBLIGATION_PREVIEW, revision=revision)

    def test_a_fault_after_the_first_insert_leaves_nothing(self, billed, monkeypatch):
        revision = billed.ob_preview_revision()
        conn = billed.conn()
        before = logical_digest(conn)
        conn.close()

        def fail(conn, chain_id, terms):
            raise RuntimeError("injected")

        monkeypatch.setattr(obligations, "insert_terms", fail)
        code, _, err = billed.ob_add(revision=revision)
        assert code == 2 and "unexpected" in err
        conn = billed.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_a_fault_in_a_dismissal_leaves_nothing(self, billed, monkeypatch):
        (key,) = billed.proposal_keys()
        revision = billed.dismiss_token(key)
        conn = billed.conn()
        before = logical_digest(conn)
        conn.close()
        original = obligations.dismiss_revision

        def check_then_fail(conn, proposal):
            conn.execute("INSERT INTO obligation_proposal_dismissal (id, account_id, "
                         "proposal_key) VALUES ('x', ?, ?)", (proposal.account_id, key))
            raise RuntimeError("injected")

        monkeypatch.setattr(obligations, "dismiss_revision", check_then_fail)
        code, _, err = billed.dismiss(key, revision=revision)
        assert code == 2 and "unexpected" in err
        monkeypatch.setattr(obligations, "dismiss_revision", original)
        conn = billed.conn()
        assert logical_digest(conn) == before
        conn.close()


class TestTermsAndUndoRefusals:
    def refused(self, ledger, attempt, message):
        before = (ledger.obligation_tables(), ledger.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (ledger.obligation_tables(), ledger.evidence()) == before

    def test_an_effective_date_in_a_closed_month(self, billed):
        obligation = billed.ob_add_ok()
        self.refused(billed, lambda: billed.ob_terms(obligation, "2026-02-27", "--amount",
                                                     "90.00", as_of="2026-03-01"),
                     TERMS_CLOSED_MONTH)
        assert billed.ob_terms(obligation, "2026-03-13", "--amount", "90.00",
                               as_of="2026-03-01")[0] == 0

    def test_an_effective_date_not_after_the_latest_terms(self, billed):
        obligation = billed.ob_add_ok()
        self.refused(billed, lambda: billed.ob_terms(obligation, "2026-01-05", "--amount",
                                                     "90.00"),
                     TERMS_NOT_LATER.format(latest="2026-01-05"))

    def test_a_cadence_needs_its_anchor_and_an_amount_or_range(self, billed):
        obligation = billed.ob_add_ok()
        self.refused(billed, lambda: billed.ob_terms(obligation, "2026-03-01", "--amount",
                                                     "90.00", "--cadence", "weekly"),
                     TERMS_CADENCE_PAIR)
        self.refused(billed, lambda: billed.ob_terms(obligation, "2026-03-01"), AMOUNT_OR_RANGE)

    def test_a_stale_terms_or_undo_token(self, billed):
        obligation = billed.ob_add_ok()
        terms, undo = billed.ob_token(obligation, "Terms"), billed.ob_token(obligation, "Undo")
        assert terms != undo
        self.refused(billed, lambda: billed.ob_terms(obligation, "2026-03-01", "--amount",
                                                     "90.00", revision=undo),
                     STALE_OBLIGATION_REVISION)
        self.refused(billed, lambda: billed.ob_undo(obligation, revision=terms),
                     STALE_OBLIGATION_REVISION)
        billed.pay("b4.csv", "2026-04-05")
        self.refused(billed, lambda: billed.ob_undo(obligation, revision=undo),
                     STALE_OBLIGATION_REVISION)

    def test_unknown_undone_and_superseded_obligations(self, billed):
        obligation = billed.ob_add_ok()
        newer = billed.ob_add_ok(name="Power 2", cadence=None, anchor=None, amount=None,
                                 obligation_class=None, supersedes=obligation)
        self.refused(billed, lambda: billed.ob_undo("nope", revision="ob1-0000000000000000"),
                     OBLIGATION_REFUSALS.not_found)
        self.refused(billed, lambda: billed.ob_undo(obligation, revision="ob1-0000000000000000"),
                     OBLIGATION_REFUSALS.superseded.format(newest=newer))
        assert billed.ob_undo(newer)[0] == 0
        self.refused(billed, lambda: billed.ob_undo(newer, revision="ob1-0000000000000000"),
                     OBLIGATION_REFUSALS.not_active)

    def test_supersede_takes_no_terms_and_keeps_its_account(self, billed):
        billed.add_account("B")
        obligation = billed.ob_add_ok()
        for options, message in (({}, SUPERSEDE_TERMS_GIVEN),
                                 ({"cadence": None, "anchor": None, "amount": None,
                                   "obligation_class": None, "account": "B"},
                                  SUPERSEDE_ACCOUNT_DIFFERS)):
            before = (billed.obligation_tables(), billed.evidence())
            code, _, err = billed.ob_preview(supersedes=obligation, **options)
            assert (code, err.strip()) == (2, f"Error: {message}")
            assert (billed.obligation_tables(), billed.evidence()) == before

    def test_no_obligation_write_changes_the_evidence(self, billed):  # G1
        before = billed.evidence()
        obligation = billed.ob_add_ok()
        assert billed.ob_terms(obligation, "2026-03-06", "--range", "80.00..90.00")[0] == 0
        newer = billed.ob_add_ok(name="Narrow", cadence=None, anchor=None, amount=None,
                                 obligation_class=None, supersedes=obligation)
        assert billed.ob_undo(newer)[0] == 0
        assert billed.ob_undo(obligation)[0] == 0
        assert billed.evidence() == before
        for name, day in (("w1.csv", "2026-01-10"), ("w2.csv", "2026-02-10"),
                          ("w3.csv", "2026-03-10")):
            billed.pay(name, day, amount="-30.00", text="SYNTHETIC WATER")
        before = billed.evidence()
        (key, *_) = billed.proposal_keys()
        assert billed.dismiss(key)[0] == 0
        (dismissal,) = re.findall(r"Dismissal (\S+):", billed.dismissals())
        assert billed.undo_dismissal(dismissal)[0] == 0
        assert billed.evidence() == before


class TestTermsAndChains:
    def test_a_later_terms_row_changes_only_later_due_dates_and_can_change_class(self, billed):
        obligation = billed.ob_add_ok()
        before = billed.ob_show(obligation, as_of="2026-03-31")
        assert billed.ob_terms(obligation, "2026-03-01", "--amount", "85.00", "--class",
                               "discretionary")[0] == 0
        after = billed.ob_show(obligation, as_of="2026-03-31")
        assert "2026-01-05 (fixed): paid" in after and "2026-02-05 (fixed): paid" in after
        assert "2026-03-05 (discretionary): paid" in after
        assert before != after
        assert [outcome[4] for outcome in billed.ob_outcomes()] == ["fixed", "fixed",
                                                                     "discretionary"]

    def test_superseding_narrows_the_matcher_and_undo_steps_back(self, billed):
        billed.pay("gas.csv", "2026-01-05", text="SYNTHETIC POWER GAS")
        obligation = billed.ob_add_ok(match="synthetic power")
        assert len(billed.ob_outcomes()) == 4
        newer = billed.ob_add_ok(name="Power only", match="power co", cadence=None, anchor=None,
                                 amount=None, obligation_class=None, supersedes=obligation)
        assert len(billed.ob_outcomes()) == 3
        assert f"Superseded by {newer}" in billed.ob_show(obligation)
        assert billed.ob_undo(newer)[0] == 0
        assert len(billed.ob_outcomes()) == 4


# IB5: "Recurring" in review show and review transaction show, only where something reaches.

class TestRecurringSection:  # IB5
    def test_only_a_transaction_something_reaches_gains_it(self, billed):
        reached, untouched = holding(billed, "b1.csv"), billed.pay("x.csv", "2026-01-09",
                                                                  text="SYNTHETIC CAFE")
        before = billed.run("review", "transaction", "show", untouched)
        assert "Recurring" not in billed.run("review", "transaction", "show", reached)[1]
        obligation = billed.ob_add_ok()
        assert billed.run("review", "transaction", "show", untouched) == before
        out = billed.run("review", "transaction", "show", reached)[1]
        assert "  Recurring:" in out
        assert (f"    Obligation {obligation} (Power): paid for the due date 2026-01-05, fixed"
                in out)

    def test_an_income_source_shows_there_too_and_tokens_do_not_move(self, billed):
        paycheck = billed.deposit("p1.csv", "2026-01-02")
        shown = billed.run("review", "transaction", "show", paycheck)[1]
        revision = re.search(r"Revision: (t\d+-[0-9a-f]{16})", shown)[1]
        source = billed.add_ok()
        out = billed.run("review", "transaction", "show", paycheck)[1]
        assert f"    Income source {source} (Pay): received for the pay date 2026-01-02" in out
        assert re.search(r"Revision: (t\d+-[0-9a-f]{16})", out)[1] == revision

    def test_names_are_escaped(self, billed):
        billed.ob_add_ok(name="Power\x1b[2J")
        out = billed.run("review", "transaction", "show", holding(billed, "b1.csv"))[1]
        assert "\x1b" not in out and "Power\\x1b[2J" in out


class TestListAndShow:
    def test_obligations_lists_each_and_spending_by_class(self, billed):
        billed.ob_add_ok()
        out = billed.run("obligations")[1]
        assert "Reaches: paid 3" in out
        assert "Fixed spending, actual: 3 transactions, out 255.00, in 0.00" in out
        assert "Discretionary spending, actual: 0 transactions, out 0.00, in 0.00" in out

    def test_names_and_text_are_escaped(self, billed):
        obligation = billed.ob_add_ok(name="Bill\x1b[2J")
        assert "\x1b" not in billed.ob_show(obligation)
        assert "\x1b" not in billed.run("obligations")[1]
