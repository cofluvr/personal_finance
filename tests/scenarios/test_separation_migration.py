"""Migration 0007 on a populated ledger holding a rejection and a confirmation (P18, D-047)."""

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
GROCER = "01/12/2026,SYNTHETIC GROCER,9.00,\n"

# How 0007 renamed columns of decision: old name, then the name a current ledger uses.
RENAMED = {"review_issue_id": "target_id", "item_revision": "target_revision"}
ADDED = {"decision": ("target_kind",), "decision_constraint": ("left_part", "right_part")}


def columns(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def tables(conn):
    return [
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name <> 'schema_migrations'"
        )
    ]


def dump(conn):
    """Every row, with columns under their current names and those 0007 added left out."""
    found = {}
    for table in tables(conn):
        names = [name for name in columns(conn, table) if name not in ADDED.get(table, ())]
        found[table] = sorted(
            conn.execute(f"SELECT {', '.join(names)} FROM {table}").fetchall(), key=repr
        )
    return found


def run(capsys, *words):
    capsys.readouterr()
    code = main(list(words))
    return code, capsys.readouterr().out


def decide(capsys, db, command, *words):
    out = run(capsys, "review", "list", "--db", db)[1]
    item = re.search(r"^Item (\S+):", out, re.MULTILINE)[1]
    out = run(capsys, "review", "show", "--db", db, item)[1]
    revision = re.search(r"Revision: (r\d+-[0-9a-f]{16})", out)[1]
    first, second = re.findall(r"^  ([0-9a-f-]{36}) ([0-9a-f-]{36})$", out, re.MULTILINE)[0]
    option = "--pair" if command == "reject" else "--group"
    code, _ = run(capsys, "review", command, "--db", db, item, "--account", "A",
                  "--revision", revision, option, first, second)
    assert code == 0


def to_version(folder: Path, version: int) -> Path:
    folder.mkdir()
    for migration in load_migrations()[:version]:
        shutil.copy(migration.path, folder / migration.path.name)
    return folder


@pytest.fixture
def populated(tmp_path, capsys):
    """A version 6 ledger holding a rejection and a confirmation, made at the latest version
    and copied back."""
    source = tmp_path / "source.db"
    db = str(source)
    assert main(["init", "--db", db]) == 0
    assert main(["account", "add", "--db", db, "--name", "A", "--type", "checking"]) == 0

    def load(number, row):
        path = tmp_path / f"{number}.csv"
        path.write_text(HEADER + " " * number + row)
        assert main(["import", "--db", db, "--account", "A", "--layout", "synthetic_card_v1",
                     str(path)]) == 0

    load(1, CAFE)
    load(2, CAFE)
    decide(capsys, db, "reject")
    load(3, GROCER)
    load(4, GROCER)
    decide(capsys, db, "confirm")

    path = tmp_path / "old.db"
    create_database(path, to_version(tmp_path / "old_migrations", 6))
    conn = connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ATTACH DATABASE ? AS source", (str(source),))
    for table in tables(conn):
        names = columns(conn, table)
        renamed = RENAMED if table == "decision" else {}
        selected = ", ".join(renamed.get(name, name) for name in names)
        conn.execute(
            f"INSERT INTO main.{table} ({', '.join(names)}) SELECT {selected} FROM source.{table}"
        )
    conn.execute("DETACH DATABASE source")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    return path


def account_of(conn):
    return conn.execute("SELECT id FROM account").fetchone()[0]


def old_dump(conn):
    """A version 6 dump under the names 0007 gives its columns."""
    found = {}
    for table in tables(conn):
        renamed = RENAMED if table == "decision" else {}
        names = ", ".join(
            f"{name} AS {renamed[name]}" if name in renamed else name
            for name in columns(conn, table)
        )
        found[table] = sorted(conn.execute(f"SELECT {names} FROM {table}").fetchall(), key=repr)
    return found


class TestPopulatedMigration:
    def test_the_fixture_holds_both_kinds_of_decision(self, populated):
        conn = connect(populated)
        assert schema_version(conn) == 6
        kinds = conn.execute("SELECT kind FROM decision ORDER BY kind").fetchall()
        assert kinds == [("confirm",), ("reject",)]
        assert len(old_dump(conn)["decision_constraint"]) == 2
        conn.close()

    def test_everything_survives_and_old_decisions_target_items(self, populated, tmp_path):
        conn = connect(populated)
        before = old_dump(conn)
        constraints = load_constraints(conn, account_of(conn))
        assert migrate(conn, to_version(tmp_path / "to_0007", 7)) == 7
        assert dump(conn) == before
        assert conn.execute("SELECT DISTINCT target_kind FROM decision").fetchall() == [("item",)]
        assert conn.execute(
            "SELECT COUNT(*) FROM decision_constraint WHERE left_part IS NOT NULL "
            "OR right_part IS NOT NULL"
        ).fetchone() == (0,)
        assert load_constraints(conn, account_of(conn)) == constraints
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        conn.close()

    def test_indexes_and_triggers_are_recreated(self, populated, tmp_path):
        conn = connect(populated)
        query = """SELECT type, name FROM sqlite_master
                   WHERE tbl_name = 'decision_constraint' AND type IN ('index', 'trigger')
                   ORDER BY name"""
        before = conn.execute(query).fetchall()
        migrate(conn, to_version(tmp_path / "to_0007", 7))
        assert conn.execute(query).fetchall() == before
        # Two indexes, the UNIQUE constraint's own index and three triggers.
        assert len(before) == 6
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

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = to_version(tmp_path / "broken", 6)
        migrations = load_migrations()
        sql = migrations[6].path.read_text() + "SELECT no_such_function();"
        (folder / migrations[6].path.name).write_text(sql)

        conn = connect(populated)
        before = old_dump(conn)
        schema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 6
        assert old_dump(conn) == before
        assert conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY name"
        ).fetchall() == schema
        assert migrate(conn) == len(migrations)
        conn.close()


@pytest.fixture
def migrated(populated, tmp_path):
    conn = connect(populated)
    migrate(conn, to_version(tmp_path / "to_0007", 7))
    conn.execute("PRAGMA foreign_keys = OFF")
    yield conn
    conn.close()


def insert_pair(conn, number, relation, left_transaction, right_transaction, parts):
    conn.execute(
        """INSERT INTO decision_constraint (decision_id, relation, pair_number,
               left_transaction_id, right_transaction_id, left_record_id, right_record_id,
               left_part, right_part)
           VALUES ('s', ?, ?, ?, ?, 'a', 'b', ?, ?)""",
        (relation, number, left_transaction, right_transaction, *parts),
    )


class TestNewChecks:
    def test_a_separation_can_hold_both_sides_in_one_transaction(self, migrated):
        migrated.execute(
            """INSERT INTO decision (id, account_id, target_id, target_revision, kind,
                                     target_kind)
               VALUES ('s', ?, 't', 't1-0', 'confirm', 'transaction')""",
            (account_of(migrated),),
        )
        insert_pair(migrated, 1, "different_event", "t", "t", (1, 2))
        insert_pair(migrated, 2, "same_event", "t", "t", (1, 1))

    @pytest.mark.parametrize(
        ("relation", "transactions", "parts"),
        [
            ("different_event", ("t", "t"), (None, None)),  # one transaction needs parts
            ("different_event", ("t", "t"), (1, None)),  # parts come together
            ("different_event", ("t", "t"), (1, 1)),  # different events are in different parts
            ("same_event", ("t", "t"), (1, 2)),  # one event is in one part
            ("same_event", ("t", "t"), (0, 0)),  # parts count from 1
        ],
    )
    def test_inconsistent_parts_are_refused(self, migrated, relation, transactions, parts):
        with pytest.raises(sqlite3.IntegrityError):
            insert_pair(migrated, 1, relation, *transactions, parts)

    def test_target_kind_is_checked(self, migrated):
        with pytest.raises(sqlite3.IntegrityError):
            migrated.execute(
                """INSERT INTO decision (id, account_id, target_id, target_revision, target_kind)
                   VALUES ('x', ?, 't', 'r', 'other')""",
                (account_of(migrated),),
            )

    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE decision_constraint SET left_part = 1",
            "DELETE FROM decision_constraint",
            """INSERT OR REPLACE INTO decision_constraint
                   SELECT * FROM decision_constraint LIMIT 1""",
            "UPDATE decision SET target_kind = 'transaction'",
            "DELETE FROM decision",
        ],
    )
    def test_decision_tables_stay_append_only(self, migrated, statement):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            migrated.execute(statement)
