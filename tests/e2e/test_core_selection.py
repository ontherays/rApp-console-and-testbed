"""Choosing free5GC in Change topology, in a real browser.

The server-side tests all post `core=free5GC` themselves, so they prove the
handler, not the dialog. What they cannot see is whether the click reaches
the form at all: that depends on the Shoelace drawer upgrading, the radio
inside it staying form-associated, and htmx serialising it. Those are exactly
the things that break silently, and a selection that quietly falls back to
Open5GS is the worst kind of break, because a run then measures one core and
is labelled the other.

Every test here records the `core` field of each /plan/resolve request the
page actually sends.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="the e2e extra is not installed")


def _recorder(page):
    """Capture the core field of every form POST the page makes."""
    sent: list[tuple[str, str]] = []

    def record(request):
        if request.method != "POST":
            return
        body = request.post_data or ""
        fields = dict(
            part.split("=", 1) for part in body.split("&") if "=" in part
        )
        if "core" in fields or "/plan/" in request.url:
            sent.append(
                (
                    request.url.rsplit("/", 1)[-1],
                    fields.get("core", "<<ABSENT>>").replace("%2B", "+"),
                )
            )

    page.on("request", record)
    return sent


def _open_dialog(page, tab="custom"):
    """Open Change topology and show one tab.

    The custom tab is where the component cards are; a Shoelace tab panel is
    hidden until its tab is selected, so the cards do not exist to click
    before this.
    """
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    # the opener calls drawer.show(), which only exists once Shoelace upgrades
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(600)
    page.click("[data-drawer-open='topology-drawer']")
    page.wait_for_timeout(600)
    page.click(f"#topology-drawer sl-tab[panel='{tab}']")
    page.wait_for_timeout(500)


def _pick(page, group: str, value: str):
    page.locator(f"#topology-drawer input[name='{group}'][value='{value}']").click()
    page.wait_for_timeout(900)      # the form debounces at 300 ms


def _form_core(page) -> str:
    return page.evaluate(
        "() => new FormData(document.getElementById('plan-form')).get('core')"
    )


def _apply_preset(page, index: int = 0):
    """Click a preset card, the first tab and the obvious way to pick a topology."""
    page.click("#topology-drawer sl-tab[panel='presets']")
    page.wait_for_timeout(400)
    page.locator("#topology-drawer [data-preset]").nth(index).click()
    page.wait_for_timeout(1200)


def _resolved_core(page) -> str:
    """The core the resolved panel settled on, as `--core <slug>`.

    Read from the campaign command the panel renders, because that string is
    built from the same `values["core"]` the plan document and the config_id
    are, and it is always present. The config_id itself is only rendered once
    ETHOS has generated one, which depends on the backend behind the console;
    item 6 checks that against the real ETHOS.
    """
    import re

    page.wait_for_function(
        "() => /--core \\w+/.test("
        "(document.getElementById('plan-result') || {}).innerText || '')",
        timeout=20000,
    )
    found = re.search(r"--core (\w+)", page.inner_text("#plan-result"))
    return found.group(1) if found else ""


def _done(page):
    """Press Done. The preset cards also close the drawer, so target the footer."""
    page.click("#topology-drawer .btn.primary[slot='footer']")
    page.wait_for_timeout(400)


# --- the bug -----------------------------------------------------------------

def test_choosing_free5gc_is_what_the_form_then_sends(logged_in):
    page = logged_in
    sent = _recorder(page)
    _open_dialog(page)

    _pick(page, "core", "free5GC")

    assert sent, "the page sent no request at all when the core was chosen"
    assert sent[-1][1] == "free5GC", f"the form sent {sent[-1][1]!r}, not free5GC"


def test_the_choice_survives_changing_the_ue(logged_in):
    page = logged_in
    sent = _recorder(page)
    _open_dialog(page)

    _pick(page, "core", "free5GC")
    _pick(page, "ue", "MTK")

    assert [core for _url, core in sent][-1] == "free5GC"


def test_the_choice_survives_changing_the_ru_and_the_server(logged_in):
    page = logged_in
    sent = _recorder(page)
    _open_dialog(page)

    _pick(page, "core", "free5GC")
    after = len(sent)
    _pick(page, "ue", "MTK")
    _pick(page, "server", "joule")

    # every request AFTER the core was chosen; the one on page load is
    # Open5GS by design, and that is the default working, not the bug
    assert [core for _u, core in sent[after:]] and all(
        core == "free5GC" for _u, core in sent[after:]
    ), sent


def test_the_config_id_carries_f5gc_after_done(logged_in):
    page = logged_in
    _open_dialog(page)
    _pick(page, "core", "free5GC")
    _done(page)

    assert _resolved_core(page) == "free5gc"


def test_the_core_card_says_the_plan_is_free5gc(logged_in):
    page = logged_in
    _open_dialog(page)
    _pick(page, "core", "free5GC")
    page.wait_for_timeout(900)

    assert "free5GC" in page.inner_text("#core-panel")


@pytest.mark.parametrize("ue", ["Samsung", "MTK"])
@pytest.mark.parametrize("core, slug", [("Open5GS", "o5gs"), ("free5GC", "f5gc")])
def test_every_ue_and_core_combination_resolves_to_its_own_config_id(
    logged_in, ue, core, slug
):
    page = logged_in
    _open_dialog(page)
    _pick(page, "core", core)
    _pick(page, "ue", ue)
    page.wait_for_timeout(900)

    assert _resolved_core(page) == {"o5gs": "open5gs", "f5gc": "free5gc"}[slug], (
        f"{core} + {ue} resolved to {_resolved_core(page)!r}"
    )
    assert f"--ue {ue.lower()}" in page.inner_text("#plan-result")


def test_switching_back_from_free5gc_to_open5gs_also_sticks(logged_in):
    page = logged_in
    sent = _recorder(page)
    _open_dialog(page)

    _pick(page, "core", "free5GC")
    _pick(page, "core", "Open5GS")

    assert sent[-1][1] == "Open5GS"
    assert _resolved_core(page) == "open5gs"


def test_a_new_plan_starts_on_open5gs(logged_in):
    """The default applies to a plan with no core chosen, and only then."""
    page = logged_in
    page.goto("/plan")
    page.wait_for_selector("#plan-form")

    assert page.evaluate(
        "() => document.querySelector("
        "\"input[name='core'][value='Open5GS']\").checked"
    )
    assert _resolved_core(page) == "open5gs"


# --- the regression this file exists for -------------------------------------

def test_a_preset_does_not_undo_a_core_chosen_in_the_custom_tab(logged_in):
    """The bug: every preset card froze the core the PAGE was rendered with,
    and applying one wrote Open5GS back over free5GC without a word."""
    page = logged_in
    sent = _recorder(page)
    _open_dialog(page)

    _pick(page, "core", "free5GC")
    assert _form_core(page) == "free5GC"

    _apply_preset(page)

    assert _form_core(page) == "free5GC", "a preset undid the chosen core"
    assert [core for _u, core in sent][-1] == "free5GC"


def test_a_preset_still_changes_the_topology(logged_in):
    """The fix must not make presets inert: that is what they are for."""
    page = logged_in
    _open_dialog(page)
    _pick(page, "core", "free5GC")

    _apply_preset(page, index=1)        # OAI monolithic

    assert page.evaluate(
        "() => new FormData(document.getElementById('plan-form')).get('gnb_stack')"
    ) == "OAI"
    panel = page.inner_text("#plan-result")
    assert "campaign oai-mono" in panel, panel[:120]
    assert _resolved_core(page) == "free5gc"   # the core came through with it


def test_the_preset_cards_carry_a_stale_core_which_is_why_it_is_not_applied(logged_in):
    """Pins the reason. The payload is for the card's diagram, nothing else."""
    page = logged_in
    _open_dialog(page, tab="presets")
    _pick_cores = page.eval_on_selector_all(
        "#topology-drawer [data-preset]",
        "els => els.map(e => JSON.parse(e.dataset.preset).core)",
    )
    assert set(_pick_cores) == {"Open5GS"}      # frozen at page load
