"""Browser flows. ETHOS is deliberately unreachable in this fixture, so these
also check the path that is hardest to produce on a real testbed: every page
still renders, and every action is disabled with the reason shown (ST-04)."""

from __future__ import annotations

import json

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


def test_run_is_offered_and_asks_for_a_preview_before_it_acts(logged_in):
    """RUN is live now, and its click is a preview rather than a start (GL-07)."""
    logged_in.goto("/plan")
    logged_in.wait_for_load_state("networkidle")
    logged_in.wait_for_timeout(1500)
    run = logged_in.locator("#readiness-panel .run-foot button").first
    assert run.is_enabled()
    run.click()
    logged_in.wait_for_selector("#plan-dialog sl-dialog", timeout=30000)
    dialog = logged_in.query_selector("#plan-dialog sl-dialog")
    assert "Nothing has been sent to the testbed yet" in dialog.inner_text()


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

    def test_run_is_the_primary_button_in_the_header(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.wait_for_timeout(1500)
        run = logged_in.locator(".topbar #run-button button")
        assert run.count() == 1
        assert "primary" in (run.get_attribute("class") or "")

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

    def test_the_run_it_panel_says_the_cli_takes_the_same_lock(self, logged_in):
        """It does now, so the panel says so rather than warning about a collision."""
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        body = logged_in.content()
        assert "takes the same testbed lock as RUN" in body
        assert "ETHOS has no testbed lock yet" not in body

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


class TestWiredFlows:
    """The surfaces B1, B2, B5, B6 and B11 turned on, in a real browser.

    Against the fake ETHOS, so no testbed is touched. What is checked is the
    thing a unit test cannot: that the dialog opens and survives, that the log
    renders as lines rather than as ETHOS's JSON, and that a refusal reaches the
    operator.
    """

    def test_the_readiness_panel_shows_ethoss_seven_checks(self, logged_in):
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.wait_for_timeout(1500)
        rows = logged_in.locator("#readiness-panel .check")
        assert rows.count() == 7
        assert logged_in.locator("#readiness-panel").count() == 1

    def test_the_confirmation_survives_the_plan_re_resolving(self, logged_in):
        """It lives outside the form, so a resolve cannot take it away."""
        logged_in.goto("/plan")
        logged_in.wait_for_load_state("networkidle")
        logged_in.wait_for_timeout(1500)
        logged_in.locator("#readiness-panel .run-foot button").first.click()
        logged_in.wait_for_selector("#plan-dialog sl-dialog", timeout=30000)
        logged_in.wait_for_timeout(3000)
        assert logged_in.locator("#plan-dialog sl-dialog").count() == 1

    def test_a_job_log_renders_lines_not_json(self, logged_in):
        """The relay passes ETHOS's JSON through; the page turns it into lines.

        It rendered the raw JSON until the renderer moved out of an inline script,
        which the console's own CSP blocks.
        """
        from tests.fake_ethos.server import SEEDED_JOB, SEEDED_LOG

        logged_in.goto(f"/jobs/{SEEDED_JOB}")
        logged_in.wait_for_selector("#job-log", timeout=30000)
        logged_in.wait_for_timeout(3000)
        text = logged_in.locator("#job-log").inner_text()
        for line in SEEDED_LOG:
            assert line in text
        assert '"seq"' not in text

    def test_stopping_a_job_asks_first(self, logged_in):
        """The Stop button opens a confirmation; it does not stop anything."""
        from tests.fake_ethos.server import SEEDED_JOB

        logged_in.goto(f"/jobs/{SEEDED_JOB}")
        logged_in.wait_for_selector("#job-snapshot", timeout=30000)
        logged_in.locator("button", has_text="Stop").first.click()
        logged_in.wait_for_selector("#stop-confirm sl-dialog", timeout=30000)
        dialog = logged_in.query_selector("#stop-confirm sl-dialog")
        assert "aborted" in dialog.inner_text()
        assert "current point" in dialog.inner_text().lower() or "point being measured" in dialog.inner_text()

    def test_the_ue_panel_lists_the_handsets_and_previews_an_attach(self, logged_in):
        logged_in.goto("/testbed")
        logged_in.wait_for_selector("#ue-panel table.data tbody tr", timeout=30000)
        body = logged_in.content()
        assert "Samsung" in body and "MTK" in body
        logged_in.locator(
            "#ue-panel tr", has_text="Samsung"
        ).locator("button", has_text="Attach").first.click()
        logged_in.wait_for_selector("#ue-confirm sl-dialog", timeout=30000)
        dialog = logged_in.query_selector("#ue-confirm sl-dialog")
        assert "Nothing has been sent to the handset yet" in dialog.inner_text()

    def test_a_held_testbed_is_named_on_every_page(self, logged_in, fake_ethos_server):
        """A CLI holder reads the same everywhere a holder appears."""
        import urllib.request

        def control(what, body):
            request = urllib.request.Request(
                f"{fake_ethos_server}/__control/{what}",
                data=json.dumps(body).encode(),
                headers={"content-type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(request, timeout=10).read()

        control("lock", {"holder": "cli:4242",
                         "what": "campaign ocudu-mono, rates 100, DL"})
        try:
            for path in ("/", "/jobs", "/testbed"):
                logged_in.goto(path)
                logged_in.wait_for_load_state("networkidle")
                assert "CLI campaign ocudu-mono, rates 100, DL" in logged_in.content(), path
        finally:
            control("reset", {})



def _channels(colour: str) -> tuple[int, ...]:
    """The numbers out of `rgb(...)` or `rgba(...)`, so a comparison does not
    depend on which of the two forms the browser happened to serialise."""
    import re

    return tuple(int(float(n)) for n in re.findall(r"[\d.]+", colour)[:3])


class TestFigures:
    """The Graphs page in a real browser, against the fake ETHOS (B9)."""

    def test_generating_shows_the_figure_its_warnings_and_its_data(self, logged_in):
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        logged_in.fill("#run_ids", "run-a run-b")
        logged_in.fill("#label", "e2e-figure")
        logged_in.select_option("#metric", "pusch_snr")
        logged_in.click("#plot-form button[type=submit]")
        logged_in.wait_for_selector("#plot-result img", timeout=30000)

        panel = logged_in.locator("#plot-result").inner_text()
        assert "e2e-figure" in panel
        # The manifest's warnings are shown as their own bars, and the Data
        # accordion carries the points, the caps and the dropped runs.
        assert logged_in.locator("#plot-result .banner.warn").count() >= 1
        data = logged_in.locator("#plot-result sl-details[summary=Data]")
        assert data.count() == 1
        data.click()
        logged_in.wait_for_selector("#plot-result sl-details table")
        assert "ocudu-mono" in data.inner_text()

    def test_naming_runs_moves_the_source_to_selected_runs(self, logged_in):
        """The radio reads back what was asked for, not what was defaulted."""
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        assert logged_in.input_value("#run_ids") == ""
        assert logged_in.is_checked("input[name=source][value=influx]")
        logged_in.fill("#run_ids", "run-a")
        assert logged_in.is_checked("input[name=source][value=runs]")
        logged_in.click("sl-details[summary='Filter instead']")
        logged_in.fill("#config_ids", "ocudu-mono")
        assert logged_in.is_checked("input[name=source][value=influx]")

    def test_select_all_and_clear_work_and_skip_a_held_out_sweep(self, logged_in):
        """These are the picker's only scripted behaviour, so they need a real
        browser to be tested at all.

        They were written as inline `onclick` handlers and never ran once: the
        console's CSP is `script-src 'self'`, which blocks inline handlers, and
        a unit test asserting the button's text was present could not see it.
        """
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")

        boxes = logged_in.locator("#job-picker input[name=job_ids]")
        enabled = logged_in.locator("#job-picker input[name=job_ids]:not([disabled])")
        held = logged_in.locator("#job-picker input[name=job_ids][disabled]")
        assert boxes.count() > 0 and held.count() > 0, "the fake seeds a held-out sweep"

        logged_in.click("#job-picker button[data-picker=all]")
        assert logged_in.locator(
            "#job-picker input[name=job_ids]:checked").count() == enabled.count()
        assert held.first.is_checked() is False, "Select all must skip a held-out sweep"

        logged_in.click("#job-picker button[data-picker=none]")
        assert logged_in.locator("#job-picker input[name=job_ids]:checked").count() == 0

    def test_a_ticked_sweep_is_visually_distinct_from_an_unticked_one(self, logged_in):
        """The highlight follows the box's own :checked state, so it is right
        the instant it is clicked and cannot be left behind when htmx swaps the
        picker on a date change."""
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")

        rows = logged_in.locator(".job-pick:not(.job-pick-held)")
        plain = rows.nth(1).evaluate("e => getComputedStyle(e).backgroundColor")
        rows.nth(0).locator("input").check()
        logged_in.mouse.move(0, 0)   # read the resting colour, not the hover one

        # The row fades to its selected colour over 120ms, so read it after it
        # has settled: sampling immediately returns a value part-way through the
        # transition, which is neither colour and compares equal to neither.
        #
        # The colour is read from `--pick-on` rather than written here, so
        # retuning the shade is a one-line change in the stylesheet and not a
        # test edit as well.
        logged_in.wait_for_function(
            """() => {
                 const row = document.querySelector('.job-pick:not(.job-pick-held)');
                 const probe = document.createElement('span');
                 probe.style.color = 'var(--pick-on)';
                 document.body.appendChild(probe);
                 const want = getComputedStyle(probe).color;
                 probe.remove();
                 return getComputedStyle(row).backgroundColor === want;
               }""",
            timeout=2000,
        )
        picked = rows.nth(0).evaluate("e => getComputedStyle(e).backgroundColor")
        edge = rows.nth(0).evaluate("e => getComputedStyle(e).borderLeftColor")
        assert picked != plain, "a ticked sweep looks the same as an unticked one"
        # Compared as channels, not as a string: Chrome serialises a colour that
        # is still transitioning as `rgba(r, g, b, 1)` and the settled one as
        # `rgb(r, g, b)`, so a string match passes or fails on timing.
        accent = logged_in.evaluate(
            """() => {
                 const p = document.createElement('span');
                 p.style.color = 'var(--pick-on-edge)';
                 document.body.appendChild(p);
                 const c = getComputedStyle(p).color;
                 p.remove();
                 return c;
               }""")
        assert _channels(edge) == _channels(accent), "the accent edge marks the selection"

    def test_the_graph_form_does_not_scroll_sideways_when_narrowed(self, logged_in):
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        try:
            for width in (1440, 1100, 900):
                logged_in.set_viewport_size({"width": width, "height": 900})
                overflows = logged_in.evaluate(
                    "() => document.documentElement.scrollWidth > "
                    "document.documentElement.clientWidth")
                assert not overflows, f"the page scrolls sideways at {width}px"
        finally:
            logged_in.set_viewport_size({"width": 1440, "height": 900})

    def test_the_form_offers_only_the_metrics_ethos_offers(self, logged_in):
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        offered = logged_in.eval_on_selector_all(
            "#metric option", "els => els.map(e => e.value)")
        assert "pusch_snr" in offered and "mcs_dl" in offered
        assert "bler_dl_first_tx" not in offered
        assert "pucch_snr" not in offered

    def test_a_refusal_shows_ethoss_message_and_the_retry_where_it_helps(
            self, logged_in, fake_ethos_server):
        import urllib.request

        message = (
            "these series mix run durations across their points -- "
            "ocudu-mono_x: [10, 20] s. Re-run with --min-duration to select "
            "one, or --allow-mixed-durations to accept it"
        )
        request = urllib.request.Request(
            f"{fake_ethos_server}/__control/refuse_plot",
            data=json.dumps({"detail": message}).encode(),
            headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(request, timeout=10).read()

        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        logged_in.fill("#run_ids", "run-a run-b")
        logged_in.click("#plot-form button[type=submit]")
        logged_in.wait_for_selector("#plot-result .card", timeout=30000)

        panel = logged_in.locator("#plot-result").inner_text()
        assert "mix run durations" in panel
        assert "10 s" in panel and "20 s" in panel

        # The retry sets the flag, and the second attempt succeeds.
        logged_in.click("#plot-result button:has-text('Retry allowing mixed durations')")
        logged_in.wait_for_selector("#plot-result img", timeout=30000)

    def test_the_gallery_regenerates_a_figure(self, logged_in):
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        logged_in.locator(".gallery button:has-text('Regenerate')").first.click()
        logged_in.wait_for_url("**/graphs/view/**", timeout=30000)
        assert logged_in.locator("sl-details[summary=Data]").count() == 1
        assert "point(s)" in logged_in.locator(".card-sub").first.inner_text()

    def test_a_download_arrives_with_its_type_and_name(self, logged_in):
        logged_in.goto("/graphs")
        logged_in.wait_for_load_state("networkidle")
        with logged_in.expect_download() as download:
            logged_in.locator(".gallery a[download]").first.click()
        name = download.value.suggested_filename
        assert name.endswith(".png")
        assert name != "image.png"

    def test_results_selection_prefills_the_form(self, logged_in):
        logged_in.goto("/results")
        logged_in.wait_for_load_state("networkidle")
        logged_in.locator("input[name=run_id]").first.check()
        logged_in.click("button:has-text('Graph selected')")
        logged_in.wait_for_url("**/graphs**", timeout=30000)
        assert logged_in.input_value("#run_ids").strip()

    def test_a_sweep_column_prefills_the_metric(self, logged_in):
        logged_in.goto("/results")
        logged_in.wait_for_load_state("networkidle")
        logged_in.locator("input[name=run_id]").first.check()
        logged_in.click("button:has-text('Compare selected')")
        logged_in.wait_for_url("**/results/compare**", timeout=30000)
        logged_in.locator("a.plot-link").nth(3).click()
        logged_in.wait_for_url("**/graphs**", timeout=30000)
        assert logged_in.input_value("#metric")
        assert logged_in.input_value("#run_ids").strip()

    def test_a_finished_job_prefills_its_id(self, logged_in):
        from tests.fake_ethos.server import SEEDED_DONE_JOB

        logged_in.goto(f"/jobs/{SEEDED_DONE_JOB}")
        logged_in.wait_for_load_state("networkidle")
        logged_in.click("a:has-text('Plot this job')")
        logged_in.wait_for_url("**/graphs**", timeout=30000)
        assert logged_in.input_value("#job_id") == SEEDED_DONE_JOB
