"""The plan page under a real browser: presets, pace, and the status strip.

Everything here goes through what the operator touches. A preset is clicked,
not posted; the pace is measured from the click to the config_id changing on
screen, which is the whole of what is waited for; and the overlap check reads
the bounding boxes the browser actually laid out, because an SVG that is
correct in the markup can still be unreadable on the page.
"""

from __future__ import annotations

import time

import pytest

#: Every preset the picker offers, and the head each one must resolve to.
#: Both halves of the Spark set, mono and split, and their joule counterparts.
PRESETS = [
    ("OCUDU monolithic", "ocudu-mono_swphy", "joule"),
    ("OAI monolithic", "oai-mono_swphy", "joule"),
    ("OCUDU CU + OCUDU DU", "ocudu-cudu_swphy", "joule"),
    ("OAI CU + OAI DU", "oai-cudu_swphy", "joule"),
    ("OCUDU CU + OAI DU", "ocuducu-oaidu_swphy", "joule"),
    ("OAI CU + OCUDU DU", "oaicu-ocududu_swphy", "joule"),
    ("OAI mono · DGX Spark", "oai-mono_aerial", "dgxspark"),
    ("OAI F1 · DGX Spark", "oai-cudu_aerial", "dgxspark"),
    ("OCUDU mono · DGX Spark", "ocudu-mono_aerial", "dgxspark"),
    ("OCUDU F1 · DGX Spark", "ocudu-cudu_aerial", "dgxspark"),
]

WIDTHS = (1440, 1280, 1024, 768)


def _settle(page, limit_s: float = 30.0) -> None:
    """Wait until no resolve is in flight."""
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        page.wait_for_timeout(100)
        if "htmx-request" not in page.eval_on_selector("#plan-form", "e => e.className"):
            return
    raise AssertionError("the plan form never finished resolving")


def _ready(page) -> None:
    """Load the plan page and wait for it to be usable.

    The opener calls `drawer.show()`, which exists only once Shoelace has
    upgraded, and the first resolve fires on load.
    """
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(600)
    _settle(page)


def _open_picker(page) -> list[str]:
    """Open the drawer on its Presets tab and list what it offers.

    A Shoelace tab panel is hidden until its tab is selected, so the cards
    cannot be clicked before this.
    """
    page.click("[data-drawer-open='topology-drawer']")
    page.wait_for_timeout(600)
    page.click("#topology-drawer sl-tab[panel='presets']")
    page.wait_for_timeout(400)
    return page.eval_on_selector_all(
        "#topology-drawer .preset .preset-name",
        "els => els.map(e => e.innerText.trim().split('\\n')[0])",
    )


def _apply(page, label: str) -> None:
    """Click one preset card the way an operator does. The card closes the
    drawer behind it, so each call opens it again."""
    names = _open_picker(page)
    assert label in names, f"{label} is not offered: {names}"
    page.locator("#topology-drawer [data-preset]").nth(names.index(label)).click()
    page.wait_for_timeout(400)
    _settle(page)


def _config_id(page) -> str:
    return page.eval_on_selector(".topo-facts .config-id", "e => e.innerText.trim()")


@pytest.mark.parametrize("label, head, server", PRESETS,
                         ids=[p[0] for p in PRESETS])
def test_a_preset_fills_the_form_and_resolves_to_its_own_config_id(
    catalogue_page, label, head, server
):
    """Clicking a card must move the form, not just the picture.

    The Spark presets carry an L1 backend and an O-Cloud as well as the stack
    and the split, so the test reads the id ETHOS generated: it names both,
    and it is the one thing on the page the console cannot have invented.
    """
    page = catalogue_page
    _ready(page)
    _apply(page, label)

    resolved = _config_id(page)
    assert resolved.startswith(head), resolved
    assert resolved.endswith(server), resolved
    if server == "dgxspark":
        assert page.eval_on_selector(
            "input[name='server']:checked", "e => e.value") == "DGX-Spark"
        assert page.eval_on_selector(
            "input[name='l1_backend']:checked", "e => e.value") == "Aerial-cuBB"


def test_two_quick_clicks_end_on_the_second_ones_result(catalogue_page):
    """The form replaces an in-flight resolve rather than racing it.

    Without `hx-sync`, the slower of two overlapping resolves lands last and
    the page ends up showing the topology the operator clicked away from.
    """
    page = catalogue_page
    _ready(page)
    _apply(page, "OCUDU monolithic")

    # Both clicks in one open drawer, closer together than the 150ms debounce.
    _open_picker(page)
    page.click("#topology-drawer sl-tab[panel='custom']")
    page.wait_for_timeout(400)
    page.locator("#topology-drawer input[name='gnb_stack'][value='OAI']").click()
    page.wait_for_timeout(60)
    page.locator("#topology-drawer input[name='gnb_stack'][value='OCUDU']").click()
    _settle(page)
    page.wait_for_timeout(600)

    assert _config_id(page).startswith("ocudu-mono"), _config_id(page)
    assert page.eval_on_selector(
        "input[name='gnb_stack']:checked", "e => e.value") == "OCUDU"


def test_the_page_does_not_say_it_is_updating_while_it_is_idle(catalogue_page):
    """"updating..." means the operator's own change, not a background poll.

    Three panels inside the form poll on their own timers (the O-Cloud cards
    every 8s, readiness every 20s, and the strip above them every 5s), and
    htmx inherits `hx-indicator` down the tree, so every one of those lit the
    header while the operator sat still: measured at 22 of 35 samples over a
    quiet 70 seconds. A spinner that is on more often than off says nothing.
    """
    page = catalogue_page
    _ready(page)

    # Watched, not sampled. Against the recorded ETHOS a poll answers in
    # milliseconds, so polling the DOM every second would step straight over
    # the flashes; htmx adds and removes the class, and the observer sees
    # every one of them however brief.
    page.evaluate("""() => {
      window._lit = [];
      const el = document.getElementById('plan-updating');
      new MutationObserver(() => {
        if (el.classList.contains('htmx-request'))
          window._lit.push([...document.querySelectorAll('.htmx-request')]
            .map(e => e.id || e.tagName).join(','));
      }).observe(el, {attributes: true, attributeFilter: ['class']});
    }""")
    page.wait_for_timeout(26000)      # at least three rounds of every poll
    lit = page.evaluate("() => window._lit")
    assert lit == [], f"the indicator lit {len(lit)} time(s) while idle: {lit[:4]}"


def test_the_page_says_it_is_updating_and_stops_saying_it(catalogue_page):
    """The indicator is the whole of the feedback a click gets, so it has to
    appear while the resolve is in flight and clear when it lands."""
    page = catalogue_page
    _ready(page)
    assert not page.is_visible("#plan-updating")

    _open_picker(page)
    page.click("#topology-drawer sl-tab[panel='custom']")
    page.wait_for_timeout(400)
    page.locator("#topology-drawer input[name='gnb_stack'][value='OAI']").click()
    page.wait_for_selector("#plan-updating", state="visible", timeout=10000)
    _settle(page)
    page.wait_for_selector("#plan-updating", state="hidden", timeout=10000)


def test_the_topology_card_names_the_o_cloud_it_read(catalogue_page):
    """The strip over the diagram follows the selected O-Cloud.

    It is read live and the diagram is not, so the two are drawn separately;
    this is what keeps them talking about the same machine.
    """
    page = catalogue_page
    _ready(page)
    _apply(page, "OCUDU monolithic")
    page.wait_for_function(
        "() => document.querySelector('#topo-cloud-live')"
        ".innerText.includes('joule')", timeout=20000)

    _apply(page, "OCUDU mono · DGX Spark")
    page.wait_for_function(
        "() => document.querySelector('#topo-cloud-live')"
        ".innerText.includes('DGX Spark')", timeout=20000)


BOXES = """() => [...document.querySelectorAll('.topo:not(.mini) text')].map(e => {
    const r = e.getBoundingClientRect();
    return {text: e.textContent.trim(), left: r.left, right: r.right,
            top: r.top, bottom: r.bottom};
})"""


@pytest.mark.parametrize("width", WIDTHS)
def test_no_two_labels_in_the_diagram_overlap(catalogue_page, width):
    """Read off the laid-out boxes, for every profile the picker offers.

    Captions sit under boxes and interface names sit on the connectors
    between them, and SVG text neither wraps nor pushes anything aside: if a
    caption is one word too long it is drawn straight over its neighbour. The
    renderer measures and wraps instead, and this is what proves it did.
    """
    page = catalogue_page
    page.set_viewport_size({"width": width, "height": 1000})
    _ready(page)

    clashes = []
    for label, _head, _server in PRESETS:
        _apply(page, label)
        boxes = page.evaluate(BOXES)
        assert len(boxes) >= 10, f"{label}: only {len(boxes)} labels drawn"
        for first in range(len(boxes)):
            for second in range(first + 1, len(boxes)):
                a, b = boxes[first], boxes[second]
                if (a["left"] < b["right"] and b["left"] < a["right"]
                        and a["top"] < b["bottom"] and b["top"] < a["bottom"]):
                    clashes.append(f"{width}px {label}: "
                                   f"{a['text']!r} over {b['text']!r}")
    assert clashes == [], clashes


@pytest.mark.parametrize("width", WIDTHS)
def test_the_page_never_scrolls_sideways(catalogue_page, width):
    """A diagram wider than the card scrolls inside the card, never the page."""
    page = catalogue_page
    page.set_viewport_size({"width": width, "height": 1000})
    _ready(page)
    _apply(page, "OCUDU F1 · DGX Spark")
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= "
        "document.documentElement.clientWidth"
    ), f"the page scrolls sideways at {width}px"
    assert page.evaluate(
        "() => { const s = document.querySelector('.topo-scroll');"
        " return getComputedStyle(s).overflowX; }") == "auto"
