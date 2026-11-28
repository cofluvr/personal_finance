"""Every append-only table refuses an update, a delete and a duplicate on its own triggers alone
(D-082's follow-up). The migration tests show a table refusing as a whole, where a foreign key or
the primary key can refuse first: three of D-082 S2's breaks survived that way. Here each table's
columns are copied with no constraint, and only its `_no_update`, `_no_delete` and `_no_replace`
triggers, exactly as the ledger holds them, stand between a statement and the row."""

import sqlite3

import pytest
from fresh_ledger import migrated_ledger_bytes

# Written over by design: accounts, imports, reconciliation markers and review items, and the
# outcomes derived from what is stated, which are rewritten whole (D-053).
MUTABLE_TABLES = frozenset({
    "account", "account_reconciliation", "import_attempt", "import_run", "ledger_transaction",
    "one_sided_transfer_effect", "review_issue", "review_issue_subject", "transaction_allocation",
    "transaction_category", "transaction_classification", "transaction_correction",
    "transaction_fund_consumption", "transaction_income_source", "transaction_loan_breakdown",
    "transaction_obligation", "transaction_rule_category", "transaction_source", "transaction_tag",
    "transfer_match_effect",
})
# Holds one row, so its replace trigger refuses any second row (D-058).
SINGLE_ROW_TABLES = frozenset({"real_ledger"})
GUARDS = ("no_update", "no_delete", "no_replace")
REFUSED = "append-only|immutable"


def ledger_schema():
    """Each table's columns, and the append-only triggers on it, from a ledger as created now."""
    conn = sqlite3.connect(":memory:")
    conn.deserialize(migrated_ledger_bytes())
    tables = [name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name")]
    columns = {table: [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
               for table in tables}
    guards = {table: {} for table in tables}
    for name, table, sql in conn.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'"):
        for guard in GUARDS:
            if name == f"{table}_{guard}":
                guards[table][guard] = sql
    conn.close()
    return tables, columns, guards


TABLES, COLUMNS, GUARD_SQL = ledger_schema()
APPEND_ONLY_TABLES = [table for table in TABLES if table not in MUTABLE_TABLES]


def test_every_table_is_append_only_or_named_mutable():
    """A new table, or one that lost a trigger, fails here until it is guarded or named above."""
    assert MUTABLE_TABLES <= set(TABLES)
    assert SINGLE_ROW_TABLES <= set(APPEND_ONLY_TABLES)
    for table in APPEND_ONLY_TABLES:
        assert sorted(GUARD_SQL[table]) == sorted(GUARDS), table


def test_the_mutable_tables_have_no_append_only_trigger():
    for table in MUTABLE_TABLES:
        assert GUARD_SQL[table] == {}, table


def scratch(table):
    """table's columns with no constraint, and its append-only triggers as the ledger holds them."""
    conn = sqlite3.connect(":memory:", autocommit=True)
    quoted_columns = ", ".join(f'"{column}"' for column in COLUMNS[table])
    conn.execute(f'CREATE TABLE "{table}" ({quoted_columns})')
    for sql in GUARD_SQL[table].values():
        conn.execute(sql)
    return conn


def row(table, number):
    """A row whose every value differs from another number's row."""
    return tuple(f"r{number}-{position}" for position in range(len(COLUMNS[table])))


def insert(conn, table, values, verb="INSERT"):
    marks = ", ".join("?" for _ in values)
    conn.execute(f'{verb} INTO "{table}" VALUES ({marks})', values)


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
class TestEachTableOnItsTriggersAlone:
    def test_a_first_row_is_taken_and_a_different_one_unless_it_holds_one(self, table):
        conn = scratch(table)
        insert(conn, table, row(table, 1))
        if table in SINGLE_ROW_TABLES:
            with pytest.raises(sqlite3.IntegrityError, match=REFUSED):
                insert(conn, table, row(table, 2))
        else:
            insert(conn, table, row(table, 2))
            assert conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 2

    def test_an_update_is_refused(self, table):
        conn = scratch(table)
        insert(conn, table, row(table, 1))
        column = COLUMNS[table][0]
        with pytest.raises(sqlite3.IntegrityError, match=REFUSED):
            conn.execute(f'UPDATE "{table}" SET "{column}" = "{column}"')

    def test_a_delete_is_refused(self, table):
        conn = scratch(table)
        insert(conn, table, row(table, 1))
        with pytest.raises(sqlite3.IntegrityError, match=REFUSED):
            conn.execute(f'DELETE FROM "{table}"')
        assert conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 1

    @pytest.mark.parametrize("verb", ["INSERT", "INSERT OR REPLACE"])
    def test_a_duplicate_is_refused(self, table, verb):
        conn = scratch(table)
        insert(conn, table, row(table, 1))
        with pytest.raises(sqlite3.IntegrityError, match=REFUSED):
            insert(conn, table, row(table, 1), verb)
        assert conn.execute(f'SELECT * FROM "{table}"').fetchall() == [row(table, 1)]
