"""Canonical JSON (D-075 point 1): UTF-8, keys sorted, no insignificant whitespace, and no float,
NaN or infinity anywhere. The same value always gives the same bytes."""

import hashlib
import json


class NotCanonical(ValueError):
    """A value the canonical encoding refuses: a float, a key that is not text, or a type JSON
    does not have."""


def refuse_non_canonical(value, where: str = "content") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return
    if isinstance(value, float):
        raise NotCanonical(f"{where} holds a float, which a snapshot never holds")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NotCanonical(f"{where} has a key that is not text")
            refuse_non_canonical(item, f"{where}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for position, item in enumerate(value):
            refuse_non_canonical(item, f"{where}[{position}]")
        return
    raise NotCanonical(f"{where} holds a {type(value).__name__}, which JSON does not have")


def canonical_bytes(value) -> bytes:
    refuse_non_canonical(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_of(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def parsed_canonical(data: bytes):
    """The value the bytes hold, refused unless they are exactly its canonical encoding."""
    try:
        value = json.loads(data.decode("utf-8"), parse_float=_refuse_float,
                           parse_constant=_refuse_float)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NotCanonical("the file is not UTF-8 JSON") from None
    if canonical_bytes(value) != data:
        raise NotCanonical("the file is not in canonical form: its bytes differ from its "
                           "value's canonical encoding")
    return value


def _refuse_float(text):
    raise NotCanonical("the file holds a number that is not an integer")
