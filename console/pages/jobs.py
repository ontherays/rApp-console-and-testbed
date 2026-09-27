"""Jobs.

A job is one campaign execution, and ETHOS has no job model: ``/campaigns/{id}/run``
and ``/campaigns/{id}/status`` answer 501, and ``/jobs`` is not routed. The console
therefore does not run campaigns. It could, it has the same API the CLI drives,
and that is exactly why it must not: a second campaign executor beside
``python -m campaign``, with the lock in the web process rather than in ETHOS,
is the thing the design forbids.

So this page reports the gap, and shows what the archive does know: the campaigns
that have run, from the ``campaign_id`` on each run record.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, Request

from console.rapps.ethos.client import EthosError
from console.rapps.ethos.models import Run
from console.templating import render

router = APIRouter()


@dataclass
class CampaignRow:
    campaign_id: str
    runs: list[Run] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.runs)

    @property
    def first(self) -> str | None:
        times = sorted(r.t_created for r in self.runs if r.t_created)
        return times[0] if times else None

    @property
    def last(self) -> str | None:
        times = sorted(r.t_created for r in self.runs if r.t_created)
        return times[-1] if times else None

    @property
    def config_ids(self) -> list[str]:
        seen: list[str] = []
        for run in self.runs:
            if run.config_id and run.config_id not in seen:
                seen.append(run.config_id)
        return seen

    @property
    def rates(self) -> list[float]:
        return sorted({r.offered_mbps for r in self.runs if r.offered_mbps is not None})

    @property
    def delivered(self) -> int:
        return sum(1 for r in self.runs if r.has_delivered)


@router.get("/jobs")
async def jobs(request: Request):
    client = request.app.state.client
    error = None
    campaigns: list[CampaignRow] = []
    loose_runs = 0
    try:
        listing = await client.runs()
        grouped: dict[str, CampaignRow] = {}
        for run in listing.runs:
            if run.campaign_id:
                grouped.setdefault(
                    run.campaign_id, CampaignRow(campaign_id=run.campaign_id)
                ).runs.append(run)
            else:
                loose_runs += 1
        campaigns = sorted(
            grouped.values(), key=lambda c: c.last or "", reverse=True
        )
    except EthosError as exc:
        error = exc.message

    return render(
        request,
        "jobs/page.html",
        {"campaigns": campaigns, "loose_runs": loose_runs, "error": error},
    )
