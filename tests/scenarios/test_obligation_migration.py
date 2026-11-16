"""Migration 0025, recurring obligations, on a populated ledger (IB1, D-067 G10, D-068 point 5),
using synthetic data only. Its tables are empty, nothing shown changes, a ledger at 24 is refused
until migrate, a failure leaves everything as it was, and every stated table is append-only."""

import sqlite3

import pytest
from test_decisions import (
    ALL_TABLES,
    ALLOCATION_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    HOUSEHOLD_TABLES,
    INCOME_TABLES,
    OBLIGATION_TABLES,
    drop_obligation_tables,
)
from test_income_sources import IncomeLedger
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_24_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES, *ALLOCATION_TABLES, *INCOME_TABLES)

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
    24, with what was shown before."""
    ledger = IncomeLedger(tmp_path, capsys)
    ledger.deposit("b1.csv", "2026-01-05", amount="-85.00", text="SYNTHETIC POWER CO",
                   financial_type="purchase")
    ledger.deposit("p1.csv", "2026-01-02")
    ledger.add_ok()
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_obligation_tables(conn)
    conn.execute("PRAGMA user_version = 24")
    conn.close()
    return ledger


class TestMigration:  # IB1
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_24_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-five", 25)) == 25
        for table in OBLIGATION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_24_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_24_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("income", "sources")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("income", "sources")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 25)
        newest = load_migrations()[24].path
        assert newest.name == "0025_recurring_obligations.sql"
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_24_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 24
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(OBLIGATION_TABLES)
        conn.close()
        assert populated.dump(VERSION_24_TABLES) == before


@pytest.fixture
def stated(tmp_path, capsys):
    """One row in every stated table of 0025, written by hand: an obligation, its terms, its made
    event, and a dismissal with its made event."""
    ledger = IncomeLedger(tmp_path, capsys)
    conn = ledger.conn()
    account = ledger.account_id("A")
    conn.execute("""INSERT INTO recurring_obligation (id, account_id, name, description_contains,
                                                     normalization_version, tolerance_days,
                                                     chain_id)
                    VALUES ('o', ?, 'Power', 'power', 1, 3, 'o')""", (account,))
    conn.execute("""INSERT INTO recurring_obligation_terms (chain_id, effective_from, cadence,
                                                            first_day, anchor, low_cents,
                                                            high_cents, obligation_class)
                    VALUES ('o', '2026-01-05', 'monthly', 5, '2026-01-05', 8500, 8500, 'fixed')""")
    conn.execute("INSERT INTO recurring_obligation_event (obligation_id, event) "
                 "VALUES ('o', 'made')")
    conn.execute("INSERT INTO obligation_proposal_dismissal (id, account_id, proposal_key) "
                 "VALUES ('d', ?, '0123456789abcdef')", (account,))
    conn.execute("INSERT INTO obligation_proposal_dismissal_event (dismissal_id, event) "
                 "VALUES ('d', 'made')")
    conn.close()
    return ledger


class TestAppendOnly:  # IB1, G2
    @pytest.mark.parametrize("statement", [
        "UPDATE recurring_obligation SET name = name",
        "DELETE FROM recurring_obligation",
        "INSERT INTO recurring_obligation SELECT * FROM recurring_obligation",
        "UPDATE recurring_obligation_terms SET high_cents = high_cents",
        "DELETE FROM recurring_obligation_terms",
        "INSERT INTO recurring_obligation_terms (chain_id, effective_from, cadence, first_day, "
        "anchor, low_cents, high_cents, obligation_class) SELECT chain_id, effective_from, "
        "cadence, first_day, anchor, low_cents, high_cents, obligation_class "
        "FROM recurring_obligation_terms",
        "UPDATE recurring_obligation_event SET event = event",
        "DELETE FROM recurring_obligation_event",
        "INSERT INTO recurring_obligation_event (obligation_id, event) SELECT obligation_id, "
        "event FROM recurring_obligation_event",
        "UPDATE obligation_proposal_dismissal SET proposal_key = proposal_key",
        "DELETE FROM obligation_proposal_dismissal",
        "INSERT INTO obligation_proposal_dismissal SELECT * FROM obligation_proposal_dismissal",
        "UPDATE obligation_proposal_dismissal_event SET event = event",
        "DELETE FROM obligation_proposal_dismissal_event",
        "INSERT INTO obligation_proposal_dismissal_event (dismissal_id, event) SELECT "
        "dismissal_id, event FROM obligation_proposal_dismissal_event",
    ])
    def test_history_refuses_change(self, stated, statement):
        before = stated.dump(OBLIGATION_TABLES)
        conn = stated.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert stated.dump(OBLIGATION_TABLES) == before

    def test_a_control_insert_of_each_succeeds(self, stated):
        conn = stated.conn()
        account = stated.account_id("A")
        conn.execute("""INSERT INTO recurring_obligation (id, account_id, name,
                                                         description_contains,
                                                         normalization_version, tolerance_days,
                                                         supersedes_id, chain_id)
                        VALUES ('new', ?, 'New', 'x', 1, 3, 'o', 'o')""", (account,))
        conn.execute("""INSERT INTO recurring_obligation_terms (chain_id, effective_from, cadence,
                                                                anchor, low_cents, high_cents,
                                                                obligation_class)
                        VALUES ('o', '2026-03-01', 'weekly', '2026-03-02', 1, 1, 'fixed')""")
        conn.execute("INSERT INTO recurring_obligation_event (obligation_id, event) "
                     "VALUES ('o', 'undone')")
        conn.execute("INSERT INTO obligation_proposal_dismissal (id, account_id, proposal_key) "
                     "VALUES ('d2', ?, '0123456789abcdef')", (account,))
        conn.execute("INSERT INTO obligation_proposal_dismissal_event (dismissal_id, event) "
                     "VALUES ('d', 'undone')")
        conn.close()

    @pytest.mark.parametrize(("columns", "values"), [
        ("cadence, first_day", "'semimonthly', 15"),
        ("cadence", "'monthly'"),
        ("cadence, first_day", "'weekly', 3"),
        ("cadence, first_day, interval_months", "'every_months', 3, 1"),
        ("cadence, low_cents, high_cents", "'weekly', 0, 0"),
        ("cadence, low_cents, high_cents", "'weekly', 5, 4"),
        ("cadence, obligation_class", "'weekly', 'sometimes'"),
    ])
    def test_terms_refuse_a_shape_they_do_not_take(self, stated, columns, values):
        conn = stated.conn()
        fields = dict(zip([name.strip() for name in columns.split(",")],
                          [value.strip() for value in values.split(",")], strict=True))
        fields.setdefault("low_cents", "1")
        fields.setdefault("high_cents", "1")
        fields.setdefault("obligation_class", "'fixed'")
        names, values = ", ".join(fields), ", ".join(fields.values())
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"""INSERT INTO recurring_obligation_terms (chain_id, effective_from,
                                                                     anchor, {names})
                             VALUES ('o', '2027-01-01', '2027-01-01', {values})""")
        conn.close()

    @pytest.mark.parametrize(("chain", "supersedes"), [("o", None), ("new", "o")])
    def test_a_chain_names_its_first_obligation(self, stated, chain, supersedes):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO recurring_obligation (id, account_id, name,
                                                             description_contains,
                                                             normalization_version,
                                                             tolerance_days, supersedes_id,
                                                             chain_id)
                            VALUES ('new', ?, 'New', 'x', 1, 3, ?, ?)""",
                         (stated.account_id("A"), supersedes, chain))
        conn.close()

    def test_a_dismissal_key_is_sixteen_characters(self, stated):
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO obligation_proposal_dismissal (id, account_id, "
                         "proposal_key) VALUES ('d3', ?, 'short')", (stated.account_id("A"),))
        conn.close()

    @pytest.mark.parametrize(("state", "nominal", "obligation_class"), [
        ("'paid'", "NULL", "'fixed'"),
        ("'unscheduled'", "'2026-01-05'", "'fixed'"),
        ("'obligation_conflict'", "NULL", "'fixed'"),
        ("'paid'", "'2026-01-05'", "NULL"),
        ("'missed'", "NULL", "'fixed'"),
    ])
    def test_the_derived_table_refuses_an_impossible_row(self, stated, state, nominal,
                                                         obligation_class):
        stated.deposit("b1.csv", "2026-01-05", amount="-85.00", financial_type="purchase")
        transaction = holding(stated, "b1.csv")
        conn = stated.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"""INSERT INTO transaction_obligation VALUES
                             (?, 'o', {state}, {nominal}, {obligation_class})""", (transaction,))
        conn.execute("""INSERT INTO transaction_obligation VALUES
                        (?, 'o', 'paid', '2026-01-05', 'fixed')""", (transaction,))
        conn.close()
