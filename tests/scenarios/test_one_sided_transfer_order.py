"""Equivalent one-sided transfers stated at different points in the import sequence of two
accounts, including the counterpart's arrival (O12, D-055), with income and spending (T11,
D-056).

Exhaustive rather than a property test: every order of four files across two accounts, and every
point at which stating is valid: after a's file arrives, and before a candidate with the
counterpart does, since one then refuses it.
"""

from itertools import permutations

import pytest
from test_decisions import CARD_HEADER, CHECKING_HEADER
from test_one_sided_transfers import OneSidedLedger
from test_supersession import holding

# Fixed bytes per file, whatever the order. b repeats a's row with a reliable ID, so the two merge
# in A. c is in S, the counterpart, and d an unrelated row there.
MOVE_WITH_ID = "S-1,2026-01-09,2026-01-10,SYNTHETIC MOVE OUT,-5.00,POSTED\n"
OTHER_SIDE = "01/12/2026,SYNTHETIC MOVE IN,,5.00\n"
OUTSIDE_THE_WINDOW = "02/20/2026,SYNTHETIC MOVE IN,,5.00\n"


def files(counterpart_row):
    return {
        "a.csv": ("A", "synthetic_checking_v1", CHECKING_HEADER + MOVE_WITH_ID),
        "b.csv": ("A", "synthetic_checking_v1", CHECKING_HEADER + " " + MOVE_WITH_ID),
        "c.csv": ("S", "synthetic_card_v1", CARD_HEADER + counterpart_row),
        "d.csv": ("S", "synthetic_card_v1", CARD_HEADER + "03/20/2026,SYNTHETIC GROCER,9.00,\n"),
    }


def outcome(ledger):
    """Everything but revisions, which cover the bound records and so differ by design."""
    view = ledger.view()
    del view["revisions"]
    return view, ledger.one_sided_states(), ledger.transfers_section(), ledger.income_section()


def bound_files(ledger, statement):
    conn = ledger.conn()
    found = sorted(row[0] for row in conn.execute(
        """SELECT document.file_name FROM one_sided_transfer_record bound
           JOIN source_record record ON record.id = bound.source_record_id
           JOIN source_document document ON document.id = record.source_document_id
           WHERE bound.one_sided_transfer_id = ?""",
        (statement,),
    ))
    conn.close()
    return found


def built(folder, capsys, contents, order, point):
    """Imports in this order, classifying a's event as a transfer and stating it one-sided with S
    after the file at this position imports."""
    folder.mkdir()
    ledger = OneSidedLedger(folder, capsys)
    ledger.add_account("S", "savings")
    statement = None
    for position, name in enumerate(order, start=1):
        account, layout, content = contents[name]
        path = folder / name
        path.write_text(content)
        ledger.load_path(path, account=account, layout=layout)
        if position == point:
            transaction = holding(ledger, "a.csv")
            ledger.classify_ok(transaction, "transfer")
            statement = ledger.one_sided_ok(transaction)
    return ledger, statement


@pytest.mark.parametrize(("counterpart_row", "found"), [(OTHER_SIDE, True),
                                                        (OUTSIDE_THE_WINDOW, False)])
def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys,
                                                                 counterpart_row, found):
    contents = files(counterpart_row)
    reference = None
    compared = 0
    for order in permutations(contents):
        first_valid = order.index("a.csv") + 1
        last_valid = order.index("c.csv") if found else len(order)
        for point in range(first_valid, last_valid + 1):
            ledger, statement = built(tmp_path / f"case{compared}", capsys, contents, order,
                                      point)
            result = outcome(ledger)
            reference = reference or result
            assert result == reference, (order, point)

            # Records arriving after the statement are never bound by it.
            b_before = order.index("b.csv") + 1 <= point
            expected = ["a.csv", "b.csv"] if b_before else ["a.csv"]
            assert bound_files(ledger, statement) == expected, (order, point)
            compared += 1

    view, states, transfers, income = reference
    if found:
        # a before c in 12 orders: c two, three or four places after a, then one fewer point.
        assert compared == 6 * 1 + 4 * 2 + 2 * 3 == 20
        assert states == [("counterpart_found", ())]
        assert "  In a candidate pair, not matched: 2 transactions\n" in transfers
        assert "  Of a transfer kind, not confirmed: 1 transactions, 5.00 out and 0.00 in\n" in \
            income
    else:
        # a at position 1 to 4 in 6 orders each, leaving 4, 3, 2 or 1 points.
        assert compared == 6 * (4 + 3 + 2 + 1) == 60
        assert states == [("applied", ("a.csv", "b.csv"))]
        assert "  One-sided, the other side not in the ledger: 1 transactions, 5.00 out" in \
            transfers
        assert "  Confirmed transfers: 1 transactions, 5.00 out and 0.00 in\n" in income
    assert view["movement"].transactions == 3
