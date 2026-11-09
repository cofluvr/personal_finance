"""Balance observations and statement reconciliation, end to end, using synthetic data only
(D-057)."""

import re

import pytest
from test_confirmations import confirm_ok
from test_decisions import (
    ALL_TABLES,
    BALANCE_TABLES,
    CHECKING_HEADER,
    declared,
    pair_up,
)
from test_one_sided_transfers import OneSidedLedger, stated
from test_pending_posted import PENDING, POSTED
from test_resolutions import CAFE_NO_AMOUNT

from personal_finance.reconcile.apply import load_constraints, load_evidence
from personal_finance.reconcile.balance_observations import (
    AMOUNT_INVALID,
    BALANCE_ON_A_LIABILITY,
    DATE_INVALID,
    DAY_ALREADY_OBSERVED,
    OBSERVATION_NOT_ACTIVE,
    OBSERVATION_NOT_FOUND,
    OBSERVATION_WRONG_ACCOUNT,
    OWED_ON_AN_ASSET,
    STALE_OBSERVATION_REVISION,
)
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports import balances
from personal_finance.reports.balances import check_balances

LEDGER_TABLES = tuple(table for table in ALL_TABLES if table not in BALANCE_TABLES)


class BalanceLedger(OneSidedLedger):
    def record(self, day, balance=None, owed=None, account="A"):
        words = ["balance", "record", "--account", account, "--date", day]
        if balance is not None:
            words.append(f"--balance={balance}")
        if owed is not None:
            words.append(f"--owed={owed}")
        return self.run(*words)

    def record_ok(self, day, balance=None, owed=None, account="A"):
        code, out, err = self.record(day, balance, owed, account)
        assert code == 0, err
        return re.search(r"Balance observation (\S+) recorded", out)[1]

    def balance_list(self, account=None):
        code, out, err = self.run("balance", "list", *(["--account", account] if account else []))
        assert code == 0, err
        return out

    def token(self, observation):
        section = self.balance_list().split(f"Observation {observation}:")[1]
        return re.match(r"[^\n]*\n  Token: (b1-[0-9a-f]{16})\n", section)[1]

    def undo_balance(self, observation, account="A", token=None):
        return self.run("balance", "undo", "--account", account, "--observation", observation,
                        "--token", token or self.token(observation))

    def check(self, account="A"):
        code, out, err = self.run("balance", "check", "--account", account)
        assert code == 0, err
        return out

    def outcomes(self, account="A"):
        return re.findall(r"^After (\S+) through (\S+): (agrees|differs by \S+)$",
                          self.check(account), re.MULTILINE)

    def intervals(self, account="A"):
        conn = self.conn()
        found = check_balances(conn, self.account_id(account)).intervals
        conn.close()
        return found

    def rows(self, name, *rows, account="A", extra=()):
        return self.load_path(self.write(name, CHECKING_HEADER, rows), *extra, account=account,
                              layout="synthetic_checking_v1")

    def stored_balances(self):
        conn = self.conn()
        found = conn.execute(
            "SELECT observed_on, balance_cents FROM balance_observation ORDER BY observed_on"
        ).fetchall()
        conn.close()
        return found


def with_id(ledger, external_id):
    conn = ledger.conn()
    (found,) = conn.execute(
        "SELECT id FROM ledger_transaction WHERE external_id = ?", (external_id,)).fetchone()
    conn.close()
    return found


@pytest.fixture
def ledger(tmp_path, capsys):
    """Checking A, savings S, a card and a loan."""
    found = BalanceLedger(tmp_path, capsys)
    found.add_account("S", "savings")
    found.add_account("Card", "credit_card")
    found.add_account("Loan", "loan")
    return found


def february(ledger, opening="100.00", closing="83.00"):
    """Opening on 31 January and closing on 28 February, with -20.00 and 3.00 posted between."""
    ledger.rows("feb.csv", "X1,2026-01-30,2026-02-01,SYNTHETIC SHOP,-20.00,POSTED",
                "X2,2026-02-27,2026-02-28,SYNTHETIC REFUND,3.00,POSTED")
    return ledger.record_ok("2026-01-31", opening), ledger.record_ok("2026-02-28", closing)


class TestReconciliation:  # B1
    def test_opening_plus_activity_equals_closing(self, ledger):
        february(ledger)
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", "agrees")]
        assert "  Opening 100.00, account movement -17.00 over 2 transactions, expected 83.00, " \
               "observed 83.00\n" in ledger.check()

    @pytest.mark.parametrize(("opening", "closing", "outcome"), [
        ("100.00", "83.01", "differs by 0.01"),
        ("100.00", "82.99", "differs by -0.01"),
        ("100.01", "83.00", "differs by -0.01"),
        ("99.99", "83.00", "differs by 0.01"),
    ])
    def test_a_cent_on_either_side_differs_by_that_cent(self, ledger, opening, closing, outcome):
        february(ledger, opening, closing)
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", outcome)]

    @pytest.mark.parametrize(("closing", "outcome"), [
        ("60.00", "agrees"), ("60.01", "differs by 0.01"), ("59.99", "differs by -0.01"),
    ])
    def test_a_card_reconciles_what_it_owes(self, ledger, closing, outcome):
        ledger.card("card.csv", "02/10/2026,SYNTHETIC SHOP,50.00,", account="Card")
        ledger.record_ok("2026-01-31", owed="10.00", account="Card")
        ledger.record_ok("2026-02-28", owed=closing, account="Card")
        assert ledger.outcomes("Card") == [("2026-01-31", "2026-02-28", outcome)]
        if outcome == "agrees":
            assert "  Opening owed 10.00, account movement -50.00 over 1 transactions, expected " \
                   "owed 60.00, observed owed 60.00\n" in ledger.check("Card")

    def test_each_pair_of_consecutive_observations_is_one_interval(self, ledger):
        february(ledger)
        ledger.record_ok("2026-03-31", "83.00")
        ledger.record_ok("2026-01-01", "90.00")
        assert ledger.outcomes() == [("2026-01-01", "2026-01-31", "differs by 10.00"),
                                     ("2026-01-31", "2026-02-28", "agrees"),
                                     ("2026-02-28", "2026-03-31", "agrees")]

    def test_one_observation_has_nothing_to_compare(self, ledger):
        ledger.record_ok("2026-01-31", "100.00")
        out = ledger.check()
        assert "Active balance observations: 1\n" in out
        assert "nothing to compare yet" in out
        assert ledger.outcomes() == []


class TestActivity:  # B2
    def edges(self, ledger):
        ledger.rows("edges.csv",
                    "E1,2026-01-31,2026-01-31,SYNTHETIC ON OPENING DAY,-1.00,POSTED",
                    "E2,2026-01-31,2026-02-01,SYNTHETIC DAY AFTER,-2.00,POSTED",
                    "E3,2026-02-28,2026-02-28,SYNTHETIC ON CLOSING DAY,-4.00,POSTED",
                    "E4,2026-02-28,2026-03-01,SYNTHETIC DAY AFTER CLOSING,-8.00,POSTED")
        ledger.record_ok("2026-01-31", "100.00")
        ledger.record_ok("2026-02-28", "94.00")

    def test_after_the_earlier_day_through_the_later_one_exactly(self, ledger):
        self.edges(ledger)
        (interval,) = ledger.intervals()
        assert (interval.activity.transactions, interval.activity.cents) == (2, -600)
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", "agrees")]

    def test_it_uses_posting_dates_not_transaction_dates(self, ledger):
        ledger.rows("dates.csv", "D1,2026-01-20,2026-02-02,SYNTHETIC POSTED LATER,-5.00,POSTED",
                    "D2,2026-02-20,2026-03-02,SYNTHETIC POSTED AFTER,-7.00,POSTED")
        ledger.record_ok("2026-01-31", "100.00")
        ledger.record_ok("2026-02-28", "95.00")
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", "agrees")]

    def test_it_uses_effective_amounts(self, ledger):
        self.edges(ledger)
        ledger.correct_ok(with_id(ledger, "E2"), "amount", "-3.00")
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", "differs by 1.00")]

    @pytest.mark.parametrize(("external_id", "posting_date", "outcome"), [
        ("E2", "2026-01-31", "differs by -2.00"),
        ("E4", "2026-02-28", "differs by 8.00"),
        ("E1", "2026-02-01", "differs by 1.00"),
    ])
    def test_it_uses_effective_posting_dates(self, ledger, external_id, posting_date, outcome):
        self.edges(ledger)
        ledger.correct_ok(with_id(ledger, external_id), "posting_date", posting_date)
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", outcome)]

    def test_types_transfers_and_classifications_do_not_enter_it(self, ledger):
        self.edges(ledger)
        check = ledger.check()
        transaction = with_id(ledger, "E2")
        ledger.classify_ok(transaction, "transfer")
        ledger.one_sided_ok(transaction)
        ledger.classify_ok(with_id(ledger, "E3"), "purchase")
        assert ledger.check() == check


class TestRefusals:  # B3
    def refused(self, ledger, outcome, message):
        code, out, err = outcome
        assert code == 2
        assert out == ""
        assert err == f"Error: {message}\n"

    def test_an_unknown_account(self, ledger):
        before = ledger.dump(BALANCE_TABLES)
        self.refused(ledger, ledger.record("2026-01-31", "1.00", account="Nobody"),
                     "account not found: Nobody")
        assert ledger.dump(BALANCE_TABLES) == before

    def test_a_second_active_observation_for_one_day(self, ledger):
        ledger.record_ok("2026-01-31", "100.00")
        before = ledger.dump(BALANCE_TABLES)
        self.refused(ledger, ledger.record("2026-01-31", "100.00"),
                     DAY_ALREADY_OBSERVED.format(day="2026-01-31"))
        assert ledger.dump(BALANCE_TABLES) == before
        # The same day in another account is another observation.
        ledger.record_ok("2026-01-31", "100.00", account="S")

    def test_a_day_is_free_again_once_its_observation_is_undone(self, ledger):
        observation = ledger.record_ok("2026-01-31", "100.00")
        assert ledger.undo_balance(observation)[0] == 0
        ledger.record_ok("2026-01-31", "101.00")
        assert ledger.stored_balances() == [("2026-01-31", 10000), ("2026-01-31", 10100)]

    def test_owed_on_an_account_that_holds_money(self, ledger):
        for account in ("A", "S"):
            self.refused(ledger, ledger.record("2026-01-31", owed="1.00", account=account),
                         OWED_ON_AN_ASSET)
        assert ledger.stored_balances() == []

    @pytest.mark.parametrize("account", ["Card", "Loan"])
    def test_a_balance_on_a_card_or_loan(self, ledger, account):
        self.refused(ledger, ledger.record("2026-01-31", "1.00", account=account),
                     BALANCE_ON_A_LIABILITY)
        assert ledger.stored_balances() == []

    @pytest.mark.parametrize("amount", ["", " ", "1.001", "ten", "1,00", "92233720368547758.08"])
    def test_an_invalid_amount(self, ledger, amount):
        self.refused(ledger, ledger.record("2026-01-31", amount), AMOUNT_INVALID)
        assert ledger.stored_balances() == []

    def test_an_amount_owed_whose_negation_is_out_of_range(self, ledger):
        self.refused(ledger, ledger.record("2026-01-31", owed="-92233720368547758.08",
                                           account="Card"), AMOUNT_INVALID)
        assert ledger.stored_balances() == []
        # The lowest amount itself is a balance that can be stored.
        ledger.record_ok("2026-01-31", "-92233720368547758.08")
        assert ledger.stored_balances() == [("2026-01-31", -(2**63))]

    @pytest.mark.parametrize("day", ["2026-02-30", "2026-2-03", "02/03/2026", "2026-02-03T00:00",
                                     ""])
    def test_an_invalid_date(self, ledger, day):
        self.refused(ledger, ledger.record(day, "1.00"), DATE_INVALID)
        assert ledger.stored_balances() == []

    @pytest.mark.parametrize("amounts", [{}, {"balance": "1.00", "owed": "1.00"}])
    def test_exactly_one_of_balance_and_owed(self, ledger, amounts):
        with pytest.raises(SystemExit) as stopped:
            ledger.record("2026-01-31", **amounts)
        assert stopped.value.code == 2
        assert ledger.stored_balances() == []

    def test_undo_with_a_wrong_account(self, ledger):
        observation = ledger.record_ok("2026-01-31", "100.00")
        token = ledger.token(observation)
        before = ledger.dump(BALANCE_TABLES)
        self.refused(ledger, ledger.undo_balance(observation, "S", token),
                     OBSERVATION_WRONG_ACCOUNT)
        assert ledger.dump(BALANCE_TABLES) == before
        assert ledger.undo_balance(observation, "A", token)[0] == 0

    def test_undo_with_a_stale_token(self, ledger):
        observation = ledger.record_ok("2026-01-31", "100.00")
        token = ledger.token(observation)
        ledger.record_ok("2026-02-28", "100.00")
        before = ledger.dump(BALANCE_TABLES)
        self.refused(ledger, ledger.undo_balance(observation, token=token),
                     STALE_OBSERVATION_REVISION)
        self.refused(ledger, ledger.undo_balance(observation, token="b1-0000000000000000"),
                     STALE_OBSERVATION_REVISION)
        assert ledger.dump(BALANCE_TABLES) == before

    def test_undo_of_an_unknown_or_undone_observation(self, ledger):
        observation = ledger.record_ok("2026-01-31", "100.00")
        token = ledger.token(observation)
        self.refused(ledger, ledger.undo_balance("no-such-observation", token=token),
                     OBSERVATION_NOT_FOUND)
        assert ledger.undo_balance(observation, token=token)[0] == 0
        before = ledger.dump(BALANCE_TABLES)
        self.refused(ledger, ledger.undo_balance(observation, token=token), OBSERVATION_NOT_ACTIVE)
        assert ledger.dump(BALANCE_TABLES) == before


class TestOwed:  # B4
    def test_owed_is_stored_negated_and_shown_as_owed(self, ledger):
        observation = ledger.record_ok("2026-01-31", owed="120.00", account="Card")
        assert ledger.stored_balances() == [("2026-01-31", -12000)]
        assert f"Observation {observation}: Card on 2026-01-31, owed 120.00, active" \
               in ledger.balance_list()

    def test_a_credit_balance_on_a_card_round_trips(self, ledger):
        observation = ledger.record_ok("2026-01-31", owed="-5.00", account="Card")
        assert ledger.stored_balances() == [("2026-01-31", 500)]
        assert f"Observation {observation}: Card on 2026-01-31, owed -5.00, active" \
               in ledger.balance_list("Card")

    def test_a_loan_states_what_it_owes(self, ledger):
        ledger.record_ok("2026-01-31", owed="1000.00", account="Loan")
        assert ledger.stored_balances() == [("2026-01-31", -100000)]

    def test_an_overdrawn_account_has_a_negative_balance(self, ledger):
        observation = ledger.record_ok("2026-01-31", "-12.50")
        assert ledger.stored_balances() == [("2026-01-31", -1250)]
        assert f"Observation {observation}: A on 2026-01-31, -12.50, active" in ledger.balance_list()


def transaction_basis(start, end):
    return ["--declare-complete-coverage", "--coverage-start", start, "--coverage-end", end,
            "--coverage-basis", "transaction"]


class TestCoverage:  # B5
    def interval_with(self, ledger, *coverage):
        for number, extra in enumerate(coverage):
            ledger.rows(f"cover{number}.csv",
                        f"C{number},2026-02-10,2026-02-10,SYNTHETIC SHOP {number},-1.00,POSTED",
                        extra=extra)
        ledger.record_ok("2026-01-31", "100.00")
        ledger.record_ok("2026-02-28", "100.00")
        (interval,) = ledger.intervals()
        return interval.covered

    def test_complete_posting_coverage_of_every_day_covers_it(self, ledger):
        assert self.interval_with(ledger, declared("2026-02-01", "2026-02-28"))
        assert "  Covered: complete posting-basis coverage spans every day of it.\n" \
               in ledger.check()

    def test_two_spans_meeting_cover_it(self, ledger):
        assert self.interval_with(ledger, declared("2026-02-01", "2026-02-14"),
                                  declared("2026-02-15", "2026-02-28"))

    @pytest.mark.parametrize("coverage", [
        [declared("2026-02-02", "2026-02-28")],
        [declared("2026-02-01", "2026-02-27")],
        [declared("2026-02-01", "2026-02-13"), declared("2026-02-15", "2026-02-28")],
        [transaction_basis("2026-01-01", "2026-03-31")],
        [()],
    ])
    def test_a_gap_partial_or_transaction_basis_coverage_does_not(self, ledger, coverage):
        assert not self.interval_with(ledger, *coverage)
        assert "  Not covered: complete posting-basis coverage does not span every day of it, " \
               "so transactions may be missing.\n" in ledger.check()

    def test_no_documents_is_not_covered(self, ledger):
        ledger.record_ok("2026-01-31", "100.00", account="S")
        ledger.record_ok("2026-02-28", "100.00", account="S")
        assert ledger.outcomes("S") == [("2026-01-31", "2026-02-28", "agrees")]
        (interval,) = ledger.intervals("S")
        assert not interval.covered


class TestDisclosures:  # B6
    def test_pending_unknown_and_no_posting_date(self, ledger):
        ledger.rows("mixed.csv",
                    "M1,2026-02-03,2026-02-04,SYNTHETIC POSTED,-1.00,POSTED",
                    "M2,2026-02-05,,SYNTHETIC PENDING,-2.00,PENDING",
                    "M3,2026-02-06,2026-02-06,SYNTHETIC UNKNOWN,-4.00,",
                    "M4,2026-02-07,,SYNTHETIC NO POSTING DATE,-8.00,POSTED",
                    "M5,2026-03-07,,SYNTHETIC PENDING LATER,-16.00,PENDING")
        ledger.record_ok("2026-01-31", "100.00")
        ledger.record_ok("2026-02-28", "87.00")
        (interval,) = ledger.intervals()
        assert (interval.pending_left_out.transactions, interval.pending_left_out.cents) == (1, -200)
        assert (interval.unknown_status.transactions, interval.unknown_status.cents) == (1, -400)
        assert (interval.without_posting_date.transactions,
                interval.without_posting_date.cents) == (1, -800)
        out = ledger.check()
        assert "After 2026-01-31 through 2026-02-28: agrees\n" in out
        assert "  Pending, left out: 1 transactions, -2.00\n" \
               "  Of unknown status, counted: 1 transactions, -4.00\n" \
               "  With no posting date, counted by transaction date: 1 transactions, -8.00\n" in out

    def test_none_is_shown_when_there_is_none(self, ledger):
        february(ledger)
        out = ledger.check()
        for label in ("Pending", "Of unknown status", "With no posting date", "Open review items",
                      "unresolved records"):
            assert label not in out

    def test_open_review_items_with_a_transaction_there(self, ledger):
        pair_up(ledger)
        ledger.record_ok("2026-01-01", "100.00")
        ledger.record_ok("2026-01-31", "87.00")
        ledger.record_ok("2026-02-28", "87.00")
        out = ledger.check()
        first, second = out.split("After 2026-01-31")
        assert "  Open review items: 1, holding 2 transactions here\n" in first
        assert "Open review items" not in second

    def test_a_resolved_review_item_is_not(self, ledger):
        # Confirming a pending and a posted row of one document leaves their item resolved, still
        # naming the one transaction they become (D-052).
        ledger.checking("a.csv", PENDING, POSTED.format(amount="-20.00"))
        (item,) = ledger.items("same_document_pending_posted")
        confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        conn = ledger.conn()
        assert conn.execute("SELECT status FROM review_issue_subject subject "
                            "JOIN review_issue issue ON issue.id = subject.review_issue_id"
                            ).fetchall() == [("resolved",)]
        conn.close()
        ledger.record_ok("2026-01-01", "100.00")
        ledger.record_ok("2026-01-31", "80.00")
        assert ledger.outcomes() == [("2026-01-01", "2026-01-31", "agrees")]
        assert "Open review items" not in ledger.check()

    def test_unresolved_records_are_disclosed(self, ledger):
        ledger.card("blank.csv", CAFE_NO_AMOUNT)
        february(ledger)
        assert "- 1 unresolved records of this account are no transaction, so no interval counts " \
               "them, and they may explain a difference.\n" in ledger.check()


def every_token(ledger, item, transaction, statement):
    return (ledger.revision(item), ledger.transaction_revision(transaction),
            ledger.one_sided_revision(statement))


def derived(ledger):
    conn = ledger.conn()
    account = ledger.account_id("A")
    found = derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                   load_constraints(conn, account))
    conn.close()
    return found


class TestEvidenceOnly:  # B7
    def scenario(self, ledger):
        item, _, _ = pair_up(ledger)
        statement, transaction = stated(ledger)
        return item, transaction, statement

    def test_observations_change_no_evidence_total_token_or_derivation(self, ledger):
        item, transaction, statement = self.scenario(ledger)
        before = (ledger.dump(LEDGER_TABLES), ledger.totals(), ledger.run("review", "list")[1],
                  every_token(ledger, item, transaction, statement), derived(ledger))
        ledger.record_ok("2026-01-01", "100.00")
        ledger.record_ok("2026-01-31", "37.00")
        ledger.record_ok("2026-02-28", "37.00")
        assert ledger.outcomes() == [("2026-01-01", "2026-01-31", "agrees"),
                                     ("2026-01-31", "2026-02-28", "agrees")]
        after = (ledger.dump(LEDGER_TABLES), ledger.totals(), ledger.run("review", "list")[1],
                 every_token(ledger, item, transaction, statement), derived(ledger))
        assert after == before

    def test_agreement_declares_no_coverage_and_settles_nothing(self, ledger):
        item, _, _ = pair_up(ledger)
        ledger.record_ok("2026-01-01", "100.00")
        ledger.record_ok("2026-01-31", "87.00")
        assert ledger.outcomes() == [("2026-01-01", "2026-01-31", "agrees")]
        assert ledger.items() == [item]
        (interval,) = ledger.intervals()
        assert not interval.covered
        assert "possible-duplicate groups" in ledger.totals()

    def test_check_writes_nothing(self, ledger):
        february(ledger)
        dumped = ledger.dump()
        ledger.check()
        ledger.balance_list()
        assert ledger.dump() == dumped

    def test_recording_and_undoing_need_no_current_account(self, ledger):
        february(ledger)
        ledger.make_stale("A")
        observation = ledger.record_ok("2026-03-31", "83.00")
        assert ledger.undo_balance(observation)[0] == 0
        assert "- This account has not been reconciled under the current matching rules" \
               in ledger.check()


class TestSurvival:  # B9
    def test_repeat_imports_reconcile_and_a_rules_change(self, ledger):
        february(ledger)
        check = ledger.check()
        ledger.load_path(ledger.folder / "feb.csv", layout="synthetic_checking_v1")
        assert ledger.run("reconcile")[0] == 0
        ledger.make_stale("A")
        assert ledger.run("reconcile", "--account", "A")[0] == 0
        assert ledger.check() == check

    def test_a_later_import_inside_an_interval_changes_its_outcome(self, ledger):
        february(ledger)
        ledger.rows("late.csv", "L1,2026-02-14,2026-02-15,SYNTHETIC LATE,-6.25,POSTED")
        assert ledger.outcomes() == [("2026-01-31", "2026-02-28", "differs by 6.25")]

    def test_an_import_outside_every_interval_changes_nothing(self, ledger):
        february(ledger)
        check = ledger.check()
        ledger.rows("march.csv", "L2,2026-03-01,2026-03-01,SYNTHETIC LATER,-6.25,POSTED")
        ledger.card("other.csv", "02/14/2026,SYNTHETIC ELSEWHERE,6.25,", account="S")
        assert ledger.check() == check


class TestTokens:  # B10
    def test_the_version_is_pinned(self, ledger):
        assert balances.OBSERVATION_REVISION_VERSION == 1
        observation = ledger.record_ok("2026-01-31", "100.00")
        assert re.fullmatch(r"b1-[0-9a-f]{16}", ledger.token(observation))

    def test_a_neighbour_changes_it_and_a_transaction_does_not(self, ledger):
        observation = ledger.record_ok("2026-01-31", "100.00")
        token = ledger.token(observation)
        ledger.rows("feb.csv", "T1,2026-02-01,2026-02-01,SYNTHETIC SHOP,-1.00,POSTED")
        ledger.record_ok("2026-01-31", "5.00", account="S")
        assert ledger.token(observation) == token
        later = ledger.record_ok("2026-02-28", "99.00")
        assert ledger.token(observation) != token
        assert ledger.undo_balance(later)[0] == 0
        assert ledger.token(observation) == token

    def test_an_earlier_neighbour_changes_it(self, ledger):
        observation = ledger.record_ok("2026-02-28", "100.00")
        token = ledger.token(observation)
        earlier = ledger.record_ok("2026-01-31", "99.00")
        assert ledger.token(observation) != token
        assert ledger.undo_balance(earlier)[0] == 0
        assert ledger.token(observation) == token

    def test_equal_in_two_ledgers(self, tmp_path, capsys):
        tokens = []
        for number in range(2):
            folder = tmp_path / str(number)
            folder.mkdir()
            ledger = BalanceLedger(folder, capsys)
            observations = [ledger.record_ok(day, "100.00")
                            for day in ("2026-01-31", "2026-02-28", "2026-03-31")]
            tokens.append([ledger.token(observation) for observation in observations])
        assert tokens[0] == tokens[1]
        assert len(set(tokens[0])) == 3

    def test_undo_restores_the_earlier_intervals_exactly(self, ledger):
        february(ledger)
        ledger.record_ok("2026-03-31", "83.00")
        check = ledger.check()
        middle = ledger.record_ok("2026-02-14", "80.00")
        assert ledger.check() != check
        assert ledger.undo_balance(middle)[0] == 0
        assert ledger.check() == check

    def test_an_undone_observation_has_no_token_and_stays_on_record(self, ledger):
        observation = ledger.record_ok("2026-01-31", "100.00")
        code, out, _ = ledger.undo_balance(observation)
        assert code == 0
        assert f"Balance observation {observation} undone." in out
        listed = ledger.balance_list()
        assert f"Observation {observation}: A on 2026-01-31, 100.00, undone" in listed
        assert "Token:" not in listed
        assert "Balance observations: 1, of which active: 0\n" in listed
        assert ledger.outcomes() == []


class TestPrivacy:
    def test_account_names_are_escaped(self, ledger):
        ledger.add_account("Odd\x1b[31m\nName", "savings")
        ledger.record_ok("2026-01-31", "1.00", account="Odd\x1b[31m\nName")
        assert "Odd\\x1b[31m\\nName on 2026-01-31, 1.00, active" in ledger.balance_list()
