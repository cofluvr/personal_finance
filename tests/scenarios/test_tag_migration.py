"""Migration 0033, tags and tag statements, on a populated ledger (WC1, D-067 G10, D-073 point 5),
using synthetic data only. Its tables are empty, nothing else shown changes, a ledger at 32 is
refused until migrate, a failure leaves everything as it was, and its tables are append-only,
each check refusing on its own with a control that succeeds."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_it_adds_empty_tables_and_changes_nothing_shown,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
)
from test_decisions import CAFE, TAG_TABLES, LIQUIDITY_TABLES, drop_tag_tables
from test_liquidity_migration import VERSION_31_TABLES
from test_funds import FundLedger

from personal_finance.db.migrate import connect

VERSION_32_TABLES = (*VERSION_31_TABLES, *LIQUIDITY_TABLES)


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("transactions",), ("review", "list"),
        ("category", "list"), ("account", "liquidity", "show"))]


@pytest.fixture
def populated(tmp_path, capsys):
    """A purchase and a possible duplicate, set back to 32, with what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    ledger.card("b.csv", CAFE)
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_tag_tables(conn)
    conn.execute("PRAGMA user_version = 32")
    conn.close()
    return ledger


class TestMigration:  # WC1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        assert_it_adds_empty_tables_and_changes_nothing_shown(
            populated, tmp_path, version=33, tables_before=VERSION_32_TABLES,
            new_tables=TAG_TABLES, shown_now=shown_now)

    def test_a_ledger_at_32_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "totals")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=33, migration_name="0033_tags.sql",
            tables_before=VERSION_32_TABLES, new_tables=TAG_TABLES)


@pytest.fixture
def stated(tmp_path, capsys):
    """Two tags, and one statement of both on the purchase, with its record and event."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    conn = ledger.conn()
    ledger.account_id = conn.execute("SELECT id FROM account").fetchone()[0]
    ledger.record_id, ledger.transaction_id = conn.execute(
        "SELECT source_record_id, transaction_id FROM transaction_source").fetchone()
    conn.execute("INSERT INTO tag (name) VALUES ('Trip'), ('Work')")
    conn.execute("INSERT INTO tag_statement (id, account_id, tags, target_transaction_id, "
                 "target_revision) VALUES ('s', ?, '1,2', ?, 't13-x')",
                 (ledger.account_id, ledger.transaction_id))
    conn.execute("INSERT INTO tag_statement_record (tag_statement_id, source_record_id) "
                 "VALUES ('s', ?)", (ledger.record_id,))
    conn.execute("INSERT INTO tag_statement_event (tag_statement_id, event) VALUES ('s', 'made')")
    conn.execute("INSERT INTO transaction_tag (transaction_id, state, tags) "
                 "VALUES (?, 'applied', '1,2')", (ledger.transaction_id,))
    conn.close()
    return ledger


def statement(stated, tags, supersedes=None, statement_id="s2", account_id=None):
    conn = stated.conn()
    try:
        conn.execute("INSERT INTO tag_statement (id, account_id, tags, target_transaction_id, "
                     "target_revision, supersedes_tag_statement_id) VALUES (?, ?, ?, ?, 't', ?)",
                     (statement_id, account_id or stated.account_id, tags,
                      stated.transaction_id, supersedes))
    finally:
        conn.close()


class TestAppendOnly:  # WC1, G2
    # transaction_tag is derived and rewritten, as transaction_category is.
    @pytest.mark.parametrize("table", [table for table in TAG_TABLES
                                       if table != "transaction_tag"])
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        assert_rows_refuse_update_delete_and_replace(stated, table, TAG_TABLES)

    def test_control_inserts_succeed(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO tag (name) VALUES ('Gift ideas')")
        conn.execute("INSERT INTO tag_statement_event (tag_statement_id, event) "
                     "VALUES ('s', 'undone')")
        conn.close()
        for tags in ("", "3", "1,2,3", "10,200"):
            statement(stated, tags, supersedes="s", statement_id=f"x{tags}")

    @pytest.mark.parametrize("tags", [",1", "1,", "1,,2", "a", "1 2", "-1", "1;2"])
    def test_a_value_that_is_not_canonical_ids_is_refused(self, stated, tags):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            statement(stated, tags)

    @pytest.mark.parametrize("name", ["", " Trip", "Trip ", "a,b"])
    def test_a_tag_name_with_padding_or_a_comma_is_refused(self, stated, name):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO tag (name) VALUES (?)", (name,))
        conn.close()

    def test_a_name_is_used_once(self, stated):
        conn = stated.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("INSERT INTO tag (name) VALUES ('Trip')")
        conn.close()

    def test_a_statement_supersedes_only_one_of_its_own_account(self, stated):
        stated.add_account("B")
        conn = stated.conn()
        other = conn.execute("SELECT id FROM account WHERE display_name = 'B'").fetchone()[0]
        conn.close()
        with pytest.raises(sqlite3.IntegrityError, match="its own account"):
            statement(stated, "1", supersedes="s", account_id=other)

    def test_an_event_it_does_not_take_is_refused(self, stated):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tag_statement_event (tag_statement_id, event) "
                         "VALUES ('s', 'paused')")
        conn.close()

    @pytest.mark.parametrize("state, tags", [("applied", None), ("conflict", "1"),
                                             ("does_not_fit", None)])
    def test_a_derived_row_holds_tags_exactly_when_applied(self, stated, state, tags):
        conn = stated.conn()
        conn.execute("DELETE FROM transaction_tag")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO transaction_tag (transaction_id, state, tags) "
                         "VALUES (?, ?, ?)", (stated.transaction_id, state, tags))
        conn.close()
