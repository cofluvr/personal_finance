"""Equivalent classifications made at different points in the import sequence (F12, D-053).

Exhaustive rather than a property test: every order of four files, and every point after the
classified record's file arrives.
"""

from itertools import permutations

from test_classifications import ClassificationLedger
from test_correction_order import FILES
from test_supersession import holding


def outcome(ledger):
    """Everything but revisions, which cover the bound records and so differ by design."""
    view = ledger.view()
    del view["revisions"]
    return view, ledger.outcomes(), ledger.types()


def bound_files(ledger, classification):
    conn = ledger.conn()
    found = sorted(row[0] for row in conn.execute(
        """SELECT document.file_name FROM type_classification_record bound
           JOIN source_record record ON record.id = bound.source_record_id
           JOIN source_document document ON document.id = record.source_document_id
           WHERE bound.classification_id = ?""",
        (classification,),
    ))
    conn.close()
    return found


def built(folder, capsys, order, point):
    """Imports in this order, classifying a's event as a purchase after the first point imports."""
    folder.mkdir()
    ledger = ClassificationLedger(folder, capsys)
    classification = None
    for position, name in enumerate(order, start=1):
        layout, content = FILES[name]
        path = folder / name
        path.write_text(content)
        ledger.load_path(path, layout=layout)
        if position == point:
            classification = ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
    return ledger, classification


def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys):
    reference = None
    compared = 0
    for order in permutations(FILES):
        first_valid = order.index("a.csv") + 1
        for point in range(first_valid, len(order) + 1):
            ledger, classification = built(tmp_path / f"case{compared}", capsys, order, point)
            found = outcome(ledger)
            reference = reference or found
            assert found == reference, (order, point)

            # Records arriving after the classification are never bound by it.
            b_before = order.index("b.csv") + 1 <= point
            expected = ["a.csv", "b.csv"] if b_before else ["a.csv"]
            assert bound_files(ledger, classification) == expected, (order, point)
            compared += 1

    # a sits at each of the four positions in 6 orders, leaving 4, 3, 2 or 1 valid points.
    assert compared == 6 * (4 + 3 + 2 + 1) == 60
    view, outcomes, types = reference
    assert outcomes == [(("a.csv", "b.csv"), "applied", "purchase")]
    assert types == [("purchase", "1", "-5.00"), ("unclassified", "2", "-14.00")]
    assert view["movement"].candidate_groups == 1
