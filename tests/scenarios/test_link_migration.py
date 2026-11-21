"""Migration 0029, account links, on a populated ledger (LA1, D-067 G10, D-071), using synthetic
data only. Its tables are empty, nothing shown changes, a ledger at 28 is refused until migrate,
a failure leaves everything as it was, and its tables are append-only."""

import sqlite3

import pytest
from test_consumption_migration import VERSION_27_TABLES
from test_decisions import CONSUMPTION_TABLES, LINK_TABLES, drop_link_tables
from test_funds import FundLedger
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_28_TABLES = (*VERSION_27_TABLES, *CONSUMPTION_TABLES)
AS_OF = "2026-03-15"


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("balance", "list"), ("funds", "--as-of", AS_OF),
        ("transactions",))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Two loans observed, set back to 28, with what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    for name in ("Mortgage", "Mortgage part"):
        ledger.add_typed_account(name, "loan")
        ledger.observe(name, "2026-03-01", "1000.00", option="--owed")
    ledger.pay("b1.csv", "2026-03-05", amount="-85.00", text="SYNTHETIC SHOP")
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_link_tables(conn)
    conn.execute("PRAGMA user_version = 28")
    conn.close()
    return ledger


class TestMigration:  # LA1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_28_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-nine", 29)) == 29
        for table in LINK_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_28_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_28_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("funds", "--as-of", AS_OF)
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("funds", "--as-of", AS_OF)[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 29)
        newest = load_migrations()[28].path
        assert newest.name == "0029_account_links.sql"
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_28_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 28
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(LINK_TABLES)
        conn.close()
        assert populated.dump(VERSION_28_TABLES) == before


@pytest.fixture
def stated(tmp_path, capsys):
    ledger = FundLedger(tmp_path, capsys)
    for name, account_type in (("L1", "loan"), ("L2", "loan"), ("Card", "credit_card")):
        ledger.add_typed_account(name, account_type)
    conn = ledger.conn()
    ledger.ids = dict(conn.execute("SELECT display_name, id FROM account"))
    conn.execute("INSERT INTO account_link (id, subaccount_id, aggregate_id) VALUES ('k', ?, ?)",
                 (ledger.ids["L2"], ledger.ids["L1"]))
    conn.execute("INSERT INTO account_link_event (link_id, event) VALUES ('k', 'made')")
    conn.close()
    return ledger


class TestAppendOnly:  # LA1, G2
    @pytest.mark.parametrize("table", LINK_TABLES)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        before = stated.dump(LINK_TABLES)
        conn = stated.conn()
        for statement in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}",
                          f"INSERT INTO {table} SELECT * FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(statement)
        conn.close()
        assert stated.dump(LINK_TABLES) == before

    def test_a_control_insert_succeeds(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO account_link_event (link_id, event) VALUES ('k', 'undone')")
        conn.execute("INSERT INTO account_link (id, subaccount_id, aggregate_id) "
                     "VALUES ('k2', ?, ?)", (stated.ids["L1"], stated.ids["L2"]))
        conn.close()

    @pytest.mark.parametrize("pair", [("Card", "L1"), ("L1", "Card"), ("L1", "L1"), ("A", "L1")])
    def test_a_link_that_is_not_loan_to_loan_is_refused(self, stated, pair):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO account_link (id, subaccount_id, aggregate_id) "
                         "VALUES ('x', ?, ?)", (stated.ids[pair[0]], stated.ids[pair[1]]))
        conn.close()

    def test_an_event_it_does_not_take_is_refused(self, stated):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO account_link_event (link_id, event) VALUES ('k', 'paused')")
        conn.close()
