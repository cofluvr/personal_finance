"""Migration 0013 on a populated ledger (F13, D-053).

A ledger built at the latest version, with 0013's empty tables dropped and set back to version 12, is
a version 12 ledger: 0013 only creates tables. Migration stops at 13, so that only 0013 is tested.
"""

import sqlite3

import pytest
from test_confirmations import confirm_ok
from test_coverage_declarations import MONTH, CoverageLedger
from test_decisions import ALL_TABLES, CLASSIFICATION_TABLES, pair_up
from test_resolutions import CAFE_NO_AMOUNT

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_12_TABLES = tuple(table for table in ALL_TABLES if table not in CLASSIFICATION_TABLES)


def set_back_to_version_12(path) -> None:
    conn = connect(path)
    for table in CLASSIFICATION_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 12")
    conn.close()


def migrations_up_to(folder, version):
    folder.mkdir()
    for migration in load_migrations()[:version]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


@pytest.fixture
def populated(tmp_path, capsys):
    """A decision, a correction, a completed row and a declaration, with no classification."""
    ledger = CoverageLedger(tmp_path, capsys)
    item, one, two = pair_up(ledger)
    confirm_ok(ledger, item, (one, two))
    ledger.card("c.csv", CAFE_NO_AMOUNT)
    (unresolved,) = ledger.unresolved()
    ledger.complete_ok(unresolved, amount="-1.00")
    ledger.correct_ok(ledger.run("transactions")[1].split()[0], "posting_date", "2026-01-12")
    ledger.declare_ok("c.csv", **MONTH)
    set_back_to_version_12(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_makes_no_account_stale_and_changes_nothing_else(
            self, populated, tmp_path):
        before = populated.dump(VERSION_12_TABLES)
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "thirteen", 13)) == 13
        for table in CLASSIFICATION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_12_TABLES) == before
        assert "have not been reconciled" not in populated.totals()

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 13)
        thirteenth = load_migrations()[12].path
        (folder / thirteenth.name).write_text(thirteenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_12_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 12
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(CLASSIFICATION_TABLES)
        conn.close()
        assert populated.dump(VERSION_12_TABLES) == before
