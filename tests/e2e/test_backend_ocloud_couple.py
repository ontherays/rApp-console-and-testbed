"""The L1 backend and the O-Cloud pick each other, clicked in a real browser.

A server-side post cannot show this: the form posts as a whole and htmx names
no control, so what these assert is the state the operator can see after a
click, in the cards, the summary and the dialog.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", reason="the e2e extra is not installed")


def _open_custom(page):
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(600)
    page.click("[data-drawer-open='topology-drawer']")
    page.wait_for_timeout(600)
    page.click("#topology-drawer sl-tab[panel='custom']")
    page.wait_for_timeout(500)
    _settle(page)


def _settle(page, limit_ms=60000):
    """Wait out the resolve in flight: htmx drops events while one is."""
    page.wait_for_function(
        "() => !document.getElementById('plan-form').classList.contains('htmx-request')",
        timeout=limit_ms)
    page.wait_for_timeout(700)


def _pick(page, group: str, value: str):
    page.locator(f"#topology-drawer input[name='{group}'][value='{value}']").click()
    page.wait_for_timeout(700)
    _settle(page)


def _checked(page, group: str) -> str:
    return page.evaluate(
        f"""() => {{ const e = document.querySelector(
                 "input[name='{group}']:checked"); return e ? e.value : ''; }}""")


def _card_selected(page, group: str, value: str) -> bool:
    """The card the operator sees as chosen, not just the radio's value."""
    return page.evaluate(
        f"""() => {{ const e = document.querySelector(
                 "input[name='{group}'][value='{value}']");
                 return !!e && e.checked && !!e.closest('label.pick'); }}""")


def _summary(page) -> str:
    el = page.query_selector(".config-id")
    return el.inner_text().strip() if el else ""


def test_choosing_aerial_selects_the_dgx_spark_card(catalogue_page) -> None:
    page = catalogue_page
    _open_custom(page)
    _pick(page, "l1_backend", "Aerial-cuBB")
    assert _checked(page, "server") == "DGX-Spark"
    assert _card_selected(page, "server", "DGX-Spark")
    assert _summary(page).endswith("_dgxspark")


def test_choosing_the_dgx_spark_selects_the_aerial_card(catalogue_page) -> None:
    page = catalogue_page
    _open_custom(page)
    _pick(page, "server", "DGX-Spark")
    assert _checked(page, "l1_backend") == "Aerial-cuBB"
    assert _card_selected(page, "l1_backend", "Aerial-cuBB")
    assert _summary(page).endswith("_dgxspark")


def test_choosing_software_phy_selects_joule(catalogue_page) -> None:
    page = catalogue_page
    _open_custom(page)
    _pick(page, "server", "DGX-Spark")
    _pick(page, "l1_backend", "software-PHY")
    assert _checked(page, "server") == "joule"
    assert _card_selected(page, "server", "joule")
    assert _summary(page).endswith("_joule")


def test_choosing_joule_selects_software_phy(catalogue_page) -> None:
    page = catalogue_page
    _open_custom(page)
    _pick(page, "l1_backend", "Aerial-cuBB")
    _pick(page, "server", "joule")
    assert _checked(page, "l1_backend") == "software-PHY"
    assert _card_selected(page, "l1_backend", "software-PHY")
    assert _summary(page).endswith("_joule")


def test_changing_the_topology_keeps_the_backend_and_the_o_cloud(catalogue_page) -> None:
    page = catalogue_page
    _open_custom(page)
    _pick(page, "l1_backend", "Aerial-cuBB")
    _pick(page, "gnb_stack", "OAI")
    assert _checked(page, "l1_backend") == "Aerial-cuBB"
    assert _checked(page, "server") == "DGX-Spark"
    assert _summary(page).startswith("oai-mono_aerial")


def test_the_dialog_names_the_id_and_the_o_cloud_the_cards_show(catalogue_page) -> None:
    """What RUN offers to start is what the form shows."""
    page = catalogue_page
    _open_custom(page)
    _pick(page, "l1_backend", "Aerial-cuBB")
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    _settle(page)
    shown = _summary(page)
    page.click(".topbar #run-button button")
    page.wait_for_selector("sl-dialog.confirm-dialog", timeout=60000)
    page.wait_for_timeout(1500)
    dialog = page.inner_text("sl-dialog.confirm-dialog")
    assert shown in dialog
    assert "O-Cloud · DGX-Spark" in dialog
