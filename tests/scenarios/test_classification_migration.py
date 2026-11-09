"""Migration 0013 on a populated ledger, and its append-only tables (F13, D-053).

A ledger built at the latest version, with the empty tables of 0013 and later dropped and set back to
version 12, is a version 12 ledger: 0013 only creates tables. Migration stops at 13, so that only 0013 is tested.
"""

import sqlite3

import pytest
from test_classifications import ClassificationLedger
from test_confirmations import confirm_ok
from test_coverage_declarations import MONTH
from test_decisions import (
    ALL_TABLES,
    BALANCE_TABLES,
    REAL_LEDGER_TABLES,
    CLASSIFICATION_TABLES,
    ONE_SIDED_TABLES,
    TRANSFER_TABLES,
    pair_up,
)
from test_resolutions import CAFE_NO_AMOUNT
from test_supersession import holding

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_12_TABLES = tuple(table for table in ALL_TABLES
                          if table not in (*CLASSIFICATION_TABLES, *TRANSFER_TABLES,
                                           *ONE_SIDED_TABLES, *BALANCE_TABLES))


def set_back_to_version_12(path) -> None:
    conn = connect(path)
    for table in (*REAL_LEDGER_TABLES, *BALANCE_TABLES, *ONE_SIDED_TABLES, *TRANSFER_TABLES, *CLASSIFICATION_TABLES):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 12")
    conn.close()


def migrations_up_to(folder, version):
    folder.mkdir()
    for migration in load_migrations()[:version]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


@pytest.fixture
def populated(tmp_path, capsys):
    """A decision, a correction, a completed row and a declaration, with no classification."""
    ledger = ClassificationLedger(tmp_path, capsys)
    item, one, two = pair_up(ledger)
    confirm_ok(ledger, item, (one, two))
    ledger.card("c.csv", CAFE_NO_AMOUNT)
    (unresolved,) = ledger.unresolved()
    ledger.complete_ok(unresolved, amount="-1.00")
    ledger.correct_ok(ledger.run("transactions")[1].split()[0], "posting_date", "2026-01-12")
    ledger.declare_ok("c.csv", **MONTH)
    set_back_to_version_12(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_makes_no_account_stale_and_changes_nothing_else(
            self, populated, tmp_path):
        before = populated.dump(VERSION_12_TABLES)
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "thirteen", 13)) == 13
        for table in CLASSIFICATION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_12_TABLES) == before
        assert "have not been reconciled" not in populated.totals()

    def test_classifications_work_after_it_without_reconciling(self, populated):
        assert populated.run("migrate")[0] == 0
        populated.classify_ok(holding(populated, "c.csv"), "purchase")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 13)
        thirteenth = load_migrations()[12].path
        (folder / thirteenth.name).write_text(thirteenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_12_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 12
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(CLASSIFICATION_TABLES)
        conn.close()
        assert populated.dump(VERSION_12_TABLES) == before


@pytest.fixture
def classified(tmp_path, capsys):
    """A chain of two classifications, the newer undone."""
    ledger = ClassificationLedger(tmp_path, capsys)
    ledger.card("a.csv", "01/10/2026,SYNTHETIC CAFE,6.50,")
    transaction = holding(ledger, "a.csv")
    first = ledger.classify_ok(transaction, "purchase")
    second = ledger.classify_ok(transaction, "fee", supersedes=first)
    assert ledger.undo_classification(second)[0] == 0
    return ledger


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE type_classification SET financial_type = 'refund'",
        "DELETE FROM type_classification",
        "INSERT INTO type_classification SELECT * FROM type_classification",
        "UPDATE type_classification_record SET source_record_id = source_record_id",
        "DELETE FROM type_classification_record",
        "INSERT INTO type_classification_record SELECT * FROM type_classification_record",
        "UPDATE type_classification_event SET event = 'made'",
        "DELETE FROM type_classification_event",
        "INSERT INTO type_classification_event (classification_id, event) "
        "SELECT classification_id, event FROM type_classification_event",
    ])
    def test_history_refuses_change(self, classified, statement):
        history = CLASSIFICATION_TABLES[1:]
        before = classified.dump(history)
        conn = classified.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert classified.dump(history) == before

    INSERT_CLASSIFICATION = """
        INSERT INTO type_classification (id, account_id, financial_type, target_transaction_id,
                                         target_revision, supersedes_classification_id)
        VALUES (?, ?, ?, 't', 't7-0', (SELECT id FROM type_classification ORDER BY id LIMIT 1))"""

    def own_account(self, conn):
        return conn.execute("SELECT id FROM account").fetchone()[0]

    @pytest.mark.parametrize("financial_type", ["unclassified", "groceries", None])
    def test_a_stored_type_must_be_one_of_the_types(self, classified, financial_type):
        conn = classified.conn()
        account = self.own_account(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(self.INSERT_CLASSIFICATION, ("x", account, financial_type))
        conn.execute(self.INSERT_CLASSIFICATION, ("control", account, "purchase"))
        conn.close()

    def test_a_classification_supersedes_only_one_of_its_own_account(self, classified):
        conn = classified.conn()
        conn.execute("INSERT INTO account (id, display_name, account_type) "
                     "VALUES ('other', 'B', 'checking')")
        with pytest.raises(sqlite3.IntegrityError, match="its own account"):
            conn.execute(self.INSERT_CLASSIFICATION, ("x", "other", "fee"))
        conn.execute(self.INSERT_CLASSIFICATION, ("control", self.own_account(conn), "fee"))
        conn.close()

    @pytest.mark.parametrize(("state", "financial_type"), [
        ("applied", None), ("conflict", "purchase"), ("superseded", None),
    ])
    def test_a_derived_row_must_fit_its_state(self, classified, state, financial_type):
        conn = classified.conn()
        # Derived and rewritten on every reconcile, so it may be cleared, unlike the history.
        conn.execute("DELETE FROM transaction_classification")
        insert = """INSERT INTO transaction_classification (transaction_id, state, financial_type)
                    VALUES ((SELECT id FROM ledger_transaction), ?, ?)"""
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(insert, (state, financial_type))
        conn.execute(insert, ("applied", "purchase"))
        conn.close()
