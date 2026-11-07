"""Migration 0005 on a populated ledger, and the append-only decision tables (D-045)."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from personal_finance.cli import main
from personal_finance.db.migrate import (
    connect,
    create_database,
    load_migrations,
    migrate,
    schema_version,
)

HEADER = "Date,Description,Debit,Credit\n"
DECLARED = ("--declare-complete-coverage", "--coverage-start", "2026-01-01",
            "--coverage-end", "2026-01-31", "--coverage-basis", "posting")
OLD_TABLES = (
    "account", "import_run", "import_attempt", "source_document", "document_coverage",
    "document_interpretation", "source_record", "record_parse", "source_record_origin",
    "ledger_transaction", "transaction_source", "transaction_link_history",
    "transaction_identity_history", "review_issue", "review_issue_subject",
    "account_reconciliation",
)
FINGERPRINT = "f" * 64


def old_migrations(folder: Path) -> Path:
    folder.mkdir()
    for migration in load_migrations()[:4]:
        shutil.copy(migration.path, folder / migration.path.name)
    return folder


def columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def dump(conn):
    """Every row of the tables that existed before 0005, leaving out the added column."""
    found = {}
    for table in OLD_TABLES:
        names = ", ".join(name for name in columns(conn, table) if name != "decision_id")
        found[table] = sorted(
            conn.execute(f"SELECT {names} FROM {table}").fetchall(), key=repr
        )
    return found


@pytest.fixture
def populated(tmp_path, capsys):
    """A version 4 ledger holding real issues, subjects, merges and an unresolved row.

    Current code cannot import into an old schema, so the rows are made at the latest
    version and copied into a ledger built by the first four migrations.
    """
    source = tmp_path / "source.db"
    assert main(["init", "--db", str(source)]) == 0
    assert main(["account", "add", "--db", str(source), "--name", "A", "--type", "checking"]) == 0

    def load(name, rows, *extra):
        path = tmp_path / name
        path.write_text(HEADER + "".join(f"{row}\n" for row in rows))
        code = main(["import", "--db", str(source), "--account", "A",
                     "--layout", "synthetic_card_v1", *extra, str(path)])
        assert code == 0

    load("a.csv", ["01/05/2026,SYNTHETIC CAFE,6.50,", "01/06/2026,SYNTHETIC BOOKS,9.00,",
                   "01/07/2026,SYNTHETIC BAD,not money,"], *DECLARED)
    load("b.csv", ["01/05/2026,SYNTHETIC CAFE,6.50,", "01/06/2026, SYNTHETIC BOOKS,9.00,"],
         *DECLARED)
    load("c.csv", ["01/06/2026,SYNTHETIC BOOKS,9.00,", "01/06/2026,SYNTHETIC BOOKS,9.00,"])
    capsys.readouterr()

    path = tmp_path / "old.db"
    create_database(path, old_migrations(tmp_path / "old_migrations"))
    conn = connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS source", (str(source),))
    for table in OLD_TABLES:
        names = ", ".join(columns(conn, table))
        conn.execute(f"INSERT INTO main.{table} ({names}) SELECT {names} FROM source.{table}")
    conn.execute("DETACH DATABASE source")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    return path


class TestPopulatedMigration:
    def test_the_fixture_really_is_populated(self, populated):
        conn = connect(populated)
        assert schema_version(conn) == 4
        rows = dump(conn)
        assert len(rows["review_issue_subject"]) >= 3
        assert {row[1] for row in rows["review_issue"]} == {
            "possible_duplicate", "unresolved_record"
        }
        assert rows["transaction_link_history"]
        conn.close()

    def test_everything_survives(self, populated):
        conn = connect(populated)
        before = dump(conn)
        assert migrate(conn) == len(load_migrations())
        assert dump(conn) == before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        conn.close()

    def test_subject_foreign_keys_and_indexes_still_hold(self, populated):
        conn = connect(populated)
        indexes = conn.execute(
            """SELECT name, sql FROM sqlite_master
               WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex%'"""
        ).fetchall()
        migrate(conn)

        after = set(conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'"))
        assert set(indexes) <= after
        references = conn.execute("PRAGMA foreign_key_list(review_issue_subject)").fetchall()
        assert {row[2] for row in references} == {
            "review_issue", "ledger_transaction", "source_record"
        }
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO review_issue_subject (review_issue_id, source_record_id)
                   VALUES ('no such issue', (SELECT id FROM source_record LIMIT 1))"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM review_issue")
        conn.close()

    def test_the_kind_is_widened_and_still_checked(self, populated):
        conn = connect(populated)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO review_issue (id, kind, rule) VALUES ('x', 'decision_conflict', 'r')"
            )
        migrate(conn)
        conn.execute(
            "INSERT INTO review_issue (id, kind, rule) VALUES ('x', 'decision_conflict', 'r')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO review_issue (id, kind, rule) VALUES ('y', 'other', 'r')")
        conn.close()

    def test_no_working_tables_remain(self, populated):
        conn = connect(populated)
        migrate(conn)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not {"review_issue_rebuilt", "review_issue_subject_moved"} & names
        conn.close()

    def test_a_migrated_ledger_is_read_and_reconciled_as_before(self, populated, capsys):
        assert main(["migrate", "--db", str(populated)]) == 0
        capsys.readouterr()
        assert main(["totals", "--db", str(populated)]) == 0
        before = capsys.readouterr().out
        conn = connect(populated)
        rows = dump(conn)["transaction_source"]
        conn.close()

        assert main(["reconcile", "--db", str(populated)]) == 0
        capsys.readouterr()
        assert main(["totals", "--db", str(populated)]) == 0
        assert capsys.readouterr().out == before
        conn = connect(populated)
        assert dump(conn)["transaction_source"] == rows
        conn.close()

    @pytest.mark.parametrize(
        "failure",
        [
            "CREATE TABLE decision (id TEXT) STRICT;",
            "SELECT no_such_function();",
        ],
        ids=["before the rebuild", "after the rebuild"],
    )
    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path, failure):
        folder = tmp_path / "broken"
        folder.mkdir()
        migrations = load_migrations()
        for migration in migrations[:4]:
            shutil.copy(migration.path, folder / migration.path.name)
        sql = migrations[4].path.read_text()
        sql = failure + sql if failure.startswith("CREATE") else sql + failure
        (folder / migrations[4].path.name).write_text(sql)

        conn = connect(populated)
        before = dump(conn)
        schema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()

        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)

        assert not conn.in_transaction
        assert schema_version(conn) == 4
        assert dump(conn) == before
        assert conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY name"
        ).fetchall() == schema
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        assert migrate(conn) == len(migrations)
        assert dump(conn) == before
        conn.close()


@pytest.fixture
def history(tmp_path):
    """One decision with a constraint and an event, written directly."""
    path = tmp_path / "ledger.db"
    create_database(path)
    conn = connect(path)
    conn.execute(
        """INSERT INTO account (id, display_name, institution, account_type)
           VALUES ('acct', 'A', 'Synthetic', 'checking')"""
    )
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        """INSERT INTO decision (id, account_id, target_id, target_revision)
           VALUES ('d1', 'acct', 'issue', 'r2-0')"""
    )
    conn.execute(
        """INSERT INTO decision_constraint (id, decision_id, relation, pair_number,
               left_transaction_id, right_transaction_id, left_record_id, right_record_id)
           VALUES (1, 'd1', 'different_event', 1, 't1', 't2', 'a', 'b')"""
    )
    conn.execute(
        """INSERT INTO decision_event (id, decision_id, event, rules_fingerprint)
           VALUES (1, 'd1', 'made', ?)""",
        (FINGERPRINT,),
    )
    yield conn
    conn.close()


REPLACEMENTS = {
    "decision": """INSERT OR REPLACE INTO decision (id, account_id, target_id, target_revision)
                   VALUES ('d1', 'acct', 'other', 'r2-1')""",
    "decision_constraint": """INSERT OR REPLACE INTO decision_constraint (id, decision_id, relation,
                   pair_number, left_transaction_id, right_transaction_id, left_record_id,
                   right_record_id)
                   VALUES (1, 'd1', 'same_event', 1, 't1', 't2', 'a', 'b')""",
    "decision_event": """INSERT OR REPLACE INTO decision_event (id, decision_id, event,
                   rules_fingerprint) VALUES (1, 'd1', 'undone', '%s')""" % FINGERPRINT,
}

# Replacing through a unique key, under a new row ID.
UNIQUE_REPLACEMENTS = {
    "decision_constraint": """INSERT OR REPLACE INTO decision_constraint (id, decision_id, relation,
                   pair_number, left_transaction_id, right_transaction_id, left_record_id,
                   right_record_id)
                   VALUES (2, 'd1', 'same_event', 1, 't1', 't2', 'a', 'b')""",
    "decision_event": """INSERT OR REPLACE INTO decision_event (id, decision_id, event,
                   rules_fingerprint) VALUES (2, 'd1', 'made', '%s')""" % FINGERPRINT,
}


class TestAppendOnly:
    @pytest.mark.parametrize("table", REPLACEMENTS)
    def test_update_is_refused(self, history, table):
        column = columns(history, table)[1]
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            history.execute(f"UPDATE {table} SET {column} = 'changed'")

    @pytest.mark.parametrize("table", REPLACEMENTS)
    def test_delete_is_refused(self, history, table):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            history.execute(f"DELETE FROM {table}")

    @pytest.mark.parametrize("table", REPLACEMENTS)
    def test_replace_is_refused(self, history, table):
        before = history.execute(f"SELECT * FROM {table}").fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            history.execute(REPLACEMENTS[table])
        assert history.execute(f"SELECT * FROM {table}").fetchall() == before

    @pytest.mark.parametrize("table", UNIQUE_REPLACEMENTS)
    def test_replace_through_a_unique_key_is_refused(self, history, table):
        before = history.execute(f"SELECT * FROM {table}").fetchall()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            history.execute(UNIQUE_REPLACEMENTS[table])
        assert history.execute(f"SELECT * FROM {table}").fetchall() == before

    def test_same_event_is_reserved_in_the_schema(self, history):
        history.execute(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                   left_transaction_id, right_transaction_id, left_record_id, right_record_id)
               VALUES ('d1', 'same_event', 2, 't1', 't2', 'a', 'b')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            history.execute(
                """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                       left_transaction_id, right_transaction_id, left_record_id, right_record_id)
                   VALUES ('d1', 'unrelated', 3, 't1', 't2', 'a', 'b')"""
            )
