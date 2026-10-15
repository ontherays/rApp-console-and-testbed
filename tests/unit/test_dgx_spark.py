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


def test_the_aerial_node_names_nvipc() -> None:
    chain = nodes_for(selection(l1_backend=AERIAL_L1))
    l1 = next(n for n in chain.hosted if n.label == "Aerial L1")
    assert "nvIPC" in l1.sub


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
