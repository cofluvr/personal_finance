"""Migration 0028, fund consumptions and tax releases, on a populated ledger (GB1, D-067 G10,
D-070), using synthetic data only. Its tables are empty, nothing shown changes, a ledger at 27 is
refused until migrate, a failure leaves everything as it was, and every stated table is
append-only."""

import sqlite3

import pytest
from test_decisions import (
    ALL_TABLES,
    ALLOCATION_TABLES,
    BUDGET_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    CONSUMPTION_TABLES,
    FUND_TABLES,
    HOUSEHOLD_TABLES,
    INCOME_TABLES,
    OBLIGATION_TABLES,
    SETTING_KEY_TABLES,
    drop_consumption_tables,
)
from test_funds import FundLedger
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_27_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES, *ALLOCATION_TABLES, *INCOME_TABLES,
                     *OBLIGATION_TABLES, *SETTING_KEY_TABLES, *BUDGET_TABLES, *FUND_TABLES)

AS_OF = "2026-03-15"


def shown_now(ledger):
    purchase = holding(ledger, "b1.csv")
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("transactions",), ("review", "classifications"),
        ("funds", "--as-of", AS_OF), ("budgets",), ("balance", "list"),
        ("report", "budget", "--month", "2026-03", "--as-of", AS_OF),
        ("review", "transaction", "show", purchase))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Savings holding a reserve's assignment, and a purchase on checking A, set back to 27, with
    what was shown before."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.add_typed_account("Savings", "savings")
    ledger.observe("Savings", "2026-03-01", "5000.00")
    ledger.deposit("b1.csv", "2026-03-05", amount="-850.00", text="SYNTHETIC INSURER",
                   financial_type="purchase")
    fund = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                              due="2026-09-01")
    ledger.assign_ok(fund, "Savings", "600.00")
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_consumption_tables(conn)
    conn.execute("PRAGMA user_version = 27")
    conn.close()
    return ledger


class TestMigration:  # GB1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_27_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-eight", 28)) == 28
        for table in CONSUMPTION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_27_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_27_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("funds", "--as-of", AS_OF)
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("funds", "--as-of", AS_OF)[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 28)
        newest = load_migrations()[27].path
        assert newest.name == "0028_fund_consumptions.sql"
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_27_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 27
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(CONSUMPTION_TABLES)
        conn.close()
        assert populated.dump(VERSION_27_TABLES) == before


STATED_TABLES = ("tax_reserve_release_event", "tax_reserve_release", "fund_consumption_event",
                 "fund_consumption_record", "fund_consumption")


@pytest.fixture
def stated(tmp_path, capsys):
    """One row in every stated table of 0028, written by hand, on a goal, an emergency fund and a
    tax reserve."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.deposit("b1.csv", "2026-03-05", amount="-85.00", text="SYNTHETIC SHOP",
                   financial_type="purchase")
    conn = ledger.conn()
    account = conn.execute("SELECT id FROM account WHERE display_name = 'A'").fetchone()[0]
    record = conn.execute("SELECT id FROM source_record").fetchone()[0]
    for fund_id, kind in (("g", "goal"), ("e", "emergency"), ("t", "tax"), ("r", "reserve")):
        conn.execute("INSERT INTO fund (id, name, kind) VALUES (?, ?, ?)",
                     (fund_id, fund_id.upper(), kind))
    conn.execute("INSERT INTO fund_consumption (id, account_id, fund_id, target_transaction_id, "
                 "target_revision) VALUES ('c', ?, 'g', 'x', 't11-0')", (account,))
    conn.execute("INSERT INTO fund_consumption_record (consumption_id, source_record_id) "
                 "VALUES ('c', ?)", (record,))
    conn.execute("INSERT INTO fund_consumption_event (consumption_id, event) VALUES ('c', 'made')")
    conn.execute("INSERT INTO tax_reserve_release (id, fund_id, amount_cents, released_on) "
                 "VALUES ('l', 't', 100, '2026-03-01')")
    conn.execute("INSERT INTO tax_reserve_release_event (release_id, event) VALUES ('l', 'made')")
    conn.close()
    ledger.account_id = account
    return ledger


class TestAppendOnly:  # GB1, G2
    @pytest.mark.parametrize("table", STATED_TABLES)
    def test_rows_refuse_update_delete_and_replace(self, stated, table):
        before = stated.dump(STATED_TABLES)
        conn = stated.conn()
        for statement in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}",
                          f"INSERT INTO {table} SELECT * FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(statement)
        conn.close()
        assert stated.dump(STATED_TABLES) == before

    def test_a_control_insert_of_each_succeeds(self, stated):
        conn = stated.conn()
        for fund_id, consumption_id in (("r", "c2"), ("t", "c3")):
            conn.execute("INSERT INTO fund_consumption (id, account_id, fund_id, "
                         "target_transaction_id, target_revision) VALUES (?, ?, ?, 'x', 't11-0')",
                         (consumption_id, stated.account_id, fund_id))
        conn.execute("INSERT INTO fund_consumption (id, account_id, fund_id, target_transaction_id, "
                     "target_revision, supersedes_consumption_id) "
                     "VALUES ('c4', ?, 'r', 'x', 't11-0', 'c')", (stated.account_id,))
        conn.execute("INSERT INTO fund_consumption_event (consumption_id, event) "
                     "VALUES ('c', 'undone')")
        conn.execute("INSERT INTO tax_reserve_release (id, fund_id, amount_cents, released_on) "
                     "VALUES ('l2', 't', 1, '2026-03-02')")
        conn.execute("INSERT INTO tax_reserve_release_event (release_id, event) "
                     "VALUES ('l', 'undone')")
        conn.close()

    @pytest.mark.parametrize("statement", [
        # The emergency fund is never consumed, and nor is a fund not on record.
        "INSERT INTO fund_consumption (id, account_id, fund_id, target_transaction_id, "
        "target_revision) VALUES ('x', :account, 'e', 'x', 't11-0')",
        "INSERT INTO fund_consumption (id, account_id, fund_id, target_transaction_id, "
        "target_revision) VALUES ('x', :account, 'nobody', 'x', 't11-0')",
        "INSERT INTO fund_consumption (id, account_id, fund_id, target_transaction_id, "
        "target_revision) VALUES ('x', 'no-account', 'g', 'x', 't11-0')",
        "INSERT INTO fund_consumption_record (consumption_id, source_record_id) "
        "VALUES ('c', 'no-record')",
        "INSERT INTO fund_consumption_event (consumption_id, event) VALUES ('c', 'paused')",
        # Only the tax reserve is released, by an amount above zero on a real date.
        "INSERT INTO tax_reserve_release (id, fund_id, amount_cents, released_on) "
        "VALUES ('x', 'g', 100, '2026-03-01')",
        "INSERT INTO tax_reserve_release (id, fund_id, amount_cents, released_on) "
        "VALUES ('x', 't', 0, '2026-03-01')",
        "INSERT INTO tax_reserve_release (id, fund_id, amount_cents, released_on) "
        "VALUES ('x', 't', 100, '2026-02-30')",
        "INSERT INTO tax_reserve_release_event (release_id, event) VALUES ('l', 'paused')",
        "INSERT INTO transaction_fund_consumption (transaction_id, state, fund_id) "
        "VALUES ((SELECT id FROM ledger_transaction), 'applied', NULL)",
        "INSERT INTO transaction_fund_consumption (transaction_id, state, fund_id) "
        "VALUES ((SELECT id FROM ledger_transaction), 'conflict', 'g')",
        "INSERT INTO transaction_fund_consumption (transaction_id, state, fund_id) "
        "VALUES ((SELECT id FROM ledger_transaction), 'consumed', NULL)",
    ])
    def test_a_row_it_does_not_take_is_refused(self, stated, statement):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement, {"account": stated.account_id})
        conn.close()

    def test_a_consumption_supersedes_only_one_of_its_own_account(self, stated):
        stated.add_typed_account("B2", "checking")
        conn = stated.conn()
        other = conn.execute("SELECT id FROM account WHERE display_name = 'B2'").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fund_consumption (id, account_id, fund_id, "
                         "target_transaction_id, target_revision, supersedes_consumption_id) "
                         "VALUES ('x', ?, 'g', 'x', 't11-0', 'c')", (other,))
        conn.execute("INSERT INTO transaction_fund_consumption (transaction_id, state, fund_id) "
                     "VALUES ((SELECT id FROM ledger_transaction), 'applied', 'g')")
        conn.close()
