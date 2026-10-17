"""The diagram's text, measured as the browser painted it.

An element box is not what the reader sees. A caption that wrapped has its
lines in tspans, a `<title>` carries a tooltip that is never drawn, and a
diagram scaled down to fit its column still reports the box it asked for.
So these read Range rects over the text nodes themselves, and compare the
painted width of each run against the font size its element declares.

Two things a reader cannot work around:

* two runs painted over one another, and
* a diagram shrunk to fit, which takes its type down with it.

Both were true of the Aerial path before this work. At 007b0b2, for the
selection `ocudu-mono_aerial_pega_samsung_o5gs_dgxspark`, "Pegatron, 7.2x
via CX7 and OcNOS" was painted across "cuPHY, FAPI over nvIPC" by 1.8px at
1440, 2.6px at 1280 and 2.7px at both 1024 and 768; and the chain was drawn
at 0.70 scale, putting five runs of 10 to 11px type on the page at about
3.5px per character.
"""

from __future__ import annotations

import time

import pytest

#: Every painted run of glyphs in the full-size diagram, with the element it
#: belongs to. The two lines of one wrapped caption share an owner and are
#: never each other's overlap; a `<title>` is not painted at all.
MEASURE = """() => {
  const svg = document.querySelector('.topo:not(.mini)');
  if (!svg) return {error: 'no diagram'};
  const owners = [...svg.querySelectorAll('text')];
  const runs = [];
  const walk = document.createTreeWalker(svg, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const node = walk.currentNode;
    if (!node.data.trim()) continue;
    if (node.parentElement.closest('title')) continue;
    const owner = node.parentElement.closest('text');
    if (!owner) continue;
    const range = document.createRange();
    range.selectNode(node);
    for (const rect of range.getClientRects()) {
      if (!rect.width || !rect.height) continue;
      runs.push({text: node.data.trim(), owner: owners.indexOf(owner),
                 size: parseFloat(getComputedStyle(owner).fontSize),
                 left: rect.left, right: rect.right,
                 top: rect.top, bottom: rect.bottom, width: rect.width});
    }
  }
  const clashes = [];
  for (let i = 0; i < runs.length; i++)
    for (let j = i + 1; j < runs.length; j++) {
      const a = runs[i], b = runs[j];
      if (a.owner === b.owner) continue;
      if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom)
        clashes.push(a.text + ' over ' + b.text + ' by ' +
                     (Math.min(a.right, b.right) - Math.max(a.left, b.left)).toFixed(1) + 'px');
    }
  // Painted at the size it asks for? The floor is generous: a proportional
  // font averages well above 0.40em, so anything under that is a diagram
  // that has been scaled, not a narrow word.
  const shrunk = runs.filter(r => r.width / r.text.length < r.size * 0.40)
                     .map(r => r.text.slice(0, 30) + ' at ' +
                               (r.width / r.text.length).toFixed(2) + 'px/char, ' +
                               r.size + 'px declared');
  const ctm = svg.getScreenCTM();
  return {runs: runs.length, clashes, shrunk, scale: ctm ? +ctm.a.toFixed(3) : null};
}"""


def _settle(page, limit_s: float = 60.0) -> None:
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        page.wait_for_timeout(150)
        if "htmx-request" not in page.eval_on_selector("#plan-form", "e => e.className"):
            return
    raise AssertionError("the plan form never finished resolving")


def _choose_aerial(page) -> None:
    """Pick the Aerial L1 from the Custom tab, which is where every version
    of the page offers it, and wait for the id that proves it landed."""
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(800)
    _settle(page)
    page.click("[data-drawer-open='topology-drawer']")
    page.wait_for_timeout(700)
    page.click("#topology-drawer sl-tab[panel='custom']")
    page.wait_for_timeout(500)
    page.locator("#topology-drawer input[name='l1_backend'][value='Aerial-cuBB']").click()
    page.wait_for_function(
        "() => { const e = document.querySelector('.config-id');"
        " return e && e.innerText.includes('dgxspark'); }", timeout=60000)
    page.wait_for_timeout(1200)


@pytest.mark.parametrize("width", [1440, 1280, 1024, 768])
def test_the_aerial_diagram_paints_no_text_over_other_text(catalogue_page, width):
    page = catalogue_page
    page.set_viewport_size({"width": width, "height": 1000})
    _choose_aerial(page)
    out = page.evaluate(MEASURE)
    assert out.get("runs", 0) >= 8, out
    assert out["clashes"] == [], f"{width}px: " + "; ".join(out["clashes"])


def test_the_aerial_diagram_is_drawn_at_the_size_it_asks_for(catalogue_page):
    """Shrink-to-fit is the other way the captions became unreadable: the
    chain was scaled into its column, so 10px type was painted at 7."""
    page = catalogue_page
    page.set_viewport_size({"width": 1440, "height": 1000})
    _choose_aerial(page)
    out = page.evaluate(MEASURE)
    assert out["shrunk"] == [], "; ".join(out["shrunk"])
    assert out["scale"] == pytest.approx(1.0, abs=0.02), out["scale"]


#: The ten profiles the picker offers, as its cards name them.
PROFILES = [
    "OCUDU monolithic", "OAI monolithic", "OCUDU CU + OCUDU DU",
    "OAI CU + OAI DU", "OCUDU CU + OAI DU", "OAI CU + OCUDU DU",
    "OAI mono · DGX Spark", "OAI F1 · DGX Spark",
    "OCUDU mono · DGX Spark", "OCUDU F1 · DGX Spark",
]

#: What the diagram occupies, against what it was given, and whether every
#: box and link reached its maximum (the one case where using less is right).
FILL = """() => {
  const svg = document.querySelector('.topo:not(.mini)');
  const scroll = document.querySelector('.topo-scroll');
  if (!svg || !scroll) return {error: 'no diagram'};
  const s = getComputedStyle(scroll);
  const avail = scroll.clientWidth
      - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
  const used = svg.getBoundingClientRect().width;
  const boxes = [...svg.querySelectorAll('g > rect')]
      .map(r => parseFloat(r.getAttribute('width')) + 1.5);
  const links = [...svg.querySelectorAll('rect[height="16"]')]
      .map(r => parseFloat(r.getAttribute('width')));
  return {avail: Math.round(avail), used: Math.round(used),
          pct: used / avail, boxes, links,
          pageScrolls: document.documentElement.scrollWidth
                     > document.documentElement.clientWidth};
}"""

#: From console.topology. Repeated rather than imported so the test states
#: the contract it is checking instead of agreeing with the code by
#: construction.
BOX_MAX = 150
LINK_MAX = 140


def _apply_preset(page, label: str) -> None:
    page.click("[data-drawer-open='topology-drawer']")
    page.wait_for_timeout(500)
    page.click("#topology-drawer sl-tab[panel='presets']")
    page.wait_for_timeout(300)
    names = page.eval_on_selector_all(
        "#topology-drawer .preset .preset-name",
        "els => els.map(e => e.innerText.trim().split('\\n')[0])",
    )
    assert label in names, f"{label} is not offered: {names}"
    page.locator("#topology-drawer [data-preset]").nth(names.index(label)).click()
    page.wait_for_timeout(1200)
    _settle(page)


@pytest.mark.parametrize("width", [1440, 1280])
def test_every_profile_fills_the_card_it_is_given(catalogue_page, width):
    """The diagram uses the card, whatever the node count.

    Four nodes used to stop halfway across while six filled it, because every
    box was the same fixed width. The row shares one width out now, so the
    only way to use less is for every box AND every link to have reached its
    maximum, which is the one case where spreading further would just make
    the boxes silly. Then it is centred instead.
    """
    page = catalogue_page
    page.set_viewport_size({"width": width, "height": 1100})
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(800)
    _settle(page)

    thin = []
    for profile in PROFILES:
        _apply_preset(page, profile)
        got = page.evaluate(FILL)
        assert "error" not in got, (profile, got)
        at_maximum = (
            all(box >= BOX_MAX - 0.5 for box in got["boxes"])
            and all(link >= LINK_MAX - 0.5 for link in got["links"])
        )
        if got["pct"] < 0.75 and not at_maximum:
            thin.append(f"{width}px {profile}: {got['used']} of {got['avail']} "
                        f"({got['pct']:.0%}), boxes "
                        f"{min(got['boxes']):.0f}-{max(got['boxes']):.0f}")
    assert thin == [], "; ".join(thin)


@pytest.mark.parametrize("width", [1440, 1280, 1024])
def test_no_profile_makes_the_page_scroll_sideways(catalogue_page, width):
    """At 1024 and wider the whole chain fits. Narrower, it scrolls inside
    the card, which is what `.topo-scroll` is for."""
    page = catalogue_page
    page.set_viewport_size({"width": width, "height": 1100})
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(800)
    _settle(page)

    for profile in ("OCUDU monolithic", "OCUDU F1 · DGX Spark"):
        _apply_preset(page, profile)
        got = page.evaluate(FILL)
        assert not got["pageScrolls"], f"{width}px {profile} scrolls the page"
