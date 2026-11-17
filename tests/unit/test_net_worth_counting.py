"""An aggregate loan and its subaccounts are never both counted, over generated link and
observation sets, with each branch of D-071 point 2 produced (LA3)."""

from hypothesis import given
from hypothesis import strategies as st

from personal_finance.planning.funds import Observation
from personal_finance.planning.net_worth import (
    AGGREGATE_NOT_VALUED,
    AGGREGATE_VALUED,
    COUNTED,
    NOT_VALUED,
    SUBACCOUNTS_VALUED,
    Link,
    counting,
)

DAYS = st.one_of(st.none(), st.sampled_from(["2026-01-10", "2026-02-10", "2026-03-10"]))


def observed(day):
    return None if day is None else Observation(day, -100_000)


@st.composite
def link_sets(draw):
    """Up to three aggregates, each with one to three subaccounts, and loose accounts."""
    observations, links = {}, []
    for aggregate in range(draw(st.integers(0, 3))):
        observations[f"agg{aggregate}"] = observed(draw(DAYS))
        for sub in range(draw(st.integers(1, 3))):
            observations[f"sub{aggregate}-{sub}"] = observed(draw(DAYS))
            links.append(Link(f"k{aggregate}-{sub}", f"sub{aggregate}-{sub}", f"agg{aggregate}"))
    for loose in range(draw(st.integers(0, 2))):
        observations[f"loose{loose}"] = observed(draw(DAYS))
    return observations, links


@given(link_sets())
def test_never_both_and_never_a_part(found):
    observations, links = found
    how = counting(observations, links)
    groups = {}
    for link in links:
        groups.setdefault(link.aggregate_id, []).append(link.subaccount_id)
    for aggregate, subaccounts in groups.items():
        counted_subaccounts = [sub for sub in subaccounts if how[sub] == COUNTED]
        if how[aggregate] == COUNTED:
            assert not counted_subaccounts
        # A group's subaccounts count all together or not at all.
        assert len(counted_subaccounts) in (0, len(subaccounts))
    for account, observation in observations.items():
        if observation is None:
            assert how[account] != COUNTED
        elif account.startswith("loose"):
            assert how[account] == COUNTED


def test_each_branch():
    links = [Link("k1", "s1", "a"), Link("k2", "s2", "a")]
    newer = {"a": observed("2026-01-10"), "s1": observed("2026-02-10"),
             "s2": observed("2026-01-10")}
    assert counting(newer, links) == {"a": SUBACCOUNTS_VALUED, "s1": COUNTED, "s2": COUNTED}
    older = {**newer, "a": observed("2026-02-10")}
    assert counting(older, links) == {"a": COUNTED, "s1": AGGREGATE_VALUED,
                                      "s2": AGGREGATE_VALUED}
    unvalued = {"a": None, "s1": observed("2026-02-10"), "s2": observed("2026-01-10")}
    assert counting(unvalued, links) == {"a": SUBACCOUNTS_VALUED, "s1": COUNTED, "s2": COUNTED}
    partly = {"a": None, "s1": observed("2026-02-10"), "s2": None}
    assert counting(partly, links) == {"a": NOT_VALUED, "s1": AGGREGATE_NOT_VALUED,
                                       "s2": NOT_VALUED}
    missing = {"a": observed("2026-01-10"), "s1": observed("2026-02-10"), "s2": None}
    assert counting(missing, links) == {"a": COUNTED, "s1": AGGREGATE_VALUED,
                                        "s2": AGGREGATE_VALUED}
