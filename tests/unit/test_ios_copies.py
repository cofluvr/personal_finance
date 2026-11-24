"""The iPhone app's copies of the backend's snapshot files stay byte for byte the same (D-079, the
I1 to I3 slice plan): its schema, which its validator reads, and its demo snapshot, the golden
fixture. A schema change must reach the phone in the same commit, as a conscious version change
under shared-contract §6."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_apps_schema_is_the_backends():
    assert (ROOT / "ios/CommonCentsKit/Sources/CommonCentsKit/Resources/schema_v1.json"
            ).read_bytes() == (ROOT / "src/personal_finance/snapshot/schema_v1.json").read_bytes()


def test_the_apps_demo_snapshot_is_the_golden_fixture():
    assert (ROOT / "ios/CommonCents/CommonCents/demo-snapshot.json").read_bytes() == (
        ROOT / "tests/fixtures/synthetic/snapshots/v1.1/household.json").read_bytes()
