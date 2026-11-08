"""Equivalent corrections made at different points in the import sequence (V14, D-049).

Exhaustive rather than a property test: every order of four files, and every point after the
corrected record's file arrives.
"""

from itertools import permutations

import test_corrections
from test_decisions import CARD_HEADER, CHECKING_HEADER
from test_supersession import holding

# Fixed bytes per file, whatever the order. b repeats a's row with a reliable ID, so the two merge.
# c is unrelated, and d is an ID-less lookalike that only raises a possible duplicate.
CAFE_WITH_ID = "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED\n"
FILES = {
    "a.csv": ("synthetic_checking_v1", CHECKING_HEADER + CAFE_WITH_ID),
    "b.csv": ("synthetic_checking_v1", CHECKING_HEADER + " " + CAFE_WITH_ID),
    "c.csv": ("synthetic_checking_v1",
              CHECKING_HEADER + "S-2,2026-02-01,2026-02-02,SYNTHETIC GROCER,-9.00,POSTED\n"),
    "d.csv": ("synthetic_card_v1", CARD_HEADER + "01/10/2026,SYNTHETIC CAFE,5.00,\n"),
}


def outcome(ledger):
    """Everything but revisions, which cover the bound records and so differ by design."""
    view = ledger.view()
    del view["revisions"]
    return view, ledger.field_states()


def built(folder, capsys, order, point):
    """Imports in this order, correcting a's event to 4.00 out after the first point imports."""
    folder.mkdir()
    ledger = test_corrections.CorrectionLedger(folder, capsys)
    correction = None
    for position, name in enumerate(order, start=1):
        layout, content = FILES[name]
        path = folder / name
        path.write_text(content)
        ledger.load_path(path, layout=layout)
        if position == point:
            correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-4.00")
    return ledger, correction


def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys):
    reference = None
    compared = 0
    for order in permutations(FILES):
        first_valid = order.index("a.csv") + 1
        for point in range(first_valid, len(order) + 1):
            ledger, correction = built(tmp_path / f"case{compared}", capsys, order, point)
            found = outcome(ledger)
            reference = reference or found
            assert found == reference, (order, point)

            # Records arriving after the correction are never bound by it.
            b_before = order.index("b.csv") + 1 <= point
            expected = ["a.csv", "b.csv"] if b_before else ["a.csv"]
            assert ledger.bound_files(correction) == expected, (order, point)
            compared += 1

    # a sits at each of the four positions in 6 orders, leaving 4, 3, 2 or 1 valid points.
    assert compared == 6 * (4 + 3 + 2 + 1) == 60
    view, states = reference
    assert states == [(("a.csv", "b.csv"), "amount", "applied")]
    assert view["movement"].net_cents == -400 - 900 - 500
    assert view["movement"].candidate_groups == 1
