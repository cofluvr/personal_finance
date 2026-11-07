"""Decisions and import order (S15, S22). Records are identified by document hash and row,
never by generated IDs or timestamps, so ledgers built differently can be compared."""

import hashlib
import tempfile
from itertools import permutations
from pathlib import Path

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from ledger_view import active_constraints, semantic_view
from test_import_order import CARD_HEADER, File, focused_card_file, focused_id_file

from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile.decisions import reject_pairs, undo_decision
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.decision_evidence import load_decision, undo_outlook
from personal_finance.reports.review_evidence import load_review_evidence, review_revision

CAFE = "01/10/2026,SYNTHETIC CAFE,5.00,\n"


def card(rows, *interval, padding=0):
    """Padding is spaces the parser strips, so that files with equal rows differ in bytes."""
    declared = declare_complete(*interval, "posting") if interval else None
    return File(CARD_HEADER + " " * padding + rows, SYNTHETIC_CARD_V1, declared)


# Overlapping by a single day, so these two never merge by themselves.
FIRST = card(CAFE, "2026-01-01", "2026-01-10")
SECOND = card(CAFE, "2026-01-10", "2026-01-20", padding=1)
WHOLE = card(CAFE + "01/15/2026,SYNTHETIC BOOKS,7.00,\n", "2026-01-01", "2026-01-20")
LOOKALIKE = card(CAFE, padding=2)
UNRELATED = card("03/20/2026,SYNTHETIC GROCER,9.00,\n")


def key_of(file: File) -> tuple[str, int]:
    return hashlib.sha256(file.content.encode("utf-8")).hexdigest(), 1


def transaction_of(conn, key) -> tuple[str, int] | None:
    """The transaction holding a record, with how many records it holds."""
    digest, row = key
    return conn.execute(
        """SELECT link.transaction_id,
                  (SELECT COUNT(*) FROM transaction_source other
                   WHERE other.transaction_id = link.transaction_id)
           FROM transaction_source link
           JOIN source_document document ON document.id = link.source_document_id
           JOIN source_record record ON record.id = link.source_record_id
           WHERE document.content_sha256 = ? AND record.record_index = ?""",
        (digest, row),
    ).fetchone()


def reject_first_and_second(conn) -> str | None:
    """Make the decision if it is valid now, binding just these two records."""
    left = transaction_of(conn, key_of(FIRST))
    right = transaction_of(conn, key_of(SECOND))
    if left is None or right is None or left[0] == right[0] or left[1] != 1 or right[1] != 1:
        return None
    for (issue,) in conn.execute(
        """SELECT id FROM review_issue
           WHERE rule = 'cross_document_candidates' AND status = 'open'"""
    ).fetchall():
        item = load_review_evidence(conn, issue)
        if {left[0], right[0]} <= {entry.transaction_id for entry in item.transactions}:
            result = reject_pairs(conn, "acct", issue, review_revision(item), [(left[0], right[0])])
            return result.decision_id
    return None


def replay(files, decide_after=None, undo=False):
    """The view after importing files, deciding once decide_after files are in.

    None means the decision was not valid at that point, as when a third file has already
    merged the two records.
    """
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'checking')"
        )
        decision = None
        try:
            for number, file in enumerate(files):
                if number == decide_after:
                    decision = reject_first_and_second(conn)
                    if decision is None:
                        return None
                source = root / f"{number}.csv"
                source.write_text(file.content, encoding="utf-8")
                (result,) = import_files(
                    conn, [source], account_id="acct", layout=file.layout,
                    declared_coverage=file.declared,
                )
                assert result.outcome != "failed", (result, file)
            if decide_after == len(files):
                decision = reject_first_and_second(conn)
                if decision is None:
                    return None
            if undo:
                token = undo_outlook(conn, load_decision(conn, decision), DEFAULT_RULES).revision
                undo_decision(conn, "acct", decision, token)
            return semantic_view(conn)
        finally:
            conn.close()


def outcomes(files, **options):
    """Every valid combination of import order and decision point."""
    return [
        view
        for order in permutations(files)
        for point in range(len(files) + 1)
        if (view := replay(order, point, **options)) is not None
    ]


class TestEveryOrderAndPoint:
    def test_a_later_file_that_would_join_them(self):
        files = [FIRST, SECOND, WHOLE, UNRELATED]
        views = outcomes(files)
        # FIRST and SECOND must be in, and WHOLE not yet, so that the pair is still a candidate.
        assert len(views) >= 6
        assert all(view == views[0] for view in views)
        assert len(views[0]["constraints"]) == 1
        assert views[0]["movement"].decision_conflicts == 1

    def test_a_lookalike_arriving_before_or_after_the_decision(self):
        files = [FIRST, SECOND, LOOKALIKE, UNRELATED]
        views = outcomes(files)
        assert len(views) >= 12
        assert all(view == views[0] for view in views)
        assert views[0]["movement"].decision_conflicts == 0
        assert views[0]["movement"].candidate_groups == 1

    def test_undo_matches_never_deciding_at_every_point(self):
        files = [FIRST, SECOND, WHOLE]
        views = outcomes(files, undo=True)
        assert len(views) == 2
        assert all(view == replay(files) for view in views)


@st.composite
def cases(draw):
    known_files = st.sampled_from((WHOLE, LOOKALIKE, UNRELATED))
    extras = draw(
        st.lists(st.one_of(known_files, focused_card_file(), focused_id_file()), max_size=3)
    )
    known = {FIRST.content, SECOND.content}
    files = [FIRST, SECOND]
    for extra in extras:
        if extra.content not in known:
            known.add(extra.content)
            files.append(extra)
    one = draw(st.permutations(files))
    other = draw(st.permutations(files))
    return one, draw(valid_points(one)), other, draw(valid_points(other))


def valid_points(order):
    """From the moment both records are in. A later file can still make a point invalid."""
    return st.integers(max(order.index(FIRST), order.index(SECOND)) + 1, len(order))


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@given(cases())
def test_equivalent_decisions_give_the_same_outcome_in_any_order(case):
    one, one_point, other, other_point = case
    first = replay(one, one_point)
    second = replay(other, other_point)
    assume(first is not None and second is not None)
    assert first["constraints"] == second["constraints"]
    assert first == second


def test_the_view_identifies_constraints_by_evidence_not_ids():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ledger.db"
        create_database(path)
        conn = connect(path)
        assert active_constraints(conn) == []
        conn.close()
