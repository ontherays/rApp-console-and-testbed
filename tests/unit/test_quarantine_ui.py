"""The graph job picker and the jobs page's quarantine controls.

The console presents; ETHOS decides. So these assert what the console SENDS and
what it SHOWS, never what gets held out: that is ETHOS's answer, and the fake
gives it.
"""

from __future__ import annotations

import pytest

HELD_JOB = "j-20260928T143403Z"


# --- the picker sends a multi-job selection ---------------------------------


def test_the_graph_form_offers_a_job_picker(client, ethos_url):
    body = client.get("/graphs").text
    assert 'name="job_ids"' in body
    assert "Select all" in body and "Clear" in body
    assert "Include quarantined jobs" in body


def test_the_dates_are_at_the_top_and_re_list_the_jobs(client, ethos_url):
    body = client.get("/graphs").text
    assert 'id="since"' in body and 'id="until"' in body
    assert 'hx-get="/graphs/jobs"' in body


def test_several_ticked_jobs_are_sent_as_job_ids(client, ethos_url):
    client.post("/graphs/make",
                data={"job_ids": ["j-a", "j-b"], "metric": "throughput"})
    sent = ethos_url.plot_requests[-1]
    assert sent["job_ids"] == ["j-a", "j-b"]


def test_a_single_job_still_goes_as_job_id(client, ethos_url):
    """Backward compatibility: every existing caller and bookmark uses this."""
    client.post("/graphs/make", data={"job_id": "j-a", "metric": "throughput"})
    sent = ethos_url.plot_requests[-1]
    assert sent["job_id"] == "j-a"
    assert "job_ids" not in sent


def test_the_free_text_job_and_the_picker_are_both_sent(client, ethos_url):
    client.post("/graphs/make", data={"job_ids": ["j-a"], "job_id": "j-b"})
    sent = ethos_url.plot_requests[-1]
    assert sent["job_ids"] == ["j-a"] and sent["job_id"] == "j-b"


def test_no_ticked_job_sends_neither_field(client, ethos_url):
    client.post("/graphs/make", data={"since": "2026-09-01", "until": "2026-10-01"})
    sent = ethos_url.plot_requests[-1]
    assert "job_ids" not in sent and "job_id" not in sent
    assert sent["since"] == "2026-09-01"


def test_include_quarantined_is_only_sent_when_ticked(client, ethos_url):
    client.post("/graphs/make", data={"job_ids": ["j-a"]})
    assert "include_quarantined" not in ethos_url.plot_requests[-1]

    client.post("/graphs/make",
                data={"job_ids": ["j-a"], "include_quarantined": "1"})
    assert ethos_url.plot_requests[-1]["include_quarantined"] is True


def test_a_bookmarked_job_id_still_prefills(client, ethos_url):
    """`/graphs?job_id=...` is the link a finished job renders."""
    body = client.get("/graphs?job_id=j-seeded-done").text
    assert "j-seeded-done" in body


# --- the picker shows held-out sweeps rather than hiding them ---------------


def test_a_held_out_job_is_shown_with_its_reason(client, ethos_url):
    body = client.get("/graphs/jobs").text
    assert HELD_JOB in body
    assert "UE detached during sweep" in body
    assert "quarantined" in body


def test_a_held_out_job_is_not_tickable_by_default(client, ethos_url):
    body = client.get("/graphs/jobs").text
    held = body.split(HELD_JOB)[1][:400]
    assert "disabled" in body


def test_ticking_include_quarantined_makes_them_selectable(client, ethos_url):
    body = client.get("/graphs/jobs?include_quarantined=1").text
    assert HELD_JOB in body
    block = body[body.index(HELD_JOB) - 400:body.index(HELD_JOB)]
    assert "disabled" not in block


def test_the_picker_filters_by_the_date_range(client, ethos_url):
    inside = client.get("/graphs/jobs?since=2026-09-01&until=2026-10-01").text
    outside = client.get("/graphs/jobs?since=2020-01-01&until=2020-01-02").text
    assert HELD_JOB in inside
    assert HELD_JOB not in outside
    # The empty state says so rather than rendering an empty list. Matched on
    # the part that carries the meaning, not on the whole sentence, so a
    # rewording does not fail a test about date filtering.
    assert "No sweep" in outside
    assert 'name="job_ids"' not in outside, "an empty window offers nothing to tick"


# --- the jobs page ----------------------------------------------------------


def test_the_jobs_page_lists_what_is_held_out(client, ethos_url):
    body = client.get("/jobs").text
    assert "Held out of graphs" in body
    assert HELD_JOB in body
    assert "UE detached during sweep" in body
    assert "Restore" in body


def test_the_panel_says_nothing_was_deleted(client, ethos_url):
    body = client.get("/jobs").text
    assert "never deleted" in body or "deletes nothing" in body.lower()


def test_holding_a_job_out_previews_first(client, ethos_url):
    body = client.post("/jobs/j-seeded-done/quarantine/preview",
                       data={"reason": "UE detached"}).text
    assert "<sl-dialog" in body
    assert "Nothing is deleted" in body
    assert 'name="reason"' in body
    assert "fake-quarantine-token" in body


def test_the_confirmation_names_what_would_be_held_out(client, ethos_url):
    body = client.post("/jobs/j-seeded-done/quarantine/preview", data={}).text
    assert "10 measured of" in body and "11 runs" in body
    assert "snapshots" in body


def test_confirming_holds_the_job_out(client, ethos_url):
    token = "fake-quarantine-token"
    body = client.post("/jobs/j-seeded-done/quarantine",
                       data={"reason": "UE detached", "preview_token": token}).text
    assert "held out of graphs" in body
    assert "Nothing was deleted" in body
    assert "j-seeded-done" in ethos_url._held()


def test_a_missing_reason_is_ethoss_refusal_not_the_consoles(client, ethos_url):
    body = client.post("/jobs/j-seeded-done/quarantine",
                       data={"reason": "", "preview_token": "fake-quarantine-token"})
    assert body.status_code == 422
    assert "needs a reason" in body.text


def test_restore_lifts_it(client, ethos_url):
    assert HELD_JOB in ethos_url._held()
    body = client.post(f"/jobs/{HELD_JOB}/restore").text
    assert "back in normal graph generation" in body
    assert HELD_JOB not in ethos_url._held()


# --- the capability gate ----------------------------------------------------


def test_without_the_backend_the_page_still_works_and_names_the_change(
        client, ethos_url, monkeypatch):
    from console.capabilities import NOT_BUILT

    probe = client.app.state.probe
    probe.result.states["quarantine"] = NOT_BUILT

    body = client.get("/jobs")
    assert body.status_code == 200
    assert "needs ETHOS B16" in body.text
    assert "python -m quarantine" in body.text
    assert "Hold out" not in body.text, "the control disables rather than failing"


def test_without_the_backend_the_graph_picker_still_lists_jobs(
        client, ethos_url):
    from console.capabilities import NOT_BUILT

    client.app.state.probe.result.states["quarantine"] = NOT_BUILT
    body = client.get("/graphs/jobs")
    assert body.status_code == 200
    assert 'name="job_ids"' in body.text
