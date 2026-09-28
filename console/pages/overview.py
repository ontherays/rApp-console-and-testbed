"""The Overview: what this testbed has been doing, and what needs attention.

Each tile and chart is computed from the run archive, which is the only thing
the console can read without a credential. Values ETHOS cannot answer yet, the
lock, the running job, the UE, name the backend change instead of guessing.
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
from console import holders
from console.rapps.ethos.client import EthosError
from console.rapps.ethos.series import series_for
from console.status import build_status
from console.templating import render

router = APIRouter()


def _age(iso: str | None, now: datetime) -> tuple[str, str, str]:
    """(value, unit, tone) for a timestamp's age. Green under a day, amber under
    a week, red beyond, with the words present as well as the colour."""
    moment = parse_utc(iso)
    if moment is None:
        return ",", "", "slate"
    hours = (now - moment).total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}", "min ago", "teal"
    if hours < 48:
        return f"{hours:.0f}", "h ago", "teal" if hours < 24 else "orange"
    days = hours / 24
    return f"{days:.0f}", "d ago", "orange" if days < 7 else "red"


def _lock_tile(summary, error: str | None, tz: str) -> dict:
    """Who holds the testbed (B1).

    A lock that was read and found free is a fact, so the tile says "free" rather
    than hedging. A holder is named the same way it is named everywhere else: a
    shell campaign reads "CLI campaign ...", because `cli:3340113` means nothing
    to somebody who did not start it.
    """
    if summary is None:
        return {"icon": "lock", "tone": "slate", "label": "Testbed lock",
                "value": "unknown", "small": True,
                "note": error or "not read", "note_icon": "info"}
    part = summary.lock
    if part.error:
        return {"icon": "lock", "tone": "slate", "label": "Testbed lock",
                "value": "unknown", "small": True, "note": part.error, "note_icon": "info"}
    if not part.held:
        return {"icon": "lock", "tone": "teal", "label": "Testbed lock",
                "value": holders.FREE, "small": True, "note": "nothing holds it"}
    return {
        "icon": "lock", "tone": "orange", "label": "Testbed lock",
        "value": holders.short(part), "small": True,
        "note": holders.describe(part, tz=tz),
        "href": f"/jobs/{part.job_id}" if part.is_job and part.job_id else None,
    }


def _deployed_tile(summary, error: str | None) -> dict:
    if summary is None:
        return {"icon": "testbed", "tone": "blue", "label": "Deployed now",
                "value": "unknown", "small": True, "note": error or "not read"}
    part = summary.deployed
    if part.error:
        return {"icon": "testbed", "tone": "blue", "label": "Deployed now",
                "value": "unknown", "small": True, "note": part.error}
    if part.anything_deployed:
        return {
            "icon": "testbed", "tone": "blue", "label": "Deployed now",
            "value": part.profile or part.stack or (
                ", ".join(str(r) for r in part.releases) or "something"
            ), "small": True,
            "note": f"{len(part.running_pods)} pod(s) running in {part.namespace}",
            "href": "/testbed",
        }
    return {"icon": "testbed", "tone": "blue", "label": "Deployed now",
            "value": "nothing", "small": True,
            "note": f"no release and no pod in {part.namespace}", "href": "/testbed"}


def _job_tile(summary, error: str | None) -> dict:
    """The latest job (B2). Its state is ETHOS's word, never inferred here."""
    if summary is None:
        return {"icon": "play", "tone": "purple", "label": "Latest job",
                "value": "unknown", "small": True, "note": error or "not read"}
    part = summary.latest_job
    if part.error:
        return {"icon": "play", "tone": "purple", "label": "Latest job",
                "value": "unknown", "small": True, "note": part.error}
    if not part.job_id:
        return {"icon": "play", "tone": "slate", "label": "Latest job",
                "value": "none", "small": True,
                "note": "no job has been started", "href": "/plan"}
    note = ", ".join(bit for bit in (part.label, part.progress and f"{part.progress} points") if bit)
    return {
        "icon": "play", "tone": "teal" if part.finished else "purple",
        "label": "Latest job", "value": part.state or "unknown", "small": True,
        "note": note or part.job_id, "href": f"/jobs/{part.job_id}",
    }


def _freshness_tile(summary, error: str | None) -> dict:
    """When each data source last said anything (B6).

    Three sources in one tile because they answer one question, and each is named
    in the note. A source that has never landed a point says so rather than
    reading as stale: never and old are different.
    """
    if summary is None:
        return {"icon": "clock", "tone": "slate", "label": "Data freshness",
                "value": ",", "note": error or "not read", "note_icon": "info"}
    part = summary.freshness
    if part.error:
        return {"icon": "clock", "tone": "slate", "label": "Data freshness",
                "value": ",", "note": part.error, "note_icon": "info"}

    landed: list[str] = []
    missing: list[str] = []
    newest_point: str | None = None
    for name, source in (("results", part.results), ("O1 PM", part.o1_pm),
                         ("O2 power", part.o2_power)):
        if source.last_point:
            landed.append(name)
            newest_point = max(newest_point or "", source.last_point)
        else:
            missing.append(name)

    now = datetime.now(timezone.utc)
    value, unit, tone = _age(newest_point, now)
    note = f"newest: {', '.join(landed)}" if landed else "nothing has landed"
    if missing:
        note += f" · nothing yet from {', '.join(missing)}"
    return {"icon": "clock", "tone": tone, "label": "Data freshness",
            "value": value, "unit": unit, "note": note, "note_icon": "info"}


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

    # One call for the lock, what is deployed, the latest job, the UE and data
    # freshness (B6). Each part carries its own error, so a probe that failed in
    # ETHOS greys out one tile instead of the row.
    summary = None
    summary_error = None
    try:
        summary = await client.status_summary()
    except EthosError as exc:
        summary_error = exc.message

    # --- the KPI row ---------------------------------------------------------
    lock_tile = _lock_tile(summary, summary_error, request.app.state.settings.tz)
    deployed_tile = _deployed_tile(summary, summary_error)
    job_tile = _job_tile(summary, summary_error)
    freshness_tile = _freshness_tile(summary, summary_error)

    best_now = best_at(window.current, 1000.0)
    best_before = best_at(window.previous, 1000.0)
    snr_now = median_snr(window.current)
    snr_before = median_snr(window.previous)
    latest = newest(runs)
    age_value, age_unit, age_tone = _age(latest.t_created if latest else None, now)

    kpis = [
        lock_tile,
        deployed_tile,
        job_tile,
        {
            "icon": "jobs", "tone": "purple", "label": f"Runs, {window.label.lower()}",
            "value": f"{len(window.current)}",
            "change": Change.between(
                float(len(window.current)), float(len(window.previous))
            ),
            "vs": f"vs {len(window.previous)}",
        },
        {
            "icon": "rate", "tone": "teal", "label": "Best DL at 1000 M",
            "value": f"{best_now:.0f}" if best_now is not None else ",",
            "unit": "Mbit/s" if best_now is not None else "",
            "change": Change.between(best_now, best_before, decimals=1, unit="Mbit/s"),
            "vs": f"vs {best_before:.0f}" if best_before is not None else "no previous run",
        },
        {
            "icon": "ru", "tone": "orange", "label": "Median PUSCH SNR",
            "value": f"{snr_now:.1f}" if snr_now is not None else ",",
            "unit": "dB" if snr_now is not None else "",
            "change": Change.between(snr_now, snr_before, decimals=1, unit="dB"),
            "vs": f"vs {snr_before:.1f} dB" if snr_before is not None else "no previous run",
            "note": None if snr_now is not None else "no run in this period recorded channel metrics",
        },
        freshness_tile,
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
            "summary": summary,
            "summary_error": summary_error,
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
