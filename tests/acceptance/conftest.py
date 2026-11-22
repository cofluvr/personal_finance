"""The acceptance tests compose the scenario tests' ledgers, so their folder is importable here."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scenarios"))
