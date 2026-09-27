"""The console's own icon set.

One sprite, inlined into every page. A name that has no symbol renders as empty
space and logs nothing, so it has to be caught here: the check runs both ways,
so a template cannot name an icon that was never drawn, and a symbol nobody uses
cannot sit in the sprite unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SPRITE = ROOT / "console" / "templates" / "components" / "sprite.html"
DOC = ROOT / "docs" / "design" / "icons.md"

SYMBOL = re.compile(r'<symbol id="icon-([a-z0-9-]+)"')
USE = re.compile(r'<use href="#icon-([a-z0-9-]+)"')
JINJA_USE = re.compile(r'\bic\(\s*[\'"]([a-z0-9-]+)[\'"]')
# pick_group('name', 'icon', ...) and chip('text', 'tone', 'icon') name one
# positionally; so does a macro default, icon='plus'.
PICK_GROUP = re.compile(r"pick_group\(\s*'[^']*'\s*,\s*'([a-z0-9-]+)'")
CHIP_ICON = re.compile(r"\bchip\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'([a-z0-9-]+)'")
TILE_ICON = re.compile(r"\btile\(\s*'([a-z0-9-]+)'")
MACRO_DEFAULT = re.compile(r"icon='([a-z0-9-]+)'")
RADIO_ICON = re.compile(r"'[^']*'\s*,\s*''\s*,\s*'([a-z0-9-]+)'\)")
# Node("ue", ...) in topology.py names the element it draws.
NODE_ICON = re.compile(r'Node\(\s*"([a-z0-9-]+)"')
PY_ICON = re.compile(r'(?:icon|note_icon)"?\s*[=:]\s*"([a-z0-9-]+)"')
NAV_ITEM = re.compile(r'Item\(\s*"[^"]+",\s*"[^"]+",\s*"([a-z0-9-]+)"')


def drawn() -> set[str]:
    return set(SYMBOL.findall(SPRITE.read_text(encoding="utf-8")))


def named() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "console" / "templates").rglob("*.html"):
        if path == SPRITE:
            continue
        text = path.read_text(encoding="utf-8")
        found |= set(USE.findall(text))
        found |= set(JINJA_USE.findall(text))
        found |= set(PICK_GROUP.findall(text))
        found |= set(CHIP_ICON.findall(text))
        found |= set(TILE_ICON.findall(text))
        found |= set(MACRO_DEFAULT.findall(text))
        found |= set(RADIO_ICON.findall(text))
    for path in (ROOT / "console").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found |= set(PY_ICON.findall(text))
        found |= set(NAV_ITEM.findall(text))
        found |= set(NODE_ICON.findall(text))
    # `{% block page_icon %}overview{% endblock %}` names the fallback
    found |= set(
        re.findall(r"#icon-\{%\s*block page_icon\s*%\}([a-z0-9-]+)",
                   (ROOT / "console" / "templates" / "base.html").read_text())
    )
    return found


def test_the_sprite_holds_the_ran_elements_the_diagrams_need():
    for name in ("ue", "ru", "du", "cu", "gnb", "core", "server", "l1"):
        assert name in drawn(), f"the topology diagram needs icon-{name}"


def test_the_sprite_holds_the_traffic_and_state_icons():
    for name in ("dl", "ul", "rate", "duration", "repeats", "iperf", "lock", "readiness"):
        assert name in drawn()


@pytest.mark.parametrize("icon", sorted(named()))
def test_every_named_icon_is_drawn(icon):
    assert icon in drawn(), (
        f"icon-{icon} is named but has no <symbol> in sprite.html"
    )


def test_no_symbol_is_drawn_that_nothing_names():
    unused = drawn() - named()
    assert not unused, f"drawn but never used: {sorted(unused)}"


def test_every_symbol_is_on_the_24_grid_with_the_same_stroke():
    """One grid and one stroke width is what makes a set look like a set."""
    text = SPRITE.read_text(encoding="utf-8")
    blocks = re.findall(r'<symbol id="icon-[a-z0-9-]+"(.*?)</symbol>', text, re.S)
    assert blocks
    for block in blocks:
        assert 'viewBox="0 0 24 24"' in block
        assert 'stroke="currentColor"' in block
        assert 'stroke-linecap="round"' in block and 'stroke-linejoin="round"' in block
        width = re.search(r'stroke-width="([\d.]+)"', block)
        assert width and 1.5 <= float(width.group(1)) <= 1.8


def test_nothing_hardcodes_a_colour():
    """An icon must take the colour of the text around it."""
    text = SPRITE.read_text(encoding="utf-8")
    assert not re.search(r'(?:stroke|fill)="#', text)


def test_every_icon_is_documented_with_a_preview():
    listed = set(re.findall(r"#icon-([a-z0-9-]+)", DOC.read_text(encoding="utf-8")))
    assert drawn() - listed == set(), "every icon needs a row in docs/design/icons.md"
