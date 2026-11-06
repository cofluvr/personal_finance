"""Import order must not change the outcome (A16), using generated synthetic files."""

import hashlib
import tempfile
from dataclasses import dataclass
from itertools import combinations, permutations
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from ledger_view import semantic_view

from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest.coverage import Coverage, declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files

CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
CARD_HEADER = "Date,Description,Debit,Credit\n"

DAYS = ("2026-01-08", "2026-01-09", "2026-01-10", "2026-01-13", "2026-01-31")
AMOUNTS = ("5.00", "6.00")
DESCRIPTIONS = ("SYNTHETIC CAFE", "SQ *SYNTHETIC CAFE #12", "SYNTHETIC GROCER", "")
INTERVALS = (
    ("2026-01-01", "2026-01-31"),
    ("2026-01-10", "2026-01-20"),
    ("2026-01-01", "2026-01-10"),
    ("2026-01-10", "2026-01-10"),
)


@dataclass(frozen=True)
class File:
    content: str
    layout: object
    declared: Coverage | None = None


days = st.sampled_from(DAYS)
amounts = st.sampled_from(AMOUNTS)
descriptions = st.sampled_from(DESCRIPTIONS)
intervals = st.sampled_from(INTERVALS)


def card_row():
    return st.one_of(
        st.builds(lambda d, t, a: f"{d[5:7]}/{d[8:10]}/{d[:4]},{t},{a},", days, descriptions, amounts),
        # Unresolved rows: a missing amount, and a row with too few cells.
        st.builds(lambda d, t: f"{d[5:7]}/{d[8:10]}/{d[:4]},{t},,", days, descriptions),
        st.just("not enough cells"),
    )


def checking_row():
    ids = st.sampled_from(("", "S-1", "S-2", "S-3"))
    optional_day = st.one_of(st.just(""), days)
    statuses = st.sampled_from(("", "POSTED", "PENDING"))
    return st.builds(
        lambda i, t, p, d, a, s: f"{i},{t},{p or (t and '') or DAYS[0]},{d},-{a},{s}",
        ids, optional_day, optional_day, descriptions, amounts, statuses,
    )


@st.composite
def card_file(draw):
    rows = draw(st.lists(card_row(), min_size=1, max_size=4))
    declared = None
    if draw(st.booleans()):
        declared = declare_complete(*draw(intervals), "posting")
    return File(CARD_HEADER + "".join(f"{row}\n" for row in rows), SYNTHETIC_CARD_V1, declared)


@st.composite
def checking_file(draw):
    rows = draw(st.lists(checking_row(), min_size=1, max_size=4))
    start, end = draw(intervals)
    basis = draw(st.sampled_from(("posting", "transaction")))
    claim = [f"# coverage-start: {start}\n", f"# coverage-end: {end}\n", f"# coverage-basis: {basis}\n"]
    choice = draw(st.sampled_from(("none", "declared", "complete", "complete_generated", "partial")))
    preamble, declared = [], None
    if choice == "declared":
        declared = declare_complete(start, end, basis)
    elif choice == "complete":
        preamble = ["# coverage-kind: complete\n", *claim]
    elif choice == "complete_generated":
        generated = draw(st.sampled_from(("2026-01-15", "2026-01-31", "2026-02-05")))
        preamble = ["# coverage-kind: complete\n", *claim, f"# generated-on: {generated}\n"]
    elif choice == "partial":
        preamble = ["# coverage-kind: partial\n"]
    body = "".join(f"{row}\n" for row in rows)
    return File("".join(preamble) + CHECKING_HEADER + body, SYNTHETIC_CHECKING_V1, declared)


def unique_files(files):
    return list({file.content: file for file in files}.values())


def replay(files):
    """Import files in order into a new ledger and return its view."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'checking')"
        )
        for number, file in enumerate(files):
            source = root / f"{number}.csv"
            source.write_text(file.content, encoding="utf-8")
            (result,) = import_files(
                conn, [source], account_id="acct", layout=file.layout, declared_coverage=file.declared
            )
            assert result.outcome != "failed", (result, file)
        view = semantic_view(conn)
        conn.close()
    return view


@st.composite
def orderings(draw):
    files = unique_files(
        draw(st.lists(st.one_of(card_file(), checking_file()), min_size=2, max_size=5))
    )
    shuffled = draw(st.permutations(files))
    repeats = draw(st.lists(st.sampled_from(files), max_size=2))
    return files, list(shuffled) + repeats


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(orderings())
def test_a16_every_order_gives_the_same_outcome(case):
    files, order = case
    assert replay(order) == replay(files)


@st.composite
def focused_card_file(draw):
    """Few distinct rows and shared coverage, so exact pairing happens often."""
    rows = draw(
        st.lists(
            st.sampled_from(("01/10/2026,SYNTHETIC CAFE,5.00,", "01/31/2026,SYNTHETIC CAFE,5.00,")),
            min_size=1,
            max_size=3,
        )
    )
    if draw(st.booleans()):
        rows = [*rows, draw(st.sampled_from(("01/10/2026,SYNTHETIC CAFE,,", "not enough cells")))]
    interval = draw(st.sampled_from((*INTERVALS[:3], None)))
    declared = declare_complete(*interval, "posting") if interval else None
    return File(CARD_HEADER + "".join(f"{row}\n" for row in rows), SYNTHETIC_CARD_V1, declared)


@st.composite
def focused_metadata_file(draw):
    """ID-less rows under metadata claims, so boundary dates happen often."""
    rows = draw(
        st.lists(
            st.sampled_from(
                (
                    ",2026-01-10,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED",
                    ",2026-01-31,2026-01-31,SYNTHETIC CAFE,-5.00,POSTED",
                )
            ),
            min_size=1,
            max_size=3,
        )
    )
    generated = draw(st.sampled_from(("", "2026-01-20", "2026-01-31", "2026-02-05", "2026-02-09")))
    preamble = [
        "# coverage-kind: complete\n",
        "# coverage-start: 2026-01-01\n",
        "# coverage-end: 2026-01-31\n",
        "# coverage-basis: posting\n",
    ]
    if generated:
        preamble.append(f"# generated-on: {generated}\n")
    body = "".join(f"{row}\n" for row in rows)
    return File("".join(preamble) + CHECKING_HEADER + body, SYNTHETIC_CHECKING_V1)


@st.composite
def focused_id_file(draw):
    """One ID across rows that agree only in part, so merges have to split."""
    rows = draw(
        st.lists(
            st.sampled_from(
                (
                    "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,",
                    "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED",
                    "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED",
                    "S-1,,2026-01-11,OTHER WORDS,-5.00,",
                )
            ),
            min_size=1,
            max_size=2,
        )
    )
    return File(CHECKING_HEADER + "".join(f"{row}\n" for row in rows), SYNTHETIC_CHECKING_V1)


@st.composite
def focused_orderings(draw):
    file = st.one_of(focused_card_file(), focused_metadata_file(), focused_id_file())
    files = unique_files(draw(st.lists(file, min_size=2, max_size=5)))
    shuffled = draw(st.permutations(files))
    repeats = draw(st.lists(st.sampled_from(files), max_size=2))
    return files, list(shuffled) + repeats


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(focused_orderings())
def test_a16_every_order_gives_the_same_outcome_on_the_hard_paths(case):
    files, order = case
    assert replay(order) == replay(files)


def test_a16_every_arrival_order_of_a_splitting_id_group_agrees():
    """Random orders rarely force a split, so every order of these files is checked."""
    rows = (
        "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,",
        "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED",
        "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED",
        "S-1,,2026-01-11,OTHER WORDS,-5.00,",
    )
    files = [File(CHECKING_HEADER + row + "\n", SYNTHETIC_CHECKING_V1) for row in rows]
    for size in (2, 3, 4):
        for subset in combinations(files, size):
            expected = replay(subset)
            for order in permutations(subset):
                assert replay(order) == expected


def card_content(*rows):
    return CARD_HEADER + "".join(f"{row}\n" for row in rows)


def content_sorting_before(existing, *rows):
    """Add an unrelated row until the file's hash sorts ahead of every existing file."""
    lowest = min(hashlib.sha256(text.encode()).hexdigest() for text in existing)
    for number in range(1, 200_000):
        cents = f"{number // 100}.{number % 100:02d}"
        content = card_content(*rows, f"06/15/2025,UNRELATED FILLER,{cents},")
        if hashlib.sha256(content.encode()).hexdigest() < lowest:
            return content
    raise AssertionError("no content found")


def import_all(conn, root, files):
    for file in files:
        path = root / f"{hashlib.sha256(file.content.encode()).hexdigest()[:12]}.csv"
        path.write_text(file.content, encoding="utf-8")
        (result,) = import_files(
            conn, [path], account_id="acct", layout=file.layout, declared_coverage=file.declared
        )
        assert result.outcome == "imported"


def test_a_document_sorting_first_regroups_consistently(conn, tmp_path):
    """Source grouping follows the document set. Public IDs follow their own rule."""
    conn.execute("INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'checking')")
    january = declare_complete("2026-01-01", "2026-01-31", "posting")
    same = "01/10/2026,SYNTHETIC CAFE,5.00,"
    other = "01/20/2026,SYNTHETIC GROCER,7.00,"
    first = File(card_content(same, same, other), SYNTHETIC_CARD_V1, january)
    second = File(card_content(other, same, same), SYNTHETIC_CARD_V1, january)
    third = File(
        content_sorting_before([first.content, second.content], same, same, same),
        SYNTHETIC_CARD_V1,
        january,
    )

    import_all(conn, tmp_path, [first, second])
    before = set(conn.execute("SELECT id FROM ledger_transaction").fetchall())
    view_before_third = semantic_view(conn)

    import_all(conn, tmp_path, [third])

    after = set(conn.execute("SELECT id FROM ledger_transaction").fetchall())
    assert before <= after, "existing public IDs must survive a document sorting first"
    assert semantic_view(conn) == replay([third, second, first]) == replay([second, third, first])
    assert semantic_view(conn)["transactions"] != view_before_third["transactions"]
    primary = conn.execute(
        """SELECT COUNT(*) FROM transaction_source link
           JOIN source_document document ON document.id = link.source_document_id
           WHERE document.content_sha256 = ?""",
        (hashlib.sha256(third.content.encode()).hexdigest(),),
    ).fetchone()
    assert primary == (4,)
