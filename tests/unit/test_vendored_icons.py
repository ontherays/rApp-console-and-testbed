"""Every icon the console names must be vendored.

The icon set is trimmed to what is used (docs/vendor-versions.md), so naming a
new one is a two-step change: put it in the template, and copy the SVG in. A
missing icon renders as empty space and logs a 404 — it looks like a styling
slip and is a missing file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
ICONS = ROOT / "console" / "static" / "vendor" / "shoelace" / "cdn" / "assets" / "icons"

# name="check2" and name="{{ 'a' if x else 'b' }}" both name an icon.
TEMPLATE_ICON = re.compile(r'<sl-icon[^>]*\bname="([^"]+)"')
QUOTED = re.compile(r"'([a-z0-9-]+)'")
# icon="x", "icon": "x", note_icon="x", and Item("Label", "/href", "x") in nav.py
PYTHON_ICON = re.compile(r'(?:icon|note_icon)"?\s*[=:]\s*"([a-z0-9-]+)"')
NAV_ITEM = re.compile(r'Item\(\s*"[^"]+",\s*"[^"]+",\s*"([a-z0-9-]+)"')
# chip('text', 'tone', 'icon') and tile('icon', 'tone') name one positionally.
MACRO_ICON = re.compile(r"\b(?:chip|tile)\(\s*'[^']*'\s*,\s*'[^']*'\s*,\s*'([a-z0-9-]+)'")
MACRO_TILE = re.compile(r"\btile\(\s*'([a-z0-9-]+)'")


def vendored() -> set[str]:
    return {path.stem for path in ICONS.glob("*.svg")}


def named() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "console" / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for value in TEMPLATE_ICON.findall(text):
            if "{{" in value:
                found |= set(QUOTED.findall(value))   # an inline conditional
            else:
                found.add(value)
        found |= set(MACRO_ICON.findall(text))
        found |= set(MACRO_TILE.findall(text))
    for path in (ROOT / "console").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found |= set(PYTHON_ICON.findall(text))
        found |= set(NAV_ITEM.findall(text))
    return {icon for icon in found if re.fullmatch(r"[a-z0-9-]+", icon)}


def test_the_icons_folder_exists_and_is_trimmed():
    have = vendored()
    assert have, "no icons are vendored"
    assert len(have) < 200, (
        "the full Shoelace set is 2052 icons; it is trimmed on purpose"
    )


@pytest.mark.parametrize("icon", sorted(named()))
def test_every_named_icon_is_vendored(icon):
    assert icon in vendored(), (
        f"{icon}.svg is named by the console but not vendored — copy it into "
        f"{ICONS.relative_to(ROOT)} and record it in docs/vendor-versions.md"
    )


def test_no_icon_is_vendored_that_nothing_names():
    """Keeps the trim honest: an icon nobody names is dead weight in the repo."""
    unused = vendored() - named()
    assert not unused, f"vendored but never named: {sorted(unused)}"
