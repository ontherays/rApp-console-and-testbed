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
        "() => !!(customElements.get('sl-icon') && customElements.get('sl-tooltip'))"
    )
    assert upgraded, "Shoelace did not upgrade — check the CSP and the vendored path"


def test_no_asset_is_requested_from_another_host(logged_in):
    hosts: list[str] = []
    logged_in.on("request", lambda request: hosts.append(request.url))
    logged_in.goto("/")
    logged_in.wait_for_load_state("networkidle")
    outside = [url for url in hosts if not url.startswith("http://127.0.0.1")]
    assert outside == [], f"a page reached outside the console: {outside}"


def test_the_status_strip_polls_and_reports_ethos_down(offline_page):
    offline_page.goto("/")
    offline_page.wait_for_selector("text=ETHOS API unreachable", timeout=15000)
    assert "Every action is disabled" in offline_page.content()


def test_the_plan_page_disables_run_and_gives_the_reason(logged_in):
    logged_in.goto("/plan")
    logged_in.wait_for_load_state("networkidle")
    run = logged_in.locator("button:has-text('RUN')").first
    assert run.is_disabled()
    assert "needs ETHOS" in logged_in.content()


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


class TestTopologyForm:
    """Task A, in a real browser: the CU and DU vendor groups follow the split."""

    def _open(self, page):
        page.goto("/plan")
        page.wait_for_load_state("networkidle")
        return page

    def _group(self, page, name):
        return page.locator(f"input[name={name}]")

    def test_monolithic_disables_both_vendor_groups(self, logged_in):
        page = self._open(logged_in)
        page.check("input[name=split_kind][value='monolithic']")
        page.wait_for_timeout(1200)
        for name in ("cu_vendor", "du_vendor"):
            inputs = self._group(page, name)
            for index in range(inputs.count()):
                assert inputs.nth(index).is_disabled(), f"{name} must be disabled"

    def test_monolithic_shows_the_gnb_stacks_value_and_the_reason(self, logged_in):
        page = self._open(logged_in)
        page.check("input[name=gnb_stack][value='OAI']")
        page.wait_for_timeout(600)
        page.check("input[name=split_kind][value='monolithic']")
        page.wait_for_timeout(1200)
        assert page.locator("input[name=cu_vendor][value='OAI']").is_checked()
        assert page.locator("input[name=du_vendor][value='OAI']").is_checked()
        assert "Monolithic runs CU and DU in one process" in page.content()

    def test_cu_du_makes_both_groups_selectable(self, logged_in):
        """The split changes without a page load, so the groups are re-rendered
        by the same request and swapped in out of band."""
        page = self._open(logged_in)
        page.check("input[name=split_kind][value='CU+DU']")
        page.wait_for_timeout(1200)
        for name in ("cu_vendor", "du_vendor"):
            inputs = self._group(page, name)
            assert inputs.count() == 2, f"{name} must offer both vendors"
            for index in range(inputs.count()):
                assert not inputs.nth(index).is_disabled(), f"{name} must be selectable"

    def test_cu_du_defaults_to_the_gnb_stacks_vendor(self, logged_in):
        page = self._open(logged_in)
        page.check("input[name=gnb_stack][value='OAI']")
        page.wait_for_timeout(600)
        page.check("input[name=split_kind][value='CU+DU']")
        page.wait_for_timeout(1200)
        assert page.locator("input[name=cu_vendor][value='OAI']").is_checked()
        assert page.locator("input[name=du_vendor][value='OAI']").is_checked()

    def test_two_different_vendors_select_the_cross_vendor_split(self, logged_in):
        page = self._open(logged_in)
        page.check("input[name=split_kind][value='CU+DU']")
        page.wait_for_timeout(1000)
        page.check("input[name=cu_vendor][value='OAI']")
        page.wait_for_timeout(600)
        page.check("input[name=du_vendor][value='OCUDU']")
        page.wait_for_timeout(1200)
        assert "experimental" in page.locator("#plan-result").inner_text().lower()

    def test_changing_the_split_updates_the_identity_panel(self, logged_in):
        page = self._open(logged_in)
        page.check("input[name=split_kind][value='CU+DU']")
        page.wait_for_timeout(1200)
        assert page.locator("#plan-result").inner_text() != ""


class TestRedesign:
    def test_the_sidebar_is_grouped_and_has_a_search_box(self, logged_in):
        logged_in.goto("/")
        logged_in.wait_for_load_state("networkidle")
        body = logged_in.content()
        for group in ("Essentials", "Measure", "Network", "System"):
            assert group in body
        assert logged_in.locator("#console-search").is_visible()

    def test_the_slash_key_focuses_the_search_box(self, logged_in):
        logged_in.goto("/")
        logged_in.wait_for_load_state("networkidle")
        logged_in.keyboard.press("/")
        focused = logged_in.evaluate("() => document.activeElement.id")
        assert focused == "console-search"

    def test_the_slash_key_is_ignored_while_typing(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("#rates")
        logged_in.keyboard.press("/")
        assert logged_in.evaluate("() => document.activeElement.id") == "rates"

    def test_the_backend_card_counts_what_is_ready(self, logged_in):
        logged_in.goto("/")
        logged_in.wait_for_load_state("networkidle")
        assert "of 6 ready" in logged_in.content()

    def test_the_overview_draws_both_charts(self, logged_in):
        logged_in.goto("/")
        logged_in.wait_for_load_state("networkidle")
        assert logged_in.locator("svg.hexgrid").count() == 1
        assert logged_in.locator("svg.dotmatrix").count() == 1

    def test_the_period_and_kind_controls_switch(self, logged_in):
        logged_in.goto("/?period=30d&kind=all")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("a:has-text('24 hours')")
        logged_in.wait_for_load_state("networkidle")
        assert "period=24h" in logged_in.url

    def test_one_primary_action_per_page(self, logged_in):
        for path in ("/", "/results", "/jobs"):
            logged_in.goto(path)
            logged_in.wait_for_load_state("networkidle")
            assert logged_in.locator(".topbar .btn.primary").count() == 1, path
