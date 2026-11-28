"""Migration 0032, what safe-to-spend reads, on a populated ledger (SA1, D-067 G10, D-072), using
synthetic data only. Its tables are empty and it seeds one setting key, nothing else shown
changes, a ledger at 31 is refused until migrate, a failure leaves everything as it was, and its
tables are append-only, each check refusing on its own trigger with a control that succeeds."""

import sqlite3

import pytest
from migration_checks import (
    assert_a_failure_leaves_everything_as_it_was,
    assert_refused_until_migrate,
    assert_rows_refuse_update_delete_and_replace,
    markers,
    migrations_up_to,
)
from test_breakdown_migration import VERSION_30_TABLES
from test_decisions import BREAKDOWN_TABLES, LIQUIDITY_TABLES, drop_liquidity_tables
from test_funds import FundLedger

from personal_finance.db.migrate import connect, migrate

VERSION_31_TABLES = (*VERSION_30_TABLES, *BREAKDOWN_TABLES)
AS_OF = "2026-03-15"


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("balance", "list"), ("funds", "--as-of", AS_OF),
        ("obligations",), ("transactions",), ("account", "links"))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Savings observed, a reserve, a payment, set back to 31, with what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.add_typed_account("S", "savings")
    ledger.observe("S", "2026-03-01", "1000.00")
    ledger.add_fund_ok(name="Insurance", kind="reserve", target="600.00", due="2026-06-10")
    ledger.pay("b1.csv", "2026-03-05", amount="-85.00", text="SYNTHETIC SHOP")
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_liquidity_tables(conn)
    conn.execute("PRAGMA user_version = 31")
    conn.close()
    return ledger


class TestMigration:  # SA1, G10
    def test_it_adds_empty_tables_seeds_the_key_and_changes_nothing_shown(self, populated,
                                                                          tmp_path):
        before = populated.dump(VERSION_31_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "thirty-two", 32)) == 32
        for table in LIQUIDITY_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT setting_key FROM ledger_setting_key ORDER BY 1").fetchall() \
            == [("checking_buffer_cents",), ("household_timezone",)]
        conn.close()
        after = populated.dump(VERSION_31_TABLES)
        assert {table: rows for table, rows in after.items() if table != "ledger_setting_key"} \
            == {table: rows for table, rows in before.items() if table != "ledger_setting_key"}
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_31_is_refused_until_migrate(self, populated):
        assert_refused_until_migrate(populated, "funds", "--as-of", AS_OF)

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        assert_a_failure_leaves_everything_as_it_was(
            populated, tmp_path, version=32, migration_name="0032_safe_to_spend_inputs.sql",
            tables_before=VERSION_31_TABLES, new_tables=LIQUIDITY_TABLES)


@pytest.fixture
def stated(tmp_path, capsys):
    """One of each row: a designation, a coverage of a loan, a restoration, with their events."""
    ledger = FundLedger(tmp_path, capsys)
    for name, account_type in (("S", "savings"), ("Loan", "loan"), ("Card", "credit_card")):
        ledger.add_typed_account(name, account_type)
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="600.00",
                                        due="2026-06-10")
    ledger.emergency = ledger.add_fund_ok(name="Rainy", kind="emergency", minimum="5000.00")
    ledger.goal = ledger.add_fund_ok(name="House")
    ledger.bill = ledger.ob_add_ok()
    conn = ledger.conn()
    ledger.ids = dict(conn.execute("SELECT display_name, id FROM account"))
    conn.execute("INSERT INTO account_liquidity (id, account_id) VALUES ('d', ?)",
                 (ledger.ids["A"],))
    conn.execute("INSERT INTO account_liquidity_event (designation_id, event) VALUES ('d', 'made')")
    conn.execute("INSERT INTO obligation_coverage (id, obligation_id, loan_account_id) "
                 "VALUES ('c', ?, ?)", (ledger.bill, ledger.ids["Loan"]))
    conn.execute("INSERT INTO obligation_coverage_event (coverage_id, event) VALUES ('c', 'made')")
    conn.execute("INSERT INTO fund_restoration (id, fund_id, effective_from, monthly_cents) "
                 "VALUES ('r', ?, '2026-03-01', 20000)", (ledger.emergency,))
    conn.execute("INSERT INTO fund_restoration_event (restoration_id, event) "
                 "VALUES ('r', 'made')")
    conn.close()
    return ledger


class TestAppendOnly:  # SA1, G2
    @pytest.mark.parametrize("table", LIQUIDITY_TABLES)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        assert_rows_refuse_update_delete_and_replace(stated, table, LIQUIDITY_TABLES)

    def test_control_inserts_succeed(self, stated):
        conn = stated.conn()
        conn.execute("INSERT INTO account_liquidity (id, account_id) VALUES ('d2', ?)",
                     (stated.ids["S"],))
        conn.execute("INSERT INTO account_liquidity_event (designation_id, event) "
                     "VALUES ('d', 'undone')")
        conn.execute("INSERT INTO obligation_coverage (id, obligation_id, fund_id) "
                     "VALUES ('c2', ?, ?)", (stated.bill, stated.reserve))
        conn.execute("INSERT INTO obligation_coverage_event (coverage_id, event) "
                     "VALUES ('c', 'undone')")
        conn.execute("INSERT INTO fund_restoration (id, fund_id, effective_from, monthly_cents) "
                     "VALUES ('r2', ?, '2026-04-01', 1)", (stated.emergency,))
        conn.execute("INSERT INTO fund_restoration_event (restoration_id, event) "
                     "VALUES ('r', 'undone')")
        conn.close()

    @pytest.mark.parametrize("account", ["Loan", "Card"])
    def test_only_checking_and_savings_are_designated(self, stated, account):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError, match="checking or savings"):
            conn.execute("INSERT INTO account_liquidity (id, account_id) VALUES ('x', ?)",
                         (stated.ids[account],))
        conn.close()

    @pytest.mark.parametrize("columns, target", [
        ("loan_account_id", "Card"), ("loan_account_id", "S"), ("fund_id", "emergency"),
        ("fund_id", "goal")])
    def test_a_coverage_of_anything_but_a_loan_or_reserve_is_refused(self, stated, columns,
                                                                     target):
        value = stated.ids.get(target) or getattr(stated, target)
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError, match="covers only"):
            conn.execute(f"INSERT INTO obligation_coverage (id, obligation_id, {columns}) "
                         "VALUES ('x', ?, ?)", (stated.bill, value))
        conn.close()

    @pytest.mark.parametrize("values", ["NULL, NULL", "?, ?"])
    def test_a_coverage_names_exactly_one_target(self, stated, values):
        conn = stated.conn()
        arguments = () if values == "NULL, NULL" else (stated.ids["Loan"], stated.reserve)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO obligation_coverage "
                         "(id, obligation_id, loan_account_id, fund_id) "
                         f"VALUES ('x', ?, {values})", (stated.bill, *arguments))
        conn.close()

    @pytest.mark.parametrize("fund, day, cents, message", [
        ("reserve", "2026-04-01", 100, "only the emergency fund"),
        ("emergency", "2026-04-31", 100, "CHECK"),
        ("emergency", "2026-04-01", 0, "CHECK")])
    def test_a_restoration_s_checks(self, stated, fund, day, cents, message):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError, match=message):
            conn.execute("INSERT INTO fund_restoration (id, fund_id, effective_from, "
                         "monthly_cents) VALUES ('x', ?, ?, ?)",
                         (getattr(stated, fund), day, cents))
        conn.close()

    @pytest.mark.parametrize("table, column", [
        ("account_liquidity_event", "designation_id"), ("obligation_coverage_event", "coverage_id"),
        ("fund_restoration_event", "restoration_id")])
    def test_an_event_it_does_not_take_is_refused(self, stated, table, column):
        conn = stated.conn()
        row = {"designation_id": "d", "coverage_id": "c", "restoration_id": "r"}[column]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"INSERT INTO {table} ({column}, event) VALUES (?, 'paused')", (row,))
        conn.close()
