"""The endpoints that landed, and what the console does with them.

B1 the lock, B2 jobs, B5 readiness, B6 the summary, B7 the per-job iperf mode and
B11 UE control. Everything here runs against the fake ETHOS, which replays
responses recorded from the real API, so the shapes are real ones.

What is under test is the console's behaviour at the seams: that it renders
ETHOS's verdict rather than forming its own, that an act always goes through a
preview and a token, that a refusal names the holder, and that the event relay
forwards the one header the resume depends on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import RECORDED, run_async

from console import holders
from console.rapps.ethos.client import EthosClient
from console.readiness import first_failure, rows, unavailable
from console.rapps.ethos.models import Readiness


# --- how a holder is worded, everywhere it appears ----------------------------


def test_a_cli_holder_is_spelled_out_not_shown_as_a_pid():
    """`cli:3340113` means nothing to somebody who did not start it."""
    said = holders.describe(
        {
            "holder": "cli:3340113",
            "what": "campaign ocudu-mono, rates 100, DL",
            "since": "2026-09-28T12:11:24Z",
        }
    )
    assert said.startswith("CLI campaign ocudu-mono, rates 100, DL since ")
    assert "3340113" not in said
    # ETHOS's own `what` starts with "campaign", and the prefix must not repeat it.
    assert "campaign campaign" not in said


def test_a_job_holder_names_the_job():
    said = holders.describe(
        {"holder": "job:j-20260928T092156Z", "what": "job ocudu-mono, rates 100,200, DL",
         "since": "2026-09-28T09:21:56Z"}
    )
    assert "j-20260928T092156Z" in said


def test_a_standalone_action_is_named_by_what_it_is_doing():
    said = holders.describe(
        {"holder": "action:ue_attach", "what": "attaching the samsung UE",
         "since": "2026-09-28T11:40:45Z"}
    )
    assert said.startswith("attaching the samsung UE since ")


def test_nothing_held_reads_as_free_not_unknown():
    """A lock that was read and found free is a fact, not an absence of one."""
    assert holders.describe({"held": False, "holder": None}) == holders.FREE
    assert holders.describe(None) == holders.FREE


def test_the_strip_form_is_short_and_still_says_which_kind():
    assert holders.short({"holder": "cli:99"}) == "CLI campaign"
    assert holders.short({"holder": "job:j-1"}) == "job"
    assert holders.short({"holder": None}) == holders.FREE


# --- readiness is ETHOS's, rendered ------------------------------------------


def _readiness(**checks) -> Readiness:
    return Readiness.model_validate(
        {
            "ready": all(c == "pass" for c in checks.values()),
            "checks": [
                {"id": name, "status": status, "reason": f"{name} says so"}
                for name, status in checks.items()
            ],
        }
    )


def test_the_rows_keep_ethoss_order():
    """Rendered in the order ETHOS sent them, not in an order chosen here."""
    readiness = _readiness(core="pass", lock="pass", topology="pass")
    assert [row.id for row in rows(readiness)] == ["core", "lock", "topology"]


def test_an_unknown_stays_unknown():
    """Never upgraded to a pass, never downgraded to a failure."""
    row = rows(_readiness(core="unknown"))[0]
    assert row.status == "unknown"
    assert not row.passed and not row.failed


def test_only_a_failure_is_a_blocker():
    """ETHOS blocks on a failure and surfaces an unknown; the button follows."""
    ready_rows = rows(_readiness(topology="pass", core="unknown"))
    assert first_failure(ready_rows) is None

    blocked = rows(_readiness(topology="pass", lock="fail"))
    assert first_failure(blocked).id == "lock"


def test_the_lock_row_is_worded_like_every_other_holder():
    readiness = _readiness(lock="fail")
    row = rows(
        readiness,
        {"held": True, "holder": "cli:3340113", "what": "campaign ocudu-mono",
         "since": "2026-09-28T12:11:24Z"},
    )[0]
    assert row.reason == "held by CLI campaign ocudu-mono since 20:11"


def test_a_readiness_that_could_not_be_asked_is_all_unknown():
    """A panel of passes drawn from a failed request is the worst outcome here."""
    panel = unavailable("ETHOS did not answer")
    assert {row.status for row in panel} == {"unknown"}
    assert len(panel) == 7
    assert first_failure(panel) is None


def test_every_check_id_ethos_sends_has_a_label():
    from console.readiness import LABELS

    for check_id in ("topology", "lock", "node_free", "ue_reachable",
                     "iperf_server", "traffic_plan", "core"):
        assert check_id in LABELS


def test_a_check_ethos_adds_later_still_renders():
    """Under its own id, rather than being dropped for want of a label."""
    row = rows(_readiness(some_new_check="pass"))[0]
    assert row.label == "some new check"


# --- the status strip, from one call -----------------------------------------


@pytest.fixture
def fake():
    """The fake ETHOS, reached through an httpx transport."""
    from tests.fake_ethos import FakeEthos

    return FakeEthos(RECORDED)


def _client(fake) -> EthosClient:
    return EthosClient("http://fake-ethos", transport=fake.transport(), status_cache_s=0)


def test_the_strip_reads_every_part_from_the_summary(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    status = run_async(build_status(_client(fake), Capabilities()))
    labels = [item.label for item in status.items]
    assert labels == [
        "ETHOS", "Lock", "Deployed", "Job", "UE", "iperf 5201", "Core", "Freshness",
    ]
    for item in status.items:
        assert item.checked_at


def test_one_failing_part_does_not_take_the_strip_down(fake):
    """ETHOS gathers each part separately; the console renders that way too."""
    from console.capabilities import Capabilities
    from console.status import build_status

    fake.answer(
        "GET", "/status/summary", 200,
        {
            "lock": {"held": False, "error": ""},
            "deployed": {"error": "the deploy host is unreachable"},
            "latest_job": {"job_id": None},
            "ue": {"ue": "samsung", "reachable": True},
            "iperf_server": {"default_mode": "app_binary"},
            "freshness": {"results": {"last_point": "2026-09-28T12:00:00Z"}},
            "api": {"version": "0.1.0"},
        },
    )
    status = run_async(build_status(_client(fake), Capabilities()))
    by_label = {item.label: item for item in status.items}
    assert by_label["Deployed"].state == "unknown"
    assert "unreachable" in by_label["Deployed"].detail
    assert by_label["Lock"].value == holders.FREE


def test_a_cli_holder_reaches_the_strip_in_the_usual_wording(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    fake.answer(
        "GET", "/status/summary", 200,
        {
            "lock": {
                "held": True, "holder": "cli:3340113",
                "what": "campaign ocudu-mono, rates 100, DL",
                "since": "2026-09-28T12:11:24Z",
            },
            "deployed": {}, "latest_job": {}, "ue": {}, "iperf_server": {},
            "freshness": {}, "api": {},
        },
    )
    status = run_async(build_status(_client(fake), Capabilities()))
    lock = next(item for item in status.items if item.label == "Lock")
    assert lock.value == "CLI campaign"
    assert lock.detail.startswith("CLI campaign ocudu-mono, rates 100, DL since ")


def test_the_strip_claims_nothing_while_ethos_is_down(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    fake.go_down()
    status = run_async(build_status(_client(fake), Capabilities()))
    assert status.ethos_up is False
    assert {item.state for item in status.items[1:]} == {"unknown"}


# --- RUN: preview, then confirm with the token (design 7.2) -------------------


PLAN_FORM = {
    "gnb_stack": "OCUDU", "split_kind": "monolithic", "l1_backend": "software-PHY",
    "ru": "Pegatron", "ue": "Samsung", "core": "Open5GS", "server": "joule",
    "direction": "DL", "rates": "100,200", "duration": "10s", "repeats": "1",
    "iperf_server": "app_binary", "label": "",
}


def test_run_asks_for_a_preview_and_shows_ethoss_own_words(client, ethos_url):
    """The dialog is ETHOS's preview, line for line, not a summary composed here."""
    body = client.post("/plan/run", data=PLAN_FORM).text
    recorded = ethos_url._load("job_preview")
    assert "<sl-dialog" in body
    for line in recorded["summary"]:
        assert line in body
    assert recorded["preview_token"] in body


def test_run_alone_starts_nothing(client, ethos_url):
    """Asking for a preview must not be the thing that acts."""
    client.post("/plan/run", data=PLAN_FORM)
    assert ("POST", "/jobs") not in ethos_url.calls
    assert ethos_url.started_plans == []


def test_confirming_sends_the_token_and_goes_to_the_job(client, ethos_url):
    preview = client.post("/plan/run", data=PLAN_FORM)
    token = ethos_url._load("job_preview")["preview_token"]
    response = client.post("/plan/start", data={**PLAN_FORM, "preview_token": token})
    assert response.status_code == 204
    assert response.headers["HX-Redirect"].startswith("/jobs/")
    started = ethos_url.started_plans[-1]
    assert started["confirm"] is True
    assert started["preview_token"] == token


def test_the_plans_iperf_mode_reaches_ethos(client, ethos_url):
    """B7: the choice on the form is the one the job runs with."""
    token = ethos_url._load("job_preview")["preview_token"]
    client.post(
        "/plan/start",
        data={**PLAN_FORM, "iperf_server": "ethos", "preview_token": token},
    )
    assert ethos_url.started_plans[-1]["iperf_server"] == "ethos"


def test_confirming_without_a_token_refuses_rather_than_starting(client, ethos_url):
    response = client.post("/plan/start", data=PLAN_FORM)
    assert response.status_code == 422
    assert ethos_url.started_plans == []


def test_a_409_names_the_holder_and_does_not_start(client, ethos_url):
    """Somebody took the testbed between the preview and the confirmation."""
    ethos_url.hold_lock("cli:3340113", "campaign ocudu-mono, rates 100, DL")
    token = ethos_url._load("job_preview")["preview_token"]
    response = client.post("/plan/start", data={**PLAN_FORM, "preview_token": token})
    assert response.status_code == 409
    assert "CLI campaign" in response.headers["X-Console-Toast"]
    assert response.headers["X-Console-Toast-Variant"] == "warning"
    assert ethos_url.started_plans == []


def test_a_412_says_the_state_changed_and_re_runs_readiness(client, ethos_url):
    ethos_url.answer(
        "POST", "/jobs", 412,
        {"detail": "the testbed changed since the preview was computed"},
    )
    token = ethos_url._load("job_preview")["preview_token"]
    response = client.post("/plan/start", data={**PLAN_FORM, "preview_token": token})
    assert response.status_code == 412
    assert "changed since the preview" in response.headers["X-Console-Toast"]
    # The panel in the same response has been re-judged.
    assert "Readiness" in response.text


def test_run_is_disabled_while_a_readiness_check_failed(client, ethos_url):
    ethos_url.answer(
        "POST", "/readiness", 200,
        {
            "ready": False,
            "first_blocker": "lock: testbed busy",
            "checks": [
                {"id": "lock", "status": "fail", "reason": "testbed busy"},
                {"id": "topology", "status": "pass", "reason": "fine"},
            ],
        },
    )
    body = client.post("/plan/resolve", data=PLAN_FORM).text
    assert "disabled" in body
    assert "Testbed lock" in body


def test_run_stays_enabled_when_a_check_is_merely_unknown(client, ethos_url):
    """ETHOS surfaces an unknown without blocking, and so does the button."""
    ethos_url.answer(
        "POST", "/readiness", 200,
        {
            "ready": True,
            "first_blocker": "",
            "checks": [
                {"id": "topology", "status": "pass", "reason": "fine"},
                {"id": "core", "status": "unknown", "reason": "no TCP answer"},
            ],
        },
    )
    body = client.post("/plan/resolve", data=PLAN_FORM).text
    assert "hx-post=\"/plan/run\"" in body
    assert "could not be made" in body


def test_the_readiness_panel_renders_ethoss_checks_in_its_order(client, ethos_url):
    """ETHOS's order, not one chosen here.

    Matched on the labels rather than the reasons: a reason carries quotes and an
    ampersand or two, which Jinja escapes, and this test is about order.
    """
    from console.readiness import label_for

    body = client.post("/plan/resolve", data=PLAN_FORM).text
    recorded = ethos_url._load("readiness")
    positions = [body.index(label_for(check["id"])) for check in recorded["checks"]]
    assert positions == sorted(positions)
    assert len(positions) == 7


# --- the jobs list and one job ------------------------------------------------


def test_the_jobs_page_lists_what_ethos_reports(client, ethos_url):
    body = client.get("/jobs").text
    for job in (ethos_url._load("jobs") or {}).get("jobs", [])[:3]:
        assert job["job_id"] in body


def test_the_jobs_page_names_a_cli_holder(client, ethos_url):
    ethos_url.hold_lock("cli:3340113", "campaign ocudu-mono, rates 100, DL")
    body = client.get("/jobs").text
    assert "CLI campaign ocudu-mono, rates 100, DL" in body


def test_a_job_page_shows_its_snapshot_and_opens_the_relay(client, ethos_url):
    job_id = (ethos_url._load("jobs") or {})["jobs"][0]["job_id"]
    body = client.get(f"/jobs/{job_id}").text
    assert f'sse-connect="/jobs/{job_id}/stream"' in body
    assert "Steps" in body and "Points" in body


def test_a_job_that_does_not_exist_is_a_404(client):
    assert client.get("/jobs/j-nope").status_code == 404


def test_stopping_goes_through_a_confirmation(client, ethos_url):
    """A stop is a state change like any other (GL-07)."""
    job_id = "j-running"
    ethos_url.add_job(job_id, state="running", stop_requested=False, ended="")
    body = client.post(f"/jobs/{job_id}/stop/preview").text
    assert "<sl-dialog" in body
    assert "aborted" in body
    assert ("POST", f"/jobs/{job_id}/stop") not in ethos_url.calls


def test_stopping_asks_ethos_and_says_what_will_happen(client, ethos_url):
    job_id = "j-running2"
    ethos_url.add_job(job_id, state="running", stop_requested=False, ended="")
    response = client.post(f"/jobs/{job_id}/stop")
    assert response.status_code == 204
    assert "current point finishes" in response.headers["X-Console-Toast"]
    assert ethos_url.jobs[job_id]["stop_requested"] is True


# --- the SSE relay ------------------------------------------------------------


def test_the_relay_passes_ethoss_events_through(client, ethos_url):
    job_id = "j-stream"
    ethos_url.add_job(job_id, state="running", ended="")
    ethos_url.emit(job_id, "log", line="deploy   : ...")
    ethos_url.emit(job_id, "state", state="deploying")

    with client.stream("GET", f"/jobs/{job_id}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b"".join(response.iter_bytes()).decode()
    assert "id: 1" in body and "id: 2" in body
    assert "deploy   : ..." in body


def test_the_relay_forwards_last_event_id_so_a_resume_has_no_gap(client, ethos_url):
    """The whole of the resume mechanism is that one header."""
    job_id = "j-resume"
    ethos_url.add_job(job_id, state="running", ended="")
    for index in range(4):
        ethos_url.emit(job_id, "log", line=f"line {index}")

    with client.stream(
        "GET", f"/jobs/{job_id}/stream", headers={"Last-Event-ID": "2"}
    ) as response:
        body = b"".join(response.iter_bytes()).decode()

    assert ethos_url.resumed_from == "2"
    assert "id: 1" not in body and "id: 2" not in body
    assert "id: 3" in body and "id: 4" in body


def test_a_broken_stream_is_reported_in_the_stream(client, ethos_url):
    """A stream that has started cannot become a toast, so it says so in band."""
    ethos_url.answer("GET", "/jobs/j-gone/events", 404, {"detail": "no such job"})
    with client.stream("GET", "/jobs/j-gone/stream") as response:
        body = b"".join(response.iter_bytes()).decode()
    assert "relay_error" in body


# --- the stream ends when the job does ---------------------------------------


def test_the_job_page_closes_its_stream_on_finished(client, ethos_url):
    """The subscription ends when the job does, not when the page is closed.

    ETHOS ends the stream once a job is terminal. That is a normal close and
    not a dropped connection, but a browser cannot tell them apart: without
    this it reconnects, gets an empty replay, is closed again, and toasts "the
    event stream dropped" on every attempt for as long as the page is open.
    """
    job_id = (ethos_url._load("jobs") or {})["jobs"][0]["job_id"]
    body = client.get(f"/jobs/{job_id}").text
    assert 'sse-close="finished"' in body


def test_the_close_event_is_the_one_ethos_actually_ends_with(client, ethos_url):
    """The attribute names an event, so it has to be the event ETHOS sends.

    `finished` is emitted by `JobRunner._end` for completed, failed and aborted
    and by `reconcile` for interrupted, and it is the last event in every case.
    The page already keys its snapshot refresh off the same one.
    """
    job_id = "j-terminal"
    ethos_url.add_job(job_id, state="completed", ended="2026-09-29T09:10:00Z")
    ethos_url.emit(job_id, "log", line="deploy   : ok")
    ethos_url.emit(job_id, "finished", state="completed", outcome="done")

    with client.stream("GET", f"/jobs/{job_id}/stream") as response:
        body = b"".join(response.iter_bytes()).decode()

    assert "event: finished" in body
    assert body.rstrip().endswith("}"), "finished is the last thing on the wire"
    assert body.index("event: log") < body.index("event: finished")

    page = client.get(f"/jobs/{job_id}").text
    assert 'sse-close="finished"' in page


def test_the_stream_is_not_closed_on_any_other_event(client, ethos_url):
    """A drop that is NOT the job finishing must still reconnect.

    The attribute closes on one event name. Everything else -- state, log,
    point_started, stop_requested, relay_error -- leaves the subscription
    alone, which is what keeps a running job live.
    """
    job_id = (ethos_url._load("jobs") or {})["jobs"][0]["job_id"]
    body = client.get(f"/jobs/{job_id}").text
    assert body.count("sse-close=") == 1
    for event in ("state", "log", "point_started", "stop_requested", "relay_error"):
        assert f'sse-close="{event}"' not in body


# --- the UE panel (B11) -------------------------------------------------------


def test_the_testbed_page_lists_every_ue_with_its_state(client, ethos_url):
    body = client.get("/testbed").text
    for entry in (ethos_url._load("ue") or {}).get("ues", []):
        assert entry["ue"] in body


def test_a_ue_ethos_does_not_drive_is_listed_with_its_reason(client, ethos_url):
    recorded = (ethos_url._load("ue") or {}).get("ues", [])
    undriven = [e for e in recorded if not e.get("driven")]
    if not undriven:
        pytest.skip("the recording has no undriven UE")
    body = client.get("/testbed").text
    assert "not driven" in body
    assert undriven[0]["reason"][:40] in body


def test_a_ue_action_previews_before_it_acts(client, ethos_url):
    body = client.post("/testbed/ue/samsung/attach/preview").text
    assert "<sl-dialog" in body
    assert "10.45.x address" in body
    assert "fake-ue-token" in body
    assert ("POST", "/ue/samsung/attach") not in ethos_url.calls


def test_a_ue_action_without_a_token_refuses(client, ethos_url):
    response = client.post("/testbed/ue/samsung/attach")
    assert response.status_code == 422
    assert ("POST", "/ue/samsung/attach") not in ethos_url.calls


def test_a_ue_action_sends_the_token_and_reports_what_happened(client, ethos_url):
    response = client.post(
        "/testbed/ue/samsung/attach", data={"preview_token": "fake-ue-token"}
    )
    assert response.status_code == 204
    assert ("POST", "/ue/samsung/attach") in ethos_url.calls
    assert "Attach done on samsung" in response.headers["X-Console-Toast"]


def test_a_ue_action_is_refused_while_the_testbed_is_held(client, ethos_url):
    ethos_url.hold_lock("cli:3340113", "campaign ocudu-mono, rates 100, DL")
    response = client.post(
        "/testbed/ue/samsung/detach", data={"preview_token": "fake-ue-token"}
    )
    assert response.status_code == 409
    assert "CLI campaign" in response.headers["X-Console-Toast"]


def test_an_unknown_ue_action_is_not_routed(client):
    assert client.post("/testbed/ue/samsung/reboot/preview").status_code == 404


def test_the_testbed_page_warns_when_a_cli_campaign_holds_the_testbed(client, ethos_url):
    ethos_url.hold_lock("cli:3340113", "campaign ocudu-mono, rates 100, DL")
    body = client.get("/testbed").text
    assert "CLI campaign ocudu-mono, rates 100, DL" in body
    assert "refused" in body


def test_the_plan_page_draws_each_panel_once(client):
    """The out-of-band fragments are inert in a full document.

    Emitting them on a first load as well as in their own place drew the readiness
    panel, the vendor groups and RUN twice.
    """
    body = client.get("/plan").text
    assert body.count('id="readiness-panel"') == 1
    assert body.count('id="run-button"') == 1
    assert body.count("Testbed lock<") <= 1


def test_a_swap_still_carries_the_out_of_band_panels(client):
    body = client.post("/plan/resolve", data=PLAN_FORM).text
    assert 'hx-swap-oob="true" id="readiness-panel"' in body
    assert 'id="run-button" hx-swap-oob="true"' in body


def test_an_endpoint_that_reaches_the_testbed_is_probed_with_the_slow_timeout():
    """`GET /ue` reads two handsets over adb through the lab's control host.

    Probed at the ordinary read timeout it would time out and be reported
    unreachable, which disables the controls that depend on it while it works.
    """
    from console.capabilities import BY_KEY

    for key in ("ue", "status_summary", "readiness"):
        assert BY_KEY[key].slow, key
    assert not BY_KEY["lock"].slow


def test_the_probe_runs_once_before_the_first_request_is_served(client):
    """Otherwise a page renders against an unprobed snapshot and RUN starts
    disabled, then enables itself a moment later under the operator's cursor."""
    probe = client.app.state.probe
    assert probe.result.checked_at is not None
    assert probe.result.ready("jobs")


def test_the_job_page_carries_no_inline_script(client, ethos_url):
    """The console serves script-src 'self', so an inline script never runs.

    The live log rendered ETHOS's raw JSON until its renderer moved into
    static/js/console.js, and nothing said why: a blocked inline script is a
    console message in the browser and silence on the server.
    """
    import re

    job_id = (ethos_url._load("jobs") or {})["jobs"][0]["job_id"]
    body = client.get(f"/jobs/{job_id}").text
    # Sourced scripts are fine; a script with a body is what the CSP blocks.
    inline = [
        tag for tag in re.findall(r"<script\b[^>]*>(.*?)</script>", body, re.S)
        if tag.strip()
    ]
    assert inline == []


def test_the_log_subscribes_to_the_log_events(client, ethos_url):
    """`sse-swap` is what subscribes an element; without it no event arrives."""
    job_id = (ethos_url._load("jobs") or {})["jobs"][0]["job_id"]
    body = client.get(f"/jobs/{job_id}").text
    assert 'id="job-log" sse-swap="log"' in body


def test_the_log_renderer_lives_in_the_served_script():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "console/static/js/console.js").read_text()
    assert "htmx:sseBeforeMessage" in js
    assert "job-log" in js
    # The swap has to be cancelled, or the raw JSON lands in the log as well.
    assert "preventDefault" in js


def test_the_page_script_never_touches_document_body_at_load():
    """`console.js` is loaded from <head>, so `document.body` is still null.

    Reaching for it threw, which silently killed every listener registered after
    that point: the job log stopped rendering and nothing on the server said so.
    """
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "console/static/js/console.js").read_text()
    assert "document.body.addEventListener" not in js


def test_the_confirmation_lives_outside_the_form(client):
    """A dialog inside the form's swap target is removed by the next resolve.

    RUN's click was followed by a `/plan/resolve`, which replaced `#plan-result`
    and took the confirmation with it about a second after it opened.
    """
    page = client.get("/plan").text
    assert 'id="plan-dialog"' in page
    # The container is after the form closes, so a resolve cannot reach it.
    assert page.index("</form>") < page.index('id="plan-dialog"')
    assert 'hx-target="#plan-dialog"' in page


def test_the_confirm_fragment_is_only_the_dialog(client, ethos_url):
    """It swaps into #plan-dialog, so it must not carry the panels as well."""
    body = client.post("/plan/run", data=PLAN_FORM).text
    assert "<sl-dialog" in body
    assert 'hx-swap-oob="true" id="readiness-panel"' not in body


def test_no_dialog_removes_itself_on_shoelaces_own_animation():
    """`sl-after-hide` fires during Shoelace's open animation, not only on close."""
    from pathlib import Path

    templates = Path(__file__).resolve().parents[2] / "console/templates"
    for path in templates.rglob("*.html"):
        # The attribute, not the word: each dialog carries a comment saying why
        # it deliberately does not use it.
        assert "hx-on:sl-after-hide" not in path.read_text(), path.name


def test_ethoss_own_status_is_passed_on_rather_than_flattened(client, ethos_url):
    """A 503 about the UE is a considered answer, not a gateway problem.

    ETHOS returns 503 for "toggled but holds no data-plane address", which is what
    an attach with nothing deployed looks like. Reporting that as 502 would tell a
    browser's network tab something untrue.
    """
    ethos_url.answer(
        "POST", "/ue/samsung/attach", 503,
        {"detail": "the samsung UE was toggled but holds no data-plane address"},
    )
    response = client.post(
        "/testbed/ue/samsung/attach", data={"preview_token": "fake-ue-token"}
    )
    assert response.status_code == 503
    assert "no data-plane address" in response.headers["X-Console-Toast"]


def test_a_cache_window_of_zero_means_do_not_cache(monkeypatch):
    """0 is a real setting here, and was silently replaced by the default.

    A timeout of 0 is still refused: it would fail every call and leave a console
    that cannot reach anything.
    """
    from console.settings import load_settings

    monkeypatch.setenv("CONSOLE_STATUS_CACHE_S", "0")
    monkeypatch.setenv("CONSOLE_RUNS_CACHE_S", "0")
    monkeypatch.setenv("CONSOLE_ETHOS_TIMEOUT_S", "0")
    settings = load_settings()
    assert settings.status_cache_s == 0
    assert settings.runs_cache_s == 0
    assert settings.ethos_timeout_s > 0


def test_the_console_parse_is_a_hint_and_never_blocks_run(client, ethos_url):
    """ETHOS's `traffic_plan` check is the authority on whether a plan can run.

    The console suggests a 5 s minimum; ETHOS accepts shorter. A hint that
    disabled RUN would refuse plans ETHOS would have run happily.
    """
    ethos_url.answer(
        "POST", "/readiness", 200,
        {
            "ready": True,
            "first_blocker": "",
            "checks": [
                {"id": "traffic_plan", "status": "pass", "reason": "1 rate(s) DL"},
            ],
        },
    )
    body = client.post("/plan/resolve", data={**PLAN_FORM, "duration": "3s"}).text
    assert 'hx-post="/plan/run"' in body
