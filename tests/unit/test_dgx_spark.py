"""The DGX Spark in the console: topology, deployability, phase, run page, reboot.

Component tests against a fake ETHOS. Nothing here talks to the live API, to
joule or to the Spark.
"""

from __future__ import annotations

import pytest

from console.pages.plan import option_list
from console.pages.testbed import reboot_blocked, spark_view
from console.rapps.ethos.models import Catalogue, DeployStatus, Holder, Run
from console.topology import AERIAL_L1, nodes_for, server_of

SPARK_CONFIG_ID = "ocudu-cudu_aerial_pega_samsung_o5gs_dgxspark"
JOULE_CONFIG_ID = "ocudu-cudu_swphy_pega_samsung_o5gs_joule"


def selection(**over) -> dict:
    base = {
        "gnb_stack": "OCUDU", "gnb_split": "monolithic", "ue": "Samsung",
        "ru": "Pegatron", "core": "Open5GS", "server": "joule",
        "l1_backend": "software-PHY",
    }
    base.update(over)
    return base


# --- 10a, topology ----------------------------------------------------------

def test_a_joule_plan_draws_the_software_phy_path() -> None:
    chain = nodes_for(selection())
    labels = [n.label for n in chain.all_nodes()]
    assert "Aerial L1" not in labels
    assert labels == ["UE", "O-RU", "gNB", "5GC"]


def test_a_spark_plan_draws_the_aerial_path() -> None:
    chain = nodes_for(selection(l1_backend=AERIAL_L1, server="DGX-Spark"))
    labels = [n.label for n in chain.all_nodes()]
    assert labels == ["UE", "O-RU", "Aerial L1", "gNB", "5GC"]


def test_the_connector_behind_the_aerial_node_names_nvipc() -> None:
    """FAPI over nvIPC is a link, so it is drawn on the link.

    The gNB reaches the L1 over it, which is what `link_in` on the node after
    the L1 says; the L1's own caption names what the node IS.
    """
    chain = nodes_for(selection(l1_backend=AERIAL_L1))
    l1 = next(n for n in chain.hosted if n.label == "Aerial L1")
    behind = chain.hosted[chain.hosted.index(l1) + 1]
    assert "nvIPC" in behind.link_in
    assert "cuPHY" in l1.sub


def test_the_spark_ru_names_the_cx7_and_ocnos_fronthaul() -> None:
    chain = nodes_for(selection(l1_backend=AERIAL_L1))
    ru = next(n for n in chain.before if n.label == "O-RU")
    assert "CX7" in ru.sub and "OcNOS" in ru.sub


def test_a_spark_split_keeps_the_cu_and_du() -> None:
    chain = nodes_for(selection(l1_backend=AERIAL_L1, gnb_split="CU+DU"))
    assert [n.label for n in chain.hosted] == ["Aerial L1", "O-DU", "O-CU"]


def test_the_chain_reads_aloud_in_order() -> None:
    chain = nodes_for(selection(l1_backend=AERIAL_L1, server="DGX-Spark"))
    spoken = chain.describe()
    assert spoken.index("O-RU") < spoken.index("Aerial L1") < spoken.index("5GC")


@pytest.mark.parametrize("config_id,expected", [
    (SPARK_CONFIG_ID, "DGX-Spark"),
    (JOULE_CONFIG_ID, "joule"),
    ("nonsense", ""),
    ("", ""),
])
def test_a_runs_server_is_derived_from_its_config_id(config_id, expected) -> None:
    """No new API field: the config_id already carries the server."""
    assert server_of(config_id) == expected


# --- 10b, deployability -----------------------------------------------------

def catalogue_with(**reasons) -> Catalogue:
    options = []
    for option_id, (deployable, reason) in reasons.items():
        options.append({
            "category": "server", "id": option_id, "slug": option_id.lower(),
            "label": option_id, "status": "supported",
            "deployable": deployable, "reason": reason,
        })
    return Catalogue.model_validate({"options": {"server": options}})


def test_ethos_reason_wins_over_the_consoles_own() -> None:
    """OPTION_REASONS is the fallback; ETHOS's own wording is the truth."""
    catalogue = catalogue_with(**{
        "joule": (True, ""),
        "DGX-Spark": (False, "Spark control disabled: set ETHOS_RAN_CTL_ENABLED=true"),
    })
    rows = option_list(catalogue, "server", None, catalogue)
    reasons = {value: reason for value, _label, reason in rows}
    assert reasons["joule"] == ""
    assert "ETHOS_RAN_CTL_ENABLED" in reasons["DGX-Spark"]


def test_without_the_route_the_console_falls_back_to_its_own_list() -> None:
    """An older ETHOS has no /catalogue, and the page must still draw."""
    catalogue = Catalogue.model_validate({"options": {"server": [
        {"category": "server", "id": "DGX-Spark", "label": "DGX-Spark",
         "status": "supported"},
    ]}})
    rows = option_list(catalogue, "server", None, None)
    assert rows and rows[0][0] == "DGX-Spark"


def test_reason_for_says_nothing_when_ethos_said_nothing() -> None:
    catalogue = Catalogue.model_validate({"options": {"server": [
        {"category": "server", "id": "joule", "label": "joule"},
    ]}})
    assert catalogue.reason_for("server", "joule") is None


def test_reason_for_is_empty_when_ethos_said_yes() -> None:
    assert catalogue_with(joule=(True, "")).reason_for("server", "joule") == ""


def test_an_unknown_option_has_no_reason() -> None:
    assert catalogue_with(joule=(True, "")).reason_for("server", "nope") is None


# --- 10c, phase and Stop RAN ------------------------------------------------

def deploy_status(**ran_mode) -> DeployStatus:
    return DeployStatus.model_validate({
        "config_id": SPARK_CONFIG_ID,
        "ran_mode": ran_mode or None,
    })


def test_a_joule_deploy_has_no_spark_panel() -> None:
    assert spark_view(DeployStatus.model_validate({"config_id": JOULE_CONFIG_ID})) is None


@pytest.mark.parametrize("phase", ["precheck", "ru_gap", "starting", "verifying",
                                   "up", "stopping", "post_stop", "down", "failed"])
def test_every_ran_ctl_phase_reaches_the_view(phase: str) -> None:
    assert spark_view(deploy_status(mode="ocudu-f1", phase=phase))["phase"] == phase


def test_a_recovery_cycle_is_carried_through() -> None:
    view = spark_view(deploy_status(mode="ocudu-f1", phase="up", recovery_cycle=True))
    assert view["recovery_cycle"] is True


def test_the_holder_and_a_stale_lease_are_carried_through() -> None:
    view = spark_view(deploy_status(
        mode="ocudu-f1", holder="run-7", lease_stale=True, blocked=True,
        reason="the RU is held by run_id 'run-7'",
    ))
    assert view["holder"] == "run-7"
    assert view["lease_stale"] is True
    assert "run-7" in view["reason"]


# --- 10e, reboot ------------------------------------------------------------

def test_a_reboot_is_offered_when_nothing_is_running() -> None:
    assert reboot_blocked(Holder(held=False), deploy_status()) == ""


def test_a_campaign_holding_the_testbed_blocks_a_reboot() -> None:
    blocked = reboot_blocked(Holder(held=True, holder="cli:123"), deploy_status())
    assert "campaign holds the testbed" in blocked


def test_a_spark_lease_blocks_a_reboot() -> None:
    """The testbed lock does not cover the Spark: its lease is on another host."""
    blocked = reboot_blocked(
        Holder(held=False), deploy_status(mode="ocudu-f1", holder="run-7")
    )
    assert "DGX Spark" in blocked and "run-7" in blocked


def test_an_unreadable_deploy_status_does_not_block_a_reboot() -> None:
    assert reboot_blocked(Holder(held=False), None) == ""


def test_reboot_is_one_of_the_offered_actions() -> None:
    from console.pages.testbed import ACTIONS

    assert ACTIONS["reboot"] == "Reboot the handset"
    assert set(ACTIONS) == {"attach", "detach", "iperf/stop", "reboot"}


# --- 10d, the run page ------------------------------------------------------

def run_with(ran_mode) -> Run:
    return Run.model_validate({
        "run_id": "r-1", "config_id": SPARK_CONFIG_ID, "ran_mode": ran_mode,
    })


def test_a_joule_run_carries_no_ran_mode() -> None:
    run = Run.model_validate({"run_id": "r-1", "config_id": JOULE_CONFIG_ID})
    assert run.ran_mode is None


def test_a_spark_run_carries_every_field_the_panel_draws() -> None:
    run = run_with({
        "mode": "ocudu-f1",
        "image_ids": {"ravi-ocudu-du": "sha256:bb"},
        "invocation_ids": {"l1": "a" * 32},
        "config_sha256": {"/conf/du.yml": "b" * 64},
        "cn5g_running": False,
        "recovery_cycle": True,
        "drift": [{"kind": "not_pinned", "blocks_start": True}],
        "verify": {"ok": True, "faults": [], "checks": {"num_tlvs": "31"}},
    })
    assert run.ran_mode["mode"] == "ocudu-f1"
    assert run.ran_mode["verify"]["checks"]["num_tlvs"] == "31"
    assert run.ran_mode["drift"][0]["blocks_start"] is True


# --- 10e, Deploy RAN: a Spark mode with no campaign behind it ---------------

from pathlib import Path                                            # noqa: E402

from console.rapps.ethos.profiles import load_profiles              # noqa: E402

RECORDED_PROFILES = Path(__file__).resolve().parents[1] / "recorded" / "deploy_profiles.yaml"

SPARK_SELECTION = {
    "gnb_stack": "OCUDU", "gnb_split": "monolithic", "ue": "Samsung",
    "ru": "Pegatron", "core": "Open5GS", "server": "DGX-Spark",
    "l1_backend": AERIAL_L1,
}


def spark_form(**over) -> dict:
    form = {
        "gnb_stack": "OCUDU", "split_kind": "monolithic",
        "cu_vendor": "OCUDU", "du_vendor": "OCUDU",
        "l1_backend": AERIAL_L1, "ru": "Pegatron", "ue": "Samsung",
        "core": "Open5GS", "server": "DGX-Spark",
        "direction": "DL", "rates": "100", "duration": "30s", "repeats": "1",
        "iperf_server": "app_binary", "label": "",
    }
    form.update(over)
    return form


def test_a_ran_ctl_profile_is_deployable_without_releases() -> None:
    """It installs no chart, so requiring one made every Spark mode read as
    an unfilled placeholder."""
    profiles = load_profiles(RECORDED_PROFILES)
    profile = profiles.resolve(SPARK_SELECTION)
    assert profile.name == "ocudu-mono-aerial"
    assert profile.is_ran_ctl is True
    assert profile.releases == ()
    deployable, reason = profiles.deployable(SPARK_SELECTION)
    assert deployable is True
    assert "RAN mode on the DGX Spark" in reason


def test_a_joule_profile_still_needs_its_releases() -> None:
    profiles = load_profiles(RECORDED_PROFILES)
    profile = profiles.resolve(selection())
    assert profile.is_ran_ctl is False
    assert profile.releases


def test_the_plan_page_offers_deploy_ran_for_a_spark_selection(client) -> None:
    body = client.post("/plan/readiness", data=spark_form()).text
    assert "Deploy RAN" in body
    assert "/plan/deploy" in body


def test_the_plan_page_offers_no_deploy_ran_for_joule(client) -> None:
    """Joule's helm profiles keep RUN as their only way in."""
    body = client.post("/plan/readiness", data=spark_form(
        l1_backend="software-PHY", server="joule")).text
    assert "RUN" in body               # the panel rendered; it just has no Deploy RAN
    assert "Deploy RAN" not in body


def test_deploy_ran_is_disabled_while_the_testbed_is_held(client, ethos_url) -> None:
    ethos_url.hold_lock("CLI campaign", "a sweep", "2026-10-15T09:00:00Z")
    body = client.post("/plan/readiness", data=spark_form()).text
    assert "Deploy RAN" in body
    assert "a campaign holds the testbed" in body


def test_deploy_ran_previews_before_it_acts(client, ethos_url) -> None:
    """The button asks ETHOS what it would do; nothing is deployed yet."""
    response = client.post("/plan/deploy", data=spark_form())
    assert response.status_code == 200, response.text
    assert "Deploy this RAN mode?" in response.text
    assert "ran-ctl start ocudu-mono" in response.text
    assert ethos_url.created_runs == []
    assert ethos_url.deployed == []


def test_confirming_creates_the_run_then_deploys(client, ethos_url) -> None:
    """A ran-ctl deploy refuses without a run_id, so the run comes first."""
    response = client.post(
        "/plan/deploy/start",
        data={**spark_form(), "preview_token": "deploy-token-1"},
    )
    assert response.status_code == 204, response.text

    assert len(ethos_url.created_runs) == 1
    created = ethos_url.created_runs[0]
    assert created["config_id"].endswith("_dgxspark")
    assert created["direction"] == "none"

    assert len(ethos_url.deployed) == 1
    sent = ethos_url.deployed[0]
    assert sent["confirm"] is True
    assert sent["preview_token"] == "deploy-token-1"
    assert sent["run_id"].endswith("-noTraffic-001")
    assert sent["config_id"] == created["config_id"]

    assert response.headers["HX-Redirect"] == f"/results/runs/{sent['run_id']}"


def test_confirming_without_a_token_sends_nothing(client, ethos_url) -> None:
    response = client.post("/plan/deploy/start", data=spark_form())
    assert response.status_code == 422
    assert ethos_url.created_runs == []
    assert ethos_url.deployed == []


def test_a_held_testbed_refuses_the_confirm_too(client, ethos_url) -> None:
    """The disabled button is the brace; this is the belt."""
    ethos_url.hold_lock("CLI campaign", "a sweep", "2026-10-15T09:00:00Z")
    response = client.post(
        "/plan/deploy/start",
        data={**spark_form(), "preview_token": "deploy-token-1"},
    )
    assert response.status_code == 409
    assert ethos_url.deployed == []


def test_a_joule_selection_cannot_deploy_ran_even_by_posting(client, ethos_url) -> None:
    """No button, and the route refuses the post a second tab could make."""
    response = client.post(
        "/plan/deploy",
        data=spark_form(l1_backend="software-PHY", server="joule"),
    )
    assert response.status_code == 409
    assert ethos_url.deployed == []


# --- 10f, Stop RAN: the rendered page, then the form it renders -------------

import re                                                           # noqa: E402

HELD_RUN = "20261015T1435Z-ocudu-mono_aerial_pega_samsung_o5gs_dgxspark-noTraffic-001"
MODE_C = "ocudu-mono_aerial_pega_samsung_o5gs_dgxspark"


def held_spark(ethos_url, *, holder=HELD_RUN, config_id=MODE_C,
               mode="ocudu-mono", heartbeat=None) -> None:
    """A Spark holding a lease, as `GET /deploy/status` with no config_id
    answers it."""
    body = ethos_url._load("deploy_status")
    body["status"]["ran_mode"] = {
        "read_ok": True, "mode": mode, "phase": "up", "holder": holder,
        "holder_config_id": config_id, "lease_stale": False,
        "recovery_cycle": False, "blocked": True, "drift": [],
        "cn5g_running": False, "heartbeat": heartbeat,
        "reason": f"the RU is held by run_id {holder!r}",
    }
    ethos_url.answers["GET /deploy/status"] = (200, body)


def form_fields(html: str, form_id: str) -> dict:
    """Every hidden input the named form actually rendered."""
    block = re.search(rf'<form id="{form_id}".*?</form>', html, re.S)
    assert block, f"no form {form_id} in the page"
    return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', block.group(0)))


def test_the_testbed_page_renders_a_stop_form_naming_the_holder(client, ethos_url) -> None:
    held_spark(ethos_url)
    page = client.get("/testbed").text

    assert "Stop RAN" in page
    assert form_fields(page, "stop-ran-form") == {
        "config_id": MODE_C, "run_id": HELD_RUN,
    }


def test_the_tile_names_the_mode_the_lease_holds(client, ethos_url) -> None:
    held_spark(ethos_url)
    page = client.get("/testbed").text
    assert "ocudu-mono" in page
    assert "no mode" not in page


def test_no_holder_renders_no_stop_button(client, ethos_url) -> None:
    body = ethos_url._load("deploy_status")
    body["status"]["ran_mode"] = {
        "read_ok": True, "mode": None, "phase": None, "holder": None,
        "holder_config_id": None, "lease_stale": False, "blocked": False,
        "drift": [], "cn5g_running": False, "heartbeat": None, "reason": "",
    }
    ethos_url.answers["GET /deploy/status"] = (200, body)
    page = client.get("/testbed").text

    assert "Stop RAN" not in page
    assert "nothing to stop" in page


def test_a_holder_with_no_known_config_renders_no_stop_button(client, ethos_url) -> None:
    """A lease ETHOS cannot name a configuration for cannot be stopped by a
    route that names one."""
    held_spark(ethos_url, config_id=None)
    page = client.get("/testbed").text

    assert "Stop RAN" not in page
    assert "this archive does not know" in page


def submit(client, html: str, form_id: str, url: str, **extra):
    """Post exactly what the rendered form carries."""
    return client.post(url, data={**form_fields(html, form_id), **extra})


def test_pressing_stop_ran_previews_and_sends_nothing(client, ethos_url) -> None:
    held_spark(ethos_url)
    page = client.get("/testbed").text

    response = submit(client, page, "stop-ran-form", "/testbed/ran/stop")
    assert response.status_code == 200, response.text
    assert "Stop this RAN mode?" in response.text
    assert "ran-ctl stop ocudu-mono" in response.text
    assert ethos_url.stopped == []


def test_confirming_the_preview_sends_the_token_and_the_holder(client, ethos_url) -> None:
    """The whole path a person takes: the page, its form, the dialog the
    preview returns, and the fields that dialog carries."""
    held_spark(ethos_url)
    page = client.get("/testbed").text

    dialog = submit(client, page, "stop-ran-form", "/testbed/ran/stop").text
    token = re.search(r'id="confirm-stop-token" name="preview_token"\s+value="([^"]+)"',
                      dialog).group(1)

    confirmed = submit(client, page, "stop-ran-form",
                       "/testbed/ran/stop/confirm", preview_token=token)
    assert confirmed.status_code == 204, confirmed.text
    assert ethos_url.stopped == [{
        "config_id": MODE_C, "run_id": HELD_RUN, "preview_token": token,
    }]
    assert confirmed.headers["HX-Redirect"] == "/testbed"


def test_confirming_a_stop_without_a_token_sends_nothing(client, ethos_url) -> None:
    held_spark(ethos_url)
    page = client.get("/testbed").text

    response = submit(client, page, "stop-ran-form", "/testbed/ran/stop/confirm")
    assert response.status_code == 422
    assert ethos_url.stopped == []


def test_a_held_testbed_refuses_the_stop(client, ethos_url) -> None:
    held_spark(ethos_url)
    page = client.get("/testbed").text
    ethos_url.hold_lock("CLI campaign", "a sweep", "2026-10-15T09:00:00Z")

    response = submit(client, page, "stop-ran-form",
                      "/testbed/ran/stop/confirm", preview_token="teardown-token-1")
    assert response.status_code == 409
    assert ethos_url.stopped == []


def test_the_tile_shows_the_heartbeat_ethos_holds(client, ethos_url) -> None:
    held_spark(ethos_url, heartbeat={
        "run_id": HELD_RUN, "interval_s": 300.0,
        "last_ok_at": "2026-10-15T14:45:00+00:00",
    })
    page = client.get("/testbed").text
    assert "ETHOS is holding the lease" in page


# --- the confirm carries the id it showed -----------------------------------

def test_a_confirm_for_another_config_id_is_refused(client) -> None:
    """What the dialog showed is what may be started, or nothing is sent."""
    reply = client.post("/plan/start", data={
        **spark_form(),
        "preview_token": "t",
        "confirmed_config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule",
    })
    assert reply.status_code == 409
    assert "nothing was sent" in reply.text
