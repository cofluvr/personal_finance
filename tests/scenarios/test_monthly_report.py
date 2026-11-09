"""Monthly reports with disclosures, end to end, using synthetic data only (D-013, D-057)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_classifications import disagreeing_after_undo as classifications_disagreeing
from test_confirmations import confirm_ok
from test_corrections import disagreeing_after_undo as corrections_disagreeing
from test_corrections import merged_by_id_then_split
from test_decisions import ALL_TABLES, CHECKING_HEADER, declared, pair_up
from test_one_sided_transfers import OneSidedLedger, stated
from test_pending_posted import PENDING, POSTED
from test_resolutions import CAFE_NO_AMOUNT
from test_supersession import holding
from test_transfers import IN_ROW, rows_of

from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.totals import GroupTotal, account_movement, income_and_spending


class MonthlyLedger(OneSidedLedger):
    def report(self, *options):
        code, out, err = self.run("report", "monthly", *options)
        assert code == 0, err
        return out

    def months(self, account=None, first_month=None, last_month=None):
        conn = self.conn()
        found = monthly_report(conn, self.account_id(account) if account else None,
                               first_month, last_month)
        conn.close()
        return found

    def month(self, month, account=None):
        (found,) = [report for report in self.months(account).months if report.month == month]
        return found

    def rows(self, name, *rows, account="A", extra=()):
        return self.load_path(self.write(name, CHECKING_HEADER, rows), *extra, account=account,
                              layout="synthetic_checking_v1")


@pytest.fixture
def ledger(tmp_path, capsys):
    return build(tmp_path, capsys)


def build(folder, capsys):
    """Checking A, savings S, and a card never imported."""
    found = MonthlyLedger(folder, capsys)
    found.add_account("S", "savings")
    found.add_account("Card", "credit_card")
    return found


def group_totals(groups) -> dict:
    """Every non-empty group of one IncomeAndSpending, keyed by group and type."""
    found = {("income",): groups.income, ("unconfirmed",): groups.unconfirmed_transfer_kinds,
             ("unclassified",): groups.unclassified}
    found.update({("spending", kind): group for kind, group in groups.spending_by_type})
    found.update({("confirmed", kind): group for kind, group in groups.confirmed_transfers_by_type})
    return {key: group for key, group in found.items() if group != GroupTotal()}


def added(dictionaries) -> dict:
    found = {}
    for dictionary in dictionaries:
        for key, group in dictionary.items():
            before = found.get(key, GroupTotal())
            found[key] = GroupTotal(before.transactions + group.transactions,
                                    before.out_cents + group.out_cents,
                                    before.in_cents + group.in_cents)
    return found


def assert_months_add_to_totals(ledger, account=None):
    conn = ledger.conn()
    account_id = ledger.account_id(account) if account else None
    movement = account_movement(conn, account_id)
    expected_groups = group_totals(income_and_spending(conn, account_id))
    conn.close()
    report = ledger.months(account)
    assert report.transactions_outside_range == 0
    assert sum(month.transactions for month in report.months) == movement.transactions
    assert sum(month.net_cents for month in report.months) == movement.net_cents
    assert sum(month.pending_transactions for month in report.months) == \
        movement.pending_transactions
    assert added(group_totals(month.income_and_spending) for month in report.months) == \
        expected_groups
    for month in report.months:  # G3
        parts = group_totals(month.income_and_spending).values()
        assert sum(group.transactions for group in parts) == month.transactions
        assert sum(group.in_cents - group.out_cents for group in parts) == month.net_cents
        assert month.dated_by_transaction_date + month.dated_by_posting_date == month.transactions


def amount(cents):
    return f"{cents // 100}.{cents % 100:02d}"


OUT_TYPES = (None, "purchase", "fee", "transfer")
IN_TYPES = (None, "refund", "income", "transfer")
rows = st.lists(
    st.tuples(st.integers(1, 9999), st.booleans(), st.integers(0, 3), st.integers(1, 89),
              st.sampled_from(("both", "transaction", "posting")), st.integers(0, 4),
              st.sampled_from(("POSTED", "PENDING", ""))),
    min_size=1, max_size=8,
)


def generated_ledger(folder, capsys, checking_rows, savings_days, one_sided):
    """Rows of A over three months, with either date or both, a posting date up to four days
    later, random types and status, and card rows in S. Also used by the local UI's tests."""
    ledger = build(folder, capsys)
    lines = []
    for index, (cents, money_in, _, day, dates, lag, status) in enumerate(checking_rows):
        transaction_day = f"2026-{1 + (day - 1) // 30:02d}-{1 + (day - 1) % 30 % 28:02d}"
        posting_day = transaction_day[:8] + f"{min(int(transaction_day[8:]) + lag, 28):02d}"
        if status == "PENDING":
            dates = "transaction"
        lines.append(",".join((
            f"R{index}", transaction_day if dates != "posting" else "",
            posting_day if dates != "transaction" else "", f"SYNTHETIC ROW {index}",
            amount(cents) if money_in else f"-{amount(cents)}", status)))
    ledger.rows("a.csv", *lines)
    transferred = None
    for transaction, (_, money_in, choice, *_) in zip(rows_of(ledger, "a.csv"),
                                                      checking_rows, strict=True):
        types = IN_TYPES if money_in else OUT_TYPES
        if types[choice]:
            ledger.classify_ok(transaction, types[choice])
        if types[choice] == "transfer":
            transferred = transaction
    if one_sided and transferred:
        ledger.one_sided_ok(transferred, "S")
    if savings_days:
        ledger.card("s.csv", *(
            f"{1 + (day - 1) // 30:02d}/{1 + (day - 1) % 30 % 28:02d}/2026,SYNTHETIC SAVED "
            f"{index},,1.00" for index, day in enumerate(savings_days)), account="S")
    return ledger


@settings(max_examples=40, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(checking_rows=rows, savings_days=st.lists(st.integers(1, 89), max_size=4),
       one_sided=st.booleans())
def test_every_transaction_is_in_one_month_and_the_months_add_to_totals(  # G1, G3
        capsys, checking_rows, savings_days, one_sided):
    with tempfile.TemporaryDirectory() as folder:
        ledger = generated_ledger(Path(folder), capsys, checking_rows, savings_days, one_sided)
        for account in (None, "A", "S", "Card"):
            assert_months_add_to_totals(ledger, account)
        # A range keeps every transaction, in its months or outside them.
        ranged = ledger.months(None, "2026-02", "2026-02")
        conn = ledger.conn()
        movement = account_movement(conn)
        conn.close()
        (february,) = ranged.months
        assert february.transactions + ranged.transactions_outside_range == movement.transactions
        assert february.net_cents + ranged.net_cents_outside_range == movement.net_cents


class TestMonths:  # G1, G2, G3
    def test_months_run_first_to_last_with_empty_months_between(self, ledger):
        ledger.rows("a.csv", "X1,2026-01-05,2026-01-06,SYNTHETIC SHOP,-1.00,POSTED",
                    "X2,2026-03-05,2026-03-06,SYNTHETIC SHOP,-2.00,POSTED")
        report = ledger.months()
        assert [(month.month, month.transactions, month.net_cents) for month in report.months] \
            == [("2026-01", 1, -100), ("2026-02", 0, 0), ("2026-03", 1, -200)]
        assert "2026-02: net account movement 0.00 over 0 transactions, of which pending: 0\n" \
            in ledger.report()

    def test_no_transactions_has_no_months(self, ledger):
        assert ledger.months().months == ()
        assert "No transactions, so there are no months to show.\n" in ledger.report()

    def test_the_transaction_date_decides_else_the_posting_date(self, ledger):
        ledger.rows("a.csv", "X1,2026-01-31,2026-02-02,SYNTHETIC LATE,-1.00,POSTED",
                    "X2,,2026-02-03,SYNTHETIC POSTED ONLY,-2.00,POSTED")
        ledger.card("card.csv", "02/28/2026,SYNTHETIC CARD,4.00,")
        january, february = ledger.months().months
        assert (january.transactions, january.dated_by_transaction_date,
                january.dated_by_posting_date) == (1, 1, 0)
        assert (february.transactions, february.dated_by_transaction_date,
                february.dated_by_posting_date) == (2, 0, 2)
        assert "  Dated by transaction date: 0, by posting date: 2\n" in ledger.report()

    def test_a_date_correction_moves_it_and_its_undo_moves_it_back(self, ledger):
        ledger.rows("a.csv", "X1,2026-01-31,2026-02-02,SYNTHETIC LATE,-1.00,POSTED")
        transaction = holding(ledger, "a.csv")
        correction = ledger.correct_ok(transaction, "transaction_date", "2026-02-01")
        assert [(month.month, month.transactions) for month in ledger.months().months] == \
            [("2026-02", 1)]
        assert ledger.undo_correction(correction)[0] == 0
        assert [(month.month, month.transactions) for month in ledger.months().months] == \
            [("2026-01", 1)]

    def test_a_posting_date_correction_moves_a_transaction_without_a_transaction_date(self,
                                                                                    ledger):
        ledger.card("card.csv", "01/31/2026,SYNTHETIC CARD,4.00,")
        ledger.correct_ok(holding(ledger, "card.csv"), "posting_date", "2026-02-01")
        assert [(month.month, month.dated_by_posting_date)
                for month in ledger.months().months] == [("2026-02", 1)]

    def test_an_amount_correction_is_the_effective_amount(self, ledger):
        ledger.card("card.csv", "01/10/2026,SYNTHETIC CARD,4.00,")
        ledger.correct_ok(holding(ledger, "card.csv"), "amount", "-6.00")
        assert ledger.month("2026-01").net_cents == -600

    def test_groups_add_to_movement_within_each_month(self, ledger):
        ledger.rows("a.csv", "X1,2026-01-05,2026-01-06,SYNTHETIC PAY,100.00,POSTED",
                    "X2,2026-01-07,2026-01-08,SYNTHETIC SHOP,-30.00,POSTED",
                    "X3,2026-02-07,,SYNTHETIC PENDING,-5.00,PENDING")
        income, purchase, _ = rows_of(ledger, "a.csv")
        ledger.classify_ok(income, "income")
        ledger.classify_ok(purchase, "purchase")
        january, february = ledger.months().months
        assert group_totals(january.income_and_spending) == {
            ("income",): GroupTotal(1, 0, 10000), ("spending", "purchase"): GroupTotal(1, 3000, 0)}
        assert (february.pending_transactions, february.net_cents) == (1, -500)
        assert_months_add_to_totals(ledger)
        out = ledger.report()
        assert "2026-01: net account movement 70.00 over 2 transactions, of which pending: 0\n" \
               "  Dated by transaction date: 2, by posting date: 0\n" \
               "  Income: 1 transactions, 100.00\n" \
               "  Spending: 1 transactions, 30.00\n" \
               "    purchase: 1 transactions, 30.00\n" in out

    def test_one_account(self, ledger):
        ledger.rows("a.csv", "X1,2026-01-05,2026-01-06,SYNTHETIC SHOP,-1.00,POSTED")
        ledger.card("s.csv", "03/01/2026,SYNTHETIC SAVED,,2.00", account="S")
        assert [month.month for month in ledger.months("S").months] == ["2026-03"]
        assert [month.month for month in ledger.months().months] == \
            ["2026-01", "2026-02", "2026-03"]
        assert_months_add_to_totals(ledger, "S")
        assert ledger.report("--account", "S").startswith(
            "2026-03: net account movement 2.00 over 1 transactions")

    def test_the_schema_refuses_a_transaction_with_no_date(self, ledger):
        ledger.card("card.csv", "01/10/2026,SYNTHETIC CARD,4.00,")
        conn = ledger.conn()
        # Migration 0001 refuses it, so only a ledger without that check could hold one.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE ledger_transaction SET posting_date = NULL")
        conn.close()


def transaction_basis(start, end):
    return ["--declare-complete-coverage", "--coverage-start", start, "--coverage-end", end,
            "--coverage-basis", "transaction"]


class TestCoverage:  # G4
    def covered(self, ledger, *coverage):
        for number, extra in enumerate(coverage):
            ledger.rows(f"cover{number}.csv",
                        f"C{number},2026-02-10,2026-02-10,SYNTHETIC SHOP {number},-1.00,POSTED",
                        extra=extra)
        february = ledger.month("2026-02")
        assert set(february.accounts_covered) | set(february.accounts_not_covered) == \
            {"A", "S", "Card"}
        return "A" in february.accounts_covered

    def test_transaction_basis_spanning_every_day_covers_it(self, ledger):
        assert self.covered(ledger, transaction_basis("2026-02-01", "2026-02-28"))
        out = ledger.report()
        assert "  Covered for the whole month: A\n" \
               "  Not covered for the whole month: Card, S\n" in out

    def test_two_spans_meeting_cover_it(self, ledger):
        assert self.covered(ledger, transaction_basis("2026-02-01", "2026-02-14"),
                            transaction_basis("2026-02-15", "2026-02-28"))

    @pytest.mark.parametrize("coverage", [
        [transaction_basis("2026-02-02", "2026-02-28")],
        [transaction_basis("2026-02-01", "2026-02-27")],
        [transaction_basis("2026-02-01", "2026-02-13"), transaction_basis("2026-02-15",
                                                                         "2026-02-28")],
        [declared("2026-01-01", "2026-03-31")],
        [()],
    ])
    def test_a_gap_at_an_edge_or_inside_or_posting_basis_does_not(self, ledger, coverage):
        assert not self.covered(ledger, *coverage)

    def test_one_account_lists_only_that_account(self, ledger):
        ledger.rows("a.csv", "X1,2026-02-10,2026-02-10,SYNTHETIC SHOP,-1.00,POSTED",
                    extra=transaction_basis("2026-02-01", "2026-02-28"))
        (february,) = ledger.months("A").months
        assert (february.accounts_covered, february.accounts_not_covered) == (("A",), ())


class TestDisclosures:  # G5
    def test_open_review_items_in_the_month_of_their_transactions(self, ledger):
        pair_up(ledger)
        ledger.rows("a.csv", "X1,2026-02-05,2026-02-06,SYNTHETIC SHOP,-1.00,POSTED")
        january, february = ledger.months().months
        assert (len(january.open_review_items), january.transactions_in_open_review_items) == \
            (1, 2)
        assert february.open_review_items == set()
        assert "  Open review items: 1, holding 2 transactions here\n" in ledger.report()

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
        assert ledger.month("2026-01").open_review_items == set()
        assert "Open review items" not in ledger.report()

    def test_unsettled_corrections(self, ledger):
        corrections_disagreeing(ledger)
        assert ledger.month("2026-01").transactions_with_unsettled_correction == 1
        assert "  With an unsettled correction: 1 transactions\n" in ledger.report()

    def test_corrections_whose_basis_changed(self, ledger):
        merged_by_id_then_split(ledger)
        assert ledger.month("2026-01").transactions_with_unsettled_correction == 2

    def test_unsettled_classifications(self, ledger):
        classifications_disagreeing(ledger)
        assert ledger.month("2026-01").transactions_with_unsettled_classification == 1
        assert "  With an unsettled classification: 1 transactions\n" in ledger.report()

    def test_a_match_that_no_longer_applies(self, ledger):
        ledger.card("out.csv", "01/30/2026,SYNTHETIC MOVE OUT,6.50,")
        ledger.card("in.csv", "02/01/2026,SYNTHETIC MOVE IN,,50.00", account="S")
        outflow, inflow = holding(ledger, "out.csv"), holding(ledger, "in.csv")
        correction = ledger.correct_ok(outflow, "amount", "-50.00")
        ledger.classify_ok(outflow, "transfer")
        ledger.match_ok(outflow, inflow)
        assert ledger.undo_correction(correction)[0] == 0
        january, february = ledger.months().months
        assert (january.transactions_with_unsettled_match,
                february.transactions_with_unsettled_match) == (1, 1)
        assert ledger.months("S").months[0].transactions_with_unsettled_match == 1
        assert january.matched_sides_with_other_side_in_another_month == 0
        assert "  With a transfer match that no longer applies: 1 transactions\n" in \
            ledger.report()

    def test_a_one_sided_transfer_that_no_longer_applies(self, ledger):
        stated(ledger)
        ledger.card("in.csv", IN_ROW, account="S")
        assert ledger.month("2026-01").transactions_with_unsettled_one_sided_transfer == 1
        assert ledger.month("2026-01", "S").transactions_with_unsettled_one_sided_transfer == 0
        assert "  With a one-sided transfer that no longer applies: 1 transactions\n" in \
            ledger.report()

    def test_applied_ones_are_not_disclosed_as_unsettled(self, ledger):
        stated(ledger)
        january = ledger.month("2026-01")
        assert (january.transactions_with_unsettled_one_sided_transfer,
                january.transactions_with_unsettled_classification) == (0, 0)
        assert "With a" not in ledger.report()

    def test_unresolved_records_are_disclosed_once(self, ledger):
        ledger.card("blank.csv", CAFE_NO_AMOUNT)
        ledger.card("card.csv", "01/10/2026,SYNTHETIC CARD,4.00,")
        assert ledger.months().unresolved_records == 1
        assert "- 1 unresolved records are no transaction, so no month counts them, and their " \
               "amounts may be unknown.\n" in ledger.report()


def matched_across(ledger, out_day="01/30/2026", in_day="02/02/2026"):
    ledger.card("out.csv", f"{out_day},SYNTHETIC MOVE OUT,50.00,")
    ledger.card("in.csv", f"{in_day},SYNTHETIC MOVE IN,,50.00", account="S")
    outflow, inflow = holding(ledger, "out.csv"), holding(ledger, "in.csv")
    ledger.classify_ok(outflow, "transfer")
    return ledger.match_ok(outflow, inflow)


class TestCrossMonthMatches:  # G6
    def test_each_side_counts_in_its_month_and_is_disclosed(self, ledger):
        match = matched_across(ledger)
        january, february = ledger.months().months
        assert (january.net_cents, february.net_cents) == (-5000, 5000)
        assert group_totals(january.income_and_spending) == {
            ("confirmed", "transfer"): GroupTotal(1, 5000, 0)}
        assert group_totals(february.income_and_spending) == {
            ("confirmed", "unclassified"): GroupTotal(1, 0, 5000)}
        assert (january.matched_sides_with_other_side_in_another_month,
                february.matched_sides_with_other_side_in_another_month) == (1, 1)
        assert ledger.months("S").months[0].matched_sides_with_other_side_in_another_month == 1
        # The side in A is outside S's report even when its month is shown there.
        january, february = ledger.months("S", "2026-01").months
        assert (january.matched_sides_with_other_side_in_another_month,
                february.matched_sides_with_other_side_in_another_month) == (0, 1)
        assert "  Matched transfers whose other side is in another month: 1, so this month's " \
               "movement includes them\n" in ledger.report()
        assert ledger.undo_match(match)[0] == 0
        assert all(month.matched_sides_with_other_side_in_another_month == 0
                   for month in ledger.months().months)

    def test_a_match_within_one_month_is_not(self, ledger):
        matched_across(ledger, "01/10/2026", "01/12/2026")
        (january,) = ledger.months().months
        assert january.matched_sides_with_other_side_in_another_month == 0
        assert january.net_cents == 0


class TestRange:  # G7
    def built(self, ledger):
        ledger.rows("a.csv", "X1,2026-01-05,2026-01-06,SYNTHETIC SHOP,-1.00,POSTED",
                    "X2,2026-03-05,2026-03-06,SYNTHETIC SHOP,-2.00,POSTED",
                    "X3,2026-04-05,2026-04-06,SYNTHETIC SHOP,-4.00,POSTED")

    def test_from_and_to_are_inclusive(self, ledger):
        self.built(ledger)
        report = ledger.months(None, "2026-02", "2026-03")
        assert [(month.month, month.transactions) for month in report.months] == \
            [("2026-02", 0), ("2026-03", 1)]
        assert (report.transactions_outside_range, report.net_cents_outside_range) == (2, -500)
        out = ledger.report("--from", "2026-02", "--to", "2026-03")
        assert out.startswith("2026-02: ")
        assert "\n2026-04" not in out
        assert "- 2 transactions, -5.00, are in months outside this range.\n" in out

    def test_one_month(self, ledger):
        self.built(ledger)
        assert [month.month for month in ledger.months(None, "2026-03", "2026-03").months] == \
            ["2026-03"]
        assert ledger.report("--from", "2026-03", "--to", "2026-03").startswith(
            "2026-03: net account movement -2.00 over 1 transactions")

    def test_either_end_alone(self, ledger):
        self.built(ledger)
        assert [month.month for month in ledger.months(None, "2026-03").months] == \
            ["2026-03", "2026-04"]
        assert [month.month for month in ledger.months(None, None, "2026-01").months] == \
            ["2026-01"]
        assert [month.month for month in ledger.months(None, "2026-06").months] == ["2026-06"]
        assert [month.month for month in ledger.months(None, None, "2025-11").months] == \
            ["2025-11"]

    def test_a_range_shows_its_months_on_an_empty_ledger(self, ledger):
        assert [month.month for month in ledger.months(None, "2025-12", "2026-01").months] == \
            ["2025-12", "2026-01"]

    def test_a_year_boundary(self, ledger):
        assert [month.month for month in ledger.months(None, "2025-11", "2026-02").months] == \
            ["2025-11", "2025-12", "2026-01", "2026-02"]

    @pytest.mark.parametrize("words", [
        ["--from", "2026-13"], ["--from", "2026-00"], ["--to", "2026-1"], ["--to", "26-01"],
        ["--from", "2026-01-01"], ["--from", " 2026-01"], ["--to", "0000-12"],
    ])
    def test_an_invalid_month_is_refused(self, ledger, words):
        code, out, err = ledger.run("report", "monthly", *words)
        assert (code, out) == (2, "")
        assert err == f"Error: {words[0]} must be a month as YYYY-MM. Nothing was changed.\n"

    def test_a_reversed_range_is_refused(self, ledger):
        assert ledger.run("report", "monthly", "--from", "2026-03", "--to", "2026-02") == \
            (2, "", "Error: --from is after --to. Nothing was changed.\n")

    def test_an_unknown_account_is_refused(self, ledger):
        assert ledger.run("report", "monthly", "--account", "Nope") == \
            (2, "", "Error: account not found: Nope\n")


class TestReadOnly:  # G7
    def test_it_writes_nothing_and_totals_is_unchanged(self, ledger):
        statement, transaction = stated(ledger)
        pair_up(ledger)
        dumped, totals = ledger.dump(ALL_TABLES), ledger.totals()
        token = ledger.transaction_revision(transaction)
        ledger.report()
        ledger.report("--account", "A", "--from", "2026-01", "--to", "2026-02")
        assert ledger.dump(ALL_TABLES) == dumped
        assert ledger.totals() == totals
        assert ledger.transaction_revision(transaction) == token

    def test_account_names_are_escaped(self, ledger):
        ledger.add_account("Odd\nName", "savings")
        ledger.card("card.csv", "01/10/2026,SYNTHETIC CARD,4.00,")
        out = ledger.report()
        assert "Odd\nName" not in out
        assert "  Not covered for the whole month: A, Card, Odd\\nName, S\n" in out
