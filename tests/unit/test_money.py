from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from personal_finance.money import (
    MAX_CENTS,
    MIN_CENTS,
    MoneyParseError,
    format_cents,
    parse_cents,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("0.00", 0),
        ("-0.00", 0),
        ("12", 1200),
        ("12.3", 1230),
        ("12.34", 1234),
        (".50", 50),
        ("+12.34", 1234),
        ("-12.34", -1234),
        ("$12.34", 1234),
        ("-$12.34", -1234),
        ("$-12.34", -1234),
        ("+$12.34", 1234),
        ("(12.34)", -1234),
        ("($12.34)", -1234),
        ("1,234.56", 123456),
        ("1,234,567.89", 123456789),
        ("  12.34  ", 1234),
        ("12.340", 1234),
        ("12.3400", 1234),
    ],
)
def test_parses_exact_amounts(text, expected):
    assert parse_cents(text) == expected


@pytest.mark.parametrize("text", ["", " ", "\t", "\n", " "])
def test_blank_is_missing_not_zero(text):
    assert parse_cents(text) is None


def test_zero_is_distinct_from_missing():
    assert parse_cents("0.00") == 0
    assert parse_cents("0.00") is not None


@pytest.mark.parametrize("text", ["12.345", "0.001", "-1.999", "12.3401"])
def test_sub_cent_precision_is_rejected_not_rounded(text):
    with pytest.raises(MoneyParseError, match="sub-cent"):
        parse_cents(text)


@pytest.mark.parametrize(
    "text",
    [
        "abc",
        "N/A",
        "-",
        "+",
        "$",
        ".",
        "()",
        "5.",
        "1e3",
        "NaN",
        "Infinity",
        "--12.34",
        "+-12.34",
        "$$12.34",
        "$-$12.34",
        "-$-12.34",
        "(-12.34)",
        "(12.34",
        "12.34)",
        "12.34-",
        "$ 12.34",
        "12 34",
        "1,23.45",
        "12,34",
        "1234,567",
        ",123",
        "12.3.4",
        "12.34 USD",
        "١٢.٣٤",
    ],
)
def test_malformed_amounts_are_rejected(text):
    with pytest.raises(MoneyParseError):
        parse_cents(text)


@pytest.mark.parametrize("value", [0.1, 12, None, Decimal("1.00"), b"1.00"])
def test_non_text_input_is_rejected(value):
    with pytest.raises(TypeError):
        parse_cents(value)


def test_error_messages_do_not_contain_the_input():
    with pytest.raises(MoneyParseError) as caught:
        parse_cents("SENTINEL 98765.43")
    assert "98765" not in str(caught.value)
    assert "SENTINEL" not in str(caught.value)


def test_amounts_beyond_decimal_default_precision_stay_exact():
    assert parse_cents("12345678901234567.89") == 1234567890123456789


def test_limits_of_the_integer_column():
    assert parse_cents(format_cents(MAX_CENTS)) == MAX_CENTS
    assert parse_cents(format_cents(MIN_CENTS)) == MIN_CENTS
    with pytest.raises(MoneyParseError, match="out of range"):
        parse_cents("92233720368547758.08")
    with pytest.raises(MoneyParseError, match="out of range"):
        parse_cents("-92233720368547758.09")


@pytest.mark.parametrize(
    "text",
    [
        "1" * 65,
        "1" * 5000,
        "9" * 1_000_000,
        "1." + "0" * 1_000_000,
        "1" + ",000" * 2000,
        "-" + "1" * 5000,
        "(" + "1" * 5000 + ")",
    ],
)
def test_excessively_long_input_fails_safely(text):
    with pytest.raises(MoneyParseError):
        parse_cents(text)


def test_surrounding_whitespace_does_not_count_towards_the_length_limit():
    assert parse_cents(" " * 1000 + "12.34" + " " * 1000) == 1234


@given(st.text(max_size=80))
def test_any_text_gives_a_value_or_a_parse_error(text):
    try:
        result = parse_cents(text)
    except MoneyParseError:
        return
    assert result is None or MIN_CENTS <= result <= MAX_CENTS


def test_summing_a_thousand_dimes_is_exact():
    assert format_cents(sum(parse_cents("0.10") for _ in range(1000))) == "100.00"


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(0, "0.00"), (5, "0.05"), (-5, "-0.05"), (1234, "12.34"), (-123456, "-1234.56")],
)
def test_format_cents(cents, expected):
    assert format_cents(cents) == expected


@pytest.mark.parametrize("value", [1.5, "12", None, True, Decimal("1")])
def test_format_rejects_non_integers(value):
    with pytest.raises(TypeError):
        format_cents(value)


@given(st.integers(min_value=MIN_CENTS, max_value=MAX_CENTS))
def test_round_trip_is_exact(cents):
    assert parse_cents(format_cents(cents)) == cents


@given(st.decimals(min_value=-(10**12), max_value=10**12, places=2, allow_nan=False))
def test_agrees_with_decimal_arithmetic(value):
    assert Decimal(parse_cents(f"{value:.2f}")) == value * 100
