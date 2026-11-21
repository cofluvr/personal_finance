"""Migration 0027, funds, on a populated ledger (GA1, D-067 G10, D-070), using synthetic data only.
Its tables are empty, nothing shown changes, a ledger at 26 is refused until migrate, a failure
leaves everything as it was, and every stated table is append-only."""

import sqlite3

import pytest
from test_decisions import (
    ALL_TABLES,
    ALLOCATION_TABLES,
    BUDGET_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    FUND_TABLES,
    HOUSEHOLD_TABLES,
    INCOME_TABLES,
    OBLIGATION_TABLES,
    SETTING_KEY_TABLES,
    drop_fund_tables,
)
from test_income_sources import IncomeLedger
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_26_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES, *ALLOCATION_TABLES, *INCOME_TABLES,
                     *OBLIGATION_TABLES, *SETTING_KEY_TABLES, *BUDGET_TABLES)

SHOWN_BEFORE_AND_AFTER = [("totals",), ("report", "monthly"), ("transactions",),
                          ("review", "classifications"), ("household", "members"),
                          ("income", "sources"), ("budgets",), ("setting", "show"),
                          ("balance", "list")]


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        *SHOWN_BEFORE_AND_AFTER, ("review", "transaction", "show", holding(ledger, "b1.csv")))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Checking A holding a bill, a paycheck under an income source and a balance observation,
    set back to 26, with what was shown before."""
    ledger = IncomeLedger(tmp_path, capsys)
    ledger.deposit("b1.csv", "2026-01-05", amount="-85.00", text="SYNTHETIC POWER CO",
                   financial_type="purchase")
    ledger.deposit("p1.csv", "2026-01-02")
    ledger.add_ok()
    assert ledger.run("balance", "record", "--account", "A", "--date", "2026-01-31",
                      "--balance", "4000.00")[0] == 0
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_fund_tables(conn)
    conn.execute("PRAGMA user_version = 26")
    conn.close()
    return ledger


class TestMigration:  # GA1
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_26_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-seven", 27)) == 27
        for table in FUND_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_26_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_26_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("budgets")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("budgets")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 27)
        newest = load_migrations()[26].path
        assert newest.name == "0027_funds.sql"
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_26_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 26
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(FUND_TABLES)
        conn.close()
        assert populated.dump(VERSION_26_TABLES) == before


@pytest.fixture
def stated(tmp_path, capsys):
    """One row in every stated table of 0027, written by hand."""
    ledger = IncomeLedger(tmp_path, capsys)
    conn = ledger.conn()
    account = conn.execute("SELECT id FROM account WHERE display_name = 'A'").fetchone()[0]
    conn.execute("INSERT INTO fund (id, name, kind) VALUES ('g', 'House', 'goal')")
    conn.execute("INSERT INTO fund (id, name, kind) VALUES ('r', 'Insurance', 'reserve')")
    conn.execute("INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
                 "VALUES ('g', '2026-01-01', 'monthly', 50000)")
    conn.execute("INSERT INTO fund_event (fund_id, event) VALUES ('g', 'made')")
    conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents) "
                 "VALUES ('a', 'g', ?, 100000)", (account,))
    conn.execute("INSERT INTO fund_assignment_event (assignment_id, event) VALUES ('a', 'made')")
    conn.execute("INSERT INTO fund_priority_event (list_id, event) VALUES ('l', 'made')")
    conn.execute("INSERT INTO fund_priority (list_id, position, fund_id) VALUES ('l', 1, 'g')")
    conn.close()
    ledger.account_id = account
    return ledger


class TestAppendOnly:  # GA1, G2
    @pytest.mark.parametrize("table", FUND_TABLES)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        before = stated.dump(FUND_TABLES)
        conn = stated.conn()
        for statement in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}",
                          f"INSERT INTO {table} SELECT * FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(statement)
        conn.close()
        assert stated.dump(FUND_TABLES) == before

    def test_a_control_insert_of_each_succeeds(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO fund (id, name, kind) VALUES ('e', 'Cushion', 'emergency')")
        conn.execute("INSERT INTO fund (id, name, kind) VALUES ('t', 'Tax', 'tax')")
        for statement in (
            "INSERT INTO fund_terms (fund_id, effective_from, shape, basis_points) "
            "VALUES ('g', '2026-02-01', 'percent', 1000)",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, by_month) "
            "VALUES ('g', '2026-03-01', 'target_by', 900000, '2027-06')",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
            "VALUES ('e', '2026-01-01', 'minimum', 500000)",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, month_count) "
            "VALUES ('e', '2026-02-01', 'months', 3)",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, due_date) "
            "VALUES ('r', '2026-01-01', 'due', 120000, '2026-09-01')",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, cadence, "
            "first_day, anchor) VALUES ('r', '2026-02-01', 'recurring', 120000, 'annual', 1, "
            "'2026-09-01')",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, cadence, "
            "first_day, interval_months, anchor) VALUES ('r', '2026-03-01', 'recurring', 60000, "
            "'every_months', 15, 6, '2026-06-15')",
            "INSERT INTO fund_terms (fund_id, effective_from, shape, basis_points) "
            "VALUES ('t', '2026-01-01', 'percent', 2500)",
            "INSERT INTO fund_event (fund_id, event) VALUES ('g', 'undone')",
            "INSERT INTO fund_assignment_event (assignment_id, event) VALUES ('a', 'undone')",
            "INSERT INTO fund_priority_event (list_id, event) VALUES ('m', 'made')",
            "INSERT INTO fund_priority (list_id, position, fund_id) VALUES ('l', 2, 'r')",
        ):
            conn.execute(statement)
        conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents) "
                     "VALUES ('b', 'g', ?, 1)", (stated.account_id,))
        conn.close()

    @pytest.mark.parametrize("statement", [
        "INSERT INTO fund (id, name, kind) VALUES ('x', ' ', 'goal')",
        "INSERT INTO fund (id, name, kind) VALUES ('x', 'X', 'retirement')",
        # A shape its kind does not take, and shapes missing or holding a column.
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
        "VALUES ('g', '2026-02-01', 'minimum', 1)",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, due_date) "
        "VALUES ('g', '2026-02-01', 'due', 1, '2026-09-01')",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, basis_points) "
        "VALUES ('r', '2026-02-01', 'percent', 1)",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
        "VALUES ('g', '2026-02-01', 'monthly', 0)",
        "INSERT INTO fund_terms (fund_id, effective_from, shape) "
        "VALUES ('g', '2026-02-01', 'monthly')",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, basis_points) "
        "VALUES ('g', '2026-02-01', 'monthly', 1, 1)",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, basis_points) "
        "VALUES ('g', '2026-02-01', 'percent', 10001)",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, by_month) "
        "VALUES ('g', '2026-02-01', 'target_by', 1, '2026-13')",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
        "VALUES ('g', '2026-02-30', 'monthly', 1)",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, cadence, "
        "first_day, anchor) VALUES ('r', '2026-02-01', 'recurring', 1, 'every_months', 1, "
        "'2026-09-01')",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, cadence, "
        "first_day, interval_months, anchor) VALUES ('r', '2026-02-01', 'recurring', 1, "
        "'annual', 1, 12, '2026-09-01')",
        "INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
        "VALUES ('nobody', '2026-02-01', 'monthly', 1)",
        "INSERT INTO fund_event (fund_id, event) VALUES ('g', 'paused')",
        "INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents) "
        "VALUES ('x', 'g', 'no-account', 1)",
        "INSERT INTO fund_assignment_event (assignment_id, event) VALUES ('a', 'paused')",
        "INSERT INTO fund_priority_event (list_id, event) VALUES ('m', 'undone')",
        "INSERT INTO fund_priority (list_id, position, fund_id) VALUES ('l', 0, 'r')",
        "INSERT INTO fund_priority (list_id, position, fund_id) VALUES ('no-list', 1, 'r')",
    ])
    def test_a_row_it_does_not_take_is_refused(self, stated, statement):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
        conn.close()

    def test_a_zero_assignment_is_refused(self, stated):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents) "
                         "VALUES ('x', 'g', ?, 0)", (stated.account_id,))
        conn.close()
