"""The Jinja environment: filters, globals, and the render helper every page uses."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from console.nav import GROUPS, Badges, backend_readiness
from console.rapps.ethos import series as series_mod
from console.rapps.ethos.metrics import NOT_MEASURED

SEEN_COOKIE = "console_seen"

_TEMPLATES: Jinja2Templates | None = None


def _parse_utc(value: str) -> datetime | None:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def localtime(value: Any, tz: str = "Asia/Taipei", fmt: str = "%Y-%m-%d %H:%M") -> str:
    """UTC in, the display zone out (GL-06). Everything stored stays UTC."""
    if not value:
        return NOT_MEASURED
    parsed = _parse_utc(str(value))
    if parsed is None:
        return str(value)
    try:
        zone = ZoneInfo(tz)
    except Exception:
        zone = ZoneInfo("UTC")
    return parsed.astimezone(zone).strftime(fmt)


def clocktime(value: Any, tz: str = "Asia/Taipei") -> str:
    return localtime(value, tz, "%H:%M")


def isoutc(value: Any) -> str:
    """The same instant as a full ISO-8601 UTC string, for a tooltip.

    Every time on every page is shown in the display zone (GL-06); this is
    the unambiguous original behind it, so nobody has to guess what a bare
    "16:27" was in UTC when reading a log beside it.
    """
    if not value:
        return ""
    parsed = _parse_utc(str(value))
    if parsed is None:
        return str(value)
    return parsed.astimezone(ZoneInfo("UTC")).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def filesize(num: Any) -> str:
    """Bytes as a person reads them. Presentation only: the value is ETHOS's.

    Matches what `python -m publication prune` prints for the same number, so
    the page and the command line do not describe one archive two ways.
    """
    if num is None:
        return NOT_MEASURED
    try:
        value = float(num)
    except (TypeError, ValueError):
        return NOT_MEASURED
    for unit in ("B", "kB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"       # pragma: no cover - the loop returns first


def duration(seconds: Any) -> str:
    if seconds is None:
        return NOT_MEASURED
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return NOT_MEASURED
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def templates() -> Jinja2Templates:
    global _TEMPLATES
    if _TEMPLATES is None:
        import pathlib

        here = pathlib.Path(__file__).parent / "templates"
        env = Jinja2Templates(directory=str(here))
        env.env.filters["localtime"] = localtime
        env.env.filters["clocktime"] = clocktime
        env.env.filters["isoutc"] = isoutc
        env.env.filters["duration"] = duration
        env.env.filters["filesize"] = filesize
        env.env.globals["series_for"] = series_mod.series_for
        env.env.globals["NOT_MEASURED"] = NOT_MEASURED
        _TEMPLATES = env
    return _TEMPLATES


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render with the context every template expects: the CSRF token, the
    capability snapshot, the navigation and its badges, and the display zone."""
    state = request.app.state
    caps = state.probe.result
    badges = getattr(request.state, "badges", None) or Badges()
    full: dict[str, Any] = {
        "request": request,
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "caps": caps,
        "settings": state.settings,
        "tz": state.settings.tz,
        "nav_groups": GROUPS,
        "badges": badges,
        "backend": backend_readiness(caps),
        "search_q": request.query_params.get("q", ""),
    }
    full.update(context or {})
    if status_code >= 400 and request.headers.get("hx-request"):
        # A refusal that was rendered rather than raised is meant to land in the
        # panel that asked for it. htmx does not swap a 4xx by default, so the
        # response says it carries a partial and console.js opts that one in.
        # Without this a 422 shows a generic toast and the accurate explanation
        # ETHOS wrote is thrown away.
        headers = {**(headers or {}), "X-Console-Inline": "1"}
    return templates().TemplateResponse(
        request, template, full, status_code=status_code, headers=headers
    )
