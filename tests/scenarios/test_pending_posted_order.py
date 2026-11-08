"""Pending and posted exports in every import order (Q14, D-052).

Exhaustive: every order of four files gives the same outcome.
"""

from itertools import permutations

import test_pending_posted
from test_decisions import CHECKING_HEADER

# Fixed bytes per file. a and b share an ID, pending then posted with a tip, so they merge. c and d
# have no ID, pending then posted with a tip, so they raise a candidate and stay apart.
FILES = {
    "a.csv": CHECKING_HEADER + "S-1,2026-01-09,,SYNTHETIC CAFE,-20.00,PENDING\n",
    "b.csv": CHECKING_HEADER + "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-24.00,POSTED\n",
    "c.csv": CHECKING_HEADER + ",2026-01-12,,SYNTHETIC BAKERY,-8.00,PENDING\n",
    "d.csv": CHECKING_HEADER + ",2026-01-12,2026-01-13,SYNTHETIC BAKERY,-9.50,POSTED\n",
}


def test_every_order_gives_the_same_outcome(tmp_path, capsys):
    reference = None
    for number, order in enumerate(permutations(FILES)):
        folder = tmp_path / f"case{number}"
        folder.mkdir()
        ledger = test_pending_posted.PendingLedger(folder, capsys)
        for name in order:
            path = folder / name
            path.write_text(FILES[name])
            ledger.load_path(path, layout="synthetic_checking_v1")
        found = ledger.view()
        reference = reference or found
        assert found == reference, order
    assert number + 1 == 24
    movement = reference["movement"]
    assert movement.transactions == 3
    assert movement.net_cents == -2400 - 800 - 950
    assert movement.candidate_groups == 1
    assert movement.transactions_posted_at_changed_amount == 1
