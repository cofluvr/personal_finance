"""Keeps docs/m1-acceptance.md honest about what exists, not about what is sufficient."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = (ROOT / "docs" / "archive" / "plan-m1-m2.md").read_text()
MATRIX = (ROOT / "docs" / "m1-acceptance.md").read_text()

ROW = re.compile(r"^\| (A\d+[ab]?) \| ([A-Za-z]+) \| (.*?) \|", re.MULTILINE)


def rows():
    return ROW.findall(MATRIX)


def test_every_criterion_in_the_plan_is_in_the_matrix_once():
    planned = re.findall(r"^\| (A\d+[ab]?) \|", PLAN, re.MULTILINE)
    assert len(planned) == len(set(planned))
    assert sorted(identifier for identifier, _, _ in rows()) == sorted(planned)


def test_every_status_is_a_known_one():
    assert {status for _, status, _ in rows()} <= {"Passed", "Deferred", "Unverified"}


def test_every_passed_criterion_names_tests_that_exist():
    defined = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        defined.update(re.findall(r"def test_([a-z0-9_]+)", path.read_text()))

    for identifier, status, tests in rows():
        names = re.findall(r"`([a-z0-9_]+)`", tests)
        if status == "Passed":
            assert names, identifier
        assert set(names) <= defined, identifier
