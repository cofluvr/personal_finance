"""F2, closed as not needed (D-077 point 9): an ID retired before migration 0004 has no stored
creation time, and only pf trace shows that fallback, labelled approximate. Nothing the browser,
an export or the phone receives presents a creation time, so no stored marker is needed. This
test keeps it so: a page, export or snapshot module that starts reading created_at fails here,
and F2's marker must then be built first."""

from pathlib import Path

import personal_finance

PACKAGE = Path(personal_finance.__file__).parent
# validate.py names created_at only to refuse it as an excluded key.
SHOWN_ELSEWHERE = [*sorted((PACKAGE / "ui").glob("*.py")),
                   *sorted(path for path in (PACKAGE / "snapshot").glob("*.py")
                           if path.name != "validate.py"),
                   PACKAGE / "db" / "exports.py"]


def test_no_page_export_or_snapshot_reads_a_creation_time():
    assert len(SHOWN_ELSEWHERE) >= 6
    readers = [path.relative_to(PACKAGE).as_posix() for path in SHOWN_ELSEWHERE
               if "created_at" in path.read_text(encoding="utf-8")]
    assert readers == []


def test_the_snapshot_refuses_one():
    from personal_finance.snapshot.validate import EXCLUDED_KEYS

    assert "created_at" in EXCLUDED_KEYS
