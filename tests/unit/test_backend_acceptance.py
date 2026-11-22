"""Keeps docs/backend-acceptance.md honest about what exists, not about what is sufficient (ZA1,
ZA2, D-077 points 1 and 2)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRD = (ROOT / "docs" / "PRD-backend.md").read_text()
MATRIX = (ROOT / "docs" / "backend-acceptance.md").read_text()
DECISIONS = (ROOT / "docs" / "decisions.md").read_text()

ROW = re.compile(r"^\| (B\d+) (.+?) \| (Passed|Owner) \| (.*?) \| (.*?) \|", re.MULTILINE)


def rows():
    return ROW.findall(MATRIX)


def defined_tests(folder: Path) -> set:
    found = set()
    for path in folder.rglob("test_*.py"):
        found.update(re.findall(r"def test_([a-z0-9_]+)", path.read_text()))
    return found


def test_every_box_of_prd_21_is_in_the_matrix_once_in_order():
    section = PRD.split("## 21. Acceptance Criteria")[1].split("\n## ")[0]
    boxes = re.findall(r"^- \[ \] (.+?)\.$", section, re.MULTILINE)
    assert len(boxes) == 15
    assert [identifier for identifier, *_ in rows()] == [f"B{n}" for n in range(1, 16)]

    def words(text):
        return re.sub(r"[^a-z]+", " ", text.lower().replace("csv/pdf", "csv and pdf")).split()

    assert [words(box) for box in boxes] == [words(title) for _, title, *_ in rows()]


def test_every_named_test_exists_and_each_box_has_its_own_end_to_end_test():
    defined = defined_tests(ROOT / "tests")
    end_to_end = defined_tests(ROOT / "tests" / "acceptance")
    for identifier, _, status, tests, own in rows():
        names = re.findall(r"`([a-z0-9_]+)`", tests)
        assert names and set(names) <= defined, (identifier, set(names) - defined)
        (own_name,) = re.findall(r"`([a-z0-9_]+)`", own)
        assert own_name.startswith(identifier.lower() + "_") and own_name in end_to_end, identifier


def test_only_b15_waits_for_the_owner():
    assert [identifier for identifier, _, status, *_ in rows() if status == "Owner"] == ["B15"]


def test_not_yet_decided_names_no_open_item():
    """ZA2: every shared-contract §6 item is decided, so the section only says so."""
    section = DECISIONS.split("## Not yet decided")[1].split("\n## ")[0]
    assert "is empty" in section and "still open" not in section
