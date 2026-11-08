"""Migration 0010 on a populated ledger, and its append-only tables (U15, D-050).

A ledger built at the latest version, with the empty tables of 0010 and 0011 dropped and set back
to version 9, is a version 9 ledger: they only create tables. Migration stops at 10, so that only 0010
is tested here.
"""

import sqlite3

import pytest
from test_confirmations import confirm_ok
from test_decisions import ALL_TABLES, CAFE, DECLARATION_TABLES, RESOLUTION_TABLES, pair_up
from test_resolutions import CAFE_NO_AMOUNT, ResolutionLedger, one_unresolved

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_9_TABLES = tuple(table for table in ALL_TABLES
                         if table not in (*RESOLUTION_TABLES, *DECLARATION_TABLES))


def up_to_version_10(folder):
    folder.mkdir()
    for migration in load_migrations()[:10]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


def set_back_to_version_9(path) -> None:
    conn = connect(path)
    for table in (*DECLARATION_TABLES, *RESOLUTION_TABLES):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 9")
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """Decisions, a correction, open items and an unresolved row, with no resolution."""
    ledger = ResolutionLedger(tmp_path, capsys)
    item, one, two = pair_up(ledger)
    confirm_ok(ledger, item, (one, two))
    ledger.card("c.csv", CAFE, CAFE_NO_AMOUNT)
    ledger.correct_ok(ledger.run("transactions")[1].split()[0], "posting_date", "2026-01-12")
    set_back_to_version_9(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_and_changes_nothing_else(self, populated, tmp_path):
        before = populated.dump(VERSION_9_TABLES)
        conn = connect(populated.path)
        assert migrate(conn, up_to_version_10(tmp_path / "ten")) == 10
        for table in RESOLUTION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_9_TABLES) == before
        assert "have not been reconciled" not in populated.totals()

    def test_resolutions_work_after_it_without_reconciling(self, populated):
        assert populated.run("migrate")[0] == 0
        (item,) = populated.unresolved()
        populated.complete_ok(item, amount="-1.00")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = tmp_path / "broken"
        folder.mkdir()
        migrations = load_migrations()
        for migration in migrations:
            (folder / migration.path.name).write_text(migration.path.read_text())
        (folder / migrations[9].path.name).write_text(
            migrations[9].path.read_text() + "SELECT no_such_function();"
        )
        before = populated.dump(VERSION_9_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 9
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(RESOLUTION_TABLES)
        conn.close()
        assert populated.dump(VERSION_9_TABLES) == before


@pytest.fixture
def resolved(tmp_path, capsys):
    ledger = ResolutionLedger(tmp_path, capsys)
    resolution = ledger.complete_ok(one_unresolved(ledger), amount="-6.00")
    ledger.undo_resolution_ok(resolution)
    return ledger


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE record_resolution SET completed_amount_cents = -1",
        "DELETE FROM record_resolution",
        "INSERT INTO record_resolution SELECT * FROM record_resolution",
        "UPDATE record_resolution_event SET event = 'made'",
        "DELETE FROM record_resolution_event",
        "INSERT INTO record_resolution_event (resolution_id, event) "
        "SELECT resolution_id, event FROM record_resolution_event",
    ])
    def test_history_refuses_change(self, resolved, statement):
        before = resolved.dump(RESOLUTION_TABLES)
        conn = resolved.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert resolved.dump(RESOLUTION_TABLES) == before

    @pytest.mark.parametrize(("kind", "amount", "posting_date", "description"), [
        ("dismissed", -600, None, None),
        ("dismissed", None, None, "CAFE"),
        ("completed", None, "2026-02-30", None),
        ("completed", None, None, "  "),
        ("ignored", None, None, None),
    ])
    def test_a_stored_resolution_must_fit_its_kind(self, resolved, kind, amount, posting_date,
                                                   description):
        conn = resolved.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO record_resolution (id, account_id, source_record_id, kind,
                                                  completed_amount_cents, completed_posting_date,
                                                  completed_description, target_issue_id,
                                                  target_revision)
                   VALUES ('x', (SELECT id FROM account), (SELECT id FROM source_record), ?, ?, ?,
                           ?, 'i', 'r6-0')""",
                (kind, amount, posting_date, description),
            )
        conn.close()
