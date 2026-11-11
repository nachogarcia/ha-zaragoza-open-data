"""Architecture rule: the card's fixtures are exactly the current action snapshots.

``make card-fixtures`` copies each response or error snapshot,
``test_<…>_snapshot[<name>].json``, to ``frontend/test/fixtures/<name>.json``; it
never deletes, so a copy left from a renamed or dropped snapshot is caught here.
"""

from pathlib import Path
import re

ROOT = Path(__file__).parents[2]
SNAPSHOTS = ROOT / "tests" / "acceptance" / "snapshots" / "test_actions"
FIXTURES = ROOT / "frontend" / "test" / "fixtures"
_SNAPSHOT_NAME = re.compile(r"\[(?P<name>[^\]]+)\]\.json")


def _expected() -> dict[str, Path]:
    """Return each fixture's file name and the snapshot it copies."""
    expected: dict[str, Path] = {}
    for snapshot in SNAPSHOTS.glob("*.json"):
        match = _SNAPSHOT_NAME.search(snapshot.name)
        assert match is not None, f"Unexpected action snapshot name: {snapshot.name}"
        name = f"{match['name']}.json"
        assert name not in expected, f"Two action snapshots would both be {name}"
        expected[name] = snapshot
    return expected


def test_card_fixtures_are_the_current_response_snapshots() -> None:
    """Every fixture is an action snapshot's copy, every snapshot has one, all current."""
    expected = _expected()
    assert expected, "No action snapshots found"
    present = {path.name for path in FIXTURES.iterdir()} if FIXTURES.is_dir() else set()

    stale = sorted(present - expected.keys())
    assert not stale, (
        "frontend/test/fixtures/ holds files that are no current action response "
        f"snapshot; remove them: {', '.join(stale)}"
    )
    missing = sorted(expected.keys() - present)
    assert not missing, (
        f"Card fixtures missing: {', '.join(missing)}; run `make card-fixtures`"
    )
    outdated = sorted(
        name
        for name, snapshot in expected.items()
        if (FIXTURES / name).read_text("utf-8") != snapshot.read_text("utf-8")
    )
    assert not outdated, (
        f"Card fixtures out of date: {', '.join(outdated)}; run `make card-fixtures`"
    )
