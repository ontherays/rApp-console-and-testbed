"""The fake ETHOS as a real process, for the browser tests.

The unit tests reach the fake through an httpx transport, which is enough when
the console is exercised in-process. A browser needs the console to be a running
server, and that console opens real sockets to ETHOS — so the same replay logic
is wrapped in an ASGI app here and served.

One implementation, two ways of reaching it: a fixture that drifts from what the
unit tests see would be worse than no fixture at all.
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


def create_app(recorded: Path = RECORDED) -> Starlette:
    fake = FakeEthos(recorded)

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
        routes=[Route("/{path:path}", handle, methods=["GET", "POST", "PUT", "DELETE"])]
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
