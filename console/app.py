"""The FastAPI application: configuration, security, and the page routers.

Middleware order matters and is asserted by a test:

    SecurityHeaders  → outermost, so even an error response carries them
    Session          → reads the cookie, refreshes it, enforces login and CSRF

There is no CORS middleware and there must never be one. The browser only ever
talks to the console; the console talks to ETHOS server-side, over loopback.
"""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse, Response

from console.auth import (
    CSRF_HEADER,
    SESSION_COOKIE,
    LoginLimiter,
    SessionCodec,
    csrf_ok,
)
from console.capabilities import CapabilityProbe
from console.env_file import load_env_file
from console.rapps.ethos.client import EthosClient
from console.settings import Settings, load_settings

log = logging.getLogger("console")

# Paths served before a session exists. Everything else requires one (SE-02).
PUBLIC_PATHS = ("/login", "/static", "/healthz")

SECURITY_HEADERS = {
    # Every asset is vendored, so the policy can be this tight (SE-09).
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        # data: is needed in connect-src as well as img-src: Shoelace's own
        # components fetch their internal icons as data: URIs through the Fetch
        # API, and without it every page logs a CSP violation and the icons
        # silently never render. It allows inline data, not another host.
        "font-src 'self' data:; connect-src 'self' data:; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class SessionMiddleware(BaseHTTPMiddleware):
    """Login, session expiry and CSRF, in one place.

    A session is refused rather than extended when it is past either limit, and
    the reason is carried to the login page — "your session was idle for 2 hours"
    is a different fact from "wrong password", and conflating them wastes time.
    """

    def __init__(self, app, codec: SessionCodec) -> None:
        super().__init__(app)
        self._codec = codec

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        request.state.csrf_token = ""
        request.state.logged_in = False

        if any(path == p or path.startswith(p + "/") for p in PUBLIC_PATHS):
            return await call_next(request)

        raw = request.cookies.get(SESSION_COOKIE)
        session = self._codec.loads(raw) if raw else None
        now = time.time()
        expired = session.expired(now) if session else None

        if session is None or expired:
            reason = expired or "please log in"
            if request.headers.get("HX-Request"):
                # htmx follows a 401 by sending the browser to the login page;
                # a redirect here would swap the login form into a panel.
                return JSONResponse(
                    {"error": "login_required", "message": reason}, status_code=401
                )
            target = f"/login?reason={reason.replace(' ', '+')}"
            if path not in ("/", "/logout"):
                target += f"&next={path}"
            response = RedirectResponse(target, status_code=303)
            response.delete_cookie(SESSION_COOKIE)
            return response

        if request.method not in ("GET", "HEAD", "OPTIONS"):
            presented = request.headers.get(CSRF_HEADER)
            if presented is None:
                form = await request.form()
                presented = form.get("csrf_token")  # type: ignore[assignment]
            if not csrf_ok(session.csrf_token, presented):
                log.warning("csrf rejected for %s %s", request.method, path)
                return JSONResponse(
                    {
                        "error": "csrf_failed",
                        "message": "This page's security token was missing or "
                        "stale. Reload the page and try again.",
                    },
                    status_code=403,
                )

        request.state.csrf_token = session.csrf_token
        request.state.logged_in = True
        request.state.badges = await _badges(request)
        response = await call_next(request)
        set_session_cookie(response, self._codec, session.touched(now))
        _remember_seen(request, response)
        return response


SEEN_COOKIE = "console_seen"


async def _badges(request: Request):
    """The sidebar counts, from what the console can actually count.

    "New runs since your last visit" is real and useful today. A running-job
    count is not: ETHOS has no job model, and a badge showing 0 would read as
    "nothing is running" on a console that cannot tell. It stays absent.
    """
    from console.nav import Badges
    from console.rapps.ethos.client import EthosError

    badges = Badges()
    if request.headers.get("HX-Request"):
        return badges  # a partial does not redraw the sidebar
    seen = request.cookies.get(SEEN_COOKIE, "")
    try:
        listing = await request.app.state.client.runs()
    except EthosError:
        return badges

    newest = max((r.t_created or "" for r in listing.runs), default="")
    request.state.newest_run = newest
    if seen and newest:
        badges.new_runs = sum(1 for r in listing.runs if (r.t_created or "") > seen) or None
    return badges


def _remember_seen(request: Request, response: Response) -> None:
    """Record the newest run this browser has been shown, so the next visit can
    say what arrived meanwhile. It is a display aid, not state: losing the
    cookie costs a badge, nothing else."""
    newest = getattr(request.state, "newest_run", "")
    if not newest or request.headers.get("HX-Request"):
        return
    if request.url.path in ("/", "/results") and request.method == "GET":
        response.set_cookie(
            SEEN_COOKIE, newest, httponly=True, secure=True, samesite="strict",
            path="/", max_age=90 * 24 * 3600,
        )


def set_session_cookie(response: Response, codec: SessionCodec, session) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        codec.dumps(session),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    load_env_file()
    resolved = settings or load_settings()

    # A session secret is required to sign cookies. Generating one instead of
    # refusing would silently log everyone out on each restart, so this only
    # happens where there is no configuration at all (the test suite).
    secret = resolved.session_secret or secrets.token_hex(32)
    codec = SessionCodec(secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.probe.start()
        yield
        await app.state.probe.stop()
        await app.state.client.aclose()

    app = FastAPI(
        title="Testbed Console",
        docs_url=None,        # the console is not an API; ETHOS has the Swagger
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    client = EthosClient(
        resolved.ethos_url,
        timeout_s=resolved.ethos_timeout_s,
        slow_timeout_s=resolved.ethos_slow_timeout_s,
        runs_cache_s=resolved.runs_cache_s,
        status_cache_s=resolved.status_cache_s,
    )
    app.state.settings = resolved
    app.state.client = client
    app.state.codec = codec
    app.state.probe = CapabilityProbe(client)
    app.state.limiter = LoginLimiter()

    app.add_middleware(SessionMiddleware, codec=codec)
    app.add_middleware(SecurityHeadersMiddleware)

    import pathlib

    app.mount(
        "/static",
        StaticFiles(directory=str(pathlib.Path(__file__).parent / "static")),
        name="static",
    )

    from console.pages import docs as docs_pages
    from console.pages import graphs, jobs, later, login, overview, plan, results, search

    for module in (login, overview, plan, jobs, results, graphs, search, later, docs_pages):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, object]:
        """The console's own liveness. It does not probe ETHOS: a console that is
        up must not report itself down because the thing it displays is down."""
        return {
            "status": "ok",
            "service": "testbed-console",
            "ethos_url": resolved.ethos_url,
        }

    return app
