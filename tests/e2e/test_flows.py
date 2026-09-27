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
    logged_in.goto("/plan")
    logged_in.wait_for_load_state("networkidle")
    upgraded = logged_in.evaluate(
        "() => !!(customElements.get('sl-tooltip') && customElements.get('sl-drawer'))"
    )
    assert upgraded, "Shoelace did not upgrade, check the CSP and the vendored path"


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
    run = logged_in.locator("#run-button button").first
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
        """The topology controls live in the drawer now, so open it."""
        page.goto("/plan")
        page.wait_for_load_state("networkidle")
        page.click("[data-drawer-open='topology-drawer']")
        page.wait_for_selector("sl-tab[panel='custom']", state="visible", timeout=10000)
        page.click("sl-tab[panel='custom']")
        page.wait_for_timeout(600)
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
        page.wait_for_timeout(1500)
        # the chip lives on the topology summary, which is swapped out of band
        summary = page.locator("#topology-summary").inner_text().lower()
        assert "experimental" in summary
        assert "oaicu-ocududu" in summary

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


class TestSelectionHighlight:
    """Exactly one option in a group may look selected.

    The highlight used to be a class the server wrote from the plan it last
    rendered. Most of these groups sit in cards the form never re-renders, so
    switching one left the old option outlined and the new one plain. It now
    follows the radio's own :checked state.
    """

    GROUPS = ["direction", "iperf_server", "gnb_stack", "split_kind", "ue", "ru",
              "core", "server", "l1_backend"]

    def _selected(self, page, group):
        """How many options in a group carry the selected style, by what the
        browser actually computed rather than by what class is in the markup."""
        return page.evaluate(
            """(group) => {
                const labels = [...document.querySelectorAll(
                    `input[name="${group}"]`)].map(i => i.closest('label, .pick, .opt'));
                return labels.filter(l => {
                    if (!l) return false;
                    const box = getComputedStyle(l).boxShadow || '';
                    return box.includes('inset');
                }).length;
            }""",
            group,
        )

    def _open_drawer(self, page):
        page.goto("/plan")
        page.wait_for_load_state("networkidle")
        page.click("[data-drawer-open='topology-drawer']")
        page.wait_for_selector("sl-tab[panel='custom']", state="visible", timeout=10000)
        page.click("sl-tab[panel='custom']")
        page.wait_for_timeout(600)

    def test_each_group_starts_with_exactly_one_selected(self, logged_in):
        self._open_drawer(logged_in)
        for group in self.GROUPS:
            if logged_in.locator(f"input[name={group}]").count() == 0:
                continue
            assert self._selected(logged_in, group) == 1, group

    def test_switching_the_split_moves_the_highlight(self, logged_in):
        """The reported bug: choosing CU + DU left Monolithic outlined."""
        self._open_drawer(logged_in)
        logged_in.check("input[name=split_kind][value='CU+DU']")
        logged_in.wait_for_timeout(900)
        assert self._selected(logged_in, "split_kind") == 1
        assert logged_in.locator("input[name=split_kind][value='CU+DU']").is_checked()
        assert not logged_in.locator(
            "input[name=split_kind][value='monolithic']"
        ).is_checked()

        logged_in.check("input[name=split_kind][value='monolithic']")
        logged_in.wait_for_timeout(900)
        assert self._selected(logged_in, "split_kind") == 1

    def test_switching_the_iperf_server_moves_the_highlight(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.check("input[name=iperf_server][value='ethos']")
        logged_in.wait_for_timeout(700)
        assert self._selected(logged_in, "iperf_server") == 1
        logged_in.check("input[name=iperf_server][value='app_binary']")
        logged_in.wait_for_timeout(700)
        assert self._selected(logged_in, "iperf_server") == 1

    def test_switching_the_direction_moves_the_highlight(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        for value in ("UL", "DL", "UL"):
            logged_in.check(f"input[name=direction][value='{value}']")
            logged_in.wait_for_timeout(500)
            assert self._selected(logged_in, "direction") == 1

    def test_every_group_in_the_drawer_keeps_one_selected_after_switching(self, logged_in):
        self._open_drawer(logged_in)
        for group, value in [("gnb_stack", "OAI"), ("ue", "MTK"), ("core", "Open5GS")]:
            target = logged_in.locator(f"input[name={group}][value='{value}']")
            if target.count() == 0 or target.is_disabled():
                continue
            target.check()
            logged_in.wait_for_timeout(900)
            assert self._selected(logged_in, group) == 1, group


class TestTopologyPicker:
    def test_the_summary_shows_the_diagram_and_the_config_id(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        assert logged_in.locator("#topology-summary svg.topo").count() == 1
        assert "ocudu-mono_" in logged_in.content()

    def test_change_topology_opens_the_drawer_on_presets(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("[data-drawer-open='topology-drawer']")
        logged_in.wait_for_selector(".preset", state="visible", timeout=10000)
        drawer = logged_in.locator("#topology-drawer")
        assert drawer.is_visible()
        assert logged_in.locator(".preset").count() >= 1
        assert logged_in.locator(".preset svg.topo").count() >= 1

    def test_the_custom_tab_offers_every_component(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("[data-drawer-open='topology-drawer']")
        logged_in.wait_for_selector("sl-tab[panel='custom']", state="visible", timeout=10000)
        logged_in.click("sl-tab[panel='custom']")
        logged_in.wait_for_timeout(600)
        body = logged_in.content()
        for group in ("gNB stack", "Split", "CU vendor", "DU vendor", "L1 backend",
                      "Radio unit", "UE", "Core network", "O-Cloud server"):
            assert group in body, group

    def test_choosing_a_preset_selects_it_and_closes_the_drawer(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("[data-drawer-open='topology-drawer']")
        logged_in.wait_for_selector(".preset", state="visible", timeout=10000)
        logged_in.locator(".preset", has_text="OAI monolithic").first.click()
        logged_in.wait_for_timeout(1500)
        assert "oai-mono_" in logged_in.content()
        assert logged_in.locator("input[name=gnb_stack][value='OAI']").is_checked()

    def test_an_undeployable_option_is_greyed_out_with_its_reason(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("[data-drawer-open='topology-drawer']")
        logged_in.wait_for_selector("sl-tab[panel='custom']", state="visible", timeout=10000)
        logged_in.click("sl-tab[panel='custom']")
        logged_in.wait_for_timeout(600)
        foxconn = logged_in.locator("input[name=ru][value='Foxconn']")
        assert foxconn.is_disabled()
        assert "No chart configuration for this RU yet." in logged_in.content()


class TestPlanLayout:
    def test_readiness_sits_in_the_right_hand_column_under_saved_plans(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        placed = logged_in.evaluate(
            """() => {
                const panel = document.getElementById('readiness-panel');
                const saved = [...document.querySelectorAll('.card-title')]
                    .find(e => e.textContent.trim() === 'Saved plans');
                if (!panel || !saved) return null;
                const column = panel.closest('.sticky-col');
                return {
                    sameColumn: !!column && column.contains(saved),
                    below: saved.getBoundingClientRect().top
                           < panel.getBoundingClientRect().top,
                    sticky: getComputedStyle(column).position === 'sticky',
                };
            }"""
        )
        assert placed and placed["sameColumn"] and placed["below"] and placed["sticky"]

    def test_run_is_the_primary_button_in_the_header_and_is_disabled(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        run = logged_in.locator(".topbar #run-button button")
        assert run.count() == 1
        assert run.is_disabled()
        assert "needs ETHOS B" in logged_in.locator(
            ".topbar #run-button sl-tooltip"
        ).get_attribute("content")

    def test_save_plan_is_secondary(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        save = logged_in.locator(".topbar button", has_text="Save plan")
        assert save.count() == 1
        assert "primary" not in (save.get_attribute("class") or "")

    def test_run_also_sits_at_the_foot_of_the_readiness_panel(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        assert logged_in.locator("#readiness-panel .run-foot button").count() == 1

    def test_the_run_it_panel_does_not_claim_the_cli_takes_a_lock(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        body = logged_in.content()
        assert "ETHOS has no testbed lock yet (B1)" in body
        assert "takes the same lock" not in body

    def test_the_generated_command_uses_seconds_for_the_duration(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.fill("#duration", "5m")
        logged_in.keyboard.press("Tab")   # change fires on blur
        logged_in.wait_for_timeout(1500)
        command = logged_in.locator("pre.cmd").first.inner_text()
        assert "--duration 300s" in command
        assert "--duration 5m" not in command


class TestIconsAndText:
    def test_the_sprite_is_on_the_page_and_icons_resolve(self, logged_in):
        logged_in.goto("/")
        logged_in.wait_for_load_state("networkidle")
        assert logged_in.locator("symbol#icon-ue").count() == 1
        drawn = logged_in.evaluate(
            """() => [...document.querySelectorAll('svg.ic use')].every(u => {
                const id = u.getAttribute('href').slice(1);
                return !!document.getElementById(id);
            })"""
        )
        assert drawn, "an icon on the page points at a symbol that is not in the sprite"

    def test_no_page_shows_an_em_dash(self, logged_in):
        """The character is built from its code point so this file does not
        contain one itself, which is what the source-level check looks for."""
        em_dash = chr(0x2014)
        for path in ("/", "/plan", "/results", "/jobs", "/graphs", "/docs"):
            logged_in.goto(path)
            logged_in.wait_for_load_state("networkidle")
            text = logged_in.evaluate("() => document.body.innerText")
            assert em_dash not in text, f"{path} shows an em dash"

    def test_the_icon_sheet_renders_its_previews(self, logged_in):
        logged_in.goto("/docs/icons")
        logged_in.wait_for_load_state("networkidle")
        assert logged_in.locator("article symbol#icon-ru").count() >= 1
        assert logged_in.locator("article svg use").count() > 20
