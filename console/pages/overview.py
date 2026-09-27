"""The Overview bento grid, and the status-strip partial every page polls.

Each tile is its own htmx partial with its own refresh, because the probes
behind them have very different costs: ``/deploy/status`` is an SSH round trip
to the KVM, ``/runs`` reads 528 manifests off disk. One slow probe must not hold
up the page (OV-01…07).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from console.rapps.ethos.client import EthosError
from console.status import build_status
from console.templating import render

router = APIRouter()


@router.get("/")
async def overview(request: Request):
    return render(request, "overview/page.html", {})


@router.get("/partials/status")
async def status_partial(request: Request):
    state = request.app.state
    status = await build_status(state.client, state.probe.result)
    return render(request, "components/status_strip.html", {"status": status})


@router.get("/partials/tiles/deployed")
async def tile_deployed(request: Request):
    client = request.app.state.client
    error = None
    deployed = None
    try:
        deployed = await client.deploy_status()
    except EthosError as exc:
        error = exc.message
    return render(
        request,
        "overview/tile_deployed.html",
        {"deployed": deployed, "error": error},
    )


@router.get("/partials/tiles/runs")
async def tile_runs(request: Request):
    client = request.app.state.client
    error = None
    latest: list = []
    total = 0
    try:
        listing = await client.runs()
        total = listing.count
        latest = sorted(
            listing.runs, key=lambda r: (r.t_created or "", r.run_id), reverse=True
        )[:5]
    except EthosError as exc:
        error = exc.message
    return render(
        request,
        "overview/tile_runs.html",
        {"runs": latest, "total": total, "error": error},
    )


@router.get("/partials/tiles/agent")
async def tile_agent(request: Request):
    """The telemetry agent and the PMU state, from ``GET /status/health``.

    This is the one part of the O-Cloud side ETHOS answers today: the O2 energy
    numbers themselves have no fresh data (``ocloud_power`` stopped on
    2026-08-27), so the tile reports the agent, not an EE-KPI.
    """
    client = request.app.state.client
    error = None
    health: dict = {}
    try:
        health = await client.status_health()
    except EthosError as exc:
        error = exc.message
    capture = health.get("capture") or {}
    return render(
        request,
        "overview/tile_agent.html",
        {
            "health": health,
            "capture": capture,
            "collectors": capture.get("collectors") or [],
            "error": error,
        },
    )
