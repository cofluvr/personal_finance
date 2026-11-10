"""The category list, named by a person. See decisions.md D-063.

Append-only: a category is never renamed, merged or deleted, so whatever is categorized keeps
meaning what it meant. One level deep: a subcategory's parent is a top-level category. Names are
compared exactly and kept as typed.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.decisions import DecisionRefused

# What spending is until a category applies. Never stored, so no category may take the name.
UNCATEGORIZED = "uncategorized"

CATEGORY_NAME_EMPTY = "a category needs a name that is not blank. Nothing was changed."
CATEGORY_NAME_RESERVED = (
    f"{UNCATEGORIZED} is what spending is until a category applies, so no category takes the "
    "name. Nothing was changed."
)
CATEGORY_NAME_USED = "a category of this name already exists. Nothing was changed."
PARENT_NOT_FOUND = "parent category not found. Run category list. Nothing was changed."
PARENT_IS_SUBCATEGORY = (
    "the parent is itself a subcategory, and categories are one level deep. Name a top-level "
    "category as the parent. Nothing was changed."
)


@dataclass(frozen=True)
class Category:
    category_id: int
    name: str
    # None for a top-level category.
    parent_id: int | None


def find_category(conn: sqlite3.Connection, name: str) -> Category | None:
    row = conn.execute("SELECT id, name, parent_id FROM category WHERE name = ?",
                       (name,)).fetchone()
    return None if row is None else Category(*row)


def add_category(conn: sqlite3.Connection, name: str, parent_name: str | None = None) -> Category:
    """Add a top-level category, or a subcategory of a top-level one, under one write lock."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        category = _add_category(conn, name, parent_name)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return category


def _add_category(conn, name, parent_name) -> Category:
    if not name.strip():
        raise DecisionRefused(CATEGORY_NAME_EMPTY)
    if name == UNCATEGORIZED:
        raise DecisionRefused(CATEGORY_NAME_RESERVED)
    if find_category(conn, name) is not None:
        raise DecisionRefused(CATEGORY_NAME_USED)
    parent_id = None
    if parent_name is not None:
        parent = find_category(conn, parent_name)
        if parent is None:
            raise DecisionRefused(PARENT_NOT_FOUND)
        if parent.parent_id is not None:
            raise DecisionRefused(PARENT_IS_SUBCATEGORY)
        parent_id = parent.category_id
    category_id = conn.execute(
        "INSERT INTO category (name, parent_id) VALUES (?, ?) RETURNING id", (name, parent_id)
    ).fetchone()[0]
    return Category(category_id, name, parent_id)


def list_categories(conn: sqlite3.Connection) -> list[Category]:
    """Every category in the order made, each top-level one followed by its subcategories."""
    categories = [Category(*row) for row in conn.execute(
        "SELECT id, name, parent_id FROM category ORDER BY id")]
    return [
        listed
        for top in categories if top.parent_id is None
        for listed in (top, *(child for child in categories
                              if child.parent_id == top.category_id))
    ]
