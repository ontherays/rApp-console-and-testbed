"""Publication: make results durable, prove it, and get them to GitHub.

**No git here.** The console has no repository, no credentials and no
subprocess; it asks ETHOS, which holds all three (SE-06). Every button on this
page is one HTTP call to an endpoint that already existed for the CLI, so the
console and `python -m publication` cannot mean different things by "publish".

**The console does not sequence anything.** Publish is commit, then verify that
commit, then push -- in that order, and ETHOS owns it. A console that fired
publish and then push as two calls would be able to push a publication that did
not land in full, which is exactly the thing the backend refuses to do.

**Nothing here deletes.** Retention is shown and never acted on: pruning removes
results from the lab host and needs a person reading a list of what would go,
which is `python -m publication prune`. There is no endpoint behind a button
here that could remove an artifact, and there must not be one.

Reads do not touch GitHub. The status call asks the remote only when the
operator asks for it, so opening this page cannot fail because the network is
down, and the retention numbers on it are the LOCAL ones -- an upper bound on
what a prune would take, because prune also requires the remote to hold the
artifact.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from starlette.responses import Response

from console.rapps.ethos.client import (
    EthosError,
    EthosInvalid,
    EthosRefused,
    EthosStateChanged,
)
from console.templating import render

router = APIRouter()


def _toast(message: str, variant: str, status: int) -> Response:
    return Response(
        status_code=status,
        headers={"X-Console-Toast": message, "X-Console-Toast-Variant": variant},
    )


def _refusal(exc: EthosError) -> Response:
    """ETHOS's own words, in the tone its status code earns.

    A 409 here is the publication lock, not the testbed lock: a campaign and a
    publish do not block each other, and the message names the process that
    does hold it.
    """
    if isinstance(exc, EthosRefused):
        return _toast(exc.message, "warning", 409)
    if isinstance(exc, (EthosStateChanged, EthosInvalid)):
        return _toast(exc.message, "warning", exc.status or 422)
    return _toast(exc.message, "danger", exc.status or 502)


async def _status(client, *, remote: bool = False):
    try:
        return await client.publish_status(remote=remote), ""
    except EthosError as exc:
        return None, exc.message


@router.get("/publication")
async def publication(request: Request):
    """The state of the archive, and the four things an operator can do to it."""
    status, error = await _status(request.app.state.client)
    return render(request, "publication/page.html", {"status": status, "error": error})


@router.get("/publication/status")
async def publication_status(request: Request):
    """The status panel on its own, for swapping in after an action."""
    remote = request.query_params.get("remote") == "true"
    status, error = await _status(request.app.state.client, remote=remote)
    return render(request, "publication/status.html",
                  {"status": status, "error": error, "asked_remote": remote})


# --- publish, and publish + push ---------------------------------------------


@router.post("/publication/publish/preview")
async def publish_preview(request: Request, push: str = Form(default="")):
    """What publishing would make durable, from ETHOS, before anything is written.

    The token the dialog carries is bound to the exact CONTENT that preview
    described. A run enriched between the preview and the confirmation makes
    the confirmation fail rather than commit something the operator never saw.
    """
    try:
        preview = await request.app.state.client.publish_preview()
    except EthosError as exc:
        return _refusal(exc)

    if not preview.preview_token:
        return _toast(
            preview.detail or "nothing to publish, everything is already durable",
            "neutral", 200,
        )
    return render(request, "publication/publish_confirm.html",
                  {"preview": preview, "push": push == "true"})


@router.post("/publication/publish")
async def publish(
    request: Request,
    preview_token: str = Form(...),
    push: str = Form(default=""),
):
    """Confirm the publication the operator has just seen.

    `push` goes to ETHOS as part of this one request. It is not a second call
    the console makes afterwards: the backend commits, verifies the commit and
    only then pushes, and that ordering is not the console's to implement.
    """
    try:
        result = await request.app.state.client.publish(
            preview_token, push=push == "true")
    except EthosError as exc:
        return _refusal(exc)
    return render(request, "publication/result.html",
                  {"result": result, "asked_push": push == "true"})


# --- verify ------------------------------------------------------------------


@router.get("/publication/verify")
async def verify(request: Request):
    """A read. Publishes nothing, commits nothing, pushes nothing, deletes nothing."""
    try:
        verification = await request.app.state.client.publish_verify()
    except EthosError as exc:
        return _refusal(exc)
    return render(request, "publication/verification.html",
                  {"verification": verification})


# --- push on its own ---------------------------------------------------------


@router.post("/publication/push/preview")
async def push_preview(request: Request):
    """Which commit a push would send.

    Offered whether or not anything is pending, because the state this exists
    for -- committed here, not upstream -- has nothing pending.
    """
    try:
        preview = await request.app.state.client.publish_push_preview()
    except EthosError as exc:
        return _refusal(exc)

    if not preview.preview_token:
        return _toast(preview.detail or "there is nothing to push", "warning", 200)
    return render(request, "publication/push_confirm.html", {"preview": preview})


@router.post("/publication/push")
async def push(request: Request, preview_token: str = Form(...)):
    try:
        result = await request.app.state.client.publish_push(preview_token)
    except EthosError as exc:
        return _refusal(exc)
    return render(request, "publication/push_result.html", {"result": result})
