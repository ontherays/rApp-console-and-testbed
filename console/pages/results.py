"""Results: the run table, one run in detail, and a sweep across offered loads."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from starlette.responses import PlainTextResponse, Response

from console.rapps.ethos.client import EthosError
from console.rapps.ethos.metrics import channel_rows
from console.rapps.ethos.query import (
    Filters,
    cell_config_consistent,
    csv_rows,
    facets,
    select,
    sweep,
)
from console.core_setup import compare_cores
from console.templating import render

router = APIRouter()

PAGE_SIZE = 50


def _filters(request: Request) -> Filters:
    q = request.query_params
    return Filters(
        config_id=q.get("config_id", ""),
        direction=q.get("direction", ""),
        core=q.get("core", ""),
        campaign_id=q.get("campaign_id", ""),
        server_owner=q.get("server_owner", ""),
        band=q.get("band", ""),
        bandwidth_mhz=q.get("bandwidth_mhz", ""),
        tdd_pattern=q.get("tdd_pattern", ""),
        rate=q.get("rate", ""),
        since=q.get("since", ""),
        until=q.get("until", ""),
        status=q.get("status", ""),
        has_flags=q.get("has_flags", "") in ("1", "yes", "true", "on"),
        usable_only=q.get("usable_only", "yes") not in ("0", "no", "false", "off"),
    )


@router.get("/results")
async def results(
    request: Request,
    sort: str = "time",
    dir: str = "desc",
    offset: int = 0,
):
    client = request.app.state.client
    filters = _filters(request)
    error = None
    page = None
    available: dict = {}
    try:
        listing = await client.runs()
        page = select(
            listing.runs,
            filters,
            sort=sort,
            descending=(dir != "asc"),
            offset=max(0, offset),
            limit=PAGE_SIZE,
        )
        available = facets(listing.runs)
    except EthosError as exc:
        error = exc.message

    return render(
        request,
        "results/page.html",
        {
            "page": page,
            "filters": filters,
            "facets": available,
            "sort": sort,
            "dir": dir,
            "error": error,
        },
    )


@router.get("/results/export.csv")
async def export_csv(request: Request, sort: str = "time", dir: str = "desc"):
    """The filtered table as CSV. Generated here until ``GET /runs.csv`` (B10)."""
    client = request.app.state.client
    filters = _filters(request)
    try:
        listing = await client.runs()
    except EthosError as exc:
        return PlainTextResponse(f"ETHOS is unreachable: {exc.message}", status_code=502)

    page = select(
        listing.runs, filters, sort=sort, descending=(dir != "asc"), offset=0, limit=0
    )
    return Response(
        csv_rows(page.rows),
        media_type="text/csv",
        headers={
            "content-disposition": 'attachment; filename="ethos-runs.csv"',
            "x-console-rows": str(len(page.rows)),
        },
    )


@router.get("/results/runs/{run_id}")
async def run_detail(request: Request, run_id: str, tab: str = "summary"):
    client = request.app.state.client
    error = None
    run = None
    raw: dict = {}
    try:
        run = await client.run(run_id)
        raw = run.model_dump(mode="json", exclude_none=False)
    except EthosError as exc:
        error = exc.message

    rows = channel_rows(run) if run else {}
    return render(
        request,
        "results/run.html",
        {
            "run": run,
            "rows": rows,
            "raw_json": json.dumps(raw, indent=2, sort_keys=False),
            "tab": tab,
            "error": error,
        },
    )


#: Each sweep column and the ETHOS metric it shows, so a "Plot" link beside a
#: column asks for exactly that metric. Columns with no cross-vendor metric
#: (first-transmission BLER is OAI-only) get no link, which is the same reason
#: ETHOS does not offer them.
SWEEP_METRICS: dict[str, str] = {
    "achieved": "throughput",
    "loss": "loss",
    "rtt_p95": "rtt_p95",
    "pusch_snr": "pusch_snr",
    "bler_dl": "bler_dl_residual",
    "bler_ul": "bler_ul_residual",
    "cqi": "cqi",
    "ri_dl": "ri_dl",
    "mcs_dl": "mcs_dl",
    "mcs_ul": "mcs_ul",
}


def plot_links(runs) -> dict[str, str]:
    """A ready-made figure query per metric column, for these runs.

    The run ids travel in the link, so the form opens describing the figure the
    column is about rather than asking the operator to retype a selection they
    have already made.
    """
    from urllib.parse import urlencode

    ids = [r.run_id for r in runs if r.run_id]
    if not ids:
        return {}
    return {
        column: "/graphs?" + urlencode(
            [("source", "runs"), ("metric", metric)]
            + [("run_id", run_id) for run_id in ids]
        )
        for column, metric in SWEEP_METRICS.items()
    }


@router.get("/results/campaigns/{campaign_id}")
async def campaign_sweep(request: Request, campaign_id: str):
    client = request.app.state.client
    error = None
    rows: list = []
    runs: list = []
    consistent, configs = True, []
    try:
        listing = await client.runs()
        runs = [r for r in listing.runs if (r.campaign_id or "") == campaign_id]
        rows = sweep(runs)
        consistent, configs = cell_config_consistent(runs)
    except EthosError as exc:
        error = exc.message

    return render(
        request,
        "results/sweep.html",
        {
            "title": campaign_id,
            "subtitle": "campaign",
            "rows": rows,
            "runs": runs,
            "consistent": consistent,
            "cell_configs": configs,
            "plot_links": plot_links(runs),
            "cores": compare_cores(runs),
            "error": error,
        },
    )


@router.get("/results/compare")
async def compare(request: Request, run_id: list[str] = Query(default=[])):
    """Selected runs, laid out as a sweep (RS-03).

    ETHOS's own ``GET /compare`` is a 501 stub, so this arranges the same
    manifests the run table already read. It computes no new measurement: every
    number is a mean of what ETHOS recorded, shown with its n.
    """
    client = request.app.state.client
    error = None
    rows: list = []
    runs: list = []
    consistent, configs = True, []
    try:
        listing = await client.runs()
        wanted = set(run_id)
        runs = [r for r in listing.runs if r.run_id in wanted]
        rows = sweep(runs)
        consistent, configs = cell_config_consistent(runs)
    except EthosError as exc:
        error = exc.message

    return render(
        request,
        "results/sweep.html",
        {
            "title": f"{len(runs)} selected run(s)",
            "subtitle": "comparison",
            "rows": rows,
            "runs": runs,
            "consistent": consistent,
            "cell_configs": configs,
            "plot_links": plot_links(runs),
            "error": error,
        },
    )
