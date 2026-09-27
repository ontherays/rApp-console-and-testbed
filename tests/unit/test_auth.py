"""Password hashing, session expiry, the login rate limit, and CSRF."""

from __future__ import annotations

from console.auth import (
    LoginLimiter,
    Session,
    SessionCodec,
    csrf_ok,
    hash_password,
    verify_password,
)
from console.settings import SESSION_ABSOLUTE_S, SESSION_IDLE_S


def test_a_password_verifies_against_its_own_hash():
    stored = hash_password("a long enough password")
    assert verify_password("a long enough password", stored)
    assert not verify_password("something else", stored)


def test_the_hash_is_argon2id_and_does_not_contain_the_password():
    stored = hash_password("hunter2hunter2")
    assert stored.startswith("$argon2id$")
    assert "hunter2" not in stored


def test_an_empty_or_malformed_hash_never_verifies():
    assert not verify_password("anything", "")
    assert not verify_password("anything", "not-a-hash")


def test_five_failures_in_the_window_lock_login_for_ten_minutes():
    now = [0.0]
    limiter = LoginLimiter(now=lambda: now[0])
    for _ in range(4):
        limiter.record_failure()
    assert not limiter.locked
    assert limiter.attempts_left() == 1
    limiter.record_failure()
    assert limiter.locked
    assert 599 <= limiter.locked_for_s() <= 600

    now[0] = 600.1
    assert not limiter.locked


def test_failures_outside_the_window_do_not_accumulate():
    now = [0.0]
    limiter = LoginLimiter(now=lambda: now[0])
    for step in range(4):
        now[0] = step * 200.0     # 0, 200, 400, 600 — the first two age out
        limiter.record_failure()
    now[0] = 600.0
    limiter.record_failure()
    assert not limiter.locked


def test_a_success_clears_the_count():
    limiter = LoginLimiter(now=lambda: 0.0)
    limiter.record_failure()
    limiter.record_failure()
    limiter.record_success()
    assert limiter.attempts_left() == 5


def test_a_session_round_trips_and_a_tampered_cookie_does_not():
    codec = SessionCodec("s" * 64)
    session = codec.new_session(1000.0)
    raw = codec.dumps(session)
    assert codec.loads(raw) == session
    assert codec.loads(raw[:-3] + "xyz") is None
    assert codec.loads("nonsense") is None


def test_a_session_expires_after_two_idle_hours_and_twelve_hours_absolute():
    codec = SessionCodec("s" * 64)
    session = codec.new_session(0.0)

    assert session.expired(60.0) is None
    assert "idle" in session.expired(SESSION_IDLE_S + 1)

    still_used = session
    for minute in range(1, 13 * 60, 30):
        still_used = still_used.touched(minute * 60.0)
    reason = still_used.expired(SESSION_ABSOLUTE_S + 1)
    assert reason is not None and "12-hour" in reason


def test_a_different_secret_cannot_read_the_cookie():
    raw = SessionCodec("a" * 64).dumps(SessionCodec("a" * 64).new_session(0.0))
    assert SessionCodec("b" * 64).loads(raw) is None


def test_csrf_needs_an_exact_match():
    assert csrf_ok("token", "token")
    assert not csrf_ok("token", "Token")
    assert not csrf_ok("token", None)
    assert not csrf_ok("", "")


def test_every_session_gets_its_own_csrf_token():
    codec = SessionCodec("s" * 64)
    first = codec.new_session(0.0)
    second = codec.new_session(0.0)
    assert first.csrf_token != second.csrf_token
    assert len(first.csrf_token) >= 32
