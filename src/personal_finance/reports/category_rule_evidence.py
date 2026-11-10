"""What a category rule would change, what one does now, and its tokens (D-064).

Everything here reads the ledger and nothing writes to it. A preview and an undo outlook compare
the rules' outcomes with and without one rule, over the evidence held now, so a person sees every
transaction whose category would change before anything is written.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.category_rule_effects import (
    RULE_CONFLICT,
    CategoryRule,
    RuleDefinition,
    RuleOutcome,
    load_active_rules,
    load_spending_facts,
    matching_rules,
    rule_outcomes,
)

# Bump whenever the material below changes, so an old token can never appear current.
PREVIEW_REVISION_VERSION = 1
RULE_UNDO_REVISION_VERSION = 1

# The ID a proposed rule takes while it is previewed. Never stored.
PROPOSED_RULE_ID = "proposed"


@dataclass(frozen=True)
class RuleChange:
    """One transaction whose category a rule, or undoing one, would change."""

    transaction_id: str
    # The rules' outcome before and after, None where no rule applies.
    before: RuleOutcome | None
    after: RuleOutcome | None


@dataclass(frozen=True)
class RuleOutlook:
    revision: str
    changes: tuple[RuleChange, ...]
    # Spending transactions the rule matches, and of them where a person's categorization comes
    # first, and where the outcome is the same with it as without.
    matched: int
    categorized_by_person: int
    unchanged: int


@dataclass(frozen=True)
class StoredRule:
    rule_id: str
    definition: RuleDefinition
    category_name: str
    # The account's name, or None for every account.
    account_name: str | None
    created_at: str
    undone_at: str | None

    @property
    def state(self) -> str:
        return "undone" if self.undone_at else "active"


@dataclass(frozen=True)
class RuleReach:
    """Where an active rule reaches now, by transaction ID."""

    categorizes: tuple[str, ...]
    # Transactions where it disagrees with another rule, and so none applies.
    disagrees: tuple[str, ...]
    # Transactions it matches where a person's categorization comes first.
    categorized_by_person: tuple[str, ...]


def preview_outlook(conn: sqlite3.Connection, definition: RuleDefinition) -> RuleOutlook:
    """What adding a rule would change, and its p1 token."""
    rules_now = load_active_rules(conn)
    proposed = CategoryRule(PROPOSED_RULE_ID, definition)
    return _outlook(conn, rules_now, (*rules_now, proposed), proposed,
                    {"definition": definition_material(conn, definition)},
                    f"p{PREVIEW_REVISION_VERSION}")


def undo_outlook(conn: sqlite3.Connection, rule: StoredRule) -> RuleOutlook:
    """What undoing an active rule would change, and its q1 token. Only an active rule has one,
    so its state is not covered."""
    rules_now = load_active_rules(conn)
    rules_after = load_active_rules(conn, treated_as_undone=rule.rule_id)
    return _outlook(conn, rules_now, rules_after, CategoryRule(rule.rule_id, rule.definition),
                    {"definition": definition_material(conn, rule.definition)},
                    f"q{RULE_UNDO_REVISION_VERSION}")


def _outlook(conn, rules_now, rules_after, rule, material, prefix) -> RuleOutlook:
    facts = load_spending_facts(conn)
    now = rule_outcomes(facts, rules_now)
    after = rule_outcomes(facts, rules_after)
    changes = tuple(
        RuleChange(transaction_id, now.get(transaction_id), after.get(transaction_id))
        for transaction_id in sorted(set(now) | set(after))
        if _effect(now.get(transaction_id)) != _effect(after.get(transaction_id))
    )
    matched = set(matching_rules(facts, (rule,)))
    by_person = {facts_of.transaction_id for facts_of in facts
                 if facts_of.categorized_by_person and facts_of.transaction_id in matched}
    name_by_category = dict(conn.execute("SELECT id, name FROM category"))
    keys = record_keys(conn, [change.transaction_id for change in changes])

    def view(outcome):
        effect = _effect(outcome)
        return None if effect is None else [effect[0], name_by_category.get(effect[1])]

    material["changes"] = sorted(
        [keys[change.transaction_id], view(change.before), view(change.after)]
        for change in changes
    )
    return RuleOutlook(f"{prefix}-{digest(material)}", changes, len(matched), len(by_person),
                       len(matched) - len(by_person)
                       - sum(1 for change in changes if change.transaction_id in matched))


def _effect(outcome: RuleOutcome | None):
    """What an outcome does to a transaction's category: which rules disagree does not change
    it."""
    return None if outcome is None else (outcome.state, outcome.category_id)


def definition_material(conn: sqlite3.Connection, definition: RuleDefinition) -> dict:
    """A rule's definition by names, which are unique and never change, since IDs say only where
    something is stored."""
    category = conn.execute("SELECT name FROM category WHERE id = ?",
                            (definition.category_id,)).fetchone()
    account = conn.execute("SELECT display_name FROM account WHERE id = ?",
                           (definition.account_id,)).fetchone()
    return {
        "category": category and category[0],
        "description_contains": definition.description_contains,
        "normalization_version": definition.normalization_version,
        "account": account and account[0],
        "financial_type": definition.financial_type,
        "from_date": definition.from_date,
    }


def record_keys(conn: sqlite3.Connection, transaction_ids) -> dict[str, list]:
    """Each transaction's records by document hash and row, which say what it holds in any
    ledger, unlike its random ID."""
    keys = {transaction_id: [] for transaction_id in transaction_ids}
    if not keys:
        return keys
    for transaction_id, content_sha256, row in conn.execute(
        """SELECT link.transaction_id, document.content_sha256, record.record_index
           FROM transaction_source link
           JOIN source_record record ON record.id = link.source_record_id
           JOIN source_document document ON document.id = record.source_document_id
           WHERE link.transaction_id IN (SELECT value FROM json_each(?))""",
        (json.dumps(sorted(keys)),),
    ):
        keys[transaction_id].append([content_sha256, row])
    return {transaction_id: sorted(found) for transaction_id, found in keys.items()}


def load_rule(conn: sqlite3.Connection, rule_id: str) -> StoredRule | None:
    row = conn.execute(
        """SELECT rule.id, rule.category_id, rule.description_contains, rule.account_id,
                  rule.financial_type, rule.from_date, rule.normalization_version,
                  category.name, account.display_name, rule.created_at, undone.created_at
           FROM category_rule rule
           JOIN category ON category.id = rule.category_id
           LEFT JOIN account ON account.id = rule.account_id
           LEFT JOIN category_rule_event undone
               ON undone.rule_id = rule.id AND undone.event = 'undone'
           WHERE rule.id = ?""",
        (rule_id,),
    ).fetchone()
    return None if row is None else _stored(row)


def list_rules(conn: sqlite3.Connection, account_id: str | None = None) -> list[StoredRule]:
    """Every rule in the order made, or those that can reach one account."""
    return [_stored(row) for row in conn.execute(
        """SELECT rule.id, rule.category_id, rule.description_contains, rule.account_id,
                  rule.financial_type, rule.from_date, rule.normalization_version,
                  category.name, account.display_name, rule.created_at, undone.created_at
           FROM category_rule rule
           JOIN category ON category.id = rule.category_id
           LEFT JOIN account ON account.id = rule.account_id
           LEFT JOIN category_rule_event undone
               ON undone.rule_id = rule.id AND undone.event = 'undone'
           WHERE :account IS NULL OR rule.account_id IS NULL OR rule.account_id = :account
           ORDER BY rule.created_at, rule.id""",
        {"account": account_id},
    )]


def _stored(row) -> StoredRule:
    (rule_id, category_id, text, account_id, financial_type, from_date, version, category_name,
     account_name, created_at, undone_at) = row
    return StoredRule(rule_id, RuleDefinition(category_id, text, account_id, financial_type,
                                              from_date, version),
                      category_name, account_name, created_at, undone_at)


def reach_of_rules(conn: sqlite3.Connection, account_id: str | None = None) -> dict[str, RuleReach]:
    """Where each active rule reaches now, from the evidence held now, optionally in one
    account."""
    rules = load_active_rules(conn)
    facts = [facts for facts in load_spending_facts(conn)
             if account_id is None or facts.account_id == account_id]
    outcomes = rule_outcomes(facts, rules)
    by_person = {facts.transaction_id for facts in facts if facts.categorized_by_person}
    reach = {rule.rule_id: ([], [], []) for rule in rules}
    for transaction_id, rule_ids in matching_rules(facts, rules).items():
        for rule_id in rule_ids:
            if transaction_id in by_person:
                reach[rule_id][2].append(transaction_id)
            elif outcomes[transaction_id].state == RULE_CONFLICT:
                reach[rule_id][1].append(transaction_id)
            else:
                reach[rule_id][0].append(transaction_id)
    return {rule_id: RuleReach(*(tuple(sorted(found)) for found in lists))
            for rule_id, lists in reach.items()}


def digest(material: dict) -> str:
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]



@dataclass(frozen=True)
class ShownTransaction:
    """A transaction's effective values, corrected where they apply (D-049), as transactions shows
    them."""

    account_name: str
    shown_date: str
    amount_cents: int
    description: str | None


def shown_transactions(conn: sqlite3.Connection, transaction_ids) -> dict[str, ShownTransaction]:
    return {
        transaction_id: ShownTransaction(*values)
        for transaction_id, *values in conn.execute(
            """SELECT entry.id, account.display_name,
                      COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date,
                               fixed_posting_date.corrected_text, entry.posting_date),
                      COALESCE(fixed_amount.corrected_amount_cents, entry.amount_cents),
                      COALESCE(fixed_description.corrected_text, entry.description)
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
               WHERE entry.id IN (SELECT value FROM json_each(?))""",
            (json.dumps(sorted(transaction_ids)),),
        )
    }
