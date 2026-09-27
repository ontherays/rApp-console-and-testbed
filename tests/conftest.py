"""Suite-wide setup.

``CONSOLE_ENV_FILE`` is pinned to a path that does not exist **before any console
module is imported**, so a developer's real ``console.env`` can never change what
the suite sees — a password hash or an ETHOS URL leaking in from the host would
make a green suite meaningless.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CONSOLE_ENV_FILE"] = "/nonexistent/console.env"
# A fixed secret, so a signed cookie can be built in a test.
os.environ.setdefault("CONSOLE_SESSION_SECRET", "t" * 64)

import pytest  # noqa: E402

from console.auth import SESSION_COOKIE, SessionCodec  # noqa: E402

RECORDED = Path(__file__).parent / "recorded"


@pytest.fixture
def ethos_url(monkeypatch):
    """Point the console at the fake ETHOS, not at the real one."""
    from tests.fake_ethos import FakeEthos

    fake = FakeEthos(RECORDED)
    monkeypatch.setenv("CONSOLE_ETHOS_URL", "http://fake-ethos")
    yield fake


@pytest.fixture
def session_cookie():
    codec = SessionCodec("t" * 64)
    session = codec.new_session(time.time())
    return {"cookie": codec.dumps(session), "csrf": session.csrf_token}


@pytest.fixture
def client(ethos_url, session_cookie, monkeypatch, tmp_path):
    """A logged-in TestClient whose ETHOS is the fake one."""
    from fastapi.testclient import TestClient

    from console.app import create_app

    monkeypatch.setenv("CONSOLE_PLANS_DIR", str(tmp_path / "plans"))
    monkeypatch.setenv("CONSOLE_PASSWORD_HASH", "")
    monkeypatch.setenv("CONSOLE_DEPLOY_PROFILES", str(RECORDED / "deploy_profiles.yaml"))
    monkeypatch.setenv("CONSOLE_GRAPH_DIR", str(RECORDED / "graphs"))

    app = create_app()
    app.state.client._client._transport = ethos_url.transport()
    with TestClient(app, base_url="https://console.test") as test_client:
        test_client.cookies.set(SESSION_COOKIE, session_cookie["cookie"])
        test_client.headers["X-CSRF-Token"] = session_cookie["csrf"]
        yield test_client


def run_async(coro):
    """Run a coroutine to completion, on a thread of its own.

    Not ``asyncio.run``: Playwright's sync API keeps a greenlet-backed event loop
    running in the main thread, so once an e2e test has run, ``asyncio.run`` in
    the same process raises "cannot be called from a running event loop". A
    dedicated thread with its own loop is immune, and keeps one ``pytest``
    command able to run the whole suite.
    """
    import asyncio
    import threading

    result: dict[str, object] = {}

    def target() -> None:
        loop = asyncio.new_event_loop()
        try:
            result["value"] = loop.run_until_complete(coro)
        except BaseException as exc:  # re-raised on the calling thread
            result["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result.get("value")
