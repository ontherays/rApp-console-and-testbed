"""The core selection, wired to ETHOS's core switching (B18).

The console does not switch anything. It passes the selected core to ETHOS
inside the plan's `config_id`, and reads `GET /core` to say what the host is
doing. Everything here runs against the fake ETHOS, which replays a recorded
`/core` response, so no test reaches a core host (NF-07).

What matters, and what these pin down: a number is only comparable if you know
which core produced it, so a run with no archived status is shown as unknown
and never as the default.
"""

from __future__ import annotations

import pytest

from tests.conftest import RECORDED, run_async

from console import core_setup
from console.rapps.ethos.client import EthosClient
from console.rapps.ethos.metrics import NOT_MEASURED
from console.rapps.ethos.models import CoreState, Run
from tests.fake_ethos import FakeEthos


@pytest.fixture
def fake():
    return FakeEthos(RECORDED)


def _client(fake) -> EthosClient:
    return EthosClient("http://fake-ethos", transport=fake.transport(), status_cache_s=0)


def _core(**overrides) -> CoreState:
    base = {
        "enabled": True,
        "core": "open5gs",
        "selected": "open5gs(default)",
        "agrees": True,
        "disagreement": None,
        "health": {"ok": True, "failing": [], "ngap_peers": ["192.168.8.13:16561"],
                   "summary": "open5gs owns N2, N3 and N4"},
        "profiles": {
            "open5gs": {"name": "open5gs", "display": "Open5GS v2.7.7", "status": "wired",
                        "ue_pool": "10.45.0.0/16", "core_data_ip": "10.45.0.1",
                        "tunnel_iface": "ogstun", "amf_n2": "192.168.8.26:38412",
                        "subscriber_db": "open5gs"},
            "free5gc": {"name": "free5gc", "display": "free5GC v4.2.3", "status": "wired",
                        "ue_pool": "10.60.0.0/16", "core_data_ip": "192.168.8.26",
                        "tunnel_iface": "upfgtp", "amf_n2": "192.168.8.26:38412",
                        "subscriber_db": "free5gc"},
        },
    }
    base.update(overrides)
    return CoreState.model_validate(base)


def _run(core_slug="o5gs", ue="samsung", **fields) -> Run:
    base = {
        "run_id": fields.pop("run_id", "r-1"),
        "config_id": f"ocudu-mono_swphy_pega_{ue}_{core_slug}_joule",
        "direction": "DL",
        "offered_mbps": 100.0,
        "server_owner": "app_binary",
        "duration_requested_s": 10.0,
    }
    base.update(fields)
    return Run.model_validate(base)


# --- the single path: the console passes the core, ETHOS switches ------------

def test_the_console_never_offers_a_way_to_switch_a_core():
    """SE-06: the only file that talks to ETHOS has one core call, and it reads.

    Checked against the calls the client makes, not against its prose: the
    module says the word "core-switch" when explaining why it does not run it.
    """
    import ast
    import inspect

    from console.rapps.ethos import client as client_module

    tree = ast.parse(inspect.getsource(client_module))
    core_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "call"
        and [a for a in node.args if isinstance(a, ast.Constant)
             and str(a.value).startswith("/core")]
    ]
    assert len(core_calls) == 1
    assert core_calls[0].args[0].value == "GET"
    assert core_calls[0].args[1].value == "/core"


def test_no_page_renders_a_control_that_would_move_the_core():
    """A switch button here would be a second thing moving a production core."""
    import pathlib

    templates = pathlib.Path("console/templates")
    for path in templates.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "/core/switch" not in text, path
        assert "sudo core-switch" not in text, path


def test_the_plan_carries_the_core_in_its_selection_and_nothing_else(client):
    """How the choice travels: a selection, a config_id, and ETHOS's job."""
    response = client.post(
        "/plan/resolve",
        data={"core": "free5GC", "ue": "Samsung", "rates": "100", "direction": "DL",
              "duration": "10s", "repeats": "1", "gnb_stack": "OCUDU",
              "gnb_split": "monolithic", "l1_backend": "software-PHY",
              "ru": "Pegatron", "server": "joule", "iperf_server": "app_binary"},
    )
    assert response.status_code == 200
    assert "f5gc" in response.text          # the config_id ETHOS generated
    # the core travels as part of the selection, and the page offers no way to
    # act on the core host itself
    assert "/core/switch" not in response.text


# --- item 2: the live state, and what it stops -------------------------------

def test_the_endpoint_is_read_through_the_client_and_parsed(fake):
    state = run_async(_client(fake).core())
    assert state.core == "open5gs"
    assert state.health.ok is True
    assert state.profiles["free5gc"].ue_pool == "10.60.0.0/16"


def test_a_settled_host_blocks_nothing():
    assert _core().blocker == ""
    assert _core().settled is True


def test_a_half_switched_host_blocks_a_run():
    state = _core(core="open5gs", selected="free5gc",
                  disagreement="core-switch says selected=free5gc but the sockets "
                               "are owned by open5gs")
    assert state.settled is False
    assert "free5gc" in state.blocker and "open5gs" in state.blocker


def test_an_unhealthy_core_blocks_a_run():
    state = _core(health={"ok": False, "failing": ["n3_2152_udp"], "ngap_peers": [],
                          "summary": "open5gs does not own N3"})
    assert "does not own N3" in state.blocker


def test_a_core_that_could_not_be_read_blocks_a_run():
    """Not knowing is not permission. The run would be unattributable."""
    assert "no route to host" in _core(error="ssh: no route to host").blocker


def test_health_that_was_never_reported_blocks_a_run():
    assert "health" in _core(health={"ok": None}).blocker


def test_a_plan_for_the_other_core_is_not_itself_a_blocker():
    """The ordinary case: free5GC planned while the host runs Open5GS.

    ETHOS switches it as part of the job. Refusing here would refuse every
    free5GC run ever started from an Open5GS host.
    """
    assert _core(core="open5gs").blocker == ""


def test_switching_being_off_blocks_nothing_either():
    """The console must behave exactly as before on a testbed with one core."""
    assert CoreState().blocker == ""
    assert CoreState().enabled is False


def test_the_strip_shows_the_core_and_its_peers(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    # the peer comes from the recording, not from here: a gNB reconnects on a
    # new ephemeral port every time, so pinning one would fail on a re-record
    expected = fake._load("status_summary")["core"]["health"]["ngap_peers"]
    status = run_async(build_status(_client(fake), Capabilities()))
    core = next(item for item in status.items if item.label == "Core")
    assert core.state == "ok"
    for peer in expected:
        assert peer in core.detail


def test_the_plan_page_holds_run_back_while_the_host_is_mid_switch(client, ethos_url):
    ethos_url.answer("GET", "/core", 200, {
        **_core(core="open5gs", selected="free5gc",
                disagreement="core-switch says selected=free5gc but the sockets "
                             "are owned by open5gs").model_dump(),
    })
    response = client.get("/plan")
    assert response.status_code == 200
    assert "sockets are owned by open5gs" in response.text


# --- item 4: results carry their core ----------------------------------------

def test_a_run_reports_the_core_read_on_the_host_over_the_one_in_its_name():
    """The config_id says what was asked for; the status says what served it."""
    run = _run(core_slug="o5gs", core_switch={"core": "free5gc"})
    assert run.core == "free5gc"
    assert run.core_confirmed is True


def test_a_run_with_no_archived_status_falls_back_to_its_config_id():
    run = _run(core_slug="f5gc")
    assert run.core == "free5gc"
    assert run.core_confirmed is False      # inferred, and the page says so


def test_a_run_that_names_no_core_at_all_is_unknown_never_open5gs():
    assert Run(run_id="r").core is None
    assert Run(run_id="r").core_label == ""


def test_the_results_table_can_be_filtered_to_one_core():
    from console.rapps.ethos.query import Filters, select

    runs = [_run(core_slug="o5gs", run_id="a"), _run(core_slug="f5gc", run_id="b")]
    page = select(runs, Filters(core="free5gc", usable_only=False))
    assert [run.run_id for run in page.rows] == ["b"]


def test_the_core_is_offered_as_a_filter_only_when_runs_have_one():
    from console.rapps.ethos.query import facets

    assert facets([_run(core_slug="f5gc")])["core"] == ["free5gc"]
    assert facets([Run(run_id="r")])["core"] == []


def test_two_cores_at_equal_everything_else_are_comparable():
    comparison = core_setup.compare_cores(
        [_run(core_slug="o5gs", run_id="a"), _run(core_slug="f5gc", run_id="b")]
    )
    assert comparison.is_cross_core
    assert comparison.comparable
    assert comparison.cores == ["free5gc", "open5gs"]


@pytest.mark.parametrize(
    "field, value, says",
    [
        ("ue", "mtk", "UE"),
        ("direction", "UL", "direction"),
        ("offered_mbps", 200.0, "offered rates"),
        ("server_owner", "ethos", "iperf server"),
        ("duration_requested_s", 30.0, "duration"),
    ],
)
def test_a_second_difference_makes_the_comparison_not_a_core_comparison(
    field, value, says
):
    other = {"ue": "samsung"}
    fields = {}
    if field == "ue":
        other["ue"] = value
    else:
        fields[field] = value
    comparison = core_setup.compare_cores([
        _run(core_slug="o5gs", run_id="a"),
        _run(core_slug="f5gc", run_id="b", ue=other["ue"], **fields),
    ])
    assert not comparison.comparable
    assert any(says in difference for difference in comparison.differences)


def test_a_run_with_no_core_is_on_neither_side():
    comparison = core_setup.compare_cores(
        [_run(core_slug="o5gs"), _run(core_slug="f5gc"), Run(run_id="mystery")]
    )
    assert len(comparison.unknown) == 1
    assert not comparison.comparable       # it could belong to either side


def test_one_core_alone_is_not_a_cross_core_comparison():
    comparison = core_setup.compare_cores([_run(run_id="a"), _run(run_id="b")])
    assert not comparison.is_cross_core
    assert not comparison.comparable


# --- item 5: a warning, never a block ----------------------------------------

def test_another_user_s_activity_warns_and_does_not_block():
    state = _core(activity={
        "checked": True,
        "findings": ["processes on the core host that are not ETHOS's: e2e_receiver:834631"],
    })
    assert state.blocker == ""              # a warning, not a refusal
    assert state.activity.findings


def test_an_unchecked_activity_probe_is_not_an_all_clear():
    state = _core(activity={"checked": False, "reason": "this host does not report it"})
    assert state.activity.checked is False
    assert state.activity.findings == []


def test_the_strip_warns_rather_than_going_red_for_someone_else_s_campaign(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    recorded = fake._load("status_summary")
    recorded["core"]["activity"] = {
        "checked": True,
        "findings": ["the core restarted at 09:00 and no core-switch of ETHOS's explains it"],
        "reason": "",
    }
    fake.answer("GET", "/status/summary", 200, recorded)

    status = run_async(build_status(_client(fake), Capabilities()))
    core = next(item for item in status.items if item.label == "Core")
    assert core.state == "warn"
    assert "no core-switch" in core.detail


# --- a core left behind: warn, never act -------------------------------------

def _stale(**overrides) -> CoreState:
    base = {
        "is_stale": True,
        "reason": ("the core host is still on free5gc and no ETHOS job is running, "
                   "so a campaign was interrupted before it could put open5gs back"),
        "remedy": "sudo core-switch open5gs",
    }
    base.update(overrides)
    return _core(core="free5gc", selected="free5gc", stale=base,
                 health={"ok": True, "failing": [], "ngap_peers": [],
                         "summary": "free5gc owns N2, N3 and N4"})


def test_a_core_left_on_free5gc_is_reported_as_stale():
    state = _stale()
    assert state.stale.is_stale is True
    assert state.stale.remedy == "sudo core-switch open5gs"


def test_a_stale_core_does_not_block_a_run():
    """It is a warning. The host is healthy, just on the wrong core, and the
    campaign about to start will switch it anyway."""
    assert _stale().blocker == ""


def test_a_core_where_it_belongs_is_not_stale():
    assert _core().stale.is_stale is False
    assert _core().stale.reason == ""


def test_the_console_offers_no_way_to_act_on_a_stale_core():
    """The remedy is a command to read, not a button.

    And it is rendered from ETHOS's own `remedy` field rather than written
    into the template: the console does not hold its own idea of what fixes
    the testbed.
    """
    import pathlib

    banner = pathlib.Path("console/templates/components/status_strip.html").read_text()
    assert "core_stale.remedy" in banner        # shown, from the endpoint
    assert "core-switch" not in banner          # not the console's own words
    assert "hx-post" not in banner              # never offered as an action


def test_the_strip_raises_a_banner_for_a_stale_core(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    recorded = fake._load("status_summary")
    recorded["core"] = _stale().model_dump()
    fake.answer("GET", "/status/summary", 200, recorded)

    status = run_async(build_status(_client(fake), Capabilities()))
    assert status.core_stale is not None
    assert "sudo core-switch open5gs" in status.core_stale.remedy
    assert "interrupted" in status.core_stale.reason


def test_the_strip_raises_no_banner_when_the_core_is_fine(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    status = run_async(build_status(_client(fake), Capabilities()))
    assert status.core_stale is None


def test_a_down_ethos_raises_no_stale_banner(fake):
    """One unreachable thing should not produce two alarms about it."""
    from console.capabilities import Capabilities
    from console.status import build_status

    fake.down = True
    status = run_async(build_status(_client(fake), Capabilities()))
    assert status.core_stale is None


def test_the_banner_is_rendered_on_every_page_through_the_strip(client, ethos_url):
    summary = ethos_url._load("status_summary")
    summary["core"] = _stale().model_dump()
    ethos_url.answer("GET", "/status/summary", 200, summary)

    page = client.get("/partials/status")
    assert page.status_code == 200
    assert "sudo core-switch open5gs" in page.text
    assert "interrupted" in page.text


def test_the_page_says_plainly_that_nothing_was_changed(client, ethos_url):
    summary = ethos_url._load("status_summary")
    summary["core"] = _stale().model_dump()
    ethos_url.answer("GET", "/status/summary", 200, summary)

    text = client.get("/partials/status").text
    assert "nothing has been changed" in text.lower()


# --- the job view names the two core stages ----------------------------------

def _step(name, started="2026-10-05T01:00:00Z", ended="", elapsed=None, **kw):
    from console.rapps.ethos.models import JobStep

    body = {"name": name, "state": "done" if ended else "running",
            "started": started, "ended": ended, "detail": kw.pop("detail", "")}
    if elapsed is not None:
        body["elapsed_s"] = elapsed
    return JobStep.model_validate(body)


def test_a_core_stage_gets_a_readable_label_not_a_slug():
    """GL-05: the page shows the label, never the wire word."""
    assert _step("switching_core").label == "switching core"
    assert _step("restoring_core").label == "restoring Open5GS"


def test_the_label_names_the_core_being_switched_to_when_the_detail_says():
    step = _step("switching_core", detail="open5gs -> free5gc; tearing the gNB down first")
    assert step.label == "switching core to free5GC"


def test_an_ordinary_stage_keeps_its_own_name():
    assert _step("deploying").label == "deploying"
    assert _step("tearing_down").label == "tearing down"


def test_a_finished_stage_shows_how_long_it_took():
    step = _step("switching_core", ended="2026-10-05T01:00:16Z", elapsed=16.0)
    assert step.took == "16.0 s"


def test_elapsed_comes_from_ethos_but_is_computed_when_it_is_absent():
    """An older ETHOS does not send elapsed_s. The two stamps are still there."""
    step = _step("restoring_core", started="2026-10-05T01:00:00Z",
                 ended="2026-10-05T01:00:21Z")
    assert step.took == "21.0 s"


def test_a_running_stage_reports_no_duration_rather_than_zero():
    assert _step("switching_core").took == NOT_MEASURED


def test_the_job_page_shows_the_stage_and_its_duration(client, ethos_url):
    job = {
        "job_id": "j-core01", "state": "completed", "source": "api", "plan": {},
        "config_id": "ocudu-mono_swphy_pega_samsung_f5gc_joule",
        "steps": [
            {"name": "switching_core", "state": "done",
             "started": "2026-10-05T01:00:00Z", "ended": "2026-10-05T01:00:16Z",
             "elapsed_s": 16.0, "detail": "open5gs -> free5gc"},
            {"name": "restoring_core", "state": "done",
             "started": "2026-10-05T01:05:00Z", "ended": "2026-10-05T01:05:20Z",
             "elapsed_s": 20.0, "detail": "open5gs"},
        ],
        "points": [], "run_ids": [],
    }
    ethos_url.answer("GET", "/jobs/j-core01", 200, job)

    page = client.get("/jobs/j-core01")
    assert page.status_code == 200
    assert "switching core to free5GC" in page.text
    assert "restoring Open5GS" in page.text
    assert "16.0 s" in page.text and "20.0 s" in page.text


# --- the shape ETHOS sends when it has not read the host ---------------------
#
# Found by running the branch against a real ETHOS with switching disabled,
# which no fixture covered: every recording had a successful status read, so
# `health` and `activity` were never null and the model never had to take one.

DISABLED = {
    "enabled": False, "core": None, "selected": None, "agrees": None,
    "disagreement": None, "health": None, "health_source": None,
    "status": None, "profile": None, "profiles": {}, "activity": None,
    "stale": {"is_stale": False, "reason": "", "remedy": ""}, "error": None,
}


def test_a_core_with_switching_disabled_parses():
    """ETHOS sends null for what it did not read. Null is a value, not a gap."""
    state = CoreState.model_validate(DISABLED)
    assert state.enabled is False
    assert state.health.ok is None          # coerced to the empty model
    assert state.activity.checked is False
    assert state.blocker == ""              # and it blocks nothing


def test_an_unreachable_core_host_parses_too():
    state = CoreState.model_validate({**DISABLED, "enabled": True,
                                      "error": "ssh: no route to host"})
    assert state.health.ok is None
    assert "no route to host" in state.blocker


def test_the_summary_takes_the_same_shape():
    """The strip reads `core` out of the summary, so it meets this shape too."""
    from console.rapps.ethos.models import StatusSummary

    summary = StatusSummary.model_validate({"core": DISABLED})
    assert summary.core.health.ok is None
    assert summary.core.stale.is_stale is False


def test_the_strip_renders_a_disabled_core_without_falling_over(fake):
    from console.capabilities import Capabilities
    from console.status import build_status

    recorded = fake._load("status_summary")
    recorded["core"] = DISABLED
    fake.answer("GET", "/status/summary", 200, recorded)

    status = run_async(build_status(_client(fake), Capabilities()))
    core = next(item for item in status.items if item.label == "Core")
    assert core.value == "not switched"
    assert status.core_stale is None


def test_the_plan_page_renders_with_switching_disabled(client, ethos_url):
    """The 500 this was found by: GET /plan on a testbed with one core."""
    ethos_url.answer("GET", "/core", 200, DISABLED)
    summary = ethos_url._load("status_summary")
    summary["core"] = DISABLED
    ethos_url.answer("GET", "/status/summary", 200, summary)

    page = client.get("/plan")
    assert page.status_code == 200
    assert "ETHOS does not switch cores" in page.text


# --- the Change topology dialog ----------------------------------------------


def _cards(core_state, category="core"):
    from console.pages.plan import card_list

    class Option:
        def __init__(self, value, display):
            self.id = value
            self.slug = value
            self.display = display
            self.status = "supported"

    class Catalogue:
        def category(self, name):
            return {
                "core": [Option("Open5GS", "Open5GS"), Option("free5GC", "free5GC")],
                "ue": [Option("Samsung", "Samsung"), Option("MTK", "MTK"),
                       Option("TM500", "TM500")],
            }.get(name, [])

    return {c[0]: c for c in card_list(Catalogue(), category, core_state=core_state)}


def _reason(cards, value):
    return cards[value][2]


def _blurb(cards, value):
    return cards[value][3]


def test_free5gc_is_selectable_once_ethos_can_switch_and_the_profile_is_wired():
    cards = _cards(_core())
    assert _reason(cards, "free5GC") == ""          # no reason means not disabled


def test_the_free5gc_card_says_what_selecting_it_costs():
    cards = _cards(_core())
    assert _blurb(cards, "free5GC") == (
        "Stops Open5GS on the shared hpe for this job and restores it afterwards."
    )
    assert "Not verified" not in _blurb(cards, "free5GC")


def test_free5gc_stays_disabled_while_switching_is_off():
    """Selecting it would label runs free5GC and measure Open5GS."""
    cards = _cards(CoreState())                      # enabled false
    reason = _reason(cards, "free5GC")
    assert reason
    assert "ETHOS_CORE_SWITCH_ENABLED" in reason


def test_free5gc_stays_disabled_when_its_profile_is_not_wired():
    state = _core()
    state.profiles["free5gc"].status = "todo"
    cards = _cards(state)
    assert "wired" in _reason(cards, "free5GC")


def test_free5gc_is_disabled_when_the_core_host_could_not_be_read():
    """Unknown is not permission: ETHOS may not be able to switch at all."""
    cards = _cards(_core(error="ssh: no route to host"))
    assert _reason(cards, "free5GC")


def test_open5gs_is_never_disabled_whatever_the_core_state():
    for state in (_core(), CoreState(), _core(error="down")):
        assert _reason(_cards(state), "Open5GS") == ""


def test_the_dialog_preselects_open5gs_for_a_new_plan():
    from console.pages.plan import DEFAULTS

    assert DEFAULTS["core"] == "Open5GS"


# --- no combination is blocked by the core -----------------------------------

@pytest.mark.parametrize("ue", ["Samsung", "MTK"])
def test_both_handsets_stay_selectable_whichever_core_is_chosen(ue):
    """The catalogue has no ue x core rule, and the console must not invent one."""
    for state in (_core(), _core(core="free5gc")):
        assert _reason(_cards(state, "ue"), ue) == ""


def test_the_unverified_mtk_combination_is_a_note_not_a_block():
    from console.pages.plan import combination_note

    note = combination_note(core="free5GC", ue="MTK")
    assert note == "MTK attach not yet verified on free5GC"


@pytest.mark.parametrize(
    "core, ue",
    [("Open5GS", "MTK"), ("Open5GS", "Samsung"), ("free5GC", "Samsung")],
)
def test_the_verified_combinations_carry_no_note(core, ue):
    from console.pages.plan import combination_note

    assert combination_note(core=core, ue=ue) == ""


def test_the_note_reaches_the_page_and_run_is_still_offered(client, ethos_url):
    ethos_url.answer("GET", "/core", 200, _core().model_dump())
    page = client.post(
        "/plan/resolve",
        data={"core": "free5GC", "ue": "MTK", "rates": "100", "direction": "DL",
              "duration": "10s", "repeats": "1", "gnb_stack": "OCUDU",
              "gnb_split": "monolithic", "l1_backend": "software-PHY",
              "ru": "Pegatron", "server": "joule", "iperf_server": "app_binary"},
    )
    assert page.status_code == 200
    assert "MTK attach not yet verified on free5GC" in page.text


# --- the effective configuration card ----------------------------------------


# --- a job that could not put the core back ----------------------------------

def _job(**overrides) -> dict:
    body = {
        "job_id": "j-restore01", "state": "completed", "source": "api", "plan": {},
        "config_id": "ocudu-mono_swphy_pega_samsung_f5gc_joule",
        "steps": [], "points": [], "run_ids": [],
        "outcome": "the sweep finished and the testbed was restored",
        "core_restore_error": "", "core_restore_remedy": "",
    }
    body.update(overrides)
    return body


FAILED_RESTORE = {
    "core_restore_error": "ssh: connection reset by peer",
    "core_restore_remedy": "sudo core-switch open5gs",
}


def test_the_job_model_carries_a_failed_restore():
    from console.rapps.ethos.models import Job

    job = Job.model_validate(_job(**FAILED_RESTORE))
    assert job.core_restore_failed is True
    assert job.core_restore_remedy == "sudo core-switch open5gs"


def test_a_job_whose_restore_worked_reports_nothing():
    from console.rapps.ethos.models import Job

    assert Job.model_validate(_job()).core_restore_failed is False


def test_an_older_job_without_the_fields_reports_nothing():
    from console.rapps.ethos.models import Job

    body = _job()
    del body["core_restore_error"], body["core_restore_remedy"]
    assert Job.model_validate(body).core_restore_failed is False


def test_the_job_page_warns_prominently_and_names_the_command(client, ethos_url):
    ethos_url.answer("GET", "/jobs/j-restore01", 200, _job(**FAILED_RESTORE))

    page = client.get("/jobs/j-restore01")
    assert page.status_code == 200
    assert "sudo core-switch open5gs" in page.text
    assert "connection reset by peer" in page.text
    assert "banner bad" in page.text          # the loudest banner the page has


def test_the_job_still_reads_as_completed(client, ethos_url):
    """The measurements stand. It is the testbed that needs attention."""
    ethos_url.answer("GET", "/jobs/j-restore01", 200, _job(**FAILED_RESTORE))

    page = client.get("/jobs/j-restore01")
    assert "completed" in page.text
    assert "failed</" not in page.text.replace("FAILED", "")


def test_a_healthy_job_page_shows_no_such_banner(client, ethos_url):
    ethos_url.answer("GET", "/jobs/j-restore01", 200, _job())

    page = client.get("/jobs/j-restore01")
    assert "core-switch open5gs" not in page.text


def test_the_command_comes_from_ethos_not_from_the_template():
    """The console holds no idea of its own about what fixes the testbed."""
    import pathlib

    html = pathlib.Path("console/templates/jobs/snapshot.html").read_text()
    assert "core_restore_remedy" in html
    assert "sudo core-switch" not in html


# --- the core must survive the dialog ----------------------------------------
#
# The bug: a preset card carried the core the page was rendered with, and
# applying one wrote it back over a core chosen in the Custom tab. Presets are
# the first tab and the obvious way to pick a topology, so free5GC "did not
# stick" for anyone who used them.

def test_a_preset_sets_the_topology_and_nothing_else():
    """It is a gNB stack and a split. Everything else on the card is for the
    diagram, and is frozen at the moment the drawer was rendered."""
    import pathlib
    import re

    js = pathlib.Path("console/static/js/console.js").read_text()
    body = js[js.index("function applyPreset"):]
    body = body[:body.index("\n  }")]
    fields = re.search(r"const fields = \{(.*?)\};", body, re.S).group(1)
    assigned = set(re.findall(r"(\w+):", fields)) | set(
        re.findall(r"fields\.(\w+) =", body)
    )
    assert assigned == {"gnb_stack", "split_kind", "cu_vendor", "du_vendor"}, assigned
    for never in ("core", "ue", "ru", "l1_backend", "server"):
        assert f"{never}: wanted." not in fields, f"a preset must not apply {never}"


def test_the_preset_payload_still_carries_a_core_for_its_diagram():
    """Removing it from the payload would blank the card. It is display only."""
    from console.topology import build_presets

    class NoProfiles:
        available = False

    presets = build_presets(NoProfiles(), {"ue": "Samsung", "ru": "Pegatron",
                                           "l1_backend": "software-PHY",
                                           "core": "free5GC", "server": "joule"}, [])
    assert presets and presets[0].selection["core"] == "free5GC"


# --- the guard ---------------------------------------------------------------

def test_a_plan_whose_config_id_is_for_the_other_core_is_refused():
    from console.pages.plan import core_mismatch

    said = core_mismatch(
        {"core": "free5GC"}, "ocudu-mono_swphy_pega_samsung_o5gs_joule"
    )
    assert said
    assert "free5GC" in said and "Open5GS" in said
    assert "Nothing has been started" in said


def test_an_agreeing_plan_passes_the_guard():
    from console.pages.plan import core_mismatch

    assert core_mismatch(
        {"core": "free5GC"}, "ocudu-mono_swphy_pega_samsung_f5gc_joule"
    ) == ""
    assert core_mismatch(
        {"core": "Open5GS"}, "ocudu-mono_swphy_pega_samsung_o5gs_joule"
    ) == ""


def test_no_config_id_yet_is_not_a_mismatch():
    from console.pages.plan import core_mismatch

    assert core_mismatch({"core": "free5GC"}, None) == ""
    assert core_mismatch({"core": "free5GC"}, "") == ""


def test_a_core_ethos_has_no_id_for_is_refused_rather_than_guessed():
    from console.pages.plan import core_mismatch

    said = core_mismatch({"core": "Nokia5GC"}, "a_b_c_d_o5gs_f")
    assert "no id for" in said


def test_run_refuses_when_ethos_generated_an_id_for_the_other_core(client, ethos_url):
    """The console must not preview, let alone start, a plan it cannot
    describe honestly. Nothing is corrected: it stops and says so."""
    ethos_url.answer("GET", "/core", 200, _core().model_dump())
    ethos_url.answer("POST", "/testdef/generate", 200, {
        "test_definition": {"config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule"},
    })

    form = {"core": "free5GC", "ue": "Samsung", "rates": "100", "direction": "DL",
            "duration": "10s", "repeats": "1", "gnb_stack": "OCUDU",
            "gnb_split": "monolithic", "l1_backend": "software-PHY",
            "ru": "Pegatron", "server": "joule", "iperf_server": "app_binary"}

    response = client.post("/plan/run", data=form)

    assert response.status_code == 409
    assert "free5GC" in response.text and "Open5GS" in response.text
    assert "Nothing has been started" in response.text
    assert ("POST", "/jobs/preview") not in ethos_url.calls


def test_start_refuses_the_same_mismatch(client, ethos_url):
    ethos_url.answer("GET", "/core", 200, _core().model_dump())
    ethos_url.answer("POST", "/testdef/generate", 200, {
        "test_definition": {"config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule"},
    })

    response = client.post("/plan/start", data={
        "core": "free5GC", "ue": "Samsung", "rates": "100", "direction": "DL",
        "duration": "10s", "repeats": "1", "gnb_stack": "OCUDU",
        "gnb_split": "monolithic", "l1_backend": "software-PHY", "ru": "Pegatron",
        "server": "joule", "iperf_server": "app_binary", "preview_token": "t",
    })

    assert response.status_code == 409
    assert ("POST", "/jobs") not in ethos_url.calls
