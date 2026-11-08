"""Equivalent coverage declarations made at different points in the import sequence (K12, D-051).

Exhaustive rather than a property test: every order of four files, and every point after the
declared document arrives.
"""

from itertools import permutations

import test_coverage_declarations
from test_decisions import CARD_HEADER, WHOLE_MONTH

# Fixed bytes per file, whatever the order. a holds the purchase with unknown coverage until it is
# declared complete. b and d repeat it under complete coverage, so all three merge once a is
# declared. c is unrelated.
FILES = {
    "a.csv": (CARD_HEADER + "01/10/2026,SYNTHETIC CAFE,6.50,\n", ()),
    "b.csv": (CARD_HEADER + " 01/10/2026,SYNTHETIC CAFE,6.50,\n", WHOLE_MONTH),
    "c.csv": (CARD_HEADER + "02/01/2026,SYNTHETIC GROCER,9.00,\n", ()),
    "d.csv": (CARD_HEADER + "  01/10/2026,SYNTHETIC CAFE,6.50,\n", WHOLE_MONTH),
}


def built(folder, capsys, order, point):
    folder.mkdir()
    ledger = test_coverage_declarations.CoverageLedger(folder, capsys)
    for position, name in enumerate(order, start=1):
        content, coverage = FILES[name]
        path = folder / name
        path.write_text(content)
        ledger.load_path(path, *coverage)
        if position == point:
            ledger.declare_ok("a.csv", **test_coverage_declarations.MONTH)
    return ledger


def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys):
    reference = None
    compared = 0
    for order in permutations(FILES):
        first_valid = order.index("a.csv") + 1
        for point in range(first_valid, len(order) + 1):
            found = built(tmp_path / f"case{compared}", capsys, order, point).view()
            reference = reference or found
            assert found == reference, (order, point)
            compared += 1

    # a sits at each of the four positions in 6 orders, leaving 4, 3, 2 or 1 valid points.
    assert compared == 6 * (4 + 3 + 2 + 1) == 60
    movement = reference["movement"]
    assert movement.net_cents == -650 - 900
    assert movement.transactions == 2
