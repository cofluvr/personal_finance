"""A consumption's portion and the assignments it reduces, by hand (GB2, D-070 point 5), and a
member's part of it in report budget (G8)."""

from personal_finance.planning.funds import (
    Assignment,
    ConsumedTransaction,
    consumed_portions,
    reductions_as_of,
)
from personal_finance.reports.budget_report import member_part_paid

NAMES = {"checking": "Checking", "savings": "Savings", "other": "Brokerage"}


def assignment(assignment_id, account, cents, made="2026-03-01T00:00:00.000Z", undone=None,
               fund="f"):
    return Assignment(assignment_id, fund, account, cents, made, undone)


def consumed(transaction, cents, day="2026-03-10", account="checking",
             stated="2026-03-20T00:00:00.000Z", fund="f"):
    return ConsumedTransaction(transaction, account, fund, day, cents, stated)


def portions(items, assignments):
    return {portion.consumed.transaction_id: (portion.consumed_cents, portion.reductions)
            for portion in consumed_portions(items, assignments, NAMES)}


def test_a_purchase_takes_at_most_what_is_assigned():
    rows = [assignment("s", "savings", 60_000)]
    assert portions([consumed("t", 85_000)], rows) == {"t": (60_000, (("s", 60_000),))}
    assert portions([consumed("t", 20_000)], rows) == {"t": (20_000, (("s", 20_000),))}


def test_the_own_account_first_then_the_others_by_name():
    rows = [assignment("s", "savings", 50_000), assignment("o", "other", 10_000),
            assignment("c", "checking", 30_000)]
    assert portions([consumed("t", 85_000)], rows) == {
        "t": (85_000, (("c", 30_000), ("o", 10_000), ("s", 45_000)))}


def test_later_purchases_take_what_earlier_ones_left_in_date_order():
    rows = [assignment("s", "savings", 60_000)]
    found = portions([consumed("late", 40_000, day="2026-03-12"),
                      consumed("early", 40_000, day="2026-03-11")], rows)
    assert found == {"early": (40_000, (("s", 40_000),)), "late": (20_000, (("s", 20_000),))}


def test_a_refund_restores_up_to_what_was_taken():
    rows = [assignment("s", "savings", 60_000)]
    found = portions([consumed("buy", 30_000, day="2026-03-10"),
                      consumed("back", -50_000, day="2026-03-11")], rows)
    assert found["back"] == (-30_000, (("s", -30_000),))


def test_only_assignments_active_when_it_was_stated():
    rows = [assignment("before", "savings", 10_000),
            assignment("after", "savings", 50_000, made="2026-03-21T00:00:00.000Z"),
            assignment("released", "savings", 50_000, undone="2026-03-19T00:00:00.000Z")]
    assert portions([consumed("t", 85_000)], rows) == {"t": (10_000, (("before", 10_000),))}


def test_another_fund_s_assignments_are_never_taken():
    rows = [assignment("s", "savings", 60_000, fund="g")]
    assert portions([consumed("t", 85_000)], rows) == {"t": (0, ())}


def test_reductions_count_only_what_is_dated_by_as_of():
    rows = [assignment("s", "savings", 60_000)]
    found = consumed_portions([consumed("t", 20_000, day="2026-03-10")], rows, NAMES)
    assert reductions_as_of(found, "2026-03-09") == {}
    assert reductions_as_of(found, "2026-03-10") == {"s": 20_000}


def test_a_member_s_part_of_what_was_paid_rounds_toward_zero():
    # 0.03 paid of a 0.03 purchase, the member's part 0.02: exactly 0.02.
    assert member_part_paid(3, 2, 3) == 2
    # 0.05 paid of a 0.10 purchase, the member's part 0.03: 0.015, rounded to 0.01.
    assert member_part_paid(5, 3, 10) == 1
    assert member_part_paid(-5, -3, -10) == -1
    assert member_part_paid(0, 3, 10) == 0
