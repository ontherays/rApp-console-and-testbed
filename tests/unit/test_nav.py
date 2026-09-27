"""The sidebar: grouping, badges, and the backend-readiness card."""

from __future__ import annotations

from console.capabilities import NOT_BUILT, OK, Capabilities
from console.nav import GROUPS, TRACKED, Badges, backend_readiness


def test_the_four_groups_are_in_the_stated_order():
    assert [group.name for group in GROUPS] == ["Essentials", "Measure", "Network", "System"]


def test_every_item_has_an_icon_and_a_destination():
    for group in GROUPS:
        for item in group.items:
            assert item.icon and item.href.startswith("/")


def test_the_later_phases_are_labelled_with_their_phase():
    network = next(g for g in GROUPS if g.name == "Network")
    assert {item.phase for item in network.items} == {"Phase 2", "Phase 3", "Phase 4"}


def test_a_badge_that_cannot_be_counted_is_absent_not_zero():
    """A "0" beside Jobs would read as "nothing is running" on a console that
    cannot tell."""
    badges = Badges()
    assert badges.get("jobs") is None
    assert badges.get("alarms") is None


def test_the_new_runs_badge_is_shown_when_there_are_any():
    assert Badges(new_runs=3).get("new_runs") == 3
    assert Badges(new_runs=None).get("new_runs") is None


def test_backend_readiness_counts_the_six_tracked_changes():
    readiness = backend_readiness(Capabilities())
    assert readiness.total == len(TRACKED) == 6
    assert readiness.ready == 0
    assert readiness.summary == "0 of 6 ready"
    assert readiness.complete is False


def test_it_names_the_next_change_that_would_land():
    readiness = backend_readiness(Capabilities())
    assert readiness.next_up.startswith("B1")


def test_it_fills_in_as_the_probe_finds_endpoints():
    caps = Capabilities(states={key: OK for key in TRACKED}, ethos_up=True)
    readiness = backend_readiness(caps)
    assert readiness.ready == 6
    assert readiness.complete is True
    assert readiness.fraction == 1.0
    assert readiness.next_up == ""


def test_a_partly_built_backend_reports_the_fraction():
    states = {key: OK for key in TRACKED[:3]}
    states.update({key: NOT_BUILT for key in TRACKED[3:]})
    readiness = backend_readiness(Capabilities(states=states, ethos_up=True))
    assert readiness.summary == "3 of 6 ready"
    assert 0.49 < readiness.fraction < 0.51
