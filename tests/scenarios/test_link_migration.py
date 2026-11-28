"""Migration 0029, account links, on a populated ledger (LA1, D-067 G10, D-071), using synthetic
data only. Its tables are empty, nothing shown changes, a ledger at 28 is refused until migrate,
a failure leaves everything as it was, and its tables are append-only."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_it_adds_empty_tables_and_changes_nothing_shown,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
)
from test_consumption_migration import VERSION_27_TABLES
from test_decisions import CONSUMPTION_TABLES, LINK_TABLES, drop_link_tables
from test_funds import FundLedger

from personal_finance.db.migrate import connect

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
        assert_it_adds_empty_tables_and_changes_nothing_shown(
            populated, tmp_path, version=29, tables_before=VERSION_28_TABLES,
            new_tables=LINK_TABLES, shown_now=shown_now)

    def test_a_ledger_at_28_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "funds", "--as-of", AS_OF)

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=29, migration_name="0029_account_links.sql",
            tables_before=VERSION_28_TABLES, new_tables=LINK_TABLES)


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
        assert_rows_refuse_update_delete_and_replace(stated, table, LINK_TABLES)

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
