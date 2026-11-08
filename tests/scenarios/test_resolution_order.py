"""Equivalent resolutions made at different points in the import sequence (U14, D-050).

Exhaustive rather than a property test: every order of four files, and every point after the
resolved record's file arrives. A resolution binds one source record, so unlike a correction
(D-049) nothing it binds depends on when it was made.
"""

from itertools import permutations

import pytest
import test_resolutions
from test_decisions import CARD_HEADER, WHOLE_MONTH

# Fixed bytes per file, whatever the order. a holds the purchase and a row the parser cannot read,
# which blocks confident pairing for a. b and d repeat the purchase under the same complete
# coverage, so all three merge once a's row stops blocking. c is unrelated.
FILES = {
    "a.csv": CARD_HEADER + "01/10/2026,SYNTHETIC CAFE,6.50,\nnot a row of this layout\n",
    "b.csv": CARD_HEADER + " 01/10/2026,SYNTHETIC CAFE,6.50,\n",
    "c.csv": CARD_HEADER + "02/01/2026,SYNTHETIC GROCER,9.00,\n",
    "d.csv": CARD_HEADER + "  01/10/2026,SYNTHETIC CAFE,6.50,\n",
}
GROCER_VALUES = {"amount": "-9.00", "posting_date": "2026-01-15", "description": "SYNTHETIC GROCER"}


def built(folder, capsys, order, point, kind):
    folder.mkdir()
    ledger = test_resolutions.ResolutionLedger(folder, capsys)
    for position, name in enumerate(order, start=1):
        path = folder / name
        path.write_text(FILES[name])
        ledger.load_path(path, *WHOLE_MONTH)
        if position == point:
            (item,) = ledger.unresolved()
            if kind == "dismissed":
                ledger.dismiss_ok(item)
            else:
                ledger.complete_ok(item, **GROCER_VALUES)
    return ledger


@pytest.mark.parametrize("kind", ["dismissed", "completed"])
def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys, kind):
    reference = None
    compared = 0
    for order in permutations(FILES):
        first_valid = order.index("a.csv") + 1
        for point in range(first_valid, len(order) + 1):
            ledger = built(tmp_path / f"case{compared}", capsys, order, point, kind)
            found = ledger.view()
            reference = reference or found
            assert found == reference, (order, point)
            compared += 1

    # a sits at each of the four positions in 6 orders, leaving 4, 3, 2 or 1 valid points.
    assert compared == 6 * (4 + 3 + 2 + 1) == 60
    movement = reference["movement"]
    completed_cents = -900 if kind == "completed" else 0
    assert movement.net_cents == -650 - 900 + completed_cents
    assert movement.unresolved_records == 0
    assert movement.transactions == (3 if kind == "completed" else 2)
