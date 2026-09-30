"""Jobs: the list, one job live, and stopping one.

A job is one campaign execution, and it runs **in ETHOS**. The console starts it,
watches it and asks it to stop, and does none of the work itself: a second
campaign executor, with the testbed lock living in a LAN-facing web process, is
the thing the design rules out. One executor, in ETHOS.

Watching is an SSE relay (`console/sse.py`). ETHOS numbers every event, the
browser remembers the last number it saw, and a reconnect resumes from there, so
a refresh or a dropped connection loses nothing (RN-07). The snapshot is fetched
alongside the stream, which is what makes arriving late work: a job that started
before this page was opened shows its steps and points immediately, then the
stream carries on from wherever the replay left off.

The console never infers a job state. `completed`, `failed`, `aborted` and
`interrupted` are ETHOS's words, and the page renders whichever one came back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, Request
from starlette.responses import Response

from console import holders
from console.rapps.ethos.client import EthosError, EthosRefused
from console.rapps.ethos.models import Job, Run
from console.sse import LAST_EVENT_ID, relay
from console.templating import render

router = APIRouter()


@dataclass
class CampaignRow:
    """A campaign as the run archive remembers it.

    Kept alongside the job list because the two answer different questions. A job
    is what ETHOS is doing or did in this process's memory of it; a campaign_id on
    a run is what the archive holds for ever, including every campaign run from a
    shell before jobs existed.
    """

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
    """Every job ETHOS knows about, newest first, and the archive's campaigns."""
    client = request.app.state.client
    settings = request.app.state.settings

    jobs_list: list[Job] = []
    jobs_error = None
    try:
        jobs_list = (await client.jobs()).jobs
    except EthosError as exc:
        jobs_error = exc.message

    lock = None
    try:
        lock = await client.lock()
    except EthosError:
        lock = None

    # Which sweeps are held out of normal graphs. Gated: when ETHOS has not got
    # B16 the panel says so and the buttons disable, rather than the page
    # failing on a call the backend cannot answer.
    caps = request.app.state.probe.result
    held, held_error = [], None
    if caps.ready("quarantine"):
        try:
            held = (await client.quarantine()).jobs
        except EthosError as exc:
            held_error = exc.message
    held_ids = {entry.job_id for entry in held}

    campaigns: list[CampaignRow] = []
    loose_runs = 0
    archive_error = None
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
        campaigns = sorted(grouped.values(), key=lambda c: c.last or "", reverse=True)
    except EthosError as exc:
        archive_error = exc.message

    return render(
        request,
        "jobs/page.html",
        {
            "jobs": jobs_list,
            "jobs_error": jobs_error,
            "running": [job for job in jobs_list if not job.finished],
            "lock": lock,
            "lock_text": holders.describe(lock, tz=settings.tz),
            "campaigns": campaigns,
            "loose_runs": loose_runs,
            "archive_error": archive_error,
            "held": held,
            "held_ids": held_ids,
            "held_error": held_error,
        },
    )


@router.get("/jobs/{job_id}")
async def job_page(request: Request, job_id: str):
    """One job: its snapshot now, and its events from here on.

    The snapshot is what makes opening this page halfway through a job useful.
    The stream is opened by the page itself, with the browser's own
    `Last-Event-ID` on a reconnect.
    """
    client = request.app.state.client
    job = None
    error = None
    try:
        job = await client.job(job_id)
    except EthosError as exc:
        error = exc.message

    return render(
        request,
        "jobs/job.html",
        {"job": job, "job_id": job_id, "error": error},
        status_code=200 if job else 404,
    )


@router.get("/jobs/{job_id}/stream")
async def job_stream(request: Request, job_id: str):
    """The SSE relay. ETHOS's stream, passed through unchanged.

    The browser's `Last-Event-ID` is forwarded verbatim; that header is the whole
    of the resume mechanism, and a relay that dropped it would turn a reconnect
    into either a replay from the start or a gap.
    """
    return await relay(
        request.app.state.client, job_id, request.headers.get(LAST_EVENT_ID)
    )


@router.get("/jobs/{job_id}/snapshot")
async def job_snapshot(request: Request, job_id: str):
    """The job's steps, points and state, for the stream to swap in.

    The events say what happened; this says where the job stands. Re-reading the
    snapshot when an event arrives is simpler than rebuilding the same state in
    the browser from the event history, and it cannot drift from what ETHOS holds.
    """
    client = request.app.state.client
    try:
        job = await client.job(job_id)
    except EthosError as exc:
        return render(
            request, "jobs/snapshot.html", {"job": None, "job_id": job_id, "error": exc.message}
        )
    return render(request, "jobs/snapshot.html", {"job": job, "job_id": job_id, "error": None})


@router.post("/jobs/{job_id}/stop/preview")
async def job_stop_preview(request: Request, job_id: str):
    """What stopping would do. Composed here, because ETHOS has no stop preview.

    The wording is ETHOS's behaviour, not a guess at it: `POST /jobs/{id}/stop`
    sets a flag, the campaign finishes the point it is measuring, then detaches
    and tears down, and the job ends `aborted` keeping every point it measured.
    """
    client = request.app.state.client
    job = None
    try:
        job = await client.job(job_id)
    except EthosError:
        job = None
    return render(request, "jobs/stop_confirm.html", {"job": job, "job_id": job_id})


@router.post("/jobs/{job_id}/stop")
async def job_stop(request: Request, job_id: str):
    """Ask the job to stop at the next point boundary."""
    client = request.app.state.client
    try:
        await client.job_stop(job_id)
    except EthosRefused as exc:
        return Response(
            status_code=409,
            headers={
                "X-Console-Toast": exc.message,
                "X-Console-Toast-Variant": "warning",
            },
        )
    except EthosError as exc:
        return Response(
            status_code=exc.status or 502,
            headers={
                "X-Console-Toast": exc.message,
                "X-Console-Toast-Variant": "danger",
            },
        )
    client.invalidate()
    return Response(
        status_code=204,
        headers={
            "HX-Redirect": f"/jobs/{job_id}",
            "X-Console-Toast": (
                "Stop requested. The current point finishes, then the testbed is "
                "torn down."
            ),
            "X-Console-Toast-Variant": "success",
        },
    )


@router.post("/jobs/{job_id}/quarantine/preview")
async def quarantine_preview(request: Request, job_id: str):
    """What holding this sweep out would cover. Sends nothing to the testbed.

    The reason travels with the preview so the dialog can show it back, but the
    token is bound to the job and the record, not to the wording: an operator
    may correct their own sentence before confirming.
    """
    form = dict(await request.form())
    reason = str(form.get("reason") or "").strip()
    try:
        preview = await request.app.state.client.quarantine_preview(job_id, reason)
    except EthosError as exc:
        return render(request, "jobs/quarantine_confirm.html",
                      {"job_id": job_id, "error": exc.message, "preview": None},
                      status_code=exc.status or 502)
    return render(request, "jobs/quarantine_confirm.html",
                  {"job_id": job_id, "preview": preview, "reason": reason,
                   "error": None})


@router.post("/jobs/{job_id}/quarantine")
async def quarantine_job(request: Request, job_id: str):
    """Hold this sweep out of normal graph generation. Deletes nothing."""
    form = dict(await request.form())
    try:
        await request.app.state.client.quarantine_add(
            job_id,
            reason=str(form.get("reason") or "").strip(),
            preview_token=str(form.get("preview_token") or ""),
        )
    except EthosError as exc:
        return render(request, "jobs/quarantine_result.html",
                      {"job_id": job_id, "error": exc.message},
                      status_code=exc.status or 502)
    return render(request, "jobs/quarantine_result.html",
                  {"job_id": job_id, "error": None, "quarantined": True})


@router.post("/jobs/{job_id}/restore")
async def restore_job(request: Request, job_id: str):
    """Let a held-out sweep back into normal graphs.

    ETHOS's restore is its own preview: called without a confirmation it
    describes what would return and hands back the token, so the console asks
    once and confirms with what it was given.
    """
    client = request.app.state.client
    try:
        preview = await client.quarantine_restore_preview(job_id)
        token = preview.get("preview_token") or ""
        await client.quarantine_restore(job_id, token)
    except EthosError as exc:
        return render(request, "jobs/quarantine_result.html",
                      {"job_id": job_id, "error": exc.message},
                      status_code=exc.status or 502)
    return render(request, "jobs/quarantine_result.html",
                  {"job_id": job_id, "error": None, "quarantined": False})
