"""One clock on every page.

The status strip used to print "08:24:17Z" while a banner two lines below it
printed "since 16:27". Same moment, two spellings, and nothing on the page
said which zone either was in. Everything stored stays UTC (GL-06); every
time SHOWN goes through one helper, in the display zone, with the exact UTC
instant in the tooltip.
"""

from __future__ import annotations

import re

import pytest

from console.templating import clocktime, isoutc, localtime

UTC = "2026-10-05T08:24:17Z"


# --- the helper --------------------------------------------------------------

def test_a_time_is_shown_in_the_display_zone():
    assert clocktime(UTC) == "16:24"          # Asia/Taipei is UTC+8


def test_the_tooltip_carries_the_exact_utc_instant():
    assert isoutc(UTC) == "2026-10-05T08:24:17Z"


def test_a_naive_timestamp_is_read_as_utc_not_as_local():
    """Guessing local would move every archived time by eight hours."""
    assert clocktime("2026-10-05T08:24:17") == "16:24"


def test_sub_second_precision_survives_the_round_trip():
    assert isoutc("2026-10-05T08:28:56.471791872Z") == "2026-10-05T08:28:56Z"
    assert clocktime("2026-10-05T08:28:56.471791872Z") == "16:28"


def test_nothing_is_rendered_for_nothing():
    assert isoutc(None) == "" and isoutc("") == ""
    assert localtime(None) == "n/a"


def test_an_unreadable_value_is_passed_through_rather_than_guessed():
    assert isoutc("whenever") == "whenever"


# --- and no page escapes it --------------------------------------------------

#: A clock time written as UTC: "08:24Z", "08:24:17Z". A full ISO instant is
#: fine, that is what the tooltips carry; this is the bare time-of-day form
#: that tells a reader nothing about the zone.
RAW_UTC_CLOCK = re.compile(r"(?<!\d)\d{2}:\d{2}(?::\d{2})?Z")

PAGES = ("/", "/plan", "/results", "/jobs", "/testbed", "/graphs", "/docs")


def _visible(html: str) -> str:
    """The text a person reads: tags and attributes stripped.

    Attributes are stripped on purpose. `title="2026-10-05T08:24:17Z"` is
    exactly what this rule asks for, and it must not be mistaken for the
    thing it forbids.
    """
    without_tags = re.sub(r"<[^>]*>", " ", html)
    return re.sub(r"\s+", " ", without_tags)


@pytest.mark.parametrize("path", PAGES)
def test_no_page_shows_a_bare_utc_clock(client, path):
    response = client.get(path)
    assert response.status_code in (200, 404), path
    if response.status_code != 200:
        return
    found = RAW_UTC_CLOCK.findall(_visible(response.text))
    assert not found, f"{path} shows a raw UTC time: {found[:3]}"


def test_the_status_strip_partial_is_covered_too(client):
    """It is swapped in every 5 s and is where the raw times used to be."""
    response = client.get("/partials/status")
    assert response.status_code == 200
    assert not RAW_UTC_CLOCK.findall(_visible(response.text))


def test_the_strip_still_carries_the_utc_instant_in_a_tooltip(client):
    """Local on the face, UTC underneath: removing the Z must not lose it."""
    response = client.get("/partials/status")
    assert re.search(r'title="[^"]*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', response.text)


@pytest.fixture
def fake():
    from tests.conftest import RECORDED
    from tests.fake_ethos import FakeEthos

    return FakeEthos(RECORDED)


def test_the_strip_hands_the_template_an_instant_not_a_formatted_string(fake):
    """The formatting belongs to the one helper, so status.py must not do it."""
    from console.capabilities import Capabilities
    from console.status import build_status
    from tests.conftest import run_async

    from console.rapps.ethos.client import EthosClient

    client = EthosClient("http://fake-ethos", transport=fake.transport(), status_cache_s=0)
    status = run_async(build_status(client, Capabilities()))
    assert status.as_of.endswith("Z") and "T" in status.as_of
    for item in status.items:
        if item.checked_at:
            assert "T" in item.checked_at, item


# --- Newest data (was "Freshness") -------------------------------------------

def test_the_strip_says_what_it_measures_not_how_it_feels():
    """"Freshness" named the quality, not the thing, so nobody could tell what
    it was measuring without reading the code."""
    from console.status import _newest_data_item
    from console.rapps.ethos.models import StatusSummary

    item = _newest_data_item(StatusSummary.model_validate({"freshness": {
        "results": {"last_point": "2026-10-05T07:00:00Z"},
        "o1_pm": {"last_point": None}, "o2_power": {"last_point": None},
    }}), "2026-10-05T08:24:17Z")
    assert item.label == "Newest data"
    assert item.when == "2026-10-05T07:00:00Z"
    assert "InfluxDB" in item.detail
    assert "30-day" in item.detail


@pytest.mark.parametrize(
    "age_s, state",
    [(60, "ok"), (5 * 3600, "ok"), (7 * 3600, "warn"),
     (3 * 24 * 3600, "warn"), (8 * 24 * 3600, "bad")],
)
def test_the_dot_follows_the_age(age_s, state):
    from datetime import datetime, timedelta, timezone

    from console.rapps.ethos.models import StatusSummary
    from console.status import _newest_data_item

    when = (datetime.now(timezone.utc) - timedelta(seconds=age_s)).isoformat()
    item = _newest_data_item(StatusSummary.model_validate({"freshness": {
        "results": {"last_point": when},
        "o1_pm": {"last_point": None}, "o2_power": {"last_point": None},
    }}), "x")
    assert item.state == state


def test_nothing_in_the_window_is_unknown_not_stale():
    from console.rapps.ethos.models import StatusSummary
    from console.status import _newest_data_item

    item = _newest_data_item(StatusSummary.model_validate({"freshness": {
        "results": {"last_point": None}, "o1_pm": {"last_point": None},
        "o2_power": {"last_point": None},
    }}), "x")
    assert item.state == "unknown" and item.value == "none"


def test_the_age_reads_like_a_person_wrote_it():
    from console.status import _age_text

    assert _age_text(30) == "just now"
    assert _age_text(20 * 60) == "20 min ago"
    assert _age_text(5040) == "1 h 24 min ago"
    assert _age_text(2 * 3600) == "2 h ago"
    assert _age_text(50 * 3600) == "2 d 2 h ago"
    assert _age_text(None) == ""


def test_each_source_is_named_in_the_tooltip():
    from console.rapps.ethos.models import StatusSummary
    from console.status import _newest_data_item

    item = _newest_data_item(StatusSummary.model_validate({"freshness": {
        "results": {"last_point": "2026-10-05T07:00:00Z"},
        "o1_pm": {"last_point": None},
        "o2_power": {"error": "no token"},
    }}), "x")
    assert "iperf results" in item.detail
    assert "O1 PM: nothing in the last 30 days" in item.detail
    assert "O2 power: no token" in item.detail
