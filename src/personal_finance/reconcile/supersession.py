"""Superseding chains, for decisions and corrections alike. See decisions.md D-048 and D-049."""

STATE_ACTIVE = "active"
STATE_UNDONE = "undone"
STATE_SUPERSEDED = "superseded"


def supersession_chain_states(
    rows_of_id_superseded_id_and_undone, treated_as_undone: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Each entry's state, and for each superseded entry, the entry superseding it now.

    Shared by decisions and corrections (D-048, D-049). An entry is superseded while any entry
    superseding it has not been undone, so only the newest of a chain is active. Only an active
    entry can be superseded, so at most one entry not undone supersedes any other.
    """
    undone_by_id = {
        entry_id: bool(undone) or entry_id == treated_as_undone
        for entry_id, _, undone in rows_of_id_superseded_id_and_undone
    }
    successor_by_superseded_id = {
        superseded_id: entry_id
        for entry_id, superseded_id, _ in rows_of_id_superseded_id_and_undone
        if superseded_id is not None and not undone_by_id[entry_id]
    }
    states_by_id = {}
    for entry_id, undone in undone_by_id.items():
        if undone:
            states_by_id[entry_id] = STATE_UNDONE
        elif entry_id in successor_by_superseded_id:
            states_by_id[entry_id] = STATE_SUPERSEDED
        else:
            states_by_id[entry_id] = STATE_ACTIVE
    return states_by_id, successor_by_superseded_id


def successor_and_newest(
    successor_by_superseded_id: dict[str, str], entry_id: str
) -> tuple[str | None, str | None]:
    """The entry superseding this one now, and the newest of its chain, or None for both while
    nothing supersedes it (D-048)."""
    successor = newest = successor_by_superseded_id.get(entry_id)
    while newest in successor_by_superseded_id:
        newest = successor_by_superseded_id[newest]
    return successor, newest
