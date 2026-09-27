"""Login and logout. One password, and a rate limit that names the wait."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Form, Request
from starlette.responses import RedirectResponse

from console.app import set_session_cookie
from console.auth import SESSION_COOKIE, verify_password
from console.templating import render

log = logging.getLogger("console")
router = APIRouter()


@router.get("/login")
async def login_form(request: Request, reason: str = "", next: str = "/"):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    return render(
        request,
        "login.html",
        {
            "reason": reason,
            "next": next or "/",
            "locked_s": int(limiter.locked_for_s()),
            "configured": bool(settings.password_hash),
            "hide_shell": True,
        },
    )


@router.post("/login")
async def login_submit(
    request: Request,
    password: str = Form(default=""),
    next: str = Form(default="/"),
):
    settings = request.app.state.settings
    limiter = request.app.state.limiter
    codec = request.app.state.codec
    client_host = request.client.host if request.client else "unknown"

    if limiter.locked:
        wait = int(limiter.locked_for_s())
        log.warning("login refused for %s: locked for %ss", client_host, wait)
        return render(
            request,
            "login.html",
            {
                "error": f"Too many failed attempts. Login is refused for "
                f"another {wait // 60 + 1} minute(s).",
                "next": next,
                "locked_s": wait,
                "configured": bool(settings.password_hash),
                "hide_shell": True,
            },
            status_code=429,
        )

    if not settings.password_hash:
        return render(
            request,
            "login.html",
            {
                "error": "No password is configured. Run "
                "`.venv/bin/python -m console set-password` on the console host.",
                "next": next,
                "configured": False,
                "hide_shell": True,
            },
            status_code=503,
        )

    # The password itself is never logged, and never echoed back to the form.
    if not verify_password(password, settings.password_hash):
        limiter.record_failure()
        left = limiter.attempts_left()
        log.warning("failed login from %s, %s attempt(s) left", client_host, left)
        message = "That password is not correct."
        if limiter.locked:
            message = (
                "That password is not correct. Login is now refused for 10 minutes."
            )
        elif left <= 2:
            message += f" {left} attempt(s) left before a 10-minute lockout."
        return render(
            request,
            "login.html",
            {
                "error": message,
                "next": next,
                # If this attempt was the one that locked login, the field is
                # disabled on this very response — saying "refused for 10
                # minutes" over an enabled field invites a sixth attempt.
                "locked_s": int(limiter.locked_for_s()),
                "configured": True,
                "hide_shell": True,
            },
            status_code=401,
        )

    limiter.record_success()
    log.info("login from %s", client_host)
    target = next if next.startswith("/") else "/"
    response = RedirectResponse(target, status_code=303)
    set_session_cookie(response, codec, codec.new_session(time.time()))
    return response


@router.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login?reason=you+logged+out", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
