"""The strip's 5201 entry, judged against the mode a run would use.

`foreign` says something is listening on 5201 that ETHOS did not start and
cannot identify: ETHOS runs as `shell` on the handset and cannot read
/proc/<pid>/exe of a process owned by another uid, so the Magic iPerf app's
own server is unidentifiable by construction.

On its own that is neither good news nor bad. The two modes want opposite
states of the port, so the same holder is exactly right for one and fatal for
the other, and a dot that is green either way tells the operator nothing:

    mode         port held by someone else      port free
    app_binary   what the mode needs    green   run refused      amber
    ethos        run refused            amber   what it needs    green

These pin that table against `readiness.checks.check_iperf_server`, which is
the gate the run itself passes through.
"""

from __future__ import annotations

from console.rapps.ethos.models import IperfPart, StatusSummary
from console.status import OK, UNKNOWN, WARN, _iperf_item

CHECKED = "2026-10-18T09:00:00Z"


def _summary(*, mode: str, held: bool, owner: str = "foreign", error: str = ""):
    """A real StatusSummary, so `held` and `owner` are the model's own."""
    holder = {"pid": "22479", "uid": "u0_a336", "owner": owner} if held else None
    return StatusSummary(
        iperf_server=IperfPart(
            default_mode=mode, holder=holder, error=error, checked_at=CHECKED,
        )
    )


class TestAppBinaryMode:
    """The operator chose the app's own server on the handset."""

    def test_a_foreign_holder_is_what_this_mode_needs(self):
        item = _iperf_item(_summary(mode="app_binary", held=True), CHECKED)
        assert item.state == OK
        assert "usable" in item.value
        # and it still says the provenance is unproven rather than hiding it
        assert "not started by ETHOS" in item.detail

    def test_a_free_port_cannot_serve_this_mode(self):
        """ETHOS neither starts nor stops the app's server, so nothing
        listening means the run has nothing to talk to."""
        item = _iperf_item(_summary(mode="app_binary", held=False), CHECKED)
        assert item.state == WARN
        assert item.value == "free"
        assert "Magic iPerf" in item.detail


class TestEthosMode:
    """ETHOS brings its own server, so it needs the port."""

    def test_a_holder_blocks_this_mode_and_the_dot_says_so(self):
        item = _iperf_item(_summary(mode="ethos", held=True), CHECKED)
        assert item.state == WARN
        assert "blocks this mode" in item.value
        assert "cannot stop another uid" in item.detail

    def test_a_free_port_is_what_this_mode_needs(self):
        item = _iperf_item(_summary(mode="ethos", held=False), CHECKED)
        assert item.state == OK
        assert item.value == "free"


class TestWhatCannotBeRead:
    def test_an_error_is_unknown_and_never_green(self):
        item = _iperf_item(
            _summary(mode="app_binary", held=True, error="the UE did not answer"),
            CHECKED)
        assert item.state == UNKNOWN
        assert item.detail == "the UE did not answer"

    def test_no_default_mode_still_names_the_holder(self):
        """With no mode to judge against the strip reports rather than rules:
        there is no pairing to call right or wrong."""
        item = _iperf_item(_summary(mode="", held=True, owner="ethos"), CHECKED)
        assert item.state == OK
        assert "22479" in item.detail


def test_the_dot_is_never_the_only_signal():
    """Greyscale and colour-blind readers get the same answer: every state
    this item can take says it in words too."""
    for mode, held in (("app_binary", True), ("app_binary", False),
                       ("ethos", True), ("ethos", False)):
        item = _iperf_item(_summary(mode=mode, held=held), CHECKED)
        assert item.value.strip()
        assert item.detail.strip()
        if item.state == WARN:
            # an amber dot always carries the reason and the way out
            assert "or plan iperf_server=" in item.detail
