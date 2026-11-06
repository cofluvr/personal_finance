"""Whether two descriptions may name the same merchant. See decisions.md D-032.

This is candidate evidence for review and must never authorize a merge. It is a
heuristic with known misses and false positives, listed in D-032.
"""

import re
import unicodedata
from dataclasses import dataclass

from personal_finance.reconcile.rules import MatchingRules

_INNER_JOINER = re.compile(r"(?<=\w)[-'’](?=\w)")
_STAR_PREFIX = re.compile(r"^(\w+)\s*\*\s*(.+)$")
_SEPARATOR = re.compile(r"[^\w]+|_")
_MASKED_NUMBER = re.compile(r"x+\d+")


@dataclass(frozen=True)
class Description:
    folded: str
    merchant: tuple[str, ...]
    references: frozenset[str]
    sufficient: bool


def fold(text: str | None) -> str:
    """Normalize case and spacing only. Two equal results are the same text."""
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def parse_description(text: str | None, rules: MatchingRules) -> Description:
    folded = fold(text)
    cleaned = _INNER_JOINER.sub("", folded)
    star = _STAR_PREFIX.match(cleaned)
    if star and star[1] in rules.star_prefixes:
        cleaned = star[2]

    tokens = _SEPARATOR.sub(" ", cleaned).split()
    start = 0
    while start < len(tokens) - 1 and tokens[start] in rules.channel_tokens:
        start += 1

    merchant, references = [], set()
    for position, token in enumerate(tokens[start:]):
        if (token.isdigit() and position > 0) or _MASKED_NUMBER.fullmatch(token):
            references.add(token)
        else:
            merchant.append(token)

    sufficient = any(token not in rules.generic_tokens and len(token) >= 2 for token in merchant)
    return Description(folded, tuple(merchant), frozenset(references), sufficient)


def block_key(description: Description, rules: MatchingRules) -> str | None:
    """Two descriptions can only be similar if they share this key, unless identical."""
    if not description.sufficient:
        return None
    return description.merchant[0][: rules.min_shared_prefix_length]


def similar(left: Description, right: Description, rules: MatchingRules) -> bool:
    if not left.folded or not right.folded:
        return False
    if left.folded == right.folded:
        return True
    if not left.sufficient or not right.sufficient:
        return False
    if not _same_token(left.merchant[0], right.merchant[0], rules):
        return False

    shorter, longer = sorted((left.merchant, right.merchant), key=len)
    if (
        len(shorter) == 1
        and left.references
        and right.references
        and left.references.isdisjoint(right.references)
    ):
        return False

    shared = _shared_tokens(shorter, longer, rules)
    if shared == len(shorter):
        return len(shorter) >= 2 or len(shorter[0]) >= rules.min_single_token_length
    dice_percent = 200 * shared
    return dice_percent >= rules.similarity_threshold_percent * (len(shorter) + len(longer))


def _same_token(left: str, right: str, rules: MatchingRules) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < rules.min_shared_prefix_length:
        return False
    return left.startswith(right) or right.startswith(left)


def _shared_tokens(shorter, longer, rules) -> int:
    remaining = list(longer)
    shared = 0
    for token in shorter:
        for other in remaining:
            if _same_token(token, other, rules):
                remaining.remove(other)
                shared += 1
                break
    return shared
