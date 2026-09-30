"""Graphs: ask ETHOS for a figure, and browse the ones that exist.

**The console draws nothing.** It fills in a form, posts it, and shows what came
back. Rendering the same numbers a second way in the browser would be a second
spelling of one figure, and the figure ETHOS produced is the one that goes into
a paper, archived with its manifest, `points.csv` and `raw.csv`.

**Every option comes from ETHOS.** The metrics, kinds, groupings, widths and
scales are `GET /plots/options`, so the form cannot offer a metric ETHOS has
dropped or hide one it has gained. The console hard-codes no list.

**The gallery is `GET /plots`**, not a directory listing. The console used to
read `ETHOS_GRAPH_DIR` off the disk, which only worked because the two happen to
run on one host and quietly assumed it; a figure is now something ETHOS serves,
like everything else.

Files are streamed through, with ETHOS's own content type and a filename built
from the figure's label, so a download lands as `full-sweep.png` rather than
`image.png`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from starlette.responses import Response, StreamingResponse

from console.rapps.ethos.client import EthosError, EthosInvalid
from console.templating import render

router = APIRouter()

#: The four files a figure serves, and what a download should be called.
DOWNLOADS: tuple[tuple[str, str, str], ...] = (
    ("image.png", "png", "PNG"),
    ("figure.pdf", "pdf", "PDF"),
    ("raw.csv", "raw.csv", "raw.csv"),
    ("points.csv", "points.csv", "points.csv"),
)

#: A plot request's fields, and how to read each one off the form. Kept as data
#: so the form and the request cannot disagree about a field's name.
FLAGS = ("allow_mixed_durations", "allow_unknown_server", "exclude_known_issues")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "on", "yes", "true")


async def _options(request: Request):
    """ETHOS's option table, or None when it could not be asked."""
    try:
        return await request.app.state.client.plot_options()
    except EthosError:
        return None


def _request_from(form: Any) -> dict[str, Any]:
    """The form as `POST /plots` takes it.

    Only fields the operator actually set are sent. An empty string for a
    source would ask ETHOS to plot nothing and get a 422 that blamed the
    operator for leaving a box alone.
    """
    body: dict[str, Any] = {}

    run_ids = [r.strip() for r in str(form.get("run_ids") or "").replace(",", " ").split()]
    if run_ids:
        body["run_ids"] = run_ids

    # The picker sends one `job_ids` per ticked box. The free-text Job field is
    # kept and still sent as `job_id`, so a bookmarked `/graphs?job_id=...` and
    # every existing caller behave exactly as before; ETHOS unions the two.
    job_ids = [j.strip() for j in (form.getlist("job_ids")
                                   if hasattr(form, "getlist") else
                                   (form.get("job_ids") or [])) if j and j.strip()]
    if job_ids:
        body["job_ids"] = job_ids

    for name in ("campaign_id", "job_id", "snapshot", "since", "until", "rates",
                 "label", "metric", "kind", "group_by", "width", "y_scale",
                 "direction", "source"):
        value = str(form.get(name) or "").strip()
        if value:
            body[name] = value
    config_ids = [c.strip() for c in str(form.get("config_ids") or "").split(",") if c.strip()]
    if config_ids:
        body["config_ids"] = config_ids

    minimum = str(form.get("min_duration_s") or "").strip()
    if minimum:
        try:
            body["min_duration_s"] = float(minimum)
        except ValueError:
            pass
    for flag in FLAGS:
        if _truthy(form.get(flag)):
            body[flag] = True
    if _truthy(form.get("include_quarantined")):
        body["include_quarantined"] = True
    return body


def _prefill(params) -> dict[str, Any]:
    """The form's starting values, from a query string.

    This is what makes "Graph these runs" work from Results, from a sweep and
    from a finished job: the entry point names the source and the metric, and
    the form opens already describing the figure that was asked for.
    """
    values: dict[str, Any] = {
        "source": params.get("source") or "",
        "run_ids": " ".join(params.getlist("run_id")) or params.get("run_ids") or "",
        "campaign_id": params.get("campaign_id") or "",
        "job_id": params.get("job_id") or "",
        "job_ids": params.getlist("job_ids") or
                   ([params["job_id"]] if params.get("job_id") else []),
        "include_quarantined": _truthy(params.get("include_quarantined")),
        "config_ids": params.get("config_ids") or "",
        "since": params.get("since") or "",
        "until": params.get("until") or "",
        "rates": params.get("rates") or "",
        "direction": params.get("direction") or "DL",
        "metric": params.get("metric") or "",
        "kind": params.get("kind") or "auto",
        "group_by": params.get("group_by") or "config",
        "width": params.get("width") or "single",
        "y_scale": params.get("y_scale") or "auto",
        "label": params.get("label") or "",
        "min_duration_s": params.get("min_duration_s") or "",
    }
    for flag in FLAGS:
        values[flag] = _truthy(params.get(flag))
    if not values["source"]:
        # Inferred from what was prefilled, so an entry point names the runs and
        # nothing else. A snapshot and a campaign each imply their own source.
        if values["run_ids"]:
            values["source"] = "runs"
        elif values["campaign_id"] or values["job_id"] or values["job_ids"]:
            values["source"] = "runs"
        else:
            values["source"] = "influx"
    return values


async def _job_choices(request, since: str = "", until: str = "") -> dict:
    """The jobs the picker offers, and which of them are quarantined.

    Built from `GET /jobs`, which already carries everything a row needs:
    the id, the state, the config, the plan's rates, and both run counts. A
    second endpoint for "this job's runs" would be a different spelling of data
    already in hand.

    Filtered by the form's own date range, so the list answers "what ran in the
    window I am plotting?" rather than "what has ever run?". A job with no
    created stamp is kept: dropping it would hide a job for a missing field.
    """
    client = request.app.state.client
    caps = request.app.state.probe.result

    jobs, error = [], None
    try:
        jobs = (await client.jobs()).jobs
    except EthosError as exc:
        error = exc.message

    held: dict = {}
    if caps.ready("quarantine"):
        try:
            held = (await client.quarantine()).by_job()
        except EthosError:
            held = {}

    start, end = (since or "").strip(), (until or "").strip()
    rows = []
    for job in jobs:
        created = (job.created or "")[:10]
        if start and created and created < start:
            continue
        if end and created and created > end:
            continue
        entry = held.get(job.job_id)
        rows.append({
            "job": job,
            "plottable": len({p.run_id for p in job.points if p.run_id}),
            "total": len(job.run_ids),
            "rates": (job.plan or {}).get("rates") or "",
            "quarantined": entry is not None,
            "reason": entry.reason if entry else "",
            "excluded_at": (entry.excluded_at[:10] if entry else ""),
        })
    return {"job_rows": rows, "jobs_error": error}


@router.get("/graphs")
async def graphs(request: Request):
    """The form, prefilled from the query string, and the gallery."""
    client = request.app.state.client
    options = await _options(request)

    figures: list = []
    gallery_error = None
    try:
        figures = await client.figures()
    except EthosError as exc:
        gallery_error = exc.message

    values = _prefill(request.query_params)
    return render(
        request,
        "graphs/page.html",
        {
            "options": options,
            "values": values,
            "figures": figures,
            "gallery_error": gallery_error,
            "result": None,
            **await _job_choices(request, values["since"], values["until"]),
        },
    )


@router.get("/graphs/metric-note")
async def metric_note(request: Request):
    """The caveat ETHOS attaches to the selected metric, swapped in on change.

    Served rather than embedded once, because the note belongs to whichever
    metric is chosen now, and a stale caveat beside a different metric is worse
    than none.
    """
    options = await _options(request)
    return render(
        request,
        "graphs/metric_note.html",
        {"options": options,
         "values": {"metric": request.query_params.get("metric") or ""}},
    )


@router.get("/graphs/jobs")
async def graph_jobs(request: Request):
    """The job picker, re-listed for a date range. Swapped in on change."""
    params = request.query_params
    return render(
        request,
        "graphs/jobs.html",
        {
            "values": {
                "job_ids": params.getlist("job_ids"),
                "include_quarantined": _truthy(params.get("include_quarantined")),
            },
            **await _job_choices(request, params.get("since") or "",
                                 params.get("until") or ""),
        },
    )


@router.post("/graphs/make")
async def make_graph(request: Request):
    """Draw one. ETHOS's refusal is shown as ETHOS worded it.

    A 422 is not a console error to translate: it says exactly what is wrong
    with the request, and the one case worth adding a button to is a point that
    would pool two run lengths, where the fix is a flag the operator has to set
    deliberately.
    """
    # NOT dict(await request.form()): a multi-select arrives as one repeated
    # key, and dict() keeps only the last of them, so ticking four jobs would
    # have sent one. The FormData itself carries getlist().
    form = await request.form()
    body = _request_from(form)

    try:
        result = await request.app.state.client.make_figure(body)
    except EthosInvalid as exc:
        # Only this panel is swapped, so the form keeps whatever the operator
        # typed, including anything they changed while waiting for the answer.
        return render(
            request,
            "graphs/result.html",
            {
                "error": exc.message,
                "retry_mixed": _flag_would_help(exc.message)
                and not body.get("allow_mixed_durations"),
                "mixed_durations": _is_mixed_duration(exc.message),
                "buckets": _buckets_in(exc.message),
                "result": None,
            },
            status_code=422,
        )
    except EthosError as exc:
        return render(
            request,
            "graphs/result.html",
            {"error": exc.message, "result": None},
            status_code=exc.status or 502,
        )

    return render(request, "graphs/result.html",
                  {"result": result, "error": None})


@router.post("/graphs/{figure_id}/regenerate")
async def regenerate(request: Request, figure_id: str):
    """Redraw a figure from its own snapshot, into a new folder."""
    try:
        result = await request.app.state.client.regenerate_figure(figure_id)
    except EthosError as exc:
        return Response(
            status_code=exc.status or 502,
            headers={"X-Console-Toast": exc.message,
                     "X-Console-Toast-Variant": "danger"},
        )
    return Response(
        status_code=204,
        headers={
            "HX-Redirect": f"/graphs/view/{result.figure_id}",
            "X-Console-Toast": f"Regenerated as {result.figure_id}",
            "X-Console-Toast-Variant": "success",
        },
    )


@router.get("/graphs/view/{figure_id}")
async def graph_detail(request: Request, figure_id: str):
    """One figure, from its manifest: the image, its warnings and its data."""
    from console.rapps.ethos.models import FigureResult

    try:
        manifest = await request.app.state.client.figure(figure_id)
    except EthosError as exc:
        return render(
            request, "graphs/detail.html",
            {"figure_id": figure_id, "result": None, "error": exc.message},
            status_code=exc.status or 502,
        )
    result = FigureResult.model_validate(
        {"figure_id": figure_id, "manifest": manifest,
         "warnings": manifest.get("warnings") or []}
    )
    return render(request, "graphs/detail.html",
                  {"figure_id": figure_id, "result": result, "error": None})


@router.get("/graphs/file/{figure_id}/{name}")
async def graph_file(request: Request, figure_id: str, name: str):
    """Stream one of a figure's four files through from ETHOS.

    Streamed rather than buffered: the console is a relay, and a PDF has no
    business sitting in the web process's memory. The filename is built from the
    figure's label so a download lands as `full-sweep.png` rather than as four
    files all called `image.png`.
    """
    served = {n for n, _suffix, _label in DOWNLOADS}
    if name not in served:
        return Response(status_code=404)

    client = request.app.state.client
    suffix = next(s for n, s, _ in DOWNLOADS if n == name)
    label = request.query_params.get("label") or figure_id
    filename = f"{_safe(label)}.{suffix}"

    upstream = client.figure_file_stream(figure_id, name)

    async def body():
        async with upstream as response:
            if response.status_code >= 400:
                await response.aread()
                return
            async for chunk in response.aiter_bytes():
                yield chunk

    # The content type is ETHOS's own; guessing it here would be a second
    # opinion about what the file is.
    media = {"image.png": "image/png", "figure.pdf": "application/pdf"}.get(
        name, "text/csv")
    return StreamingResponse(
        body(),
        media_type=media,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )


# --- small helpers ------------------------------------------------------------


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in text) or "figure"


def _is_mixed_duration(message: str) -> bool:
    """Whether this 422 is about run lengths at all. Both cases count."""
    text = (message or "").lower()
    return "duration" in text and ("pool" in text or "mix run durations" in text
                                   or "mix run durations across" in text)


def _flag_would_help(message: str) -> bool:
    """Whether `allow_mixed_durations` actually fixes THIS refusal.

    ETHOS refuses two different things and only one of them is a flag away.

    Lengths that differ BETWEEN points are a deliberate design (a ladder
    measured 30 s per rate with 150 s at the top), and the flag accepts it.

    Two lengths INSIDE one point is not: the mean would describe neither run,
    and ETHOS says in the same breath that the flag "does NOT permit it". So no
    retry button is offered there, because it would fail again in the same way
    and read as the console not understanding its own backend. The buckets are
    still listed, and ETHOS's own message already names the two fixes that do
    work.
    """
    text = (message or "").lower()
    if "does not permit it" in text:
        return False
    return _is_mixed_duration(message)


def _buckets_in(message: str) -> list[str]:
    """The run lengths ETHOS named, so the retry says what it is about to mix."""
    import re

    buckets: list[str] = []
    for group in re.findall(r"\[([\d,\s]+)\]\s*s", message or ""):
        for item in group.split(","):
            seconds = item.strip()
            if seconds and f"{seconds} s" not in buckets:
                buckets.append(f"{seconds} s")
    return buckets
