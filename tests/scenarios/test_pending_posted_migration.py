"""Migration 0012, the D-008 migration, on populated data (Q9, D-008, D-052).

The ledger is built from the first 11 migrations and populated through the import API, which works
on either form of transaction_source. Reconciling writes the tables 0013 to 0015 and 0019 to 0021 create, so
they are added by hand, leaving the version at 11. They refer to nothing 0012 rebuilds. Migration stops at 12,
so that only 0012 is tested here.
"""

import sqlite3
from pathlib import Path

import pytest

from personal_finance.db.migrate import connect, create_database, load_migrations, migrate, schema_version
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files

CARD = "Date,Description,Debit,Credit\n"
CHECKING = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"


def migrations_up_to(folder: Path, version: int) -> Path:
    folder.mkdir()
    for migration in load_migrations()[:version]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


@pytest.fixture
def at_version_11(tmp_path):
    path = tmp_path / "ledger.db"
    create_database(path, migrations_up_to(tmp_path / "eleven", 11))
    conn = connect(path)
    # The tables today's import code reads, and 0012 does not touch.
    for migration in (*load_migrations()[12:15], *load_migrations()[18:21]):
        conn.executescript(migration.path.read_text())
    conn.execute("INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'A', 'checking')")
    month = declare_complete("2026-01-01", "2026-01-31", "posting")
    files = (
        ("a.csv", CARD + "01/10/2026,SYNTHETIC CAFE,6.50,\nnot a row of this layout\n", SYNTHETIC_CARD_V1, month),
        ("b.csv", CARD + " 01/10/2026,SYNTHETIC CAFE,6.50,\n02/01/2026,SYNTHETIC SHOP,3.00,\n",
         SYNTHETIC_CARD_V1, month),
        ("c.csv", CHECKING + "S-1,2026-01-09,2026-01-10,SYNTHETIC GROCER,-9.00,POSTED\n",
         SYNTHETIC_CHECKING_V1, None),
        ("d.csv", CHECKING + " S-1,2026-01-09,2026-01-10,SYNTHETIC GROCER,-9.00,POSTED\n",
         SYNTHETIC_CHECKING_V1, None),
    )
    for name, content, layout, coverage in files:
        source = tmp_path / name
        source.write_text(content)
        (result,) = import_files(conn, [source], account_id="acct", layout=layout,
                                 declared_coverage=coverage)
        assert result.outcome == "imported", result
    assert schema_version(conn) == 11
    yield conn, tmp_path
    conn.close()


def links(conn):
    return sorted(conn.execute("SELECT * FROM transaction_source").fetchall())


def unlinked_record_of_a_linked_document(conn):
    """An unresolved record, and a transaction holding a record of its document."""
    return conn.execute(
        """SELECT record.id, record.source_document_id, link.transaction_id
           FROM source_record record
           JOIN transaction_source link ON link.source_document_id = record.source_document_id
           WHERE record.id NOT IN (SELECT source_record_id FROM transaction_source)"""
    ).fetchone()


def insert_link(conn, record, document, transaction, rule):
    conn.execute(
        """INSERT INTO transaction_source (transaction_id, source_record_id, source_document_id,
                                           account_id, link_rule)
           VALUES (?, ?, ?, 'acct', ?)""",
        (transaction, record, document, rule),
    )


def test_every_link_is_kept_and_only_confirmed_links_are_exempt(at_version_11, tmp_path):
    conn, _ = at_version_11
    before = links(conn)
    # Five valid rows. a.csv's unreadable row keeps its exact pair from being confident (D-024).
    assert len(before) == 5 and {row[4] for row in before} == {"new_record", "reliable_external_id"}
    record, document, transaction = unlinked_record_of_a_linked_document(conn)
    conn.execute("BEGIN")
    with pytest.raises(sqlite3.IntegrityError):
        insert_link(conn, record, document, transaction, "confirmed_same_event")
    conn.execute("ROLLBACK")

    assert migrate(conn, migrations_up_to(tmp_path / "twelve", 12)) == 12
    assert links(conn) == before
    conn.execute("BEGIN")
    with pytest.raises(sqlite3.IntegrityError):
        insert_link(conn, record, document, transaction, "new_record")
    insert_link(conn, record, document, transaction, "confirmed_same_event")
    conn.execute("ROLLBACK")
    assert links(conn) == before


def test_the_other_constraints_still_hold(at_version_11, tmp_path):
    conn, _ = at_version_11
    assert migrate(conn, migrations_up_to(tmp_path / "twelve", 12)) == 12
    (record, document, transaction) = conn.execute(
        "SELECT source_record_id, source_document_id, transaction_id FROM transaction_source LIMIT 1"
    ).fetchone()
    conn.execute("BEGIN")
    with pytest.raises(sqlite3.IntegrityError):
        insert_link(conn, record, document, transaction, "confirmed_same_event")
    with pytest.raises(sqlite3.IntegrityError):
        insert_link(conn, "no-such-record", document, transaction, "confirmed_same_event")
    conn.execute("ROLLBACK")


def test_a_failure_leaves_everything_as_it_was(at_version_11):
    conn, tmp_path = at_version_11
    before = links(conn)
    folder = tmp_path / "broken"
    folder.mkdir()
    migrations = load_migrations()
    for migration in migrations:
        (folder / migration.path.name).write_text(migration.path.read_text())
    (folder / migrations[11].path.name).write_text(
        migrations[11].path.read_text() + "SELECT no_such_function();"
    )
    with pytest.raises(sqlite3.Error):
        migrate(conn, folder)
    assert not conn.in_transaction
    assert schema_version(conn) == 11
    assert links(conn) == before
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "transaction_source_rebuilt" not in names
    assert "transaction_source_one_record_per_document" not in names
