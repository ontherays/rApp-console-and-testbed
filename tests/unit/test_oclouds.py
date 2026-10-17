"""The two O-Cloud cards: one shape, two readings, and never a guess.

joule and the DGX Spark are deployed by different mechanisms, so they are read
differently: joule has helm releases and pods, the Spark has an op phase and a
lease. What they must never do is agree on a word they did not read. A card
that could not be read says so.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from console.oclouds import (
    BAD,
    BUSY,
    IDLE,
    OK,
    WAIT,
    build_oclouds,
    card_for_server,
    joule_card,
    spark_card,
)
from console.rapps.ethos.client import EthosError
from tests.conftest import run_async


def _joule(**overrides):
    state = {"node_free": True, "releases": [], "running_pods": [],
             "node_reason": ""}
    state.update(overrides)
    return SimpleNamespace(**state)


def _spark(**overrides):
    record = {"read_ok": True, "phase": "down", "mode": None, "holder": None,
              "heartbeat": {}, "drift": []}
    record.update(overrides)
    return SimpleNamespace(ran_mode=record)


class TestJoule:
    def test_a_node_with_nothing_on_it_is_free(self):
        card = joule_card(_joule())
        assert (card.word, card.tone) == ("free", OK)
        assert not card.unreadable

    def test_a_node_with_a_release_on_it_is_busy_and_names_it(self):
        card = joule_card(_joule(node_free=False, releases=["ocudu-gnb"],
                                 running_pods=["ocudu-gnb-0"]))
        assert (card.word, card.tone) == ("busy", BUSY)
        rows = {row.label: row.value for row in card.rows}
        assert rows["gNB release"] == "ocudu-gnb"
        assert rows["pods running"] == "1"

    def test_a_free_node_that_still_has_a_release_is_busy(self):
        """Installed and running are different answers, and either one means
        the node is not free for another stack."""
        card = joule_card(_joule(node_free=True, releases=["ocudu-gnb"]))
        assert card.word == "busy"


class TestSpark:
    def test_a_mode_that_is_up_says_up(self):
        card = spark_card(_spark(phase="up", mode="ocudu-mono"))
        assert (card.word, card.tone) == ("up", OK)
        assert {"mode": "ocudu-mono"}.items() <= {
            row.label: row.value for row in card.rows}.items()

    def test_nothing_running_is_down_and_not_an_alarm(self):
        card = spark_card(_spark(phase="down"))
        assert (card.word, card.tone) == ("down", IDLE)

    @pytest.mark.parametrize("phase", ["starting", "verifying", "stopping"])
    def test_a_phase_on_the_way_is_shown_as_itself(self, phase):
        card = spark_card(_spark(phase=phase))
        assert (card.word, card.tone) == (phase, WAIT)

    def test_a_lease_held_by_this_ethos_names_its_last_beat(self):
        card = spark_card(_spark(phase="up", holder="ethos",
                                 heartbeat={"last_ok_at": "09:12:30Z"}))
        rows = {row.label: row.value for row in card.rows}
        assert rows["holder"] == "ethos"
        assert "09:12:30Z" in rows["lease"]

    def test_a_lease_held_by_someone_else_says_so(self):
        card = spark_card(_spark(holder="someone", heartbeat={}))
        rows = {row.label: row.value for row in card.rows}
        assert rows["lease"] == "held, not by this process"

    def test_a_reading_that_did_not_happen_is_never_down(self):
        """`down` is a measurement. Not having one is a different answer, and
        reporting it as down would say the Spark is free when nobody looked."""
        card = spark_card(SimpleNamespace(
            ran_mode={"read_ok": False, "reason": "ssh timed out"}))
        assert card.unreadable
        assert (card.word, card.tone) == ("can't read status", BAD)
        assert card.reason == "ssh timed out"
        assert card.rows == []

    def test_a_missing_record_is_unreadable_too(self):
        assert spark_card(SimpleNamespace(ran_mode=None)).unreadable


class TestBoth:
    class _Client:
        def __init__(self, answers):
            self.answers = answers

        async def deploy_status(self, config_id):
            answer = self.answers[config_id]
            if isinstance(answer, Exception):
                raise answer
            return answer

    def test_one_unreadable_o_cloud_does_not_hide_the_other(self):
        from console.oclouds import JOULE_CONFIG_ID, SPARK_CONFIG_ID

        cards = run_async(build_oclouds(self._Client({
            JOULE_CONFIG_ID: _joule(),
            SPARK_CONFIG_ID: EthosError("ETHOS did not answer"),
        })))
        assert [card.name for card in cards] == ["joule", "DGX Spark"]
        assert cards[0].word == "free"
        assert cards[1].unreadable
        assert "did not answer" in cards[1].reason

    def test_the_strip_follows_the_server_the_plan_names(self):
        cards = [joule_card(_joule()), spark_card(_spark())]
        assert card_for_server(cards, "joule").name == "joule"
        assert card_for_server(cards, "DGX-Spark").name == "DGX Spark"
        assert card_for_server(cards, "") is None
        assert card_for_server(cards, "somewhere-else") is None
