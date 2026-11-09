"""Migration 0017 on a populated ledger (H6, D-058).

A ledger built at the latest version, with 0017's empty table dropped and set back to version 16, is a
version 16 ledger: 0017 creates a table and its triggers only. Migration stops at 17, so that only
0017 is tested.
"""

import sqlite3

import pytest
from test_balance_observations import BalanceLedger
from test_decisions import ALL_TABLES, REAL_LEDGER_TABLES
from test_one_sided_transfers import stated
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.db.real_ledger import is_real_ledger

VERSION_16_TABLES = (*ALL_TABLES, "account", "import_run")


def set_back_to_version_16(path) -> None:
    conn = connect(path)
    for table in REAL_LEDGER_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 16")
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """Checking A and savings S, holding February's rows, a one-sided transfer and an observation."""
    ledger = BalanceLedger(tmp_path, capsys)
    ledger.add_account("S", "savings")
    ledger.rows("feb.csv", "X1,2026-01-30,2026-02-01,SYNTHETIC SHOP,-20.00,POSTED")
    stated(ledger)
    ledger.record_ok("2026-01-31", "100.00")
    set_back_to_version_16(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_an_empty_table_and_makes_no_account_stale(self, populated, tmp_path):
        before = populated.dump(VERSION_16_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "seventeen", 17)) == 17
        assert conn.execute("SELECT COUNT(*) FROM real_ledger").fetchone()[0] == 0
        assert not is_real_ledger(conn)
        conn.close()
        assert populated.dump(VERSION_16_TABLES) == before
        assert markers(populated) == ["A"]
        assert "have not been reconciled" not in populated.totals()

    def test_the_ledger_stays_synthetic_and_cannot_be_marked(self, populated):
        assert populated.run("migrate")[0] == 0
        conn = connect(populated.path)
        with pytest.raises(sqlite3.IntegrityError, match="holding nothing yet"):
            conn.execute("INSERT INTO real_ledger (only_row) VALUES (1)")
        assert not is_real_ledger(conn)
        conn.close()

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 17)
        seventeenth = load_migrations()[16].path
        (folder / seventeenth.name).write_text(seventeenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_16_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 16
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not {name for name in names if name.startswith("real_ledger")}
        conn.close()
        assert populated.dump(VERSION_16_TABLES) == before
