"""Migration 0031, loan payment breakdowns, on a populated ledger (LC1, D-067 G10, D-071), using
synthetic data only. Its tables are empty, nothing shown changes, a ledger at 30 is refused until
migrate, a failure leaves everything as it was, and its stated tables are append-only."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_it_adds_empty_tables_and_changes_nothing_shown,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
)
from test_decisions import BREAKDOWN_TABLES, LOAN_TABLES, drop_breakdown_tables
from test_funds import FundLedger
from test_loan_migration import VERSION_29_TABLES

from personal_finance.db.migrate import connect

VERSION_30_TABLES = (*VERSION_29_TABLES, *LOAN_TABLES)
STATED = ("loan_payment_breakdown_event", "loan_payment_breakdown_record",
          "loan_payment_breakdown")


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("report", "household"), ("transactions",),
        ("report", "loans", "--as-of", "2026-03-31"))]


@pytest.fixture
def populated(tmp_path, capsys):
    """A loan payment confirmed to a loan, set back to 30, with what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.add_typed_account("Mortgage", "loan")
    payment = ledger.pay("p1.csv", "2026-03-05", amount="-1500.00", text="SYNTHETIC MORTGAGE",
                         financial_type="loan_payment")
    assert ledger.one_sided(payment, "Mortgage")[0] == 0
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_breakdown_tables(conn)
    conn.execute("PRAGMA user_version = 30")
    conn.close()
    return ledger


class TestMigration:  # LC1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        assert_it_adds_empty_tables_and_changes_nothing_shown(
            populated, tmp_path, version=31, tables_before=VERSION_30_TABLES,
            new_tables=BREAKDOWN_TABLES, shown_now=shown_now)

    def test_a_ledger_at_30_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "totals")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=31, migration_name="0031_loan_breakdowns.sql",
            tables_before=VERSION_30_TABLES, new_tables=BREAKDOWN_TABLES)


@pytest.fixture
def stated(tmp_path, capsys):
    ledger = FundLedger(tmp_path, capsys)
    ledger.pay("p1.csv", "2026-03-05", amount="-1500.00", financial_type="loan_payment")
    ledger.add_typed_account("B2", "checking")
    conn = ledger.conn()
    ledger.ids = dict(conn.execute("SELECT display_name, id FROM account"))
    record = conn.execute("SELECT id FROM source_record").fetchone()[0]
    conn.execute("INSERT INTO loan_payment_breakdown (id, account_id, breakdown, "
                 "target_transaction_id, target_revision) VALUES ('b', ?, '57250:0', 'x', 't13-0')",
                 (ledger.ids["A"],))
    conn.execute("INSERT INTO loan_payment_breakdown_record (breakdown_id, source_record_id) "
                 "VALUES ('b', ?)", (record,))
    conn.execute("INSERT INTO loan_payment_breakdown_event (breakdown_id, event) "
                 "VALUES ('b', 'made')")
    conn.close()
    return ledger


class TestAppendOnly:  # LC1, G2
    @pytest.mark.parametrize("table", STATED)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        assert_rows_refuse_update_delete_and_replace(stated, table, STATED)

    def test_a_control_insert_of_each_succeeds(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO loan_payment_breakdown (id, account_id, breakdown, "
                     "target_transaction_id, target_revision, supersedes_breakdown_id) "
                     "VALUES ('c', ?, '0:500', 'x', 't13-0', 'b')", (stated.ids["A"],))
        conn.execute("INSERT INTO loan_payment_breakdown_event (breakdown_id, event) "
                     "VALUES ('b', 'undone')")
        conn.execute("INSERT INTO transaction_loan_breakdown (transaction_id, state, breakdown) "
                     "VALUES ((SELECT id FROM ledger_transaction), 'applied', '57250:0')")
        conn.close()

    @pytest.mark.parametrize("statement", [
        "INSERT INTO loan_payment_breakdown (id, account_id, breakdown, target_transaction_id, "
        "target_revision) VALUES ('x', :a, '0:0', 'x', 't13-0')",
        "INSERT INTO loan_payment_breakdown (id, account_id, breakdown, target_transaction_id, "
        "target_revision) VALUES ('x', :a, '-5:0', 'x', 't13-0')",
        "INSERT INTO loan_payment_breakdown (id, account_id, breakdown, target_transaction_id, "
        "target_revision) VALUES ('x', :a, '5.00:0', 'x', 't13-0')",
        "INSERT INTO loan_payment_breakdown (id, account_id, breakdown, target_transaction_id, "
        "target_revision, supersedes_breakdown_id) VALUES ('x', :b2, '5:0', 'x', 't13-0', 'b')",
        "INSERT INTO loan_payment_breakdown_event (breakdown_id, event) VALUES ('b', 'paused')",
        "INSERT INTO transaction_loan_breakdown (transaction_id, state, breakdown) "
        "VALUES ((SELECT id FROM ledger_transaction), 'applied', NULL)",
        "INSERT INTO transaction_loan_breakdown (transaction_id, state, breakdown) "
        "VALUES ((SELECT id FROM ledger_transaction), 'split', NULL)",
    ])
    def test_a_row_it_does_not_take_is_refused(self, stated, statement):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement, {"a": stated.ids["A"], "b2": stated.ids["B2"]})
        conn.close()
