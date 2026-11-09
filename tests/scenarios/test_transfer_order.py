"""Equivalent transfer matches made at different points in the import sequence of two accounts
(X11, D-054), with income and spending (T11, D-056).

Exhaustive rather than a property test: every order of four files across two accounts, and every
point after both sides' files arrive.
"""

from itertools import permutations

from test_decisions import CARD_HEADER, CHECKING_HEADER
from test_supersession import holding
from test_transfers import TransferLedger

# Fixed bytes per file, whatever the order. b repeats a's row with a reliable ID, so the two merge
# in A. c is the other side in S, and d a second inflow of the same amount there.
MOVE_WITH_ID = "S-1,2026-01-09,2026-01-10,SYNTHETIC MOVE OUT,-5.00,POSTED\n"
FILES = {
    "a.csv": ("A", "synthetic_checking_v1", CHECKING_HEADER + MOVE_WITH_ID),
    "b.csv": ("A", "synthetic_checking_v1", CHECKING_HEADER + " " + MOVE_WITH_ID),
    "c.csv": ("S", "synthetic_card_v1", CARD_HEADER + "01/12/2026,SYNTHETIC MOVE IN,,5.00\n"),
    "d.csv": ("S", "synthetic_card_v1", CARD_HEADER + "02/20/2026,SYNTHETIC REFUND,,5.00\n"),
}


def outcome(ledger):
    """Everything but revisions, which cover the bound records and so differ by design."""
    view = ledger.view()
    del view["revisions"]
    return (view, ledger.matches(), ledger.outcomes(), ledger.transfers_section(),
            ledger.income_section())


def bound_files(ledger, match, side):
    conn = ledger.conn()
    found = sorted(row[0] for row in conn.execute(
        """SELECT document.file_name FROM transfer_match_record bound
           JOIN source_record record ON record.id = bound.source_record_id
           JOIN source_document document ON document.id = record.source_document_id
           WHERE bound.match_id = ? AND bound.side = ?""",
        (match, side),
    ))
    conn.close()
    return found


def built(folder, capsys, order, point):
    """Imports in this order, classifying a's event as a transfer and matching it with c's after
    the first point imports."""
    folder.mkdir()
    ledger = TransferLedger(folder, capsys)
    ledger.add_account("S", "savings")
    match = None
    for position, name in enumerate(order, start=1):
        account, layout, content = FILES[name]
        path = folder / name
        path.write_text(content)
        ledger.load_path(path, account=account, layout=layout)
        if position == point:
            outflow, inflow = holding(ledger, "a.csv"), holding(ledger, "c.csv")
            ledger.classify_ok(outflow, "transfer")
            match = ledger.match_ok(outflow, inflow)
    return ledger, match


def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys):
    reference = None
    compared = 0
    for order in permutations(FILES):
        first_valid = max(order.index("a.csv"), order.index("c.csv")) + 1
        for point in range(first_valid, len(order) + 1):
            ledger, match = built(tmp_path / f"case{compared}", capsys, order, point)
            found = outcome(ledger)
            reference = reference or found
            assert found == reference, (order, point)

            # Records arriving after the match are never bound by it.
            b_before = order.index("b.csv") + 1 <= point
            expected = ["a.csv", "b.csv"] if b_before else ["a.csv"]
            assert bound_files(ledger, match, "outflow") == expected, (order, point)
            assert bound_files(ledger, match, "inflow") == ["c.csv"], (order, point)
            compared += 1

    # Both a and c are imported by position 2, 3 or 4 in 4, 8 and 12 orders, leaving 3, 2 or 1
    # valid points.
    assert compared == 4 * 3 + 8 * 2 + 12 * 1 == 40
    view, matches, outcomes, transfers, income = reference
    assert matches == [("applied", ("a.csv", "b.csv"), ("c.csv",))]
    assert outcomes == [(("a.csv", "b.csv"), "applied", "transfer")]
    assert transfers.startswith("  Matched: 1 pairs, moving 5.00\n"
                                "  In a candidate pair, not matched: 0 transactions\n")
    assert "  Confirmed transfers: 2 transactions, 5.00 out and 5.00 in\n" in income
    assert "  Unclassified: 1 transactions, 0.00 out and 5.00 in\n" in income
    assert view["movement"].transactions == 3
