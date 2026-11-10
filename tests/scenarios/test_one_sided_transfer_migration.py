"""Migration 0015 on a populated ledger, and its append-only tables (O13, D-055).

A ledger built at the latest version, with 0015's empty tables dropped and set back to version 14, is
a version 14 ledger: 0015 creates tables only. Migration stops at 15, so that only 0015 is tested.
"""

import sqlite3

import pytest
from test_decisions import ALL_TABLES, BACKUP_TABLES, BALANCE_TABLES, ONE_SIDED_TABLES, REAL_LEDGER_TABLES, drop_category_tables
from test_one_sided_transfers import OneSidedLedger, stated
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to
from test_transfers import matched

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_14_TABLES = tuple(table for table in ALL_TABLES
                          if table not in (*ONE_SIDED_TABLES, *BALANCE_TABLES))


def set_back_to_version_14(path) -> None:
    conn = connect(path)
    drop_category_tables(conn)
    for table in (*BACKUP_TABLES, *REAL_LEDGER_TABLES, *BALANCE_TABLES, *ONE_SIDED_TABLES):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 14")
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """Two accounts holding a transfer match and a classified transaction."""
    ledger = OneSidedLedger(tmp_path, capsys)
    ledger.add_account("S", "savings")
    matched(ledger)
    ledger.card("alone.csv", "03/10/2026,SYNTHETIC MOVE OUT,7.00,")
    ledger.classify_ok(holding(ledger, "alone.csv"), "transfer")
    set_back_to_version_14(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_and_makes_no_account_stale(self, populated, tmp_path):
        before = populated.dump(VERSION_14_TABLES)
        assert markers(populated) == ["A", "S"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "fifteen", 15)) == 15
        for table in ONE_SIDED_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_14_TABLES) == before
        assert markers(populated) == ["A", "S"]
        assert "have not been reconciled" not in populated.totals()

    def test_one_sided_transfers_work_after_it(self, populated):
        assert populated.run("migrate")[0] == 0
        populated.one_sided_ok(holding(populated, "alone.csv"))
        assert populated.one_sided_states() == [("applied", ("alone.csv",))]
        assert populated.matches() == [("applied", ("out.csv",), ("in.csv",))]

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 15)
        fifteenth = load_migrations()[14].path
        (folder / fifteenth.name).write_text(fifteenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_14_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 14
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(ONE_SIDED_TABLES)
        conn.close()
        assert populated.dump(VERSION_14_TABLES) == before


@pytest.fixture
def history(tmp_path, capsys):
    """A one-sided transfer stated and undone, and one active."""
    ledger = OneSidedLedger(tmp_path, capsys)
    ledger.add_account("S", "savings")
    ledger.add_account("Card", "credit_card")
    statement, transaction = stated(ledger)
    assert ledger.undo_one_sided(statement)[0] == 0
    ledger.one_sided_ok(transaction)
    ledger.card("s.csv", "02/20/2026,SYNTHETIC GROCER,9.00,", account="S")
    return ledger


def ids(conn):
    accounts = dict(conn.execute("SELECT display_name, id FROM account"))
    records = dict(conn.execute(
        """SELECT document.file_name, record.id FROM source_record record
           JOIN source_document document ON document.id = record.source_document_id"""
    ))
    return accounts, records


def new_statement(conn, account, counterpart):
    conn.execute(
        """INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                           target_transaction_id, target_revision)
           VALUES ('new', ?, ?, 't', 't10-0')""",
        (account, counterpart),
    )


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE one_sided_transfer SET target_revision = 't10-0'",
        "DELETE FROM one_sided_transfer",
        "INSERT INTO one_sided_transfer SELECT * FROM one_sided_transfer",
        "UPDATE one_sided_transfer_record SET source_record_id = source_record_id",
        "DELETE FROM one_sided_transfer_record",
        "INSERT INTO one_sided_transfer_record SELECT * FROM one_sided_transfer_record",
        "UPDATE one_sided_transfer_event SET event = 'made'",
        "DELETE FROM one_sided_transfer_event",
        "INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) "
        "SELECT one_sided_transfer_id, event FROM one_sided_transfer_event",
    ])
    def test_history_refuses_change(self, history, statement):
        stored = ONE_SIDED_TABLES[1:]
        before = history.dump(stored)
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.dump(stored) == before

    def test_the_counterpart_is_another_account(self, history):
        conn = history.conn()
        accounts, _ = ids(conn)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            new_statement(conn, accounts["A"], accounts["A"])
        new_statement(conn, accounts["A"], accounts["Card"])
        conn.close()

    def test_it_binds_records_of_its_own_account(self, history):
        conn = history.conn()
        accounts, records = ids(conn)
        new_statement(conn, accounts["A"], accounts["Card"])
        insert = "INSERT INTO one_sided_transfer_record VALUES ('new', ?)"
        with pytest.raises(sqlite3.IntegrityError, match="its own account"):
            conn.execute(insert, (records["s.csv"],))
        conn.execute(insert, (records["out.csv"],))
        conn.close()

    @pytest.mark.parametrize(("state", "with_transaction"), [
        ("applied", False), ("counterpart_found", True), ("matched", True),
    ])
    def test_a_derived_row_must_fit_its_state(self, history, state, with_transaction):
        conn = history.conn()
        # Derived and rewritten wherever matches are, so it may be cleared.
        conn.execute("DELETE FROM one_sided_transfer_effect")
        (statement,) = conn.execute(
            """SELECT id FROM one_sided_transfer WHERE id NOT IN (
                   SELECT one_sided_transfer_id FROM one_sided_transfer_event
                   WHERE event = 'undone')""").fetchone()
        (transaction,) = conn.execute(
            "SELECT id FROM ledger_transaction WHERE amount_cents = -5000").fetchone()
        insert = "INSERT INTO one_sided_transfer_effect VALUES (?, ?, ?)"
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(insert, (statement, state, transaction if with_transaction else None))
        conn.execute(insert, (statement, "applied", transaction))
        conn.close()

    def test_no_transaction_holds_two_applied_ones(self, history):
        conn = history.conn()
        conn.execute("DELETE FROM one_sided_transfer_effect")
        first, second = (row[0] for row in conn.execute(
            "SELECT id FROM one_sided_transfer ORDER BY id"))
        (transaction,) = conn.execute(
            "SELECT id FROM ledger_transaction WHERE amount_cents = -5000").fetchone()
        insert = "INSERT INTO one_sided_transfer_effect VALUES (?, 'applied', ?)"
        conn.execute(insert, (first, transaction))
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(insert, (second, transaction))
        conn.execute("INSERT INTO one_sided_transfer_effect VALUES (?, 'conflict', NULL)",
                     (second,))
        conn.close()
