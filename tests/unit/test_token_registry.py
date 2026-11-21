"""Every revision token's kind, pinned (D-067 G5).

Every module under src/ is parsed, not run. A token's kind is the text before its version in an
f-string such as f"r{REVISION_VERSION}": one or two lowercase letters. A single letter followed by a
digit never reads as a two-letter kind, so t10 and tg1 cannot collide. A kind added, reused by a
second version constant, or written another way fails here.
"""

import ast
import re
from pathlib import Path

import personal_finance

PACKAGE_FOLDER = Path(personal_finance.__file__).parent
KIND = re.compile(r"[a-z]{1,2}")

# Each kind and the constant holding its version. Each later slice adds its own (G5's table).
REGISTRY = {
    "a": "ATTRIBUTION_REVISION_VERSION",
    "al": "LINK_REVISION_VERSION",
    "b": "OBSERVATION_REVISION_VERSION",
    "bp": "BUDGET_REVISION_VERSION",
    "c": "CORRECTION_REVISION_VERSION",
    "d": "DECISION_REVISION_VERSION",
    "f": "CLASSIFICATION_REVISION_VERSION",
    "fa": "ASSIGNMENT_REVISION_VERSION",
    "fc": "CONSUMPTION_REVISION_VERSION",
    "fu": "FUND_REVISION_VERSION",
    "g": "CATEGORIZATION_REVISION_VERSION",
    "h": "SHARE_REVISION_VERSION",
    "in": "INCOME_REVISION_VERSION",
    "k": "DECLARATION_REVISION_VERSION",
    "lb": "BREAKDOWN_REVISION_VERSION",
    "lq": "LIQUIDITY_REVISION_VERSION",
    "lt": "LOAN_REVISION_VERSION",
    "m": "MATCH_REVISION_VERSION",
    "o": "ONE_SIDED_REVISION_VERSION",
    "ob": "OBLIGATION_REVISION_VERSION",
    "p": "PREVIEW_REVISION_VERSION",
    "q": "RULE_UNDO_REVISION_VERSION",
    "r": "REVISION_VERSION",
    "s": "ALLOCATION_REVISION_VERSION",
    "sc": "SCENARIO_REVISION_VERSION",
    "st": "SETTING_REVISION_VERSION",
    "t": "TRANSACTION_REVISION_VERSION",
    "tg": "TAGGING_REVISION_VERSION",
    "u": "RESOLUTION_REVISION_VERSION",
    "v": "DOCUMENT_COVERAGE_REVISION_VERSION",
}


def token_kinds(tree) -> list[tuple[str, str]]:
    """Each kind and version constant an f-string starts a token with: letters, then a
    *_VERSION constant."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or len(node.values) < 2:
            continue
        first, second = node.values[:2]
        if (isinstance(first, ast.Constant) and str(first.value).isalpha()
                and isinstance(second, ast.FormattedValue)
                and isinstance(second.value, ast.Name)
                and second.value.id.endswith("_VERSION")):
            found.append((first.value, second.value.id))
    return found


def every_token_kind() -> list[tuple[str, str]]:
    return [found for path in sorted(PACKAGE_FOLDER.rglob("*.py"))
            for found in token_kinds(ast.parse(path.read_text(), str(path)))]


def test_every_kind_is_registered_once():
    found = every_token_kind()
    assert all(KIND.fullmatch(kind) for kind, _ in found), found
    assert dict(found) == REGISTRY
    assert len(set(found)) == len(REGISTRY)


def test_a_reused_or_unregistered_kind_fails():
    tree = ast.parse('A = f"r{OTHER_REVISION_VERSION}-x"\nB = f"zz{NEW_VERSION}-x"')
    found = token_kinds(tree)
    assert found == [("r", "OTHER_REVISION_VERSION"), ("zz", "NEW_VERSION")]
    assert dict([*every_token_kind(), *found]) != REGISTRY


def test_a_single_letter_and_a_version_never_read_as_two_letters():
    assert not KIND.fullmatch("t1")
    assert re.fullmatch(r"([a-z]{1,2})(\d+)-[0-9a-f]{16}", "t12-0123456789abcdef").groups() == (
        "t", "12")
    assert re.fullmatch(r"([a-z]{1,2})(\d+)-[0-9a-f]{16}", "in1-0123456789abcdef").groups() == (
        "in", "1")
