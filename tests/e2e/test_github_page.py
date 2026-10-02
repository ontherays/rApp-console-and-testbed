"""The GitHub page in a real browser.

The server-side suite checks what the page renders. What it cannot check is
that the controls still work after this pass swapped Shoelace's `sl-button` for
the console's own `.btn`, which every other page uses: whether htmx fires from a
plain `<button>` is a browser question, and a rendered-HTML assertion would pass
either way.

It also watches the two things a density pass is most likely to break: content
clipped off the side, and a layout that only works at one width.
"""

from __future__ import annotations

PAGE = "/publication"


def test_the_actions_still_drive_ethos(logged_in):
    """Check GitHub, Verify and a publish preview, clicked rather than posted."""
    page = logged_in
    page.goto(PAGE)
    page.wait_for_load_state("networkidle")
    assert "Not asked" in page.content(), "the remote starts unchecked"

    page.click("text=Check GitHub")
    page.wait_for_timeout(1200)
    assert "In sync" in page.content()
    assert "origin/main" in page.content()

    page.click("text=Verify")
    page.wait_for_timeout(1200)
    assert "Verification" in page.content()

    page.click("text=Publish + Push")
    page.wait_for_timeout(1200)
    assert "Publish and push?" in page.content(), "the preview gate still opens"

    real = [e for e in page.console_errors if "favicon" not in e.lower()]
    assert real == [], real


def test_the_page_does_not_scroll_sideways_at_either_width(logged_in):
    """A density pass that overflows horizontally has made things worse."""
    page = logged_in
    page.goto(PAGE)
    page.wait_for_load_state("networkidle")

    for width in (1400, 700):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(400)
        scroll = page.evaluate("() => document.documentElement.scrollWidth")
        client = page.evaluate("() => document.documentElement.clientWidth")
        assert scroll <= client, f"horizontal overflow at {width}px: {scroll} > {client}"


def test_the_actions_sit_above_the_status(logged_in):
    """What an operator can do comes before what there is, on a page they open
    in order to publish."""
    page = logged_in
    page.goto(PAGE)
    page.wait_for_load_state("networkidle")

    actions = page.locator("text=Publish + Push").first.bounding_box()
    artifacts = page.locator("text=Artifacts").first.bounding_box()
    assert actions and artifacts
    assert actions["y"] < artifacts["y"]
