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
            "open5gs": {"name": "open5gs", "display": "Open5GS v2.7.7",
                        "ue_pool": "10.45.0.0/16", "core_data_ip": "10.45.0.1",
                        "tunnel_iface": "ogstun", "amf_n2": "192.168.8.26:38412",
                        "subscriber_db": "open5gs"},
            "free5gc": {"name": "free5gc", "display": "free5GC v4.2.3",
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

    status = run_async(build_status(_client(fake), Capabilities()))
    core = next(item for item in status.items if item.label == "Core")
    assert core.state == "ok"
    assert "192.168.8.13:16561" in core.detail


def test_the_plan_page_holds_run_back_while_the_host_is_mid_switch(client, ethos_url):
    ethos_url.answer("GET", "/core", 200, {
        **_core(core="open5gs", selected="free5gc",
                disagreement="core-switch says selected=free5gc but the sockets "
                             "are owned by open5gs").model_dump(),
    })
    response = client.get("/plan")
    assert response.status_code == 200
    assert "sockets are owned by open5gs" in response.text


# --- item 3: what Show config has to say -------------------------------------

def test_the_config_panel_describes_the_core_the_plan_is_for():
    rows = {row.label: row.value for row in core_setup.core_rows(_core(), "free5GC")}
    assert rows["UE pool"] == "10.60.0.0/16"
    assert rows["Core data IP"] == "192.168.8.26"
    assert rows["Tunnel"] == "upfgtp"


def test_it_describes_the_plan_s_core_not_the_running_one():
    """A free5GC plan shows free5GC's pool even while Open5GS is serving."""
    rows = {row.label: row.value for row in core_setup.core_rows(_core(core="open5gs"), "Open5GS")}
    assert rows["UE pool"] == "10.45.0.0/16"
    assert rows["Tunnel"] == "ogstun"


def test_an_unknown_core_says_so_rather_than_showing_the_other_one():
    rows = core_setup.core_rows(_core(), "SomeOtherCore")
    assert len(rows) == 1
    assert "no profile" in rows[0].hint


def test_the_iperf_rows_name_the_binary_the_port_and_the_bind_address():
    rows = {
        row.label: row.value
        for row in core_setup.iperf_rows(
            iperf_server="app_binary", core=_core(), planned="free5GC"
        )
    }
    assert rows["UE-side server"] == "Magic iPerf app on the UE"
    assert rows["Recorded as"] == "app_binary"
    assert rows["Port"] == "5201"
    assert rows["Client bind address"] == "192.168.8.26"


def test_the_bind_address_follows_the_core():
    rows = {
        row.label: row.value
        for row in core_setup.iperf_rows(
            iperf_server="ethos", core=_core(), planned="Open5GS"
        )
    }
    assert rows["Client bind address"] == "10.45.0.1"
    assert rows["Recorded as"] == "ethos"


def test_a_plan_whose_server_differs_from_the_open5gs_runs_is_flagged():
    """Two variables at once: a different core AND a different iperf server."""
    archive = [_run(server_owner="app_binary") for _ in range(4)]
    warning = core_setup.owner_warning(
        iperf_server="ethos", runs=archive, planned="free5GC"
    )
    assert "Magic iPerf" in warning and "ETHOS's own iperf3 server" in warning
    assert "4 Open5GS run(s)" in warning


def test_the_same_server_as_the_reference_is_not_flagged():
    archive = [_run(server_owner="app_binary") for _ in range(4)]
    assert core_setup.owner_warning(
        iperf_server="app_binary", runs=archive, planned="free5GC"
    ) == ""


def test_an_open5gs_plan_is_never_flagged_for_this():
    """It is the reference. Comparing it with itself raises no question."""
    archive = [_run(server_owner="app_binary") for _ in range(4)]
    assert core_setup.owner_warning(
        iperf_server="ethos", runs=archive, planned="Open5GS"
    ) == ""


def test_with_no_open5gs_runs_in_the_archive_there_is_nothing_to_compare():
    archive = [_run(core_slug="f5gc", server_owner="ethos")]
    assert core_setup.owner_warning(
        iperf_server="app_binary", runs=archive, planned="free5GC"
    ) == ""


def test_the_reference_is_read_from_the_archive_not_written_down():
    archive = (
        [_run(server_owner="ethos") for _ in range(5)]
        + [_run(server_owner="app_binary") for _ in range(2)]
    )
    assert core_setup.reference_owner(archive) == ("ethos", 5)


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
