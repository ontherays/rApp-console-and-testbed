"""The testbed-held banner, on every page where it changes what you can do.

It lived only on Jobs and Testbed. The Test Plan offered a RUN button that
ETHOS would refuse, and said nothing about why; Overview, the first page
anybody opens, did not mention it at all. One component now, three pages.
"""

from __future__ import annotations

import pytest

HELD = {
    "held": True,
    "holder": "job:j-20261005T063029Z",
    "what": "campaign ocudu-mono, rates 300, DL",
    "since": "2026-10-05T06:30:29Z",
    "error": "",
    "checked_at": "2026-10-05T06:31:00Z",
}
FREE = {"held": False, "holder": None, "what": None, "since": None,
        "error": "", "checked_at": "2026-10-05T06:31:00Z"}


def _summary(ethos_url, lock):
    body = ethos_url._load("status_summary")
    body["lock"] = lock
    ethos_url.answer("GET", "/status/summary", 200, body)
    ethos_url.answer("GET", "/lock", 200, lock)


PAGES = ["/", "/plan", "/jobs"]


@pytest.mark.parametrize("path", PAGES)
def test_a_held_testbed_is_announced_on_every_page_that_needs_it(client, ethos_url, path):
    _summary(ethos_url, HELD)

    text = client.get(path).text

    assert "The testbed is held by" in text, path
    assert "j-20261005T063029Z" in text, path
    assert "ocudu-mono" in text, path
    assert "Watch it" in text, path


@pytest.mark.parametrize("path", PAGES)
def test_a_free_testbed_says_nothing(client, ethos_url, path):
    _summary(ethos_url, FREE)
    assert "The testbed is held by" not in client.get(path).text, path


def test_all_three_pages_render_the_same_component(client, ethos_url):
    """One wording, not three that drift apart."""
    _summary(ethos_url, HELD)
    banners = []
    for path in PAGES:
        text = client.get(path).text
        start = text.index("The testbed is held by")
        banners.append(" ".join(text[start:start + 260].split()))
    assert banners[0] == banners[1] == banners[2], banners


def test_the_since_time_is_local_with_utc_in_the_tooltip(client, ethos_url):
    _summary(ethos_url, HELD)
    text = client.get("/").text
    assert "14:30" in text                       # 06:30:29Z in Asia/Taipei
    assert 'title="2026-10-05T06:30:29Z"' in text


def test_a_cli_holder_is_worded_as_a_warning_and_offers_no_link(client, ethos_url):
    _summary(ethos_url, {**HELD, "holder": "cli:3340113", "what": "campaign oai-mono"})
    text = client.get("/plan").text
    assert "running from a shell" in text
    assert "Watch it" not in text


def test_the_component_is_one_file_included_rather_than_copied():
    import pathlib

    held = pathlib.Path("console/templates/components/testbed_held.html")
    assert held.is_file()
    for page in ("overview/page.html", "plan/page.html", "jobs/page.html"):
        text = pathlib.Path("console/templates", page).read_text()
        assert 'include "components/testbed_held.html"' in text, page
        assert "The testbed is held by" not in text, f"{page} has its own copy"
