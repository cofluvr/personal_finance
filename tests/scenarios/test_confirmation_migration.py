"""Migration 0006 on a populated ledger holding a rejection (C18, D-046)."""

import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from personal_finance.cli import main
from personal_finance.db.migrate import connect, create_database, load_migrations, migrate, schema_version
from personal_finance.reconcile.apply import load_constraints

HEADER = "Date,Description,Debit,Credit\n"
CAFE = "01/10/2026,SYNTHETIC CAFE,6.50,\n"


def columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def tables(conn):
    return [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name <> 'schema_migrations'"
        )
    ]


def dump(conn, leave_out=("kind", "supersedes_decision_id")):
    found = {}
    for table in tables(conn):
        names = ", ".join(name for name in columns(conn, table) if name not in leave_out)
        found[table] = sorted(conn.execute(f"SELECT {names} FROM {table}").fetchall(), key=repr)
    return found


def run(capsys, *words):
    capsys.readouterr()
    code = main(list(words))
    return code, capsys.readouterr().out


@pytest.fixture
def populated(tmp_path, capsys):
    """A version 5 ledger holding a rejection, made at the latest version and copied back."""
    source = tmp_path / "source.db"
    db = str(source)
    assert main(["init", "--db", db]) == 0
    assert main(["account", "add", "--db", db, "--name", "A", "--type", "checking"]) == 0
    for number, name in enumerate(("a.csv", "b.csv", "c.csv")):
        path = tmp_path / name
        path.write_text(HEADER + " " * number + CAFE)
        assert main(["import", "--db", db, "--account", "A", "--layout", "synthetic_card_v1",
                     str(path)]) == 0
    out = run(capsys, "review", "list", "--db", db)[1]
    item = re.search(r"^Item (\S+):", out, re.MULTILINE)[1]
    out = run(capsys, "review", "show", "--db", db, item)[1]
    revision = re.search(r"Revision: (r\d+-[0-9a-f]{16})", out)[1]
    first, second = re.findall(r"^  ([0-9a-f-]{36}) ([0-9a-f-]{36})$", out, re.MULTILINE)[0]
    code, _ = run(capsys, "review", "reject", "--db", db, item, "--account", "A",
                  "--revision", revision, "--pair", first, second)
    assert code == 0

    folder = tmp_path / "old_migrations"
    folder.mkdir()
    for migration in load_migrations()[:5]:
        shutil.copy(migration.path, folder / migration.path.name)
    path = tmp_path / "old.db"
    create_database(path, folder)
    conn = connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS source", (str(source),))
    for table in tables(conn):
        names = ", ".join(columns(conn, table))
        conn.execute(f"INSERT INTO main.{table} ({names}) SELECT {names} FROM source.{table}")
    conn.execute("DETACH DATABASE source")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    return path


def account_of(conn):
    return conn.execute("SELECT id FROM account").fetchone()[0]


class TestPopulatedMigration:
    def test_the_fixture_holds_a_decision(self, populated):
        conn = connect(populated)
        assert schema_version(conn) == 5
        assert len(dump(conn)["decision_constraint"]) == 1
        conn.close()

    def test_everything_survives_and_old_decisions_are_rejections(self, populated):
        conn = connect(populated)
        before = dump(conn)
        assert migrate(conn) == len(load_migrations())
        assert dump(conn) == before
        assert conn.execute(
            "SELECT kind, supersedes_decision_id FROM decision"
        ).fetchall() == [("reject", None)]
        (constraint,) = load_constraints(conn, account_of(conn))
        assert constraint.relation == "different_event" and not constraint.confirmation
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        conn.close()

    def test_a_migrated_ledger_reconciles_to_the_same_state(self, populated, capsys):
        assert main(["migrate", "--db", str(populated)]) == 0
        before = run(capsys, "totals", "--db", str(populated))[1]
        conn = connect(populated)
        links = dump(conn)["transaction_source"]
        conn.close()
        assert run(capsys, "reconcile", "--db", str(populated))[0] == 0
        assert run(capsys, "totals", "--db", str(populated))[1] == before
        conn = connect(populated)
        assert dump(conn)["transaction_source"] == links
        conn.close()

    def test_kind_is_checked_and_superseding_stays_in_one_account(self, populated):
        conn = connect(populated)
        migrate(conn)
        account = account_of(conn)
        (old,) = conn.execute("SELECT id FROM decision").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO decision (id, account_id, review_issue_id, item_revision, kind)
                   VALUES ('x', ?, 'i', 'r', 'other')""",
                (account,),
            )
        conn.execute("INSERT INTO account (id, display_name, account_type) VALUES ('b', 'B', 'checking')")
        with pytest.raises(sqlite3.IntegrityError, match="its own account"):
            conn.execute(
                """INSERT INTO decision (id, account_id, review_issue_id, item_revision, kind,
                                         supersedes_decision_id)
                   VALUES ('y', 'b', 'i', 'r', 'confirm', ?)""",
                (old,),
            )
        conn.execute(
            """INSERT INTO decision (id, account_id, review_issue_id, item_revision, kind,
                                     supersedes_decision_id)
               VALUES ('z', ?, 'i', 'r', 'confirm', ?)""",
            (account, old),
        )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE decision SET supersedes_decision_id = NULL")
        conn.close()

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = tmp_path / "broken"
        folder.mkdir()
        migrations = load_migrations()
        for migration in migrations[:5]:
            shutil.copy(migration.path, folder / migration.path.name)
        sql = migrations[5].path.read_text() + "SELECT no_such_function();"
        (folder / migrations[5].path.name).write_text(sql)

        conn = connect(populated)
        before = dump(conn)
        schema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 5
        assert dump(conn) == before
        assert conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY name"
        ).fetchall() == schema
        assert migrate(conn) == len(migrations)
        conn.close()
