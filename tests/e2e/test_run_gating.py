"""RUN and Deploy RAN are offered only for a plan ETHOS has judged.

Since the readiness checks were taken off the click's path they arrive after
the plan does, which opens a window the buttons have to survive: between the
click and the answer the page is showing a new plan and the old verdict. These
tests hold the readiness answer open so that window is observable rather than
a matter of luck, and read the buttons the operator would press.

The server refuses as well, and the two are not the same gate:

* `POST /plan/run` and `POST /plan/deploy` rebuild with the checks and read
  the verdict: `can_run` and `can_deploy_ran` are re-checked there and answer
  409 when they fail. That is what makes a stale page harmless.
* `POST /plan/start` re-runs the checks and then **ignores them**. It builds
  with readiness, paying the seconds that costs, but gates only on three
  things: the `config_id` still matching the one the dialog showed (409), the
  core still matching (409), and a preview token being present (422). It
  never reads `can_run`. What actually protects the start is ETHOS: the token
  is bound to the testbed state it was read against, so a state that has
  moved comes back 412.

  So on the start path the readiness gate is `/plan/run` plus ETHOS's token,
  never the button and never `/plan/start` itself. Recorded here rather than
  changed: adding a `can_run` gate to the start path is a behaviour change on
  the one route that starts a job, and ETHOS's 412 already covers the case it
  would catch.
"""

from __future__ import annotations

import time

import pytest

SPARK = "OCUDU mono · DGX Spark"

STATE = """() => {
  const find = t => [...document.querySelectorAll('button')]
      .find(b => b.innerText.trim() === t);
  const run = find('RUN'), deploy = find('Deploy RAN');
  return {run: run ? (run.disabled ? 'disabled' : 'enabled') : 'absent',
          deploy: deploy ? (deploy.disabled ? 'disabled' : 'enabled') : 'absent'};
}"""


def _settle(page, limit_s: float = 30.0) -> None:
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        page.wait_for_timeout(100)
        if "htmx-request" not in page.eval_on_selector("#plan-form", "e => e.className"):
            return
    raise AssertionError("the plan form never finished resolving")


def _block_readiness(page):
    """Withhold the readiness answer, and count the times it was asked for.

    Not a slow response: a sync route handler that sleeps blocks the test
    thread with it, so the window would be shut again before it could be
    read. A refused request leaves the page exactly as it looks while the
    checks are still running, because the panel swaps nothing until one
    arrives.
    """
    asked: list[str] = []

    def block(route):
        asked.append(route.request.url)
        route.abort()

    page.route("**/plan/readiness", block)
    return asked


def _ready(page) -> None:
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(600)
    _settle(page)


def _apply(page, label: str) -> None:
    page.click("[data-drawer-open='topology-drawer']")
    page.wait_for_timeout(600)
    page.click("#topology-drawer sl-tab[panel='presets']")
    page.wait_for_timeout(400)
    names = page.eval_on_selector_all(
        "#topology-drawer .preset .preset-name",
        "els => els.map(e => e.innerText.trim().split('\\n')[0])",
    )
    assert label in names, f"{label} is not offered: {names}"
    page.locator("#topology-drawer [data-preset]").nth(names.index(label)).click()
    page.wait_for_timeout(300)
    _settle(page)


def _wait_enabled(page, which: str, timeout_ms: int = 25000) -> None:
    page.wait_for_function(
        """which => {
             const b = [...document.querySelectorAll('button')]
                 .find(x => x.innerText.trim() === which);
             return b && !b.disabled;
           }""",
        arg=which, timeout=timeout_ms)


def test_run_is_not_offered_until_the_checks_have_answered(catalogue_page):
    page = catalogue_page
    asked = _block_readiness(page)
    page.goto("/plan")
    page.wait_for_selector("#plan-form")
    page.wait_for_function("() => !!customElements.get('sl-tab-group')")
    page.wait_for_timeout(1500)
    assert asked, "the panel never asked for the checks"
    assert page.evaluate(STATE)["run"] == "disabled"

    page.unroute("**/plan/readiness")
    _apply(page, "OCUDU monolithic")
    _wait_enabled(page, "RUN")


def test_a_click_puts_run_back_to_being_checked(catalogue_page):
    """The window this opens, and the one thing that must not happen in it.

    The resolve lands first and the checks follow, so for a moment the page
    shows a plan nothing has judged. RUN must not carry the previous plan's
    verdict across that moment: it is a different config_id.
    """
    page = catalogue_page
    _ready(page)
    _wait_enabled(page, "RUN")
    before = page.inner_text(".topo-facts .config-id")

    asked = _block_readiness(page)
    _apply(page, SPARK)
    page.wait_for_function(
        "was => document.querySelector('.topo-facts .config-id')"
        ".innerText.trim() !== was", arg=before, timeout=20000)
    after = page.inner_text(".topo-facts .config-id")
    assert after.endswith("dgxspark"), after
    assert page.evaluate(STATE)["run"] == "disabled", (
        "RUN carried the previous plan's verdict onto a new config_id")

    # The panel asks again on its own, and while that answer is withheld RUN
    # stays where the resolve put it rather than drifting back.
    page.wait_for_timeout(1500)
    assert asked, "the readiness panel never asked again after the click"
    assert page.evaluate(STATE)["run"] == "disabled"

    page.unroute("**/plan/readiness")
    _apply(page, SPARK)
    _wait_enabled(page, "RUN")


def test_deploy_ran_waits_for_the_checks_too(catalogue_page):
    """Deploy RAN takes the Spark's lease, so an unjudged plan must not offer
    it either. Its gate is the same one, read from the same checks."""
    page = catalogue_page
    _ready(page)
    _wait_enabled(page, "RUN")

    _block_readiness(page)
    _apply(page, SPARK)
    page.wait_for_timeout(1200)
    state = page.evaluate(STATE)
    assert state["run"] == "disabled"
    assert state["deploy"] in ("disabled", "absent"), state

    page.unroute("**/plan/readiness")
    _apply(page, SPARK)
    _wait_enabled(page, "Deploy RAN")
    assert page.evaluate(STATE)["deploy"] == "enabled"


def test_the_panel_keeps_asking_after_every_change(catalogue_page):
    """The answer replaces the panel, so the element that asks has to be a
    different one: a panel that replaced itself would ask exactly once, and
    RUN would still be judging the plan the page was opened with."""
    page = catalogue_page
    _ready(page)
    _wait_enabled(page, "RUN")

    asks: list[str] = []
    page.on("request", lambda r: asks.append(r.url) if "/plan/readiness" in r.url else None)
    for label in ("OCUDU monolithic", SPARK, "OAI monolithic"):
        _apply(page, label)
        page.wait_for_timeout(1500)
    assert len(asks) >= 3, f"the panel asked {len(asks)} time(s) for three changes"

    assert page.eval_on_selector(
        "#readiness-ask", "e => e.getAttribute('hx-trigger')"), \
        "the asking element lost its trigger"
