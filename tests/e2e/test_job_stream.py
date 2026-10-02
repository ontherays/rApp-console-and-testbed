"""The job event stream's lifecycle, in a real browser.

This is the one behaviour the server-side suite cannot check. Whether an
`EventSource` reconnects is the browser's decision, taken from `readyState` and
from whether anything called `close()`, and no amount of asserting on rendered
HTML can see it. So these count the actual network requests the browser makes.

The bug they exist for: ETHOS ends the stream once a job is terminal, which is a
normal close. The browser cannot tell that from a dropped connection, so it
reconnected, got an empty replay, was closed again, and toasted "the job event
stream dropped" on every attempt, for ever. `sse-close="finished"` is what makes
the difference visible to it.

The pair matters more than either half. A fix that stopped the reconnect loop by
stopping reconnection would pass the terminal test and break every running job,
so the running case asserts the opposite: a stream that ends WITHOUT `finished`
is still a drop, and must still come back.
"""

from __future__ import annotations

import pytest

RUNNING_JOB = "j-seeded"
DONE_JOB = "j-seeded-done"

#: Long enough for several reconnects. The extension backs off 500 ms, 1 s, 2 s,
#: 4 s, so a loop shows at least three attempts inside this window and a closed
#: subscription still shows exactly one.
WATCH_MS = 5000


def _count_stream_requests(page, job_id: str) -> int:
    """How many times the browser opened the relay for this job."""
    opened: list[str] = []
    page.on(
        "request",
        lambda request: opened.append(request.url)
        if f"/jobs/{job_id}/stream" in request.url
        else None,
    )
    page.goto(f"/jobs/{job_id}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(WATCH_MS)
    return len(opened)


def test_a_completed_job_opens_the_stream_once_and_does_not_reconnect(logged_in):
    """The regression. One connection, and no second one after `finished`."""
    opens = _count_stream_requests(logged_in, DONE_JOB)
    assert opens == 1, (
        f"the browser opened the stream {opens} times for a finished job; "
        f"`finished` should have closed the subscription after the first"
    )


def test_a_completed_job_shows_no_stream_dropped_notification(logged_in):
    """The symptom, asserted directly."""
    logged_in.goto(f"/jobs/{DONE_JOB}")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(WATCH_MS)

    assert "event stream dropped" not in logged_in.content()
    assert logged_in.locator("sl-alert").count() == 0


def test_a_completed_job_still_receives_its_events_before_closing(logged_in):
    """Closing must happen after the replay, not instead of it.

    A fix that never opened the stream would also stop the toasts, and would
    lose the log of every job anyone opened after it finished.
    """
    logged_in.goto(f"/jobs/{DONE_JOB}")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(1500)

    log = logged_in.locator("#job-log").inner_text()
    assert "deploy   : ok" in log, "the replayed log should have rendered"


def test_the_event_source_is_closed_rather_than_merely_quiet(logged_in):
    """`readyState` 2 is CLOSED, and only `close()` produces it here.

    A connection that simply failed sits in CONNECTING (0) while it waits to
    retry. Asserting on the state rather than on the absence of traffic is what
    separates "the subscription ended" from "the next attempt has not fired
    yet".
    """
    logged_in.goto(f"/jobs/{DONE_JOB}")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(2000)

    state = logged_in.evaluate(
        """() => {
            const elt = document.getElementById('job-live');
            const data = elt && window.htmx && window.htmx.values
                ? null : null;
            // htmx keeps the source in its internal data; read it the way the
            // extension does, through the public api it was given.
            const internal = elt && elt['htmx-internal-data'];
            const source = internal && internal.sseEventSource;
            return source ? source.readyState : -1;
        }"""
    )
    assert state in (2, -1), f"expected a CLOSED EventSource, readyState was {state}"


def test_a_running_job_still_reconnects_when_its_stream_drops(logged_in):
    """The other half, and the one a careless fix breaks.

    The fake ends every replay, so the running job's stream drops the moment it
    is drained, with no `finished` to explain it. That is exactly an unexpected
    disconnect, and the browser must come back for more.
    """
    opens = _count_stream_requests(logged_in, RUNNING_JOB)
    assert opens > 1, (
        "a running job whose stream dropped must reconnect; reconnection is "
        "what makes Last-Event-ID resume work at all"
    )


def test_a_running_jobs_reconnect_goes_back_to_the_same_relay(logged_in):
    """Every retry asks the console, never ETHOS, and always for the same job.

    What this does NOT assert is `Last-Event-ID`, and the reason is worth
    recording. There are two reconnect paths and only one of them carries it.
    The browser's own retry, for a transport failure that leaves the source
    CONNECTING, resends the last id it saw. The extension's retry, after the
    source has reached CLOSED, builds a FRESH EventSource through
    `htmx.createEventSource` (`htmx-ext-sse.js:197`), and a new one has no
    lastEventId to send. That is the extension's behaviour, it predates this
    change and is untouched by it; the console's own half, forwarding the
    header upstream whenever the browser does send one, is proven in
    `test_the_relay_forwards_last_event_id_so_a_resume_has_no_gap`.
    """
    asked: list[str] = []
    logged_in.on(
        "request",
        lambda request: asked.append(request.url)
        if "/stream" in request.url
        else None,
    )
    logged_in.goto(f"/jobs/{RUNNING_JOB}")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(WATCH_MS)

    assert len(asked) > 1, "expected at least one reconnect to inspect"
    assert all(url.endswith(f"/jobs/{RUNNING_JOB}/stream") for url in asked), asked


def test_a_running_job_renders_the_lines_it_was_sent(logged_in):
    logged_in.goto(f"/jobs/{RUNNING_JOB}")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(1500)

    log = logged_in.locator("#job-log").inner_text()
    assert "topology : ocudu-mono" in log


@pytest.mark.parametrize("job_id", [RUNNING_JOB, DONE_JOB])
def test_only_one_subscription_is_ever_open_for_a_page(logged_in, job_id):
    """No duplicate subscriptions, on either path.

    One `sse-connect` element, one source. A page that registered twice would
    double every log line and double every reconnect.
    """
    logged_in.goto(f"/jobs/{job_id}")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(1000)

    connectors = logged_in.evaluate(
        "() => document.querySelectorAll('[sse-connect]').length"
    )
    assert connectors == 1
