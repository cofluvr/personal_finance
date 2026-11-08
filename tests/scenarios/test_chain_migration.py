"""Migration 0008 on a populated ledger holding a superseding chain (N12, N13, D-048).

0008 changes no schema, so a ledger built at the latest version, set back to version 7 and stripped
of 0009's empty tables is a version 7 ledger. Building it with the current code is what lets the
chain be made at all.
"""

import re
import sqlite3
from pathlib import Path

import pytest
from test_confirmations import confirm_ok
from test_decisions import ALL_TABLES, CAFE
from test_separations import SeparationLedger
from test_supersession import chain_of_three
from test_decisions import (
    CLASSIFICATION_TABLES,
    DECLARATION_TABLES,
    RESOLUTION_TABLES,
    TRANSFER_TABLES,
)

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.reconcile.decisions import STALE_ACCOUNT


def markers(conn):
    return dict(conn.execute(
        """SELECT account.display_name, marker.rules_fingerprint FROM account_reconciliation marker
           JOIN account ON account.id = marker.account_id"""
    ))


# Created by 0009 to 0011 and 0013, children first. Nothing in these ledgers corrects a value,
# resolves a record, declares coverage or classifies a transaction.
VERSION_9_TABLES = (*TRANSFER_TABLES, "transaction_correction", "value_correction_event", "value_correction_record",
                    "value_correction", *RESOLUTION_TABLES, *DECLARATION_TABLES,
                    *CLASSIFICATION_TABLES)


def set_back(path: Path) -> None:
    conn = connect(path)
    for table in VERSION_9_TABLES:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 7")
    conn.close()


VERSION_8_TABLES = tuple(table for table in ALL_TABLES if table not in VERSION_9_TABLES)


def up_to_version_8(folder: Path) -> Path:
    folder.mkdir()
    for migration in load_migrations()[:8]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


@pytest.fixture
def chained(tmp_path, capsys):
    """Account A holds a chain of three. Account B holds one decision superseding another."""
    ledger = SeparationLedger(tmp_path, capsys)
    chain = chain_of_three(ledger)
    earlier = set(ledger.items())
    ledger.add_account("B")
    for name in ("p.csv", "q.csv", "r.csv"):
        ledger.card(name, CAFE, account="B")
    (item,) = set(ledger.items()) - earlier
    one, two, _ = ledger.transactions(item)
    code, out, _ = ledger.reject(item, (one, two), account="B")
    assert code == 0
    old = re.search(r"Decision (\S+) recorded", out)[1]
    confirm_ok(ledger, item, (one, two), account="B", supersedes=old)
    set_back(ledger.path)
    return ledger, chain


class TestMigration:  # N12
    def test_only_an_account_holding_a_chain_loses_its_marker(self, chained, tmp_path):
        ledger, _ = chained
        conn = connect(ledger.path)
        before = markers(conn)
        assert migrate(conn, up_to_version_8(tmp_path / "eight")) == 8
        assert markers(conn) == {"B": before["B"]}
        conn.close()

    def test_nothing_else_changes(self, chained, tmp_path):
        ledger, _ = chained
        before = ledger.dump(VERSION_8_TABLES)
        conn = connect(ledger.path)
        migrate(conn, up_to_version_8(tmp_path / "eight"))
        conn.close()
        after = ledger.dump(VERSION_8_TABLES)
        for table, rows in before.items():
            if table != "account_reconciliation":
                assert after[table] == rows, table

    def test_a_failure_leaves_everything_as_it_was(self, chained, tmp_path):
        ledger, _ = chained
        folder = tmp_path / "broken"
        folder.mkdir()
        migrations = load_migrations()[:8]
        for migration in migrations:
            (folder / migration.path.name).write_text(migration.path.read_text())
        (folder / migrations[7].path.name).write_text(
            migrations[7].path.read_text() + "SELECT no_such_function();"
        )
        before = ledger.dump(VERSION_8_TABLES)
        conn = connect(ledger.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 7
        conn.close()
        assert ledger.dump(VERSION_8_TABLES) == before


class TestAfterMigration:  # N13
    def test_the_account_is_stale_until_reconciled(self, chained, capsys):
        ledger, (_, _, newest) = chained
        assert ledger.run("migrate")[0] == 0
        assert "have not been reconciled" in ledger.totals()
        before = ledger.dump(VERSION_8_TABLES)
        code, _, err = ledger.undo(newest, "d6-0000000000000000")
        assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump(VERSION_8_TABLES) == before

        assert ledger.run("reconcile")[0] == 0
        assert "have not been reconciled" not in ledger.totals()
        assert ledger.undo(newest)[0] == 0
