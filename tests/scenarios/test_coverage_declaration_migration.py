"""Migration 0011 on a populated ledger, and its append-only tables (K13, D-051).

A ledger built at the latest version, with the empty tables of 0011, 0013 and 0014 dropped and set
back to version 10, is a version 10 ledger as far as 0011 is concerned: they only create tables,
0014 clears no marker on a ledger with no classification, and 0012 rebuilds a table 0011 does not
touch. Migration stops at 11, so that only 0011 is tested here.
"""

import sqlite3

import pytest
from test_confirmations import confirm_ok
from test_coverage_declarations import MONTH, CoverageLedger, unknown_beside_complete
from test_decisions import (
    ALL_TABLES,
    BACKUP_TABLES,
    BALANCE_TABLES,
    REAL_LEDGER_TABLES,
    CLASSIFICATION_TABLES,
    DECLARATION_TABLES,
    ONE_SIDED_TABLES,
    TRANSFER_TABLES,
    pair_up,
)
from test_resolutions import CAFE_NO_AMOUNT

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_10_TABLES = tuple(table for table in ALL_TABLES
                          if table not in (*DECLARATION_TABLES, *CLASSIFICATION_TABLES,
                                           *TRANSFER_TABLES, *ONE_SIDED_TABLES,
                                           *BALANCE_TABLES))


def set_back_to_version_10(path) -> None:
    conn = connect(path)
    for table in (*BACKUP_TABLES, *REAL_LEDGER_TABLES, *BALANCE_TABLES, *ONE_SIDED_TABLES, *TRANSFER_TABLES, *CLASSIFICATION_TABLES, *DECLARATION_TABLES):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 10")
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """A decision, a completed row and open items, with no declaration."""
    ledger = CoverageLedger(tmp_path, capsys)
    item, one, two = pair_up(ledger)
    confirm_ok(ledger, item, (one, two))
    ledger.card("c.csv", CAFE_NO_AMOUNT)
    (unresolved,) = ledger.unresolved()
    ledger.complete_ok(unresolved, amount="-1.00")
    set_back_to_version_10(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_and_changes_nothing_else(self, populated, tmp_path):
        before = populated.dump(VERSION_10_TABLES)
        conn = connect(populated.path)
        folder = tmp_path / "eleven"
        folder.mkdir()
        for migration in load_migrations()[:11]:
            (folder / migration.path.name).write_text(migration.path.read_text())
        assert migrate(conn, folder) == 11
        for table in DECLARATION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_10_TABLES) == before
        assert "have not been reconciled" not in populated.totals()

    def test_declarations_work_after_it_without_reconciling(self, populated):
        assert populated.run("migrate")[0] == 0
        populated.declare_ok("c.csv", **MONTH)

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = tmp_path / "broken"
        folder.mkdir()
        migrations = load_migrations()
        for migration in migrations:
            (folder / migration.path.name).write_text(migration.path.read_text())
        (folder / migrations[10].path.name).write_text(
            migrations[10].path.read_text() + "SELECT no_such_function();"
        )
        before = populated.dump(VERSION_10_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 10
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(DECLARATION_TABLES)
        conn.close()
        assert populated.dump(VERSION_10_TABLES) == before


@pytest.fixture
def declared(tmp_path, capsys):
    ledger = CoverageLedger(tmp_path, capsys)
    unknown_beside_complete(ledger)
    declaration = ledger.declare_ok("a.csv", **MONTH)
    assert ledger.undo_declaration(declaration, ledger.undo_token("a.csv"))[0] == 0
    return ledger


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE coverage_declaration SET coverage_end = coverage_start",
        "DELETE FROM coverage_declaration",
        "INSERT INTO coverage_declaration SELECT * FROM coverage_declaration",
        "UPDATE coverage_declaration_event SET event = 'made'",
        "DELETE FROM coverage_declaration_event",
        "INSERT INTO coverage_declaration_event (declaration_id, event) "
        "SELECT declaration_id, event FROM coverage_declaration_event",
    ])
    def test_history_refuses_change(self, declared, statement):
        before = declared.dump(DECLARATION_TABLES)
        conn = declared.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert declared.dump(DECLARATION_TABLES) == before

    @pytest.mark.parametrize(("kind", "start", "end", "basis"), [
        ("complete", "2026-01-01", None, "posting"),
        ("complete", "2026-01-20", "2026-01-01", "posting"),
        ("unknown", "2026-01-01", None, None),
        ("partial", None, None, None),
        ("complete", "2026-01-01", "2026-01-20", "weekly"),
    ])
    def test_a_stored_declaration_must_fit_its_kind(self, declared, kind, start, end, basis):
        conn = declared.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO coverage_declaration (id, account_id, source_document_id,
                                                     coverage_kind, coverage_start, coverage_end,
                                                     date_basis, target_revision)
                   SELECT 'x', account_id, source_document_id, ?, ?, ?, ?, 'v1-0'
                   FROM document_coverage LIMIT 1""",
                (kind, start, end, basis),
            )
        conn.close()

    def test_a_declaration_supersedes_only_its_own_document(self, declared):
        conn = declared.conn()
        (other_document,) = conn.execute(
            """SELECT coverage.source_document_id FROM document_coverage coverage
               WHERE coverage.source_document_id NOT IN
                   (SELECT source_document_id FROM coverage_declaration)"""
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO coverage_declaration (id, account_id, source_document_id,
                                                     coverage_kind, supersedes_declaration_id,
                                                     target_revision)
                   SELECT 'x', account_id, ?, 'unknown', id, 'v1-0' FROM coverage_declaration""",
                (other_document,),
            )
        conn.close()
