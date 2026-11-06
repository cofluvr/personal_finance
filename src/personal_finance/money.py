"""Exact money handling.

Amounts are signed integer cents. Parsing works on the digits directly, so no
float or rounding context is involved at any step. See decisions.md D-003.
"""

import re

# Limits of a SQLite INTEGER column.
MIN_CENTS = -(2**63)
MAX_CENTS = 2**63 - 1

# Far longer than any valid amount. Checked first so that hostile or corrupt
# input never reaches int(), which raises its own error on very long digit runs.
MAX_AMOUNT_TEXT = 64

_DIGITS = r"(?P<whole>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)?(?:\.(?P<fraction>[0-9]+))?"
_SIGNED = re.compile(r"(?P<sign>[+-]?\$?|\$[+-])" + _DIGITS)
_BRACKETED = re.compile(r"\(\$?" + _DIGITS + r"\)")


class MoneyParseError(ValueError):
    """The text is present but is not an exact amount of USD cents."""


def parse_cents(text: str) -> int | None:
    """Convert source text to signed cents, or None when the text is blank.

    Blank means missing, which is different from zero. Anything else that
    cannot be represented exactly raises MoneyParseError. The error message
    never includes the input, so it is safe to log.
    """
    if not isinstance(text, str):
        raise TypeError("amounts must be parsed from text")

    body = text.strip()
    if not body:
        return None
    if len(body) > MAX_AMOUNT_TEXT:
        raise MoneyParseError("amount text is too long")

    bracketed = _BRACKETED.fullmatch(body)
    match = bracketed or _SIGNED.fullmatch(body)
    if match is None or not (match["whole"] or match["fraction"]):
        raise MoneyParseError("malformed amount")
    negative = bracketed is not None or "-" in match["sign"]

    whole = (match["whole"] or "0").replace(",", "")
    fraction = match["fraction"] or ""
    if fraction[2:].strip("0"):
        raise MoneyParseError("amount has sub-cent precision")

    cents = int(whole) * 100 + int(fraction[:2].ljust(2, "0"))
    if negative:
        cents = -cents
    if not MIN_CENTS <= cents <= MAX_CENTS:
        raise MoneyParseError("amount is out of range")
    return cents


def format_cents(cents: int) -> str:
    """Render cents as a plain decimal string such as -1234.56."""
    if not isinstance(cents, int) or isinstance(cents, bool):
        raise TypeError("cents must be an integer")
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"
