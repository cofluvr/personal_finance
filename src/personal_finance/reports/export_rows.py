"""The rows pf export transactions writes (D-073 point 7, shared-contract §4).

Fixed, documented columns, each the effective value the ledger reports: a corrected value where
one applies, else the source's (D-049); the applied type; the category in effect, a person's
before the rules' (D-064); and the tags applying (D-073 point 5). Money is a decimal string such
as -12.34, dates are ISO, and a missing value is empty, never 0.
"""

import sqlite3

from personal_finance.money import format_cents

TRANSACTION_COLUMNS = ("transaction_id", "account", "transaction_date", "posting_date", "amount",
                       "status", "description", "financial_type", "category", "tags")
AMOUNT_COLUMNS = frozenset({"amount"})


def transaction_export_rows(conn: sqlite3.Connection, account_id: str | None = None,
                            first_date: str | None = None,
                            last_date: str | None = None) -> list[tuple]:
    """Every transaction, or one account's, whose date shown in transactions is within the range,
    inclusive, in that list's order."""
    name_by_tag = dict(conn.execute("SELECT id, name FROM tag"))
    rows = conn.execute(
        """SELECT entry.id, account.display_name,
                  COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date),
                  COALESCE(fixed_posting_date.corrected_text, entry.posting_date),
                  COALESCE(fixed_amount.corrected_amount_cents, entry.amount_cents),
                  entry.settlement_status,
                  COALESCE(fixed_description.corrected_text, entry.description),
                  kind.financial_type,
                  (SELECT name FROM category WHERE category.id = COALESCE(
                       by_person.category_id, by_rules.category_id)),
                  tagged.tags,
                  COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date,
                           fixed_posting_date.corrected_text, entry.posting_date) AS shown_date
           FROM ledger_transaction entry
           JOIN account ON account.id = entry.account_id
           LEFT JOIN transaction_correction fixed_amount
               ON fixed_amount.transaction_id = entry.id AND fixed_amount.field = 'amount'
              AND fixed_amount.state = 'applied'
           LEFT JOIN transaction_correction fixed_transaction_date
               ON fixed_transaction_date.transaction_id = entry.id
              AND fixed_transaction_date.field = 'transaction_date'
              AND fixed_transaction_date.state = 'applied'
           LEFT JOIN transaction_correction fixed_posting_date
               ON fixed_posting_date.transaction_id = entry.id
              AND fixed_posting_date.field = 'posting_date'
              AND fixed_posting_date.state = 'applied'
           LEFT JOIN transaction_correction fixed_description
               ON fixed_description.transaction_id = entry.id
              AND fixed_description.field = 'description'
              AND fixed_description.state = 'applied'
           LEFT JOIN transaction_classification kind
               ON kind.transaction_id = entry.id AND kind.state = 'applied'
           LEFT JOIN transaction_category by_person
               ON by_person.transaction_id = entry.id AND by_person.state = 'applied'
           LEFT JOIN transaction_rule_category by_rules
               ON by_rules.transaction_id = entry.id AND by_rules.state = 'applied'
           LEFT JOIN transaction_tag tagged
               ON tagged.transaction_id = entry.id AND tagged.state = 'applied'
           WHERE (:account IS NULL OR entry.account_id = :account)
           ORDER BY shown_date, entry.id""",
        {"account": account_id}).fetchall()
    found = []
    for (*values, tags, shown_date) in rows:
        if (first_date and shown_date < first_date) or (last_date and shown_date > last_date):
            continue
        transaction_id, account, transaction_date, posting_date, cents, *rest = values
        names = sorted(name_by_tag[int(tag_id)] for tag_id in tags.split(",")) if tags else []
        found.append((transaction_id, account, transaction_date, posting_date,
                      format_cents(cents), *rest, ", ".join(names) or None))
    return found
