"""The Overview: what this testbed has been doing, and what needs attention.

Each tile and chart is computed from the run archive, which is the only thing
the console can read without a credential. Values ETHOS cannot answer yet — the
lock, the running job, the UE — name the backend change instead of guessing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from console.charts import Column, HexCell, dot_matrix, hex_grid, tick_bar
from console.overview import (
    DEFAULT_KIND,
    DEFAULT_PERIOD,
    KINDS,
    PERIODS,
    Change,
    any_flagged,
    best_at,
    best_per_day,
    by_topology,
    median_snr,
    newest,
    parse_utc,
    slice_runs,
    topologies_needing_you,
)
from console.rapps.ethos.client import EthosError
from console.rapps.ethos.series import series_for
from console.status import build_status
from console.templating import render

router = APIRouter()


def _age(iso: str | None, now: datetime) -> tuple[str, str, str]:
    """(value, unit, tone) for a timestamp's age. Green under a day, amber under
    a week, red beyond — with the words present as well as the colour."""
    moment = parse_utc(iso)
    if moment is None:
        return "—", "", "slate"
    hours = (now - moment).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}", "min ago", "teal"
    if hours < 48:
        return f"{hours:.0f}", "h ago", "teal" if hours < 24 else "orange"
    days = hours / 24
    return f"{days:.0f}", "d ago", "orange" if days < 7 else "red"


@router.get("/")
async def overview(request: Request, period: str = DEFAULT_PERIOD, kind: str = DEFAULT_KIND):
    client = request.app.state.client
    caps = request.app.state.probe.result
    period = period if period in PERIODS else DEFAULT_PERIOD
    kind = kind if kind in KINDS else DEFAULT_KIND

    error = None
    runs: list = []
    try:
        listing = await client.runs()
        runs = listing.runs
    except EthosError as exc:
        error = exc.message

    now = datetime.now(timezone.utc)
    window = slice_runs(runs, period, kind, now=now)

    deployed = None
    deploy_error = None
    try:
        deployed = await client.deploy_status()
    except EthosError as exc:
        deploy_error = exc.message

    # --- the KPI row ---------------------------------------------------------
    if deployed is None:
        deployed_value, deployed_note = "unknown", deploy_error or "not read"
    elif deployed.anything_deployed:
        deployed_value = deployed.profile or deployed.stack or "something"
        deployed_note = f"{len(deployed.running_pods)} pod(s) running in {deployed.namespace}"
    else:
        deployed_value, deployed_note = "nothing", deployed.namespace_summary

    best_now = best_at(window.current, 1000.0)
    best_before = best_at(window.previous, 1000.0)
    snr_now = median_snr(window.current)
    snr_before = median_snr(window.previous)
    latest = newest(runs)
    age_value, age_unit, age_tone = _age(latest.t_created if latest else None, now)

    kpis = [
        {
            "icon": "lock", "tone": "slate", "label": "Testbed lock",
            "value": "unknown", "small": True,
            "note": caps.why("lock"), "note_icon": "info-circle",
        },
        {
            "icon": "hdd-network", "tone": "blue", "label": "Deployed now",
            "value": deployed_value, "small": True, "note": deployed_note,
        },
        {
            "icon": "activity", "tone": "purple", "label": f"Runs, {window.label.lower()}",
            "value": f"{len(window.current)}",
            "change": Change.between(
                float(len(window.current)), float(len(window.previous))
            ),
            "vs": f"vs {len(window.previous)}",
        },
        {
            "icon": "speedometer2", "tone": "teal", "label": "Best DL at 1000 M",
            "value": f"{best_now:.0f}" if best_now is not None else "—",
            "unit": "Mbit/s" if best_now is not None else "",
            "change": Change.between(best_now, best_before, decimals=1, unit="Mbit/s"),
            "vs": f"vs {best_before:.0f}" if best_before is not None else "no previous run",
        },
        {
            "icon": "reception-4", "tone": "orange", "label": "Median PUSCH SNR",
            "value": f"{snr_now:.1f}" if snr_now is not None else "—",
            "unit": "dB" if snr_now is not None else "",
            "change": Change.between(snr_now, snr_before, decimals=1, unit="dB"),
            "vs": f"vs {snr_before:.1f} dB" if snr_before is not None else "no previous run",
            "note": None if snr_now is not None else "no run in this period recorded channel metrics",
        },
        {
            "icon": "clock-history", "tone": age_tone, "label": "Data freshness",
            "value": age_value, "unit": age_unit,
            "note": "newest run in the archive · O1 and energy freshness need B6",
            "note_icon": "info-circle",
        },
    ]

    # --- runs by topology ----------------------------------------------------
    shares = by_topology(window.current)
    cells = [
        HexCell(
            colour=series_for(run.config_id).colour,
            label=f"{series_for(run.config_id).label} · {run.run_id}",
        )
        for run in window.current
    ]
    hex_svg = hex_grid(cells)

    # --- throughput per day --------------------------------------------------
    days = best_per_day(window)
    matrix = dot_matrix(
        [
            Column(
                label=day.label,
                value=day.best,
                caption=(
                    f"{day.label}: best {day.best:.0f} Mbit/s over {day.runs} run(s)"
                    if day.best is not None
                    else f"{day.label}: no run"
                ),
            )
            for day in days
        ],
        unit=" Mbit/s",
    )
    measured_days = [d for d in days if d.best is not None]
    period_best = max((d.best for d in measured_days), default=None)

    rows = topologies_needing_you(window)

    base = f"kind={kind}"
    period_options = [
        (key, label.replace("Last ", ""), f"/?period={key}&{base}", False)
        for key, (label, _) in PERIODS.items()
    ]
    kind_options = [
        (
            key,
            label,
            f"/?period={period}&kind={key}",
            key == "flagged" and any_flagged(window.all_runs),
        )
        for key, label in KINDS.items()
    ]

    return render(
        request,
        "overview/page.html",
        {
            "error": error,
            "window": window,
            "period": period,
            "kind": kind,
            "period_options": period_options,
            "kind_options": kind_options,
            "kpis": kpis,
            "shares": shares,
            "hex_svg": hex_svg,
            "matrix": matrix,
            "period_best": period_best,
            "measured_days": len(measured_days),
            "rows": rows,
            "tick_bar": tick_bar,
        },
    )


@router.get("/partials/status")
async def status_partial(request: Request):
    state = request.app.state
    status = await build_status(state.client, state.probe.result)
    return render(request, "components/status_strip.html", {"status": status})
