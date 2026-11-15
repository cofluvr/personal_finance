"""Rules every planning module keeps, parsed, not run (D-067 G7 and G8).

G7: no planning module reads the clock. Every computation takes its as-of date as an argument, and
only the CLI may turn the current time into one. G8: money is integer cents, so no planning module
holds a float, calls float or divides with /.
"""

import ast
from pathlib import Path

import pytest

import personal_finance

PLANNING_FOLDER = Path(personal_finance.__file__).parent / "planning"
CLOCK_CALLS = {"today", "now", "utcnow", "time", "time_ns", "monotonic", "localtime",
               "gmtime"}


def planning_modules():
    modules = sorted(PLANNING_FOLDER.rglob("*.py"))
    assert len(modules) >= 4
    return modules


def clock_reads(tree) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in CLOCK_CALLS:
            found.append(node.attr)
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            found.append("from time")
        if isinstance(node, ast.Import) and any(alias.name == "time" for alias in node.names):
            found.append("import time")
    return found


def floats(tree) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            found.append(repr(node.value))
        if isinstance(node, ast.Name) and node.id == "float":
            found.append("float")
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, ast.Div):
            found.append("/")
    return found


@pytest.mark.parametrize("path", planning_modules(), ids=lambda path: path.name)
def test_no_planning_module_reads_the_clock(path):  # G7
    assert clock_reads(ast.parse(path.read_text(), str(path))) == []


@pytest.mark.parametrize("path", planning_modules(), ids=lambda path: path.name)
def test_no_planning_module_holds_a_float(path):  # G8
    assert floats(ast.parse(path.read_text(), str(path))) == []


def test_each_check_fails_on_what_it_refuses():
    assert clock_reads(ast.parse("from datetime import date\nx = date.today()")) == ["today"]
    assert clock_reads(ast.parse("import time")) == ["import time"]
    assert sorted(floats(ast.parse("x = 1.5\ny = float(2)\nz = 3 / 2\nz /= 2"))) == [
        "/", "/", "1.5", "float"]
