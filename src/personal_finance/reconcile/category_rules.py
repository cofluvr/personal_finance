"""Adding category rules stated by a person. See decisions.md D-064.

Every command checks everything under one write lock and either commits with the rules' outcomes
rewritten or changes nothing, in D-043's order: every account the rule can reach is current, then
the rule is valid, then its token. A rule moves no record and changes no amount, type, transfer or
person's categorization, so only the rules' outcomes are rewritten.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from personal_finance.reconcile.apply import stale_accounts
from personal_finance.reconcile.categories import find_category
from personal_finance.reconcile.categorizations import CATEGORY_UNKNOWN
from personal_finance.reconcile.category_rule_effects import (
    RuleDefinition,
    load_active_rules,
    normalized_text,
    write_rule_category_effects,
)
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.category_rule_evidence import RuleOutlook, preview_outlook

RULE_TEXT_BLANK = (
    "a category rule needs description text that is not blank once spaces are collapsed. "
    "Nothing was changed."
)
RULE_DATE_INVALID = "--from must be a date written YYYY-MM-DD. Nothing was changed."
RULE_ALREADY_ACTIVE = (
    "category rule {rule} is active and says exactly this already. Nothing was changed."
)
STALE_PREVIEW = (
    "this preview does not match what the rule would change now. Nothing was changed. Run "
    "category rule preview with the same options and check the changes again."
)


@dataclass(frozen=True)
class RuleAdded:
    rule_id: str
    outlook: RuleOutlook


def checked_definition(conn: sqlite3.Connection, category_name: str, description_contains: str,
                       account_id: str | None = None, financial_type: str | None = None,
                       from_date: str | None = None) -> RuleDefinition:
    """A rule as stated, refused if it names an unknown category, has no text or a bad date. The
    account and type are checked by whoever reads them."""
    category = find_category(conn, category_name)
    if category is None:
        raise DecisionRefused(CATEGORY_UNKNOWN)
    if not normalized_text(description_contains):
        raise DecisionRefused(RULE_TEXT_BLANK)
    if from_date is not None:
        try:
            parsed = date.fromisoformat(from_date)
        except ValueError:
            raise DecisionRefused(RULE_DATE_INVALID) from None
        if parsed.isoformat() != from_date:
            raise DecisionRefused(RULE_DATE_INVALID)
    return RuleDefinition(category.category_id, description_contains, account_id,
                          financial_type, from_date)


def same_meaning(one: RuleDefinition, other: RuleDefinition) -> bool:
    """Whether two rules match the same transactions and give the same category, texts differing
    only in what normalization removes."""
    return (one.category_id, normalized_text(one.description_contains), one.account_id,
            one.financial_type, one.from_date) == (
        other.category_id, normalized_text(other.description_contains), other.account_id,
        other.financial_type, other.from_date)


def refuse_unless_current(conn: sqlite3.Connection, account_id: str | None,
                          rules: MatchingRules) -> None:
    """Every account the rule can reach must be current (D-033), or nothing is decided."""
    if stale_accounts(conn, rules, account_id):
        raise DecisionRefused(STALE_ACCOUNT)


def add_rule(
    conn: sqlite3.Connection,
    category_name: str,
    description_contains: str,
    preview_revision: str,
    account_id: str | None = None,
    financial_type: str | None = None,
    from_date: str | None = None,
    rules: MatchingRules = DEFAULT_RULES,
) -> RuleAdded:
    """Record a rule whose preview is still current, and rewrite the rules' outcomes."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _add_rule(conn, category_name, description_contains, preview_revision,
                           account_id, financial_type, from_date, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _add_rule(conn, category_name, description_contains, preview_revision, account_id,
              financial_type, from_date, rules) -> RuleAdded:
    refuse_unless_current(conn, account_id, rules)
    definition = checked_definition(conn, category_name, description_contains, account_id,
                                    financial_type, from_date)
    for active in load_active_rules(conn):
        if same_meaning(active.definition, definition):
            raise DecisionRefused(RULE_ALREADY_ACTIVE.format(rule=active.rule_id))
    outlook = preview_outlook(conn, definition)
    if outlook.revision != preview_revision:
        raise DecisionRefused(STALE_PREVIEW)

    rule_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO category_rule (id, account_id, category_id, description_contains,
                                      normalization_version, financial_type, from_date)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rule_id, account_id, definition.category_id, description_contains,
         definition.normalization_version, financial_type, from_date),
    )
    conn.execute("INSERT INTO category_rule_event (rule_id, event) VALUES (?, 'made')", (rule_id,))
    write_rule_category_effects(conn)
    return RuleAdded(rule_id, outlook)
