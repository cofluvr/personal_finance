"""Description similarity is review evidence with known limits (D-032)."""

from dataclasses import replace

import pytest

from personal_finance.reconcile.rules import DEFAULT_RULES, RULES_VERSION, MatchingRules
from personal_finance.reconcile.similarity import block_key, parse_description, similar


def is_similar(left, right, rules=DEFAULT_RULES):
    return similar(parse_description(left, rules), parse_description(right, rules), rules)


@pytest.mark.parametrize(
    "left, right",
    [
        ("SYNTHETIC CAFE", "synthetic  cafe"),
        ("SQ *SYNTHETIC CAFE #1042", "SYNTHETIC CAFE"),
        ("POS DEBIT SYNTHETIC GROCER 0098", "SYNTHETIC GROCER STORE 98 OAKLAND CA"),
        ("SYNTHETIC HARDWARE SUPP", "SYNTHETIC HARDWARE SUPPLY CO"),
        ("TARGET T-1234 OAKLAND CA", "TARGET"),
        ("PAYPAL *NETFLIX", "NETFLIX.COM"),
    ],
)
def test_plausible_variations_are_similar(left, right):
    assert is_similar(left, right)


@pytest.mark.parametrize(
    "left, right",
    [
        ("7-ELEVEN 34512", "7ELEVEN"),
        ("FOREVER 21 #123", "FOREVER 21"),
        ("76 GAS 1234", "76 GAS 1234 OAKLAND"),
    ],
)
def test_merchant_names_containing_digits_keep_their_identity(left, right):
    assert is_similar(left, right)


@pytest.mark.parametrize(
    "left, right",
    [
        ("365 MARKET", "366 MARKET"),
        ("A1 AUTO", "A2 AUTO"),
        ("FOREVER 21", "FOREVER 22"),
    ],
)
def test_digits_can_distinguish_merchants(left, right):
    assert not is_similar(left, right)


@pytest.mark.parametrize(
    "left, right",
    [("CARD FACTORY 12", "CARD FACTORY"), ("VISA ELECTRONICS", "VISA ELECTRONICS 88")],
)
def test_channel_words_inside_a_merchant_name_are_kept(left, right):
    assert is_similar(left, right)
    assert parse_description(left, DEFAULT_RULES).merchant[0] in ("card", "visa")


def test_channel_terms_are_stripped_only_as_a_leading_run():
    assert parse_description("POS DEBIT ACME SYSTEMS", DEFAULT_RULES).merchant == ("acme", "systems")
    assert parse_description("ACME POS SYSTEMS", DEFAULT_RULES).merchant == ("acme", "pos", "systems")


@pytest.mark.parametrize(
    "left, right",
    [
        ("CHECK 1001", "CHECK 1002"),
        ("ACH PAYMENT", "ACH PAYMENT 998"),
        ("ONLINE TRANSFER 1", "ONLINE TRANSFER 2"),
        ("POS PURCHASE", "POS PURCHASE 44"),
        ("12345", "67890"),
    ],
)
def test_removing_noise_can_leave_too_little_merchant_evidence(left, right):
    assert not is_similar(left, right)


def test_identical_text_is_similar_even_without_merchant_evidence():
    assert is_similar("ACH PAYMENT", "ach  payment")


@pytest.mark.parametrize("left, right", [("", "SYNTHETIC CAFE"), (None, "X"), ("", ""), (None, None)])
def test_a_blank_description_is_no_evidence(left, right):
    assert not is_similar(left, right)


@pytest.mark.parametrize(
    "left, right",
    [
        ("SYNTHETIC CAFE", "SYNTHETIC GROCER"),
        ("UBER TRIP", "UBER EATS"),
        ("COFFEE", "BLUE BOTTLE COFFEE"),
        ("AMAZON MKTP US", "AMAZON RETAIL US"),
        ("CITY WATER DEPT", "CITY PARKING DEPT"),
        ("ACME FITNESS", "ACME FOODS"),
        ("JOE", "JOE MARKET"),
    ],
)
def test_different_merchants_are_not_similar(left, right):
    assert not is_similar(left, right)


@pytest.mark.parametrize(
    "left, right",
    [
        ("3M COMPANY", "3M CO"),
        ("24 HOUR FITNESS", "24HR FITNESS"),
        ("NORTHWIND MKT 4471", "NORTHWIND MARKET"),
        ("SQ *CAFE", "CAFE"),
    ],
)
def test_known_misses_stay_documented(left, right):
    """Recorded in D-032. Fixing one is welcome, but must update the decision."""
    assert not is_similar(left, right)


@pytest.mark.parametrize(
    "left, right",
    [
        ("NORTHWIND STORE 12", "NORTHWIND STORE 98"),
        ("76 GAS 1234", "76 GAS 9876"),
        ("BLUE BOTTLE COFFEE OAKLAND", "BLUE BOTTLE COFFEE BERKELEY"),
    ],
)
def test_known_false_positives_stay_documented(left, right):
    """Recorded in D-032. Each costs one review, never a merge."""
    assert is_similar(left, right)


def test_the_threshold_is_inclusive_and_configurable():
    pair = ("BLUE BOTTLE COFFEE OAKLAND", "BLUE BOTTLE COFFEE BERKELEY")
    assert is_similar(*pair, replace(DEFAULT_RULES, similarity_threshold_percent=75))
    assert not is_similar(*pair, replace(DEFAULT_RULES, similarity_threshold_percent=76))


def test_similarity_is_symmetric():
    pairs = [("SQ *SYNTHETIC CAFE #1", "SYNTHETIC CAFE"), ("FOREVER 21", "FOREVER 22")]
    for left, right in pairs:
        assert is_similar(left, right) == is_similar(right, left)


def test_similar_descriptions_always_share_a_block():
    """Blocking must not lose a match: similarity needs a shared token prefix."""
    pairs = [("SYNTHETIC HARDWARE SUPP", "SYNTHETIC HARDWARE SUPPLY"), ("STAR COFFEE", "STARBUCKS COFFEE")]
    for left, right in pairs:
        one, other = (parse_description(text, DEFAULT_RULES) for text in (left, right))
        assert block_key(one, DEFAULT_RULES) == block_key(other, DEFAULT_RULES)


def test_the_default_fingerprint_is_pinned():
    """If this fails, bump RULES_VERSION and update the value: see D-033."""
    assert RULES_VERSION == 1
    assert DEFAULT_RULES.fingerprint() == "0df28441bc67a7bac8cd422a7a10e148b8b84e4fcaaa8e090db0507a9f0bf4f6"


def test_any_override_changes_the_fingerprint():
    assert replace(DEFAULT_RULES, date_window_days=4).fingerprint() != DEFAULT_RULES.fingerprint()
    extra = DEFAULT_RULES.generic_tokens | {"zelle"}
    assert replace(DEFAULT_RULES, generic_tokens=extra).fingerprint() != DEFAULT_RULES.fingerprint()
    assert MatchingRules().fingerprint() == DEFAULT_RULES.fingerprint()
