"""The planning layer's byte-identical evidence check (D-067 G1): a digest of every table that is
not a planning table, which every planning write must leave unchanged."""

import hashlib
import json
import sqlite3

from test_decisions import (
    BUDGET_TABLES,
    CONSUMPTION_TABLES,
    FUND_TABLES,
    LINK_TABLES,
    LOAN_TABLES,
    BREAKDOWN_TABLES,
    INCOME_TABLES,
    OBLIGATION_TABLES,
    SETTING_KEY_TABLES,
)

from personal_finance.db.backups import tagged

# Every table M12 and later add. Each later planning migration adds its own.
PLANNING_TABLES = frozenset((*INCOME_TABLES, *OBLIGATION_TABLES, *SETTING_KEY_TABLES,
                             *BUDGET_TABLES, *FUND_TABLES, *CONSUMPTION_TABLES,
                             *LINK_TABLES, *LOAN_TABLES,
                             *BREAKDOWN_TABLES))


def evidence_digest(conn: sqlite3.Connection) -> str:
    """SHA-256 over every pre-M12 table's rows in primary-key order, tables by name."""
    digest = hashlib.sha256()
    names = [name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name") if name not in PLANNING_TABLES]
    for name in names:
        columns = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        keys = [column[1] for column in sorted(columns, key=lambda column: column[5])
                if column[5]] or [column[1] for column in columns]
        order = ", ".join(f'"{key}"' for key in keys)
        digest.update(json.dumps(["table", name]).encode() + b"\n")
        for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY {order}'):
            digest.update(json.dumps([tagged(value) for value in row]).encode() + b"\n")
    return digest.hexdigest()
