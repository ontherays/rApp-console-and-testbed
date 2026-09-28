"""Relays ETHOS's job event stream to the browser.

**Why relay at all, rather than letting the browser open ETHOS directly.** ETHOS
listens on loopback and holds every credential (SE-06, SE-07); the browser is on
the LAN and is only ever allowed to talk to the console. So the console opens the
upstream stream and passes each event on, adding nothing to it.

**What this must not lose.** Every ETHOS event carries a dense sequence number as
its SSE `id`. The browser remembers the last one it saw and sends it back as
`Last-Event-ID` when it reconnects; ETHOS replays from there. The relay therefore
has exactly one job beyond copying bytes: pass that header upstream unchanged. A
relay that dropped it would turn every reconnect into a replay from the beginning
(duplicates) or from now (a gap), and the whole point of the sequence numbers is
that a dropped connection loses nothing (RN-07).

Bytes are passed through as they arrive rather than re-parsed and re-serialised.
Re-emitting would mean this file deciding what an event means, and then a new
ETHOS event type would need a console change before it could be seen at all.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from starlette.responses import StreamingResponse

#: The header the browser resumes with, and the only thing this relay adds.
LAST_EVENT_ID = "Last-Event-ID"

#: Told to a browser whose upstream stream ended or could not be opened. It is a
#: comment plus a named event, so htmx sees a reason rather than a silent close.
_SSE_HEADERS = {
    "cache-control": "no-cache, no-transform",
    "x-accel-buffering": "no",     # nginx must not buffer a stream
    "connection": "keep-alive",
}


def _event(name: str, payload: dict[str, object]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


async def relay(client, job_id: str, last_event_id: str | None) -> StreamingResponse:
    """Stream `GET /jobs/{job_id}/events` from ETHOS to this browser.

    *last_event_id* comes from the browser's own `Last-Event-ID` header and is
    forwarded verbatim. None means "from the beginning", which is what a first
    connection wants: a client that arrives late still gets the whole history
    before the live events.
    """

    async def body() -> AsyncIterator[bytes]:
        headers = {"accept": "text/event-stream"}
        if last_event_id:
            headers[LAST_EVENT_ID] = str(last_event_id)
        try:
            async with client.stream(
                "GET", f"/jobs/{job_id}/events", headers=headers
            ) as upstream:
                if upstream.status_code >= 400:
                    await upstream.aread()
                    yield _event(
                        "relay_error",
                        {
                            "status": upstream.status_code,
                            "message": (
                                f"ETHOS refused the event stream for {job_id} "
                                f"(HTTP {upstream.status_code})"
                            ),
                        },
                    )
                    return
                # Normally ETHOS streams and this iterates as events arrive. A
                # response that arrived whole (a transport that does not stream,
                # or a short replay that ETHOS closed at once) has nothing left to
                # iterate, and asking anyway raises. Yield what it holds instead:
                # the browser cares about the events, not about how they arrived.
                if getattr(upstream, "is_closed", False) or upstream.is_stream_consumed:
                    body_bytes = await upstream.aread()
                    if body_bytes:
                        yield body_bytes
                    return
                async for chunk in upstream.aiter_raw():
                    if chunk:
                        yield chunk
        except Exception as exc:                                   # noqa: BLE001
            # A stream that has already started cannot become a toast, so the
            # browser is told in the stream itself and htmx reconnects with the
            # last id it saw.
            yield _event(
                "relay_error",
                {"status": None, "message": f"the event stream stopped: {exc}"},
            )

    return StreamingResponse(body(), media_type="text/event-stream", headers=_SSE_HEADERS)
