"""A real browser against a real console process, with a fake ETHOS behind it.

The pytest suite covers the server: status codes, headers, rendered HTML. What it
cannot check is that the Shoelace web components actually upgrade and that the
htmx swaps land — both depend on the vendored assets being served correctly under
a strict Content-Security-Policy, which is exactly the kind of thing that breaks
silently.

These tests need the optional extra:

    .venv/bin/python -m pip install -e '.[e2e]'
    .venv/bin/playwright install chromium

They skip themselves when it is not installed.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="the e2e extra is not installed"
)

ROOT = Path(__file__).resolve().parent.parent.parent
RECORDED = ROOT / "tests" / "recorded"
PASSWORD = "e2e-test-password"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_fake_ethos():
    """Serve the recorded ETHOS responses, so the pages have data to draw."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.fake_ethos.server", "--port", str(port)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for(port, process, "the fake ETHOS")
    return f"http://127.0.0.1:{port}", process


def _wait_for(port: int, process, what: str) -> None:
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            if process.poll() is not None:
                output = (process.stdout.read() or b"").decode()
                pytest.fail(f"{what} exited while starting:\n{output}")
            time.sleep(0.1)
    process.kill()
    pytest.fail(f"{what} did not start")


def _start_console(ethos_url: str | None = None):
    """Start a console process and return (base_url, process).

    Plain HTTP on loopback rather than the self-signed certificate: these tests
    check the page, not the TLS setup, and a browser told to ignore certificate
    errors hides real ones.
    """
    from console.auth import hash_password

    port = _free_port()
    environment = dict(os.environ)
    environment.update(
        {
            "CONSOLE_ENV_FILE": "/nonexistent/console.env",
            "CONSOLE_BIND": "127.0.0.1",
            "CONSOLE_PORT": str(port),
            "CONSOLE_TLS_CERT": "",
            "CONSOLE_TLS_KEY": "",
            "CONSOLE_PASSWORD_HASH": hash_password(PASSWORD),
            "CONSOLE_SESSION_SECRET": "e" * 64,
            # A real fake ETHOS when one is given, so the catalogue-driven
            # option lists exist; an address with nothing on it otherwise, which
            # is how the "ETHOS is down" path is exercised.
            "CONSOLE_ETHOS_URL": ethos_url or f"http://127.0.0.1:{_free_port()}",
            "CONSOLE_GRAPH_DIR": str(RECORDED / "graphs"),
            "CONSOLE_DEPLOY_PROFILES": str(RECORDED / "deploy_profiles.yaml"),
            "CONSOLE_PLANS_DIR": "/tmp/testbed-console-e2e-plans",
            "CONSOLE_LOG_LEVEL": "warning",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "console", "serve", "--insecure"],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    _wait_for(port, process, "the console")
    return f"http://127.0.0.1:{port}", process


def _stop_console(process) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture(scope="session")
def fake_ethos_server():
    base, process = _start_fake_ethos()
    yield base
    _stop_console(process)


@pytest.fixture(scope="session")
def console_server(fake_ethos_server):
    """The console, with the recorded ETHOS behind it."""
    base, process = _start_console(fake_ethos_server)
    yield base
    _stop_console(process)


@pytest.fixture(scope="session")
def console_without_ethos():
    """The console with nothing behind it, for the outage paths."""
    base, process = _start_console()
    yield base
    _stop_console(process)


@pytest.fixture
def fresh_console(fake_ethos_server):
    """A console process of its own.

    The login rate limit is held in memory, so a test that deliberately locks
    login would lock it for every later test sharing the process. That test gets
    its own.
    """
    base, process = _start_console(fake_ethos_server)
    yield base
    _stop_console(process)


@pytest.fixture(scope="session")
def browser():
    with playwright_api.sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser, console_server):
    context = browser.new_context(base_url=console_server, viewport={"width": 1400, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda message: errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.console_errors = errors  # type: ignore[attr-defined]
    yield page
    context.close()


@pytest.fixture
def logged_in(page):
    page.goto("/login")
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url("**/")
    return page


@pytest.fixture
def fresh_page(browser, fresh_console):
    context = browser.new_context(base_url=fresh_console, viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.console_errors = []  # type: ignore[attr-defined]
    yield page
    context.close()


@pytest.fixture
def offline_page(browser, console_without_ethos):
    """A page served by a console whose ETHOS is not answering."""
    context = browser.new_context(
        base_url=console_without_ethos, viewport={"width": 1400, "height": 900}
    )
    page = context.new_page()
    page.console_errors = []  # type: ignore[attr-defined]
    page.goto("/login")
    page.fill("#password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url("**/")
    yield page
    context.close()
