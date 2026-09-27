"""Browser flows. ETHOS is deliberately unreachable in this fixture, so these
also check the path that is hardest to produce on a real testbed: every page
still renders, and every action is disabled with the reason shown (ST-04)."""

from __future__ import annotations

import pytest

PAGES = ["/", "/plan", "/jobs", "/results", "/graphs", "/testbed", "/o1", "/o2", "/docs"]


def test_login_is_required_and_then_works(page):
    page.goto("/results")
    assert "/login" in page.url
    page.fill("#password", "wrong password")
    page.click("button[type=submit]")
    assert "not correct" in page.content()

    page.fill("#password", "e2e-test-password")
    page.click("button[type=submit]")
    page.wait_for_url("**/results")
    assert "Results" in page.content()


def test_five_wrong_passwords_lock_login(fresh_page):
    """On its own console process: the limiter is in memory, so locking login
    here would lock it for every test that shared the process."""
    fresh_page.goto("/login")
    for _ in range(5):
        fresh_page.fill("#password", "wrong password")
        fresh_page.click("button[type=submit]")
    assert "10 minutes" in fresh_page.content()
    assert fresh_page.locator("#password").is_disabled()


@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders_in_a_browser_with_no_javascript_error(logged_in, path):
    logged_in.goto(path)
    logged_in.wait_for_load_state("networkidle")
    assert logged_in.locator("nav.side").is_visible()
    real = [e for e in logged_in.console_errors if "favicon" not in e.lower()]
    assert real == [], f"javascript errors on {path}: {real}"


def test_the_vendored_components_upgrade(logged_in):
    """A Shoelace component that never upgrades leaves an inert custom element,
    which looks like a styling bug and is actually a blocked script."""
    logged_in.goto("/results")
    logged_in.wait_for_load_state("networkidle")
    upgraded = logged_in.evaluate(
        "() => !!(customElements.get('sl-breadcrumb') && customElements.get('sl-icon'))"
    )
    assert upgraded, "Shoelace did not upgrade — check the CSP and the vendored path"


def test_no_asset_is_requested_from_another_host(logged_in):
    hosts: list[str] = []
    logged_in.on("request", lambda request: hosts.append(request.url))
    logged_in.goto("/")
    logged_in.wait_for_load_state("networkidle")
    outside = [url for url in hosts if not url.startswith("http://127.0.0.1")]
    assert outside == [], f"a page reached outside the console: {outside}"


def test_the_status_strip_polls_and_reports_ethos_down(logged_in):
    logged_in.goto("/")
    logged_in.wait_for_selector("text=ETHOS API unreachable", timeout=10000)
    assert "Every action is disabled" in logged_in.content()


def test_the_plan_page_disables_run_and_gives_the_reason(logged_in):
    logged_in.goto("/plan")
    logged_in.wait_for_load_state("networkidle")
    run = logged_in.locator("button:has-text('RUN')").first
    assert run.is_disabled()
    body = logged_in.content()
    assert "needs ETHOS" in body or "unreachable" in body


def test_the_gallery_opens_a_figure_and_shows_its_manifest(logged_in):
    logged_in.goto("/graphs")
    logged_in.wait_for_load_state("networkidle")
    logged_in.click("text=full-sweep")
    logged_in.wait_for_load_state("networkidle")
    assert "achieved_over_tx_mbps" in logged_in.content()


def test_a_figure_png_downloads(logged_in):
    logged_in.goto("/graphs/view/2026-09-25/185503_line_full-sweep")
    with logged_in.expect_download() as download:
        logged_in.click("a[download][href$='/png']")
    assert download.value.suggested_filename.endswith(".png")
