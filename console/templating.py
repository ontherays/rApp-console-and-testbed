"""The Jinja environment: filters, globals, and the render helper every page uses."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from console.rapps.ethos import series as series_mod
from console.rapps.ethos.metrics import DASH

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
        return DASH
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


def duration(seconds: Any) -> str:
    if seconds is None:
        return DASH
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return DASH
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
        env.env.filters["duration"] = duration
        env.env.globals["series_for"] = series_mod.series_for
        env.env.globals["DASH"] = DASH
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
    capability snapshot, and the display time zone."""
    state = request.app.state
    full: dict[str, Any] = {
        "request": request,
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "caps": state.probe.result,
        "settings": state.settings,
        "tz": state.settings.tz,
    }
    full.update(context or {})
    return templates().TemplateResponse(
        request, template, full, status_code=status_code, headers=headers
    )
