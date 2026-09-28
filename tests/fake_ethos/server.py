"""The fake ETHOS as a real process, for the browser tests.

The unit tests reach the fake through an httpx transport, which is enough when
the console is exercised in-process. A browser needs the console to be a running
server, and that console opens real sockets to ETHOS, so the same replay logic
is wrapped in an ASGI app here and served.

One implementation, two ways of reaching it: a fixture that drifts from what the
unit tests see would be worse than no fixture at all.

Because it is a separate process, a browser test cannot reach into it the way a
unit test does. So it seeds a running job with a few events at startup, and
exposes a small control surface under ``/__control/`` for the states a browser
test has to set up: the lock being held, and clearing it again. That path is not
an ETHOS endpoint and nothing in the console knows about it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from tests.fake_ethos import FakeEthos

RECORDED = Path(__file__).resolve().parent.parent / "recorded"


#: The job a browser test watches. Seeded rather than created through the API so
#: the page has a log to render the moment it opens.
SEEDED_JOB = "j-seeded"

SEEDED_LOG = (
    "topology : ocudu-mono",
    "deploy   : ok",
    "attach   : ok",
    "  DL    100M     99.99 Mbit/s  loss 0.0%",
)


def create_app(recorded: Path = RECORDED) -> Starlette:
    fake = FakeEthos(recorded)

    fake.add_job(SEEDED_JOB, state="running", stop_requested=False, ended="",
                 outcome="", error="")
    for line in SEEDED_LOG:
        fake.emit(SEEDED_JOB, "log", line=line)

    async def control(request: Request) -> Response:
        """Set up a state a browser test needs. Not an ETHOS endpoint."""
        what = request.path_params["what"]
        body = await request.json() if await request.body() else {}
        if what == "lock":
            if body.get("holder"):
                fake.hold_lock(
                    body["holder"], body.get("what", ""),
                    body.get("since", "2026-09-28T09:32:58Z"),
                )
            else:
                fake.locked_by = None
                fake.answers.pop("GET /lock", None)
                fake.answers.pop("GET /status/summary", None)
            return Response(status_code=204)
        if what == "reset":
            fake.answers.clear()
            fake.locked_by = None
            fake.refuse_with = None
            fake.down = False
            return Response(status_code=204)
        return Response("unknown control", status_code=404)

    async def handle(request: Request) -> Response:
        body = await request.body()
        outgoing = httpx.Request(
            request.method,
            httpx.URL(str(request.url)),
            content=body or None,
            headers=dict(request.headers),
        )
        try:
            answer = fake.handle(outgoing)
        except httpx.ConnectError:
            return Response("fake ethos is down", status_code=502)
        return Response(
            content=answer.content,
            status_code=answer.status_code,
            media_type=answer.headers.get("content-type", "application/json"),
        )

    return Starlette(
        routes=[
            Route("/__control/{what}", control, methods=["POST"]),
            Route("/{path:path}", handle, methods=["GET", "POST", "PUT", "DELETE"]),
        ]
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
