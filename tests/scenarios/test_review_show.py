"""Inspecting one review item, end to end, using only synthetic data (D-037, D-040)."""

import hashlib
import re
from pathlib import Path

import pytest

from personal_finance import cli
from personal_finance.cli import DUPLICATE_NOTICE, UNRESOLVED_NOTICE, main
from personal_finance.db.migrate import connect

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"
CARD_HEADER = "Date,Description,Debit,Credit\n"
CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
CAFE = "01/05/2026,SYNTHETIC CAFE,6.50,"

LEDGER_TABLES = (
    "account", "import_run", "import_attempt", "source_document", "document_coverage",
    "document_interpretation", "source_record", "record_parse", "source_record_origin",
    "ledger_transaction", "transaction_source", "transaction_link_history",
    "transaction_identity_history", "review_issue", "review_issue_subject",
    "account_reconciliation", "decision", "decision_constraint", "decision_event",
    "value_correction", "value_correction_record", "value_correction_event",
    "transaction_correction", "record_resolution", "record_resolution_event",
    "coverage_declaration", "coverage_declaration_event", "type_classification",
    "type_classification_record", "type_classification_event", "transaction_classification",
)


@pytest.fixture
def db(tmp_path, capsys):
    path = tmp_path / "ledger.db"
    assert main(["init", "--db", str(path)]) == 0
    assert main(["account", "add", "--db", str(path), "--name", "A", "--type", "checking"]) == 0
    capsys.readouterr()
    return str(path)


@pytest.fixture
def card(db, tmp_path, capsys):
    def run(name, *rows, extra=()):
        path = tmp_path / name
        # Spaces the parser strips, so that files with equal rows are not byte-identical.
        padding = " " * len(list(tmp_path.glob("*.csv")))
        path.write_text(CARD_HEADER + padding + "".join(f"{row}\n" for row in rows))
        code = main(["import", "--db", db, "--account", "A", "--layout", "synthetic_card_v1",
                     *extra, str(path)])
        capsys.readouterr()
        assert code == 0

    return run


@pytest.fixture
def checking(db, tmp_path, capsys):
    def run(name, *rows, metadata=()):
        path = tmp_path / name
        lines = "".join(f"# {line}\n" for line in metadata)
        path.write_text(lines + CHECKING_HEADER + "".join(f"{row}\n" for row in rows))
        code = main(["import", "--db", db, "--account", "A",
                     "--layout", "synthetic_checking_v1", str(path)])
        capsys.readouterr()
        assert code == 0
        return path

    return run


@pytest.fixture
def items(db, capsys):
    """The IDs of open review items whose review list line holds the given text."""

    def run(text=""):
        capsys.readouterr()
        assert main(["review", "list", "--db", db]) == 0
        lines = capsys.readouterr().out.splitlines()
        return [line.split()[1].rstrip(":") for line in lines
                if line.startswith("Item ") and text in line]

    return run


@pytest.fixture
def show(db, capsys):
    def run(item_id):
        capsys.readouterr()
        assert main(["review", "show", "--db", db, item_id]) == 0
        return capsys.readouterr().out

    return run


def revision_of(text):
    return re.search(r"Revision: (r7-[0-9a-f]{16})", text)[1]


def section_order(text, *labels):
    positions = [text.index(label) for label in labels]
    return positions == sorted(positions)


class TestList:
    def test_each_item_shows_an_id_that_review_show_accepts(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE, "01/20/2026,OTHER,1.00,")
        (item,) = items()
        assert item in show(item)

    def test_it_points_to_show_only_when_there_is_something_to_see(self, db, card, capsys):
        main(["review", "list", "--db", db])
        assert "review show" not in capsys.readouterr().out
        card("a.csv", CAFE)
        card("b.csv", CAFE, "01/20/2026,OTHER,1.00,")
        main(["review", "list", "--db", db])
        assert "run review show" in capsys.readouterr().out

    def test_it_carries_no_revision(self, db, card, capsys):
        """A revision is derived from row contents, so routine output leaves it out."""
        card("a.csv", CAFE)
        card("b.csv", CAFE, "01/20/2026,OTHER,1.00,")
        main(["review", "list", "--db", db])
        out = capsys.readouterr().out
        assert "Revision" not in out and not re.search(r"\br\d+-", out)


class TestSupportedItems:
    def test_a_candidate_group_separates_each_kind_of_evidence(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", "01/06/2026,SYNTHETIC CAFE,6.50,")
        (item,) = items("cross_document_candidates")
        out = show(item)

        assert section_order(
            out, "Revision:", "Machine-generated reasons:", "Current logical transaction values:",
            "Primary-source selection:", "Original source cells:", "Parsed source values:",
            "Coverage evidence:",
        )
        assert "Rule: cross_document_candidates" in out
        assert "similar_description: same amount" in out
        assert "Dates involved: 2026-01-05 to 2026-01-06" in out
        assert "Original source cells: ['01/05/2026', 'SYNTHETIC CAFE', '6.50', '']" in out
        assert "Amount: -6.50" in out and "Status: posted" in out
        assert "Transaction 2 of 2:" in out

    def test_an_ambiguous_group_states_no_adjustment(self, card, items, show):
        card("a.csv", CAFE, CAFE)
        card("b.csv", CAFE, CAFE, CAFE)
        (item,) = items("cross_document_candidates")
        out = show(item)

        assert DUPLICATE_NOTICE in out
        assert set(re.findall(r"-?\d+\.\d\d", out)) == {"-6.50", "6.50"}

    def test_records_from_one_document_are_identified(self, card, items, show):
        card("a.csv", CAFE, CAFE)
        card("b.csv", CAFE)
        (item,) = items("cross_document_candidates")
        out = show(item)

        assert "Records from the same document:\n  a.csv: rows 1, 2\n" in out
        assert out.count("Shares its document with another record in this item") == 2

    def test_records_from_different_documents_are_not_marked(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE, "01/20/2026,OTHER,1.00,")
        out = show(items("cross_document_candidates")[0])
        assert "Records from the same document" not in out
        assert "Shares its document" not in out

    def test_a_conflicting_reliable_id_shows_both_values(self, checking, items, show):
        checking("a.csv", "S-1,2026-01-05,,SYNTHETIC BISTRO,-20.00,POSTED")
        checking("b.csv", "S-1,2026-01-05,,SYNTHETIC BISTRO,-24.00,POSTED")
        (item,) = items("cross_document_external_id")
        out = show(item)

        assert "external_id_conflict: records with this ID disagree" in out
        assert "Amount: -20.00" in out and "Amount: -24.00" in out
        assert "External ID: S-1" in out
        assert "External ID guarantee: stable_unique" in out

    def test_current_values_are_shown_apart_from_what_each_source_says(
        self, checking, items, show
    ):
        checking("a.csv", "S-1,2026-01-05,,SYNTHETIC BISTRO,-20.00,POSTED")
        checking("b.csv", "S-1,2026-01-05,,SYNTHETIC BISTRO,-24.00,POSTED")
        out = show(items("cross_document_external_id")[0])
        current = out.split("Current logical transaction values:")[1].split("Primary-source")[0]

        for label in ("Transaction date: 2026-01-05", "Posting date: missing", "Amount: -",
                      "Status: posted", "Description: SYNTHETIC BISTRO", "External ID: S-1"):
            assert label in current

    @pytest.mark.parametrize(
        "rule, rows",
        [
            ("same_document_repeated_external_id",
             ["S-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED", "S-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED"]),
            ("same_document_pending_posted",
             ["S-1,2026-01-05,,SYNTHETIC A,-1.00,PENDING", "S-2,2026-01-05,2026-01-07,SYNTHETIC A,-1.00,POSTED"]),
        ],
    )
    def test_same_document_items_show_both_rows(self, checking, items, show, rule, rows):
        checking("a.csv", *rows)
        (item,) = items(rule)
        out = show(item)

        assert f"Rule: {rule}" in out
        assert cli.RULE_EXPLANATIONS[rule] in out
        assert "a.csv: rows 1, 2" in out

    def test_a_merged_transaction_explains_its_primary_source(self, checking, items, show):
        checking("a.csv", "S-1,2026-01-05,,SYNTHETIC BISTRO,-20.00,")
        checking("b.csv", "S-1,2026-01-05,,OTHER BISTRO NAME,-20.00,POSTED")
        checking("c.csv", "S-1,2026-01-05,,SYNTHETIC BISTRO,-99.00,POSTED")
        (item,) = items("cross_document_external_id")
        out = show(item)

        assert "b.csv row 1 supplies the values above" in out
        assert "Role: primary, supplies the displayed values" in out
        assert "Role: alternative, not selected on: settlement status" in out
        assert "Link rule: reliable_external_id" in out
        # The alternative's own reading stays visible beside the chosen values.
        assert "Status: unknown" in out and "Description: OTHER BISTRO NAME" in out
        assert "Description: SYNTHETIC BISTRO" in out

    def test_an_unrecorded_primary_source_says_so(self, db, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        conn = connect(Path(db))
        conn.execute("UPDATE ledger_transaction SET primary_source_record_id = NULL")
        conn.close()
        out = show(items("cross_document_candidates")[0])

        assert "Not recorded. Run reconcile to record it." in out
        assert "Role: not recorded" in out
        assert "has not been reconciled under the current matching rules" in out

    def test_a_resolved_item_says_so(self, db, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items("cross_document_candidates")
        conn = connect(Path(db))
        conn.execute("UPDATE review_issue SET status = 'resolved', resolved_at = '2026-02-01'")
        conn.close()
        assert "Status: resolved" in show(item)


class TestMissingValues:
    def test_an_unresolved_row_shows_what_was_read_and_what_is_missing(
        self, db, items, show, capsys
    ):
        main(["import", "--db", db, "--account", "A", "--layout", "synthetic_checking_v1",
              str(FIXTURES / "checking_problem_rows.csv")])
        out = show(items("missing_amount")[0])

        assert "Result: unresolved (missing_amount)" in out
        assert "Amount: missing" in out
        assert "Description: SYNTHETIC GROCER" in out
        assert "'SYN-2001', '2026-02-01', '2026-02-02', 'SYNTHETIC GROCER', ''" in out
        assert "Role: unresolved, no transaction" in out
        assert UNRESOLVED_NOTICE in out
        assert "Current logical transaction values" not in out
        assert DUPLICATE_NOTICE not in out

    def test_a_row_of_the_wrong_shape_keeps_its_original_cells(self, db, items, show, capsys):
        main(["import", "--db", db, "--account", "A", "--layout", "synthetic_checking_v1",
              str(FIXTURES / "checking_problem_rows.csv")])
        out = show(items("wrong_column_count")[0])

        assert "'UNEXPECTED'" in out
        for label in ("Transaction date", "Posting date", "Amount", "Description", "External ID"):
            assert f"{label}: missing" in out

    def test_zero_is_not_missing_and_blank_is_not_zero(self, checking, items, show):
        checking("a.csv", "S-1,2026-01-05,,,0.00,POSTED")
        checking("b.csv", "S-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED")
        out = show(items("cross_document_external_id")[0])

        assert "Amount: 0.00" in out
        assert "Amount: missing" not in out
        assert "Description: missing" in out
        assert "Posting date: missing" in out
        assert "['S-1', '2026-01-05', '', '', '0.00', 'POSTED']" in out

    def test_unknown_coverage_stays_unstated(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        out = show(items("cross_document_candidates")[0])

        assert "Coverage kind: unknown" in out
        assert "Claimed interval: missing to missing" in out
        assert "Coverage evidence: missing" in out
        assert "Last date matching relies on" not in out


class TestCoverage:
    def test_metadata_coverage_shows_claim_and_effective_end_apart(self, checking, items, show):
        metadata = ["coverage-kind: complete", "coverage-start: 2026-01-01",
                    "coverage-end: 2026-01-31", "coverage-basis: transaction",
                    "generated-on: 2026-01-31"]
        row = ",2026-01-31,,SYNTHETIC CAFE,-6.50,POSTED"
        checking("a.csv", row, metadata=metadata)
        checking("b.csv", row, ",2026-01-02,,OTHER,-1.00,POSTED", metadata=metadata)
        out = show(items("cross_document_candidates")[0])

        assert "boundary_date: the date is too close" in out
        assert "Coverage kind: complete" in out
        assert "Claimed interval: 2026-01-01 to 2026-01-31" in out
        assert "Date basis: transaction" in out
        assert "Coverage evidence: document_metadata" in out
        assert "Generated on: 2026-01-31" in out
        assert "Last date matching relies on: 2026-01-30" in out
        assert "Pending rows: included" in out

    def test_a_user_declaration_is_named_as_such(self, card, items, show):
        declared = ["--declare-complete-coverage", "--coverage-start", "2026-01-05",
                    "--coverage-end", "2026-01-05", "--coverage-basis", "posting"]
        card("a.csv", CAFE, extra=declared)
        card("b.csv", CAFE, "01/20/2026,OTHER,1.00,", extra=declared)
        out = show(items("cross_document_candidates")[0])

        assert "single_day_overlap: the documents overlap by a single day" in out
        assert "Coverage evidence: user_declared" in out
        assert "Last date matching relies on: 2026-01-05" in out
        assert "Pending rows: excluded" in out


class TestDisplaySafety:
    def test_a_cell_cannot_imitate_other_sections(self, checking, items, show):
        forged = '"SYNTHETIC\nCoverage evidence:\n  forged"'
        checking("a.csv", f"S-1,2026-01-05,,{forged},-1.00,POSTED")
        checking("b.csv", "S-1,2026-01-05,,SYNTHETIC,-2.00,POSTED")
        out = show(items("cross_document_external_id")[0])

        assert out.count("\nCoverage evidence:\n") == 1
        assert "\n  forged" not in out
        assert "Description: SYNTHETIC\\nCoverage evidence:\\n  forged" in out

    def test_terminal_controls_are_escaped(self, checking, items, show):
        checking("a.csv", "S-1,2026-01-05,,SYNTHETIC\x1b[2JCAFE,-1.00,POSTED")
        checking("b.csv", "S-1,2026-01-05,,SYNTHETIC,-2.00,POSTED")
        out = show(items("cross_document_external_id")[0])
        assert "\x1b" not in out


class TestRevision:
    def test_showing_twice_gives_the_same_revision(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items()
        assert revision_of(show(item)) == revision_of(show(item))

    def test_a_repeat_import_and_a_reconcile_change_nothing(
        self, db, tmp_path, card, items, show, capsys
    ):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items()
        before = revision_of(show(item))

        assert main(["import", "--db", db, "--account", "A", "--layout", "synthetic_card_v1",
                     str(tmp_path / "a.csv")]) == 0
        assert main(["reconcile", "--db", db]) == 0

        assert items() == [item]
        assert revision_of(show(item)) == before

    def test_an_unrelated_file_changes_nothing(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items()
        before = revision_of(show(item))
        card("c.csv", "02/20/2026,UNRELATED,1.00,")
        assert revision_of(show(item)) == before

    def test_a_new_member_keeps_the_item_id_but_changes_the_revision(self, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items()
        before = revision_of(show(item))
        card("c.csv", CAFE)

        assert items() == [item]
        assert revision_of(show(item)) != before

    def test_a_new_source_for_a_member_changes_its_primary_and_the_revision(
        self, checking, items, show
    ):
        checking("a.csv", "S-1,2026-01-05,,SYNTHETIC CAFE,-6.50,")
        checking("x.csv", ",2026-01-05,,SYNTHETIC CAFE,-6.50,")
        (item,) = items("cross_document_candidates")
        before = show(item)
        checking("c.csv", "S-1,2026-01-05,2026-01-06,SYNTHETIC CAFE,-6.50,POSTED")
        after = show(item)

        assert items("cross_document_candidates") == [item]
        assert "c.csv row 1 supplies the values above" in after
        assert revision_of(after) != revision_of(before)

    def test_a_rules_change_warns_without_changing_the_revision(self, db, card, items, show):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items()
        before = show(item)
        conn = connect(Path(db))
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        after = show(item)

        assert "not been reconciled" not in before
        assert "not been reconciled" in after
        assert revision_of(after) == revision_of(before)


class TestReadOnly:
    def populated(self, db, card, checking):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        checking("c.csv", "S-1,2026-01-05,,,1.00,", "BAD ROW")

    def snapshot(self, db):
        conn = connect(Path(db), read_only=True)
        tables = {table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in LEDGER_TABLES}
        conn.close()
        return tables

    def test_list_and_show_leave_every_table_and_the_file_unchanged(
        self, db, card, checking, items, show
    ):
        self.populated(db, card, checking)
        tables = self.snapshot(db)
        before = hashlib.sha256(Path(db).read_bytes()).hexdigest()

        for item in items():
            show(item)

        assert self.snapshot(db) == tables
        assert hashlib.sha256(Path(db).read_bytes()).hexdigest() == before

    def test_the_snapshot_covers_every_ledger_table(self, db):
        conn = connect(Path(db), read_only=True)
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )}
        conn.close()
        assert names == set(LEDGER_TABLES)

    def test_both_commands_open_the_ledger_read_only(self, db, card, items, monkeypatch):
        card("a.csv", CAFE)
        card("b.csv", CAFE)
        (item,) = items()
        opened = []

        def recording_connect(path, *, read_only=False):
            opened.append(read_only)
            return connect(path, read_only=read_only)

        monkeypatch.setattr(cli, "connect", recording_connect)
        main(["review", "list", "--db", db])
        main(["review", "show", "--db", db, item])
        assert opened == [True, True]

    def test_an_unknown_item_is_refused_and_changes_nothing(self, db, capsys):
        tables = self.snapshot(db)
        assert main(["review", "show", "--db", db, "no-such-item"]) == 2
        captured = capsys.readouterr()
        assert "review item not found" in captured.err
        assert "no-such-item" not in captured.err
        assert captured.out == ""
        assert self.snapshot(db) == tables
