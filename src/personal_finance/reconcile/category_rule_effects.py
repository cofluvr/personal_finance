"""Which category rules reach which spending transaction, and the category they give. See
decisions.md D-064.

A rule is not D-033's matching rules, which this never reads. A rule matches a spending
transaction when the transaction's effective description contains the rule's text, both
normalized, and every account, type and first date the rule names holds. It binds no records, so
its outcome is derived from the evidence held now, wherever categories are rewritten, and depends
on nothing about when the rule or the transaction arrived. A person's categorization reaching a
transaction, in any state, comes first, and no rule applies there. Rules that agree apply, and
rules that disagree leave the transaction uncategorized in rule_conflict.
"""

import json
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from personal_finance.reconcile.category_effects import CONFIRMED_TRANSFER_SQL, SPENDING_TYPES

# Bump whenever normalized_text changes. A rule keeps the version it was made under, and a rule of
# a version this code does not know is refused rather than read a new way.
NORMALIZATION_VERSION = 1

RULE_APPLIED = "applied"
RULE_CONFLICT = "rule_conflict"


def normalized_text(text: str) -> str:
    """Unicode NFKC, case folded, every run of whitespace one space, trimmed."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


@dataclass(frozen=True)
class RuleDefinition:
    """What a rule says. None for account, type or first date means it is not narrowed by it."""

    category_id: int
    description_contains: str
    account_id: str | None = None
    financial_type: str | None = None
    from_date: str | None = None
    normalization_version: int = NORMALIZATION_VERSION


@dataclass(frozen=True)
class CategoryRule:
    rule_id: str
    definition: RuleDefinition


@dataclass(frozen=True)
class SpendingFacts:
    """A spending transaction as a rule reads it: effective values, corrected where they apply."""

    transaction_id: str
    account_id: str
    financial_type: str
    # Normalized, or None where the transaction has no description.
    normalized_description: str | None
    # The effective transaction date, else the effective posting date, as a month is chosen.
    reporting_date: str
    # Whether a person's categorization reaches it, which comes first.
    categorized_by_person: bool


@dataclass(frozen=True)
class RuleOutcome:
    state: str
    # The category while the rules agree, else None.
    category_id: int | None
    # Every active rule matching the transaction, by ID.
    rule_ids: tuple[str, ...]


class UnknownNormalization(RuntimeError):
    """A stored rule was made under a normalization this code does not know."""


def load_active_rules(conn: sqlite3.Connection,
                      treated_as_undone: str | None = None) -> tuple[CategoryRule, ...]:
    """Every rule not undone, in the order made. treated_as_undone leaves one out."""
    rules = []
    for (rule_id, category_id, text, account_id, financial_type, from_date,
         version) in conn.execute(
        """SELECT rule.id, rule.category_id, rule.description_contains, rule.account_id,
                  rule.financial_type, rule.from_date, rule.normalization_version
           FROM category_rule rule
           WHERE NOT EXISTS (SELECT 1 FROM category_rule_event undone
                             WHERE undone.rule_id = rule.id AND undone.event = 'undone')
           ORDER BY rule.created_at, rule.id"""
    ):
        if version != NORMALIZATION_VERSION:
            raise UnknownNormalization(
                f"category rule {rule_id} uses normalization version {version}, which this code "
                "does not know"
            )
        if rule_id != treated_as_undone:
            rules.append(CategoryRule(rule_id, RuleDefinition(
                category_id, text, account_id, financial_type, from_date, version)))
    return tuple(rules)


def load_spending_facts(conn: sqlite3.Connection,
                        transaction_ids=None) -> tuple[SpendingFacts, ...]:
    """Every spending transaction of the ledger, D-056's spending group, or those of
    transaction_ids. Types, transfer effects, corrections and person's categorizations must
    already be final."""
    marks = ", ".join("?" for _ in SPENDING_TYPES)
    only = "" if transaction_ids is None else "AND entry.id IN (SELECT value FROM json_each(?))"
    parameters = [*SPENDING_TYPES]
    if transaction_ids is not None:
        parameters.append(json.dumps(sorted(transaction_ids)))
    return tuple(
        SpendingFacts(transaction_id, account_id, financial_type,
                      None if description is None else normalized_text(description),
                      reporting_date, bool(categorized_by_person))
        for (transaction_id, account_id, financial_type, description, reporting_date,
             categorized_by_person) in conn.execute(
            f"""SELECT entry.id, entry.account_id, kind.financial_type,
                       COALESCE(description_fix.corrected_text, entry.description),
                       COALESCE(date_fix.corrected_text, entry.transaction_date,
                                posting_fix.corrected_text, entry.posting_date),
                       EXISTS (SELECT 1 FROM transaction_category person
                               WHERE person.transaction_id = entry.id)
                FROM ledger_transaction entry
                JOIN transaction_classification kind
                    ON kind.transaction_id = entry.id AND kind.state = 'applied'
                   AND kind.financial_type IN ({marks})
                LEFT JOIN transaction_correction description_fix
                    ON description_fix.transaction_id = entry.id
                   AND description_fix.field = 'description' AND description_fix.state = 'applied'
                LEFT JOIN transaction_correction date_fix
                    ON date_fix.transaction_id = entry.id
                   AND date_fix.field = 'transaction_date' AND date_fix.state = 'applied'
                LEFT JOIN transaction_correction posting_fix
                    ON posting_fix.transaction_id = entry.id
                   AND posting_fix.field = 'posting_date' AND posting_fix.state = 'applied'
                WHERE NOT ({CONFIRMED_TRANSFER_SQL}) {only}
                ORDER BY entry.id""",
            parameters,
        )
    )


def matching_rules(facts_list, rules) -> dict[str, tuple[str, ...]]:
    """The IDs of every rule matching each transaction that some rule matches, a person's
    categorization reaching it or not."""
    matched = defaultdict(list)
    for rule in rules:
        definition = rule.definition
        needle = normalized_text(definition.description_contains)
        for facts in facts_list:
            if (facts.normalized_description is not None
                    and needle in facts.normalized_description
                    and definition.account_id in (None, facts.account_id)
                    and definition.financial_type in (None, facts.financial_type)
                    and (definition.from_date is None
                         or facts.reporting_date >= definition.from_date)):
                matched[facts.transaction_id].append(rule.rule_id)
    return {transaction_id: tuple(sorted(rule_ids)) for transaction_id, rule_ids in matched.items()}


def rule_outcomes(facts_list, rules) -> dict[str, RuleOutcome]:
    """The outcome on every spending transaction a rule matches and no person's categorization
    reaches, keyed by transaction ID."""
    category_by_rule = {rule.rule_id: rule.definition.category_id for rule in rules}
    by_person = {facts.transaction_id for facts in facts_list if facts.categorized_by_person}
    outcomes = {}
    for transaction_id, rule_ids in matching_rules(facts_list, rules).items():
        if transaction_id in by_person:
            continue
        categories = {category_by_rule[rule_id] for rule_id in rule_ids}
        if len(categories) == 1:
            outcomes[transaction_id] = RuleOutcome(RULE_APPLIED, categories.pop(), rule_ids)
        else:
            outcomes[transaction_id] = RuleOutcome(RULE_CONFLICT, None, rule_ids)
    return outcomes


def write_rule_category_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every rule outcome of the ledger. The caller holds the transaction, and person's
    categorizations, types, transfer effects and corrections must already be final. A ledger with
    no active rule keeps no rows."""
    conn.execute("DELETE FROM transaction_rule_category")
    rules = load_active_rules(conn)
    if not rules:
        return
    outcomes = rule_outcomes(load_spending_facts(conn), rules)
    conn.executemany(
        """INSERT INTO transaction_rule_category (transaction_id, state, category_id)
           VALUES (?, ?, ?)""",
        [(transaction_id, outcome.state, outcome.category_id)
         for transaction_id, outcome in sorted(outcomes.items())],
    )


def rules_matching_texts(rules, account_id: str, texts) -> tuple[CategoryRule, ...]:
    """The rules that can reach an account and whose text one of texts contains, both normalized.
    With the evidence a token already covers, they decide the rules' outcome there."""
    normalized = [normalized_text(text) for text in texts if text]
    return tuple(
        rule for rule in rules
        if rule.definition.account_id in (None, account_id)
        and any(normalized_text(rule.definition.description_contains) in text
                for text in normalized)
    )


def rule_material(conn: sqlite3.Connection, rules) -> list:
    """Rules by what they say, names standing for IDs, for a token."""
    name_by_category = dict(conn.execute("SELECT id, name FROM category"))
    return sorted(
        [name_by_category[rule.definition.category_id], rule.definition.description_contains,
         rule.definition.financial_type, rule.definition.from_date,
         rule.definition.account_id is None]
        for rule in rules
    )
