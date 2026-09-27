"""The sections that arrive in later phases: Testbed, O1, O2.

They are routed, and each page says what it will show, which ETHOS change it
needs, and what can be done today instead. A disabled navigation entry with no
page behind it leaves an operator guessing whether the feature exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request

from console.templating import render

router = APIRouter()


@dataclass(frozen=True)
class Section:
    title: str
    phase: str
    capability: str
    icon: str
    intro: str
    items: tuple[tuple[str, str], ...]
    today: str = ""


TESTBED = Section(
    title="Testbed control",
    phase="Phase 2",
    capability="ue",
    icon="hdd-network",
    intro=(
        "Deploy a topology and leave it running without traffic, tear down what is "
        "deployed, attach and detach a UE, and read the handset's signal — each "
        "action behind a confirmation that shows ETHOS's preview of what will happen."
    ),
    items=(
        ("TB-01", "Deploy a chosen topology with no traffic, confirmation first."),
        ("TB-02", "Tear down what is deployed, DU before CU."),
        ("TB-03", "Releases, pods, restarts, age, and the cell config read at deploy."),
        ("UE-01", "The testbed's UEs with driver, control path, reachability, attach state and IP."),
        ("UE-02", "Attach and detach, each confirmed, each refused while the lock is held."),
        ("UE-03", "Whether an app_binary server holds port 5201, and a confirmed stop."),
        ("UE-04", "The UE's SS-RSRP / RSRQ / SINR, read on demand."),
    ),
    today=(
        "ETHOS's UE endpoints are scoped to a run today "
        "(POST /runs/{id}/ue/attach), which is right for the record but means "
        "there is no standalone UE panel. Deploy and teardown act on the first "
        "call, with no preview, so they stay out of a web page until backend "
        "change B3 adds preview-then-confirm."
    ),
)

O1 = Section(
    title="O1",
    phase="Phase 3",
    capability="o1_freshness",
    icon="broadcast-pin",
    intro=(
        "PM per run and per cell, active alarms, the current CM of the deployed "
        "gNB, and tests driven by a CM change."
    ),
    items=(
        ("O1-01", "PM freshness per managed element of this testbed."),
        ("O1-02", "PM per run, per vendor — OCUDU and OAI share no counters, so there is no combined chart."),
        ("O1-03", "Active alarms and history, from the existing ONAP/VES path."),
        ("O1-04", "The current CM of the deployed gNB."),
        ("O1-05", "A CM change: pick a writable parameter, preview, confirm."),
        ("O1-06", "A CM step before traffic."),
        ("O1-07", "A CM sweep: the same rate list at several values of one parameter."),
    ),
    today=(
        "Per-run O1 reads already work and are on each run's page. The parameters "
        "ETHOS will let you write, with their safe ranges, are readable now at "
        "GET /cm/params/writable — and a CM write is the only thing in this system "
        "that mutates a live RAN, so it stays behind ETHOS's preview → confirm=true "
        "path and is never auto-confirmed."
    ),
)

O2 = Section(
    title="O2",
    phase="Phase 4",
    capability="o2_nf",
    icon="cpu",
    intro=(
        "NF checks in ravi-ns, pod deployment duration per deploy, O-Cloud energy "
        "and EE-KPI, and the StarlingX DMS inventory."
    ),
    items=(
        ("O2-01", "Helm releases and pods with status, restarts, age and readiness."),
        ("O2-02", "Time from helm install to all pods ready, per deploy and as a trend."),
        ("O2-03", "Energy per run and EE-KPI — never for an Aerial run, since the DGX-Spark is ARM and Intel RAPL does not apply."),
        ("O2-04", "The O2 IMS/DMS inventory, which needs a client certificate held by ETHOS."),
    ),
    today=(
        "O-Cloud power (ocloud_power) has had no point since 2026-08-27, so every "
        "EE-KPI would be null with a reason. Fixing the RAPL shipper on galileo "
        "comes before this page shows a number. The telemetry agent's own state is "
        "on the Overview."
    ),
)


def _page(request: Request, section: Section):
    return render(request, "later.html", {"section": section})


@router.get("/testbed")
async def testbed(request: Request):
    return _page(request, TESTBED)


@router.get("/o1")
async def o1(request: Request):
    return _page(request, O1)


@router.get("/o2")
async def o2(request: Request):
    return _page(request, O2)
