"""The category list, migration 0019 and its append-only table (CA1 to CA3, D-063).

A ledger built at the latest version, with 0019's table dropped and set back to version 18, is a
version 18 ledger: 0019 creates a table, its triggers and its starting rows only. Migration stops at
19, so that only 0019 is tested.
"""

import sqlite3
from pathlib import Path

import pytest
from test_classifications import ClassificationLedger, single
from test_decisions import ALL_TABLES, CATEGORY_TABLES, drop_category_tables
from test_real_ledger import RealLedger, vault  # noqa: F401
from test_transfer_migration import markers, migrations_up_to

from personal_finance import cli
from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.db.real_ledger import is_real_ledger
from personal_finance.reconcile.categories import (
    CATEGORY_NAME_EMPTY,
    CATEGORY_NAME_RESERVED,
    CATEGORY_NAME_USED,
    PARENT_IS_SUBCATEGORY,
    PARENT_NOT_FOUND,
)

STARTING_CATEGORIES = [
    "Housing", "Utilities and communications", "Food", "Transportation", "Health",
    "Shopping and household", "Entertainment", "Travel", "Gifts and donations", "Insurance",
    "Interest and financial fees", "Other",
]
VERSION_18_TABLES = (*ALL_TABLES, "account", "import_run", "backup_record")


def set_back_to_version_18(path) -> None:
    conn = connect(path)
    drop_category_tables(conn)
    conn.execute("PRAGMA user_version = 18")
    conn.close()


def category_rows(ledger):
    conn = ledger.conn()
    rows = conn.execute("SELECT id, name, parent_id FROM category ORDER BY id").fetchall()
    conn.close()
    return rows


def listed(ledger):
    code, out, err = ledger.run("category", "list")
    assert code == 0, err
    return out


def everything_shown(ledger, transaction):
    """What a person sees of a classified ledger, tokens included."""
    return [ledger.run(*words) for words in (
        ("totals",), ("report", "monthly"), ("transactions",), ("review", "list"),
        ("review", "classifications"), ("review", "transaction", "show", transaction),
    )]


@pytest.fixture
def populated(tmp_path, capsys):
    """Card A holding a purchase classified, then set back to version 18."""
    ledger = ClassificationLedger(tmp_path, capsys)
    transaction = single(ledger)
    ledger.classify_ok(transaction, "purchase")
    ledger.shown = everything_shown(ledger, transaction)
    ledger.transaction = transaction
    set_back_to_version_18(ledger.path)
    return ledger


class TestMigration:
    """CA1."""

    def test_it_adds_the_starting_list_and_changes_nothing_else(self, populated, tmp_path):
        before = populated.dump(VERSION_18_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "nineteen", 19)) == 19
        conn.close()
        assert populated.dump(VERSION_18_TABLES) == before
        assert markers(populated) == ["A"]
        assert [name for _, name, _ in category_rows(populated)] == STARTING_CATEGORIES
        assert all(parent is None for *_, parent in category_rows(populated))

    def test_no_total_report_or_token_changes(self, populated):
        assert populated.run("migrate")[0] == 0
        assert everything_shown(populated, populated.transaction) == populated.shown

    def test_a_ledger_at_18_is_refused_until_migrated(self, populated):
        before = populated.dump(VERSION_18_TABLES)
        code, out, err = populated.run("category", "list")
        assert (code, out) == (2, "")
        assert f"schema version 18 and this code needs {len(load_migrations())}" in err
        assert populated.dump(VERSION_18_TABLES) == before
        assert populated.run("migrate")[0] == 0
        assert listed(populated).splitlines()[0] == "Housing"

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 19)
        nineteenth = load_migrations()[18].path
        (folder / nineteenth.name).write_text(nineteenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_18_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 18
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not {name for name in names if name.startswith("category")}
        conn.close()
        assert populated.dump(VERSION_18_TABLES) == before

    def test_a_real_ledger_migrates_and_stays_real(self, vault, capsys):  # noqa: F811
        ledger = RealLedger(vault, capsys)
        set_back_to_version_18(ledger.path)
        assert ledger.run("migrate")[0] == 0
        conn = connect(ledger.path)
        assert is_real_ledger(conn)
        conn.close()
        assert [name for _, name, _ in category_rows(ledger)] == STARTING_CATEGORIES


@pytest.fixture
def ledger(tmp_path, capsys):
    return ClassificationLedger(tmp_path, capsys)


def add(ledger, name, parent=None):
    words = ["category", "add", name] + (["--parent", parent] if parent else [])
    return ledger.run(*words)


class TestAdding:
    """CA2."""

    def test_a_top_level_category_and_a_subcategory(self, ledger):
        assert add(ledger, "Pets") == (0, "Added category Pets\n", "")
        assert add(ledger, "Groceries", "Food") == (
            0, "Added category Groceries, under Food\n", "")
        rows = category_rows(ledger)
        food = next(category_id for category_id, name, _ in rows if name == "Food")
        assert rows[-2:] == [(13, "Pets", None), (14, "Groceries", food)]

    @pytest.mark.parametrize(("name", "parent", "message"), [
        ("", None, CATEGORY_NAME_EMPTY),
        ("  \t", None, CATEGORY_NAME_EMPTY),
        ("Food", None, CATEGORY_NAME_USED),
        ("Groceries", "Food", None),
        ("uncategorized", None, CATEGORY_NAME_RESERVED),
        ("Snacks", "No such parent", PARENT_NOT_FOUND),
        ("Snacks", "food", PARENT_NOT_FOUND),
        ("Snacks", "Groceries", PARENT_IS_SUBCATEGORY),
    ])
    def test_refusals_change_nothing(self, ledger, name, parent, message):
        assert add(ledger, "Groceries", "Food")[0] == 0
        before = ledger.dump((*CATEGORY_TABLES, "account"))
        code, out, err = add(ledger, name, parent)
        if message is None:
            message = CATEGORY_NAME_USED
        assert (code, out, err) == (2, "", f"Error: {message}\n")
        assert ledger.dump((*CATEGORY_TABLES, "account")) == before

    def test_names_are_compared_exactly(self, ledger):
        assert add(ledger, "food")[0] == 0
        assert add(ledger, "Food ")[0] == 0
        assert [name for _, name, _ in category_rows(ledger)][-2:] == ["food", "Food "]


class TestAppendOnly:
    """CA2: the triggers, each with a control insert that succeeds."""

    @pytest.mark.parametrize("statement", [
        "UPDATE category SET name = name",
        "UPDATE category SET parent_id = NULL",
        "DELETE FROM category WHERE name = 'Other'",
        "INSERT INTO category SELECT * FROM category WHERE name = 'Other'",
        "INSERT OR REPLACE INTO category (id, name) VALUES (1, 'Rent')",
        "INSERT OR REPLACE INTO category (name) VALUES ('Housing')",
    ])
    def test_history_refuses_change(self, ledger, statement):
        before = ledger.dump(CATEGORY_TABLES)
        conn = ledger.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        assert ledger.dump(CATEGORY_TABLES) == before
        conn.execute("INSERT INTO category (name) VALUES ('Control')")
        conn.close()

    @pytest.mark.parametrize(("parent", "error"), [
        ("(SELECT id FROM category WHERE name = 'Groceries')", "top-level"),
        ("999", "top-level"),
    ])
    def test_a_parent_must_be_top_level(self, ledger, parent, error):
        assert add(ledger, "Groceries", "Food")[0] == 0
        conn = ledger.conn()
        with pytest.raises(sqlite3.IntegrityError, match=error):
            conn.execute(f"INSERT INTO category (name, parent_id) VALUES ('Snacks', {parent})")
        conn.execute("INSERT INTO category (name, parent_id) VALUES "
                     "('Snacks', (SELECT id FROM category WHERE name = 'Food'))")
        conn.close()

    @pytest.mark.parametrize("name", ["", "   ", "uncategorized"])
    def test_a_name_must_be_usable(self, ledger, name):
        conn = ledger.conn()
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO category (name) VALUES (?)", (name,))
        conn.execute("INSERT INTO category (name) VALUES ('Uncategorized')")
        conn.close()


class TestListing:
    """CA3."""

    def test_each_category_is_listed_under_its_parent(self, ledger):
        assert add(ledger, "Groceries", "Food")[0] == 0
        assert add(ledger, "Pets")[0] == 0
        assert add(ledger, "Rent", "Housing")[0] == 0
        assert add(ledger, "Restaurants", "Food")[0] == 0
        lines = listed(ledger).splitlines()
        assert lines[:6] == ["Housing", "  Rent", "Utilities and communications", "Food",
                             "  Groceries", "  Restaurants"]
        assert lines[-2:] == ["Pets", "Categories: 16"]

    def test_names_are_escaped(self, ledger):
        assert add(ledger, "Odd\x1b[2J\nname‮")[0] == 0
        code, out, err = add(ledger, "Inner\r", "Odd\x1b[2J\nname‮")
        assert (code, err) == (0, "")
        assert out == "Added category Inner\\r, under Odd\\x1b[2J\\nname\\u202e\n"
        lines = listed(ledger).splitlines()
        assert lines[-3:] == ["Odd\\x1b[2J\\nname\\u202e", "  Inner\\r", "Categories: 14"]

    def test_it_opens_the_ledger_read_only(self, ledger, monkeypatch):
        opened = []

        def recording_connect(path: Path, *, read_only=False):
            opened.append(read_only)
            return connect(path, read_only=read_only)

        monkeypatch.setattr(cli, "connect", recording_connect)
        listed(ledger)
        assert opened == [True]
