"""Income and spending in totals, end to end, using synthetic data only (D-056)."""

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st
from test_decisions import ALL_TABLES
from test_one_sided_transfers import OneSidedLedger, outflow, stated
from test_supersession import holding
from test_transfers import IN_ROW, matched, rows_of

from personal_finance.reports.totals import GroupTotal, account_movement, income_and_spending

PAYMENT_ON_THE_CARD = "01/12/2026,SYNTHETIC PAYMENT,,50.00"
PURCHASE_ON_THE_CARD = "01/05/2026,SYNTHETIC SHOP,50.00,"


def build(folder, capsys):
    """Checking A, savings S, and a card, a loan and an investment account never imported."""
    found = OneSidedLedger(folder, capsys)
    for name, account_type in (("S", "savings"), ("Card", "credit_card"), ("Loan", "loan"),
                               ("Invest", "investment")):
        found.add_account(name, account_type)
    return found


@pytest.fixture
def ledger(tmp_path, capsys):
    return build(tmp_path, capsys)


def groups(ledger, account=None):
    conn = ledger.conn()
    found = income_and_spending(conn, ledger.account_id(account) if account else None)
    conn.close()
    return found


def every_group(found):
    return (found.income, *(group for _, group in found.spending_by_type),
            *(group for _, group in found.confirmed_transfers_by_type),
            found.unconfirmed_transfer_kinds, found.unclassified)


def assert_adds_to_movement(ledger, account=None):
    conn = ledger.conn()
    movement = account_movement(conn, ledger.account_id(account) if account else None)
    conn.close()
    parts = every_group(groups(ledger, account))
    assert sum(group.transactions for group in parts) == movement.transactions
    assert sum(group.in_cents - group.out_cents for group in parts) == movement.net_cents


# Types that fit each direction on a checking account, and the counterpart a one-sided transfer of
# each transfer kind names, so that its type fits (D-054).
OUT_TYPES = (None, "purchase", "fee", "interest", "transfer", "card_payment", "loan_payment",
             "investment_contribution")
IN_TYPES = (None, "refund", "income", "transfer")
COUNTERPART_BY_TYPE = {"transfer": "S", "card_payment": "Card", "loan_payment": "Loan",
                       "investment_contribution": "Invest"}

def amount(cents):
    return f"{cents // 100}.{cents % 100:02d}"


rows = st.lists(
    st.tuples(st.integers(1, 9999), st.booleans(), st.integers(0, 7), st.booleans()),
    min_size=1, max_size=6,
)


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(checking_rows=rows, mirrored=st.lists(st.integers(0, 5), max_size=3))
def test_every_transaction_is_in_one_group_adding_to_movement(capsys, checking_rows,
                                                              mirrored):  # T1
    """Random types and one-sided statements in A, then rows in S mirroring some of A's, a day
    later, so that a counterpart may arrive."""
    with tempfile.TemporaryDirectory() as folder:
        ledger = build(Path(folder), capsys)
        ledger.card("a.csv", *(
            f"01/{1 + 3 * index:02d}/2026,SYNTHETIC ROW {index},"
            + (f",{amount(cents)}" if money_in else f"{amount(cents)},")
            for index, (cents, money_in, _, _) in enumerate(checking_rows)
        ))
        for transaction, (_, money_in, choice, state_one_sided) in zip(
                rows_of(ledger, "a.csv"), checking_rows, strict=True):
            types = IN_TYPES if money_in else OUT_TYPES
            financial_type = types[choice % len(types)]
            if financial_type:
                ledger.classify_ok(transaction, financial_type)
            if state_one_sided and financial_type in COUNTERPART_BY_TYPE:
                ledger.one_sided_ok(transaction, COUNTERPART_BY_TYPE[financial_type])
        mirrors = sorted({choice % len(checking_rows) for choice in mirrored})
        if mirrors:
            ledger.card("s.csv", *(
                f"01/{2 + 3 * index:02d}/2026,SYNTHETIC SAVED {index},"
                + (f"{amount(cents)}," if money_in else f",{amount(cents)}")
                for index in mirrors for cents, money_in, _, _ in [checking_rows[index]]
            ), account="S")
        # Shows with --hypothesis-show-statistics that examples reach every outcome.
        for state, _ in ledger.one_sided_states():
            event(f"one-sided {state}")
        for account in (None, "A", "S", "Card", "Loan", "Invest"):
            assert_adds_to_movement(ledger, account)


class TestReadOnly:  # T2
    def test_totals_writes_nothing_and_changes_no_token(self, ledger):
        _, transaction = stated(ledger)
        dumped, token = ledger.dump(ALL_TABLES), ledger.transaction_revision(transaction)
        ledger.totals()
        assert ledger.dump(ALL_TABLES) == dumped
        assert ledger.transaction_revision(transaction) == token


class TestMatches:  # T3
    def test_both_sides_are_confirmed_including_an_unclassified_one(self, ledger):
        match, _, _ = matched(ledger)
        found = groups(ledger)
        assert found.confirmed_transfers_by_type == (
            ("transfer", GroupTotal(1, 5000, 0)), ("unclassified", GroupTotal(1, 0, 5000)))
        assert found.unconfirmed_transfer_kinds == found.unclassified == GroupTotal()
        assert groups(ledger, "S").confirmed_transfers_by_type == (
            ("unclassified", GroupTotal(1, 0, 5000)),)

        assert ledger.undo_match(match)[0] == 0
        found = groups(ledger)
        assert found.confirmed_transfers_by_type == ()
        assert found.unconfirmed_transfer_kinds == GroupTotal(1, 5000, 0)
        assert found.unclassified == GroupTotal(1, 0, 5000)


class TestOneSided:  # T4
    def test_applied_it_is_confirmed(self, ledger):
        stated(ledger)
        assert groups(ledger).confirmed_transfers_by_type == (("transfer", GroupTotal(1, 5000, 0)),)
        assert groups(ledger).unconfirmed_transfer_kinds == GroupTotal()

    def test_no_longer_applying_it_is_unconfirmed(self, ledger):
        stated(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        assert ledger.one_sided_states() == [("counterpart_found", ())]
        found = groups(ledger)
        assert found.confirmed_transfers_by_type == ()
        assert found.unconfirmed_transfer_kinds == GroupTotal(1, 5000, 0)

    def test_once_its_type_is_undone_it_is_unclassified(self, ledger):
        transaction = outflow(ledger, financial_type=None)
        classification = ledger.classify_ok(transaction, "transfer")
        ledger.one_sided_ok(transaction)
        assert ledger.undo_classification(classification)[0] == 0
        assert ledger.one_sided_states() == [("type_differs", ())]
        found = groups(ledger)
        assert found.confirmed_transfers_by_type == ()
        assert found.unclassified == GroupTotal(1, 5000, 0)


class TestCardPayments:  # T5
    def test_a_matched_payment_does_not_duplicate_the_purchase(self, ledger):
        ledger.card("shop.csv", PURCHASE_ON_THE_CARD, account="Card")
        ledger.classify_ok(holding(ledger, "shop.csv"), "purchase", account="Card")
        ledger.card("pay.csv", PAYMENT_ON_THE_CARD, account="Card")
        payment = outflow(ledger, financial_type="card_payment")
        ledger.match_ok(payment, holding(ledger, "pay.csv"), counterpart_account="Card")
        found = groups(ledger)
        assert found.spending == GroupTotal(1, 5000, 0)
        assert found.confirmed_transfers_by_type == (
            ("card_payment", GroupTotal(1, 5000, 0)), ("unclassified", GroupTotal(1, 0, 5000)))

    def test_a_one_sided_payment_is_out_of_spending_and_still_warns(self, ledger):
        stated(ledger, "Card", financial_type="card_payment")
        assert groups(ledger).spending == GroupTotal()
        assert "spending on that card is understated" in ledger.totals()


class TestSpendingAndIncome:  # T6
    def test_purchases_fees_and_interest_less_refunds(self, ledger):
        ledger.card("a.csv", "01/01/2026,SYNTHETIC SHOP,50.00,", "01/04/2026,SYNTHETIC FEE,2.00,",
                    "01/07/2026,SYNTHETIC INTEREST,3.00,", "01/10/2026,SYNTHETIC REFUND,,7.00",
                    "01/13/2026,SYNTHETIC PAY,,100.00")
        for transaction, financial_type in zip(
                rows_of(ledger, "a.csv"), ("purchase", "fee", "interest", "refund", "income"),
                strict=True):
            ledger.classify_ok(transaction, financial_type)
        assert ledger.income_section() == (
            "  Income: 1 transactions, 100.00\n"
            "  Spending: 4 transactions, 48.00\n"
            "    purchase: 1 transactions, 50.00\n"
            "    refund: 1 transactions, -7.00\n"
            "    fee: 1 transactions, 2.00\n"
            "    interest: 1 transactions, 3.00\n"
            "  Confirmed transfers: 0 transactions, 0.00 out and 0.00 in\n"
            "  Of a transfer kind, not confirmed: 0 transactions, 0.00 out and 0.00 in\n"
            "  Unclassified: 0 transactions, 0.00 out and 0.00 in\n"
        )

    def test_a_refund_larger_than_the_purchases_is_negative_spending(self, ledger):
        ledger.card("a.csv", "01/10/2026,SYNTHETIC REFUND,,60.00")
        ledger.classify_ok(holding(ledger, "a.csv"), "refund")
        assert "  Spending: 1 transactions, -60.00\n" in ledger.income_section()

    def test_a_transfer_in_is_not_income(self, ledger):
        ledger.card("a.csv", "01/10/2026,SYNTHETIC MOVE IN,,60.00")
        ledger.classify_ok(holding(ledger, "a.csv"), "transfer")
        assert groups(ledger).income == GroupTotal()
        assert groups(ledger).unconfirmed_transfer_kinds == GroupTotal(1, 0, 6000)


class TestDisclosure:  # T7
    def test_it_bounds_both_exactly(self, ledger):
        outflow(ledger)
        ledger.card("a.csv", "02/10/2026,SYNTHETIC ODD,,20.00",
                    "02/20/2026,SYNTHETIC GROCER,9.00,")
        assert "- Income and spending count only what you classified, and leave out transfers you " \
               "confirmed. Spending may be understated by up to 59.00 and income by up to 20.00, " \
               "the money out and in of transactions of a transfer kind not confirmed and of " \
               "unclassified transactions.\n" in ledger.totals()

    def test_none_once_everything_is_classified_or_confirmed(self, ledger):
        stated(ledger)
        assert "Income and spending count only" not in ledger.totals()


class TestConfirmedByType:  # T8
    def test_each_kind_on_its_own_line_apart_from_spending(self, ledger):
        for name, row, financial_type, counterpart in (
                ("card.csv", "01/10/2026,SYNTHETIC CARD,50.00,", "card_payment", "Card"),
                ("loan.csv", "01/20/2026,SYNTHETIC LOAN,40.00,", "loan_payment", "Loan"),
                ("invest.csv", "01/30/2026,SYNTHETIC FUND,30.00,", "investment_contribution",
                 "Invest")):
            ledger.card(name, row)
            transaction = holding(ledger, name)
            ledger.classify_ok(transaction, financial_type)
            ledger.one_sided_ok(transaction, counterpart)
        assert ledger.income_section() == (
            "  Income: 0 transactions, 0.00\n"
            "  Spending: 0 transactions, 0.00\n"
            "  Confirmed transfers: 3 transactions, 120.00 out and 0.00 in\n"
            "    card_payment: 1 transactions, 50.00 out and 0.00 in\n"
            "    loan_payment: 1 transactions, 40.00 out and 0.00 in\n"
            "    investment_contribution: 1 transactions, 30.00 out and 0.00 in\n"
            "  Of a transfer kind, not confirmed: 0 transactions, 0.00 out and 0.00 in\n"
            "  Unclassified: 0 transactions, 0.00 out and 0.00 in\n"
        )


class TestLoanPayments:  # T9
    WARNING = ("1 loan payments, 40.00, go to a loan whose interest for those dates is not in the "
               "ledger, so spending on interest is understated.")

    def test_a_payment_to_a_loan_with_no_history_warns(self, ledger):
        ledger.card("loan.csv", "01/20/2026,SYNTHETIC LOAN,40.00,")
        transaction = holding(ledger, "loan.csv")
        ledger.classify_ok(transaction, "loan_payment")
        ledger.one_sided_ok(transaction, "Loan")
        assert self.WARNING in ledger.totals()
        assert self.WARNING in ledger.run("totals", "--account", "Loan")[1]

    def test_a_payment_received_on_the_loan_does_not_warn(self, ledger):
        ledger.card("loan.csv", "01/20/2026,SYNTHETIC PAYMENT,,40.00", account="Loan")
        transaction = holding(ledger, "loan.csv")
        ledger.classify_ok(transaction, "loan_payment", account="Loan")
        ledger.one_sided_ok(transaction, "A", account="Loan")
        assert "loan payments" not in ledger.totals()


class TestBrokenFit:  # T10
    def test_a_confirmed_side_of_another_type_stops_the_report(self, ledger):
        _, transaction = stated(ledger)
        conn = ledger.conn()
        conn.execute("UPDATE transaction_classification SET financial_type = 'purchase' "
                     "WHERE transaction_id = ?", (transaction,))
        conn.close()
        code, out, err = ledger.run("totals")
        assert code == 2
        assert out == ""
        assert "an unexpected problem stopped this command" in err
