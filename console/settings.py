"""Every ``CONSOLE_*`` variable the console reads, and where each is used.

Each name is declared once, as a module-level constant, and it is that constant
that is passed to ``os.environ.get``. ``console.variables.known_env_vars()``
collects the constants by importing this module, so the documented list can
never drift from the list the code actually reads.

Nothing here reaches the testbed. The console holds no InfluxDB token, no SSH
key and no SDNC password (SE-06); the one address it knows is ETHOS's loopback
URL (SE-07).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- the server ---------------------------------------------------------------
ENV_BIND = "CONSOLE_BIND"
ENV_PORT = "CONSOLE_PORT"
ENV_TLS_CERT = "CONSOLE_TLS_CERT"
ENV_TLS_KEY = "CONSOLE_TLS_KEY"
ENV_LOG_LEVEL = "CONSOLE_LOG_LEVEL"

# --- login and sessions -------------------------------------------------------
ENV_PASSWORD_HASH = "CONSOLE_PASSWORD_HASH"
ENV_SESSION_SECRET = "CONSOLE_SESSION_SECRET"

# --- ETHOS --------------------------------------------------------------------
ENV_ETHOS_URL = "CONSOLE_ETHOS_URL"
ENV_ETHOS_TIMEOUT_S = "CONSOLE_ETHOS_TIMEOUT_S"
ENV_ETHOS_SLOW_TIMEOUT_S = "CONSOLE_ETHOS_SLOW_TIMEOUT_S"
ENV_ETHOS_ACT_TIMEOUT_S = "CONSOLE_ETHOS_ACT_TIMEOUT_S"
ENV_RUNS_CACHE_S = "CONSOLE_RUNS_CACHE_S"
ENV_STATUS_CACHE_S = "CONSOLE_STATUS_CACHE_S"

# --- read-only stand-ins for ETHOS endpoints that do not exist yet ------------
# Both are plain data files on this host. Neither holds a credential, and the
# console only ever reads them. They are removed when B4 and B9 land.
ENV_DEPLOY_PROFILES = "CONSOLE_DEPLOY_PROFILES"   # stands in for GET /catalogue (B4)
ENV_GRAPH_DIR = "CONSOLE_GRAPH_DIR"               # stands in for GET /plots (B9)
ENV_ETHOS_REPO = "CONSOLE_ETHOS_REPO"             # only to render a copy-able CLI command

# --- console's own storage ----------------------------------------------------
ENV_PLANS_DIR = "CONSOLE_PLANS_DIR"

# --- presentation -------------------------------------------------------------
ENV_GRAFANA_URL = "CONSOLE_GRAFANA_URL"
ENV_TZ = "CONSOLE_TZ"

DEFAULT_BIND = "0.0.0.0"
DEFAULT_PORT = 8443
DEFAULT_LOG_LEVEL = "info"
DEFAULT_ETHOS_URL = "http://127.0.0.1:8081"
DEFAULT_ETHOS_TIMEOUT_S = 10.0
DEFAULT_ETHOS_SLOW_TIMEOUT_S = 60.0
#: Attaching a handset toggles the radio, waits for it to settle and reads the
#: address back, which is minutes rather than seconds. A read timeout here
#: would abandon an action ETHOS is still performing.
DEFAULT_ETHOS_ACT_TIMEOUT_S = 900.0
DEFAULT_RUNS_CACHE_S = 20.0
DEFAULT_STATUS_CACHE_S = 15.0
DEFAULT_ETHOS_REPO = "/home/oai-gnb/ravi-ethos-rApp"
DEFAULT_PLANS_DIR = "~/testbed-console-data/plans"
DEFAULT_TZ = "Asia/Taipei"

# 12 hours from login, 2 hours without a request (SE-04).
SESSION_ABSOLUTE_S = 12 * 60 * 60
SESSION_IDLE_S = 2 * 60 * 60

# 5 wrong passwords in 10 minutes locks login for 10 minutes (SE-05).
LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW_S = 10 * 60
LOGIN_LOCKOUT_S = 10 * 60


def _float(name: str, default: float, *, allow_zero: bool = False) -> float:
    """A positive number, or the default.

    `allow_zero` is for the cache windows, where 0 is a real setting meaning "do
    not cache". For a timeout it is not: a zero timeout would fail every call, so
    there the default still wins and the operator is not left with a console that
    cannot reach anything.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < 0:
        return default
    if value == 0:
        return 0.0 if allow_zero else default
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if 0 < value < 65536 else default


def _text(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _path(name: str, default: str = "") -> Path | None:
    raw = _text(name, default)
    return Path(raw).expanduser() if raw else None


@dataclass(frozen=True)
class Settings:
    """The resolved configuration. Built once, at startup."""

    bind: str
    port: int
    tls_cert: Path | None
    tls_key: Path | None
    log_level: str
    password_hash: str
    session_secret: str
    ethos_url: str
    ethos_timeout_s: float
    ethos_slow_timeout_s: float
    ethos_act_timeout_s: float
    runs_cache_s: float
    status_cache_s: float
    deploy_profiles: Path | None
    graph_dir: Path | None
    ethos_repo: Path
    plans_dir: Path
    grafana_url: str
    tz: str

    @property
    def tls_ready(self) -> bool:
        return bool(
            self.tls_cert
            and self.tls_key
            and self.tls_cert.is_file()
            and self.tls_key.is_file()
        )

    @property
    def login_ready(self) -> bool:
        return bool(self.password_hash and self.session_secret)

    def problems(self) -> list[str]:
        """What would stop the console serving, in the order worth fixing."""
        found: list[str] = []
        if not self.password_hash:
            found.append(
                f"{ENV_PASSWORD_HASH} is not set, run "
                "`.venv/bin/python -m console set-password`"
            )
        if not self.session_secret:
            found.append(
                f"{ENV_SESSION_SECRET} is not set, 64 hex characters, "
                "`openssl rand -hex 32`"
            )
        if not self.tls_cert or not self.tls_key:
            found.append(
                f"{ENV_TLS_CERT} and {ENV_TLS_KEY} must both be set, "
                "run `deploy/make-cert.sh` (SE-01: HTTPS only)"
            )
        elif not self.tls_ready:
            missing = [
                str(p)
                for p in (self.tls_cert, self.tls_key)
                if p and not p.is_file()
            ]
            found.append("TLS file not found: " + ", ".join(missing))
        return found


def load_settings() -> Settings:
    return Settings(
        bind=_text(ENV_BIND, DEFAULT_BIND),
        port=_int(ENV_PORT, DEFAULT_PORT),
        tls_cert=_path(ENV_TLS_CERT),
        tls_key=_path(ENV_TLS_KEY),
        log_level=_text(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL),
        password_hash=_text(ENV_PASSWORD_HASH),
        session_secret=_text(ENV_SESSION_SECRET),
        ethos_url=_text(ENV_ETHOS_URL, DEFAULT_ETHOS_URL).rstrip("/"),
        ethos_timeout_s=_float(ENV_ETHOS_TIMEOUT_S, DEFAULT_ETHOS_TIMEOUT_S),
        ethos_act_timeout_s=_float(
            ENV_ETHOS_ACT_TIMEOUT_S, DEFAULT_ETHOS_ACT_TIMEOUT_S
        ),
        ethos_slow_timeout_s=_float(
            ENV_ETHOS_SLOW_TIMEOUT_S, DEFAULT_ETHOS_SLOW_TIMEOUT_S
        ),
        runs_cache_s=_float(ENV_RUNS_CACHE_S, DEFAULT_RUNS_CACHE_S, allow_zero=True),
        status_cache_s=_float(
            ENV_STATUS_CACHE_S, DEFAULT_STATUS_CACHE_S, allow_zero=True
        ),
        deploy_profiles=_path(ENV_DEPLOY_PROFILES),
        graph_dir=_path(ENV_GRAPH_DIR),
        ethos_repo=Path(_text(ENV_ETHOS_REPO, DEFAULT_ETHOS_REPO)).expanduser(),
        plans_dir=Path(_text(ENV_PLANS_DIR, DEFAULT_PLANS_DIR)).expanduser(),
        grafana_url=_text(ENV_GRAFANA_URL),
        tz=_text(ENV_TZ, DEFAULT_TZ),
    )
