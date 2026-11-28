"""Migration 0026, settings and budget plans, on a populated ledger (BA1, D-067 G10, D-069),
using synthetic data only. Its tables are empty, nothing shown changes, a ledger at 24 is refused
until migrate, a failure leaves everything as it was, and every stated table is append-only."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
    markers,
    migrations_up_to,
)
from test_decisions import (
    ALL_TABLES,
    ALLOCATION_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    HOUSEHOLD_TABLES,
    BUDGET_TABLES,
    INCOME_TABLES,
    OBLIGATION_TABLES,
    SETTING_KEY_TABLES,
    drop_budget_tables,
)
from test_income_sources import IncomeLedger
from test_supersession import holding

from personal_finance.db.migrate import connect, migrate

VERSION_25_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES, *ALLOCATION_TABLES, *INCOME_TABLES,
                     *OBLIGATION_TABLES)

SHOWN_BEFORE_AND_AFTER = [("totals",), ("report", "monthly"), ("transactions",),
                          ("review", "classifications"), ("category", "rules"),
                          ("household", "members"), ("review", "allocations"),
                          ("income", "sources"), ("income", "proposals")]


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        *SHOWN_BEFORE_AND_AFTER, ("review", "transaction", "show", holding(ledger, "b1.csv")))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Checking A holding a bill typed purchase and a paycheck under an income source, set back to
    25, with what was shown before."""
    ledger = IncomeLedger(tmp_path, capsys)
    ledger.deposit("b1.csv", "2026-01-05", amount="-85.00", text="SYNTHETIC POWER CO",
                   financial_type="purchase")
    ledger.deposit("p1.csv", "2026-01-02")
    ledger.add_ok()
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_budget_tables(conn)
    conn.execute("PRAGMA user_version = 25")
    conn.close()
    return ledger


class TestMigration:  # IB1
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_25_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-six", 26)) == 26
        for table in BUDGET_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT * FROM ledger_setting_key").fetchall() == [
            ("household_timezone",)]
        conn.close()
        assert populated.dump(VERSION_25_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_25_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "income", "sources")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=26, migration_name="0026_settings_and_budgets.sql",
            tables_before=VERSION_25_TABLES, new_tables={*BUDGET_TABLES,*SETTING_KEY_TABLES})


@pytest.fixture
def stated(tmp_path, capsys):
    """One row in every stated table of 0026, written by hand."""
    ledger = IncomeLedger(tmp_path, capsys)
    conn = ledger.conn()
    conn.execute("INSERT INTO household_member (name) VALUES ('M')")
    conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                 "VALUES ('s', 'household_timezone', 'America/Chicago')")
    conn.execute("INSERT INTO ledger_setting_event (setting_id, event) VALUES ('s', 'made')")
    conn.execute("INSERT INTO budget_plan (id, effective_from, allowance_cents, "
                 "corrected_closed_month) VALUES ('p', '2026-01', 100000, 0)")
    conn.execute("INSERT INTO budget_plan_member_part VALUES ('p', 1, 100000)")
    conn.execute("INSERT INTO budget_plan_category VALUES ('p', 3, 40000)")
    conn.execute("INSERT INTO budget_plan_event (plan_id, event) VALUES ('p', 'made')")
    conn.close()
    return ledger


EVERY_TABLE = (*SETTING_KEY_TABLES, *BUDGET_TABLES)


class TestAppendOnly:  # BA1, G2
    @pytest.mark.parametrize("table", EVERY_TABLE)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        assert_rows_refuse_update_delete_and_replace(stated, table, EVERY_TABLE)

    def test_a_control_insert_of_each_succeeds(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO household_member (name) VALUES ('N')")
        conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                     "VALUES ('s2', 'household_timezone', 'UTC')")
        conn.execute("INSERT INTO ledger_setting_event (setting_id, event) "
                     "VALUES ('s', 'undone')")
        conn.execute("INSERT INTO budget_plan (id, effective_from, allowance_cents, "
                     "supersedes_id, corrected_closed_month) VALUES ('q', '2026-02', 0, 'p', 1)")
        conn.execute("INSERT INTO budget_plan_member_part VALUES ('p', 2, 0)")
        conn.execute("INSERT INTO budget_plan_category VALUES ('p', 4, 0)")
        conn.execute("INSERT INTO budget_plan_event (plan_id, event) VALUES ('p', 'undone')")
        conn.close()

    @pytest.mark.parametrize("statement", [
        "INSERT INTO ledger_setting (id, setting_key, value) VALUES ('x', 'no_such_key', 'v')",
        "INSERT INTO ledger_setting (id, setting_key, value) VALUES ('x', 'household_timezone', ' ')",
        "INSERT INTO budget_plan (id, effective_from, allowance_cents, corrected_closed_month) "
        "VALUES ('x', '2026-13', 0, 0)",
        "INSERT INTO budget_plan (id, effective_from, allowance_cents, corrected_closed_month) "
        "VALUES ('x', '2026-01', -1, 0)",
        "INSERT INTO budget_plan (id, effective_from, allowance_cents, corrected_closed_month) "
        "VALUES ('x', '2026-01-01', 0, 0)",
        "INSERT INTO budget_plan_member_part VALUES ('p', 99, 0)",
        "INSERT INTO budget_plan_category VALUES ('p', 4, -1)",
        "INSERT INTO budget_plan_event (plan_id, event) VALUES ('p', 'paused')",
    ])
    def test_a_row_it_does_not_take_is_refused(self, stated, statement):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
        conn.close()
