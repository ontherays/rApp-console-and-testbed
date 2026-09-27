"""Search: find a run, a configuration or a campaign by name.

The archive is the only thing there is to search: 528 run records keyed by
run_id, each carrying a config_id and sometimes a campaign_id. A single exact
run_id goes straight to that run; anything else lists what matched, grouped by
what kind of thing it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from console.rapps.ethos.client import EthosError
from console.rapps.ethos.models import Run
from console.rapps.ethos.series import series_for
from console.templating import render

router = APIRouter()

MAX_RUNS = 40


@dataclass
class Group:
    kind: str
    rows: list = field(default_factory=list)


@router.get("/search")
async def search(request: Request, q: str = ""):
    needle = q.strip()
    client = request.app.state.client
    error = None
    runs: list[Run] = []
    configs: list[tuple[str, int]] = []
    campaigns: list[tuple[str, int]] = []

    if needle:
        try:
            listing = await client.runs()
        except EthosError as exc:
            error = exc.message
            listing = None

        if listing is not None:
            lowered = needle.lower()

            exact = [r for r in listing.runs if r.run_id == needle]
            if exact:
                return RedirectResponse(f"/results/runs/{exact[0].run_id}", status_code=303)

            runs = [r for r in listing.runs if lowered in r.run_id.lower()]
            runs.sort(key=lambda r: r.t_created or "", reverse=True)

            config_counts: dict[str, int] = {}
            campaign_counts: dict[str, int] = {}
            for run in listing.runs:
                if run.config_id and lowered in run.config_id.lower():
                    config_counts[run.config_id] = config_counts.get(run.config_id, 0) + 1
                if run.campaign_id and lowered in run.campaign_id.lower():
                    campaign_counts[run.campaign_id] = campaign_counts.get(run.campaign_id, 0) + 1
            configs = sorted(config_counts.items(), key=lambda kv: -kv[1])
            campaigns = sorted(campaign_counts.items(), key=lambda kv: -kv[1])

    total = len(runs) + len(configs) + len(campaigns)
    return render(
        request,
        "search.html",
        {
            "q": needle,
            "runs": runs[:MAX_RUNS],
            "run_total": len(runs),
            "configs": [(cid, count, series_for(cid)) for cid, count in configs],
            "campaigns": campaigns,
            "total": total,
            "error": error,
        },
    )
