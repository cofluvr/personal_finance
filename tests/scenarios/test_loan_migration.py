"""Migration 0030, loan terms and the payoff plan, on a populated ledger (LB1, D-067 G10, D-071),
using synthetic data only. Its tables are empty, nothing shown changes, a ledger at 29 is refused
until migrate, a failure leaves everything as it was, and its tables are append-only."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_it_adds_empty_tables_and_changes_nothing_shown,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
)
from test_decisions import LINK_TABLES, LOAN_TABLES, drop_loan_tables
from test_funds import FundLedger
from test_link_migration import VERSION_28_TABLES

from personal_finance.db.migrate import connect

VERSION_29_TABLES = (*VERSION_28_TABLES, *LINK_TABLES)
AS_OF = "2026-03-31"


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("balance", "list"),
        ("report", "net-worth", "--as-of", AS_OF), ("account", "links"))]


@pytest.fixture
def populated(tmp_path, capsys):
    """A loan observed and a card, set back to 29, with what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.add_typed_account("Mortgage", "loan")
    ledger.observe("Mortgage", "2026-03-01", "1000.00", option="--owed")
    ledger.pay("b1.csv", "2026-03-05", amount="-85.00", text="SYNTHETIC SHOP")
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_loan_tables(conn)
    conn.execute("PRAGMA user_version = 29")
    conn.close()
    return ledger


class TestMigration:  # LB1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        assert_it_adds_empty_tables_and_changes_nothing_shown(
            populated, tmp_path, version=30, tables_before=VERSION_29_TABLES,
            new_tables=LOAN_TABLES, shown_now=shown_now)

    def test_a_ledger_at_29_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "account", "links")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=30, migration_name="0030_loan_terms.sql",
            tables_before=VERSION_29_TABLES, new_tables=LOAN_TABLES)


@pytest.fixture
def stated(tmp_path, capsys):
    ledger = FundLedger(tmp_path, capsys)
    ledger.add_typed_account("Mortgage", "loan")
    ledger.add_typed_account("Card", "credit_card")
    conn = ledger.conn()
    ledger.ids = dict(conn.execute("SELECT display_name, id FROM account"))
    conn.execute("INSERT INTO loan_terms (id, account_id, due_day) VALUES ('t', ?, 5)",
                 (ledger.ids["Mortgage"],))
    conn.execute("INSERT INTO loan_terms (id, account_id, due_day) VALUES ('c', ?, 5)",
                 (ledger.ids["Card"],))
    conn.execute("INSERT INTO loan_terms_event (terms_id, event) VALUES ('t', 'made')")
    conn.execute("INSERT INTO loan_rate_period (terms_id, effective_from, rate_millionths) "
                 "VALUES ('t', '2026-01-01', 6875000)")
    conn.execute("INSERT INTO loan_payment_period (terms_id, effective_from, payment_cents) "
                 "VALUES ('t', '2026-01-01', 150000)")
    conn.execute("INSERT INTO payoff_plan (id, order_kind) VALUES ('p', 'avalanche')")
    conn.execute("INSERT INTO payoff_plan_event (plan_id, event) VALUES ('p', 'made')")
    conn.close()
    return ledger


STATED = ("payoff_plan_event", "payoff_plan", "loan_payment_period", "loan_rate_period",
          "loan_terms_event", "loan_terms")


class TestAppendOnly:  # LB1, G2
    @pytest.mark.parametrize("table", STATED)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        assert_rows_refuse_update_delete_and_replace(stated, table, STATED)

    def test_a_control_insert_of_each_succeeds(self, stated):
        conn = stated.conn()
        for statement in (
            "INSERT INTO loan_terms_event (terms_id, event) VALUES ('t', 'undone')",
            "INSERT INTO loan_rate_period (terms_id, effective_from, rate_millionths) "
            "VALUES ('c', '2026-01-01', 24990000)",
            "INSERT INTO loan_payment_period (terms_id, effective_from, payment_cents) "
            "VALUES ('t', '2027-01-01', 160000)",
            "INSERT INTO payoff_plan (id, order_kind, custom_order, extra_cents) "
            "VALUES ('q', 'custom', 'a,b', 10000)",
            "INSERT INTO payoff_plan_event (plan_id, event) VALUES ('q', 'made')",
        ):
            conn.execute(statement)
        conn.close()

    @pytest.mark.parametrize("statement", [
        "INSERT INTO loan_terms (id, account_id, due_day) VALUES ('x', :checking, 5)",
        "INSERT INTO loan_terms (id, account_id, due_day) VALUES ('x', :loan, 29)",
        "INSERT INTO loan_terms (id, account_id, due_day, remaining_months) "
        "VALUES ('x', :loan, 5, 0)",
        "INSERT INTO loan_rate_period (terms_id, effective_from, rate_millionths) "
        "VALUES ('t', '2026-02-01', 100000001)",
        "INSERT INTO loan_rate_period (terms_id, effective_from, rate_millionths) "
        "VALUES ('t', '2026-02-30', 1)",
        "INSERT INTO loan_payment_period (terms_id, effective_from, payment_cents) "
        "VALUES ('t', '2026-02-01', 0)",
        "INSERT INTO loan_payment_period (terms_id, effective_from, payment_cents) "
        "VALUES ('c', '2026-02-01', 100)",
        "INSERT INTO payoff_plan (id, order_kind) VALUES ('x', 'largest')",
        "INSERT INTO payoff_plan (id, order_kind) VALUES ('x', 'custom')",
        "INSERT INTO payoff_plan (id, order_kind, custom_order) VALUES ('x', 'avalanche', 'a')",
        "INSERT INTO payoff_plan (id, order_kind, extra_cents, extra_fund_id) "
        "VALUES ('x', 'avalanche', 1, 'f')",
        "INSERT INTO payoff_plan_event (plan_id, event) VALUES ('p', 'undone')",
    ])
    def test_a_row_it_does_not_take_is_refused(self, stated, statement):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement, {"checking": stated.ids["A"], "loan": stated.ids["Mortgage"]})
        conn.close()
