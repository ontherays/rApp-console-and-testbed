"""One password, a signed session cookie, a login rate limit and a CSRF token.

There is one user (Ravi), so there are no accounts and no roles. What this file
has to get right is narrow:

* the password exists only as an argon2id hash, in the git-ignored env file, and
  the plain password is never written or logged (SE-03);
* a session expires 12 hours after login and 2 hours after the last request
  (SE-04), both, because a forgotten open tab is the case that matters;
* five wrong passwords in ten minutes stops login for ten minutes (SE-05);
* every non-GET request carries a CSRF token (SE-08).

The lockout is tracked in memory. A restart clears it, which is acceptable: a
restart needs shell access on the host, and anyone with that does not need the
login page.
"""

from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from console.settings import (
    LOGIN_FAILURE_WINDOW_S,
    LOGIN_LOCKOUT_S,
    LOGIN_MAX_FAILURES,
    SESSION_ABSOLUTE_S,
    SESSION_IDLE_S,
)

SESSION_COOKIE = "console_session"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """The argon2id hash to put in ``CONSOLE_PASSWORD_HASH``."""
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time-ish check. A malformed or empty hash never verifies."""
    if not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


@dataclass
class LoginLimiter:
    """Five failures in ten minutes, then ten minutes of refusal (SE-05)."""

    max_failures: int = LOGIN_MAX_FAILURES
    window_s: float = LOGIN_FAILURE_WINDOW_S
    lockout_s: float = LOGIN_LOCKOUT_S
    now: object = time.monotonic
    _failures: list[float] = field(default_factory=list)
    _locked_until: float = 0.0

    def _clock(self) -> float:
        return float(self.now())  # type: ignore[operator]

    def locked_for_s(self) -> float:
        """Seconds until login is accepted again; 0 when it is open."""
        remaining = self._locked_until - self._clock()
        return remaining if remaining > 0 else 0.0

    @property
    def locked(self) -> bool:
        return self.locked_for_s() > 0

    def record_failure(self) -> None:
        now = self._clock()
        self._failures = [t for t in self._failures if now - t < self.window_s]
        self._failures.append(now)
        if len(self._failures) >= self.max_failures:
            self._locked_until = now + self.lockout_s
            self._failures.clear()

    def record_success(self) -> None:
        self._failures.clear()
        self._locked_until = 0.0

    def attempts_left(self) -> int:
        now = self._clock()
        recent = [t for t in self._failures if now - t < self.window_s]
        return max(0, self.max_failures - len(recent))


@dataclass(frozen=True)
class Session:
    """A logged-in session: when it began, when it was last used, its CSRF token."""

    logged_in_at: float
    last_seen: float
    csrf_token: str

    def expired(self, now: float) -> str | None:
        """The reason this session is over, or None while it is valid."""
        if now - self.logged_in_at > SESSION_ABSOLUTE_S:
            return "your session reached its 12-hour limit"
        if now - self.last_seen > SESSION_IDLE_S:
            return "your session was idle for 2 hours"
        return None

    def touched(self, now: float) -> "Session":
        return Session(
            logged_in_at=self.logged_in_at,
            last_seen=now,
            csrf_token=self.csrf_token,
        )


class SessionCodec:
    """Signs and reads the session cookie. The cookie carries no secret."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("a session secret is required to sign cookies")
        self._serializer = URLSafeTimedSerializer(secret, salt="testbed-console")

    def new_session(self, now: float) -> Session:
        return Session(
            logged_in_at=now, last_seen=now, csrf_token=secrets.token_urlsafe(32)
        )

    def dumps(self, session: Session) -> str:
        return self._serializer.dumps(
            {
                "logged_in_at": session.logged_in_at,
                "last_seen": session.last_seen,
                "csrf": session.csrf_token,
            }
        )

    def loads(self, raw: str) -> Session | None:
        try:
            data = self._serializer.loads(raw, max_age=SESSION_ABSOLUTE_S)
        except (BadSignature, SignatureExpired):
            return None
        try:
            return Session(
                logged_in_at=float(data["logged_in_at"]),
                last_seen=float(data["last_seen"]),
                csrf_token=str(data["csrf"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def csrf_ok(expected: str, presented: str | None) -> bool:
    if not expected or not presented:
        return False
    return hmac.compare_digest(expected, presented)
