"""The snapshot schema's validator, a standard-library subset (D-075 point 5): types, required
fields, null, enums and full-match patterns, and a value kind for every money field. A consumer
ignores fields it does not know, so the validator does too; unknown_fields lists them, for the
builder's own test. Also point 6's reconciliations and point 3's excluded keys, which snapshot
verify checks."""

import json
import re
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema_v1.json"
VALUE_KINDS = ("actual", "projected", "reserved", "allocated")
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}

# Point 3: no key by these names may appear anywhere in a snapshot's content.
EXCLUDED_KEYS = frozenset({
    "raw", "raw_text", "raw_row", "cells", "file_name", "path", "document_hash",
    "content_hash", "sha256", "external_id", "source_record_id", "record_id",
    "source_document_id", "last4", "institution", "source_description", "created_at",
    "imported_at", "device", "device_id", "pairing",
})


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def major(version: str) -> int:
    return int(version.split(".")[0])


def validate(document, schema: dict) -> list[str]:
    """Every way the document differs from the schema, by path. Empty when it conforms."""
    errors = []
    version = document.get("schema_version") if isinstance(document, dict) else None
    if isinstance(version, str) and re.fullmatch(r"[0-9]+\.[0-9]+", version) and \
            major(version) != major(schema["schema_version"]):
        return [f"schema version {version} is not supported: this code reads "
                f"{major(schema['schema_version'])}.x. Use a release that reads "
                f"{major(version)}.x."]
    check(document, schema["document"], "snapshot", errors)
    return errors


def check(value, spec: dict, where: str, errors: list[str]) -> None:
    if value is None:
        if not spec["nullable"]:
            errors.append(f"{where} is null, and may not be")
        return
    expected = TYPES[spec["type"]]
    if isinstance(value, bool) and expected is not bool or not isinstance(value, expected):
        errors.append(f"{where} is not a {spec['type']}")
        return
    if spec["type"] == "object":
        for name, field in spec["fields"].items():
            if name not in value:
                if field["required"]:
                    errors.append(f"{where}.{name} is missing")
                continue
            check(value[name], field, f"{where}.{name}", errors)
    elif spec["type"] == "array":
        for position, item in enumerate(value):
            check(item, spec["items"], f"{where}[{position}]", errors)
    elif spec["type"] == "string":
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{where} is not one of its values")
        if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
            errors.append(f"{where} is not of its pattern")


def unknown_fields(value, spec: dict, where: str = "snapshot") -> list[str]:
    """Fields the schema does not describe: none may be in what the builder writes."""
    found = []
    if isinstance(value, dict) and spec["type"] == "object":
        for name, item in value.items():
            if name not in spec["fields"]:
                found.append(f"{where}.{name}")
            else:
                found += unknown_fields(item, spec["fields"][name], f"{where}.{name}")
    elif isinstance(value, list) and spec["type"] == "array":
        for position, item in enumerate(value):
            found += unknown_fields(item, spec["items"], f"{where}[{position}]")
    return found


def undeclared_money(spec: dict, where: str = "snapshot") -> list[str]:
    """Every field ending _cents needs a value kind: the paths of any that have none."""
    found = []
    if spec["type"] == "object":
        for name, field in spec["fields"].items():
            if name.endswith("_cents") and field.get("value_kind") not in VALUE_KINDS:
                found.append(f"{where}.{name}")
            found += undeclared_money(field, f"{where}.{name}")
    elif spec["type"] == "array":
        found += undeclared_money(spec["items"], f"{where}[]")
    return found


def excluded_keys(value, where: str = "content") -> list[str]:
    """Point 3's exclusions, checked by key wherever they appear."""
    found = []
    if isinstance(value, dict):
        for name, item in value.items():
            if name in EXCLUDED_KEYS:
                found.append(f"{where}.{name}")
            found += excluded_keys(item, f"{where}.{name}")
    elif isinstance(value, list):
        for position, item in enumerate(value):
            found += excluded_keys(item, f"{where}[{position}]")
    return found


def moved(group: dict) -> int:
    return group["in_cents"] - group["out_cents"]


def unreconciled(content: dict) -> list[str]:
    """Point 6: each month's five groups add to its net movement and its categories to its
    spending; each household month's members and unattributed add to the household; each
    transaction's member parts add to its amount."""
    errors = []
    for month in content["months"]:
        groups = ("income", "spending", "confirmed_transfers", "unconfirmed_transfer_kinds",
                  "unclassified")
        if sum(moved(month[name]) for name in groups) != month["net_cents"]:
            errors.append(f"month {month['month']}: the five groups do not add to net movement")
        for side in ("out_cents", "in_cents"):
            if sum(each[side] for each in month["spending_by_category"]) != \
                    month["spending"][side]:
                errors.append(f"month {month['month']}: categories do not add to spending")
    for month in content["household"]["months"]:
        for side in ("out_cents", "in_cents"):
            parts = sum(member[side] for member in month["members"])
            if parts + month["unattributed"][side] != month["household"][side]:
                errors.append(f"household month {month['month']}: members and unattributed do "
                              "not add to the household")
    for transaction in content["transactions"]:
        parts = transaction["member_parts"]
        if parts and sum(part["amount_cents"] for part in parts) != transaction["amount_cents"]:
            errors.append(f"transaction {transaction['transaction_id']}: member parts do not add "
                          "to its amount")
    return errors
