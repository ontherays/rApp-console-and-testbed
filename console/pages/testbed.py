"""The Testbed page: the UE panel, and what is deployed.

The UE half is live (B11). Every read is a read, and every action goes through
ETHOS's own preview and then a confirmation carrying its token, so a click can
never be the thing that acts (GL-07).

**Nothing here reaches a handset.** The console has no adb, no SSH and no
credentials; it asks ETHOS, which holds them (SE-06). What the page adds is the
ordering an operator needs: see the state, see what an action would do, then do
it, and see the state again.

Deploy and teardown are still out. ETHOS has the preview gate for them now, but a
deploy is minutes of a shared testbed and belongs with the job that needs it,
which is what RUN already does. A standalone deploy button would offer a second
way to occupy the testbed with no run to attribute it to.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Request
from starlette.responses import Response

from console import holders
from console.rapps.ethos.client import (
    EthosError,
    EthosNotImplemented,
    EthosRefused,
    EthosStateChanged,
)
from console.templating import render

router = APIRouter()

#: The three actions this page offers, and what each one is called. Each is
#: preview-then-confirm; the path is ETHOS's own.
ACTIONS: dict[str, str] = {
    "attach": "Attach",
    "detach": "Detach",
    "iperf/stop": "Stop the iperf app",
}


@dataclass(frozen=True)
class UeView:
    """One UE row, with the port-5201 holder beside it where there is one."""

    entry: object
    iperf: object | None = None
    iperf_error: str = ""


async def _ue_views(client, *, with_iperf: bool = True) -> tuple[list[UeView], str]:
    """Every UE, each with its iperf port read where the UE has an adb path."""
    try:
        listing = await client.ues()
    except EthosError as exc:
        return [], exc.message

    views: list[UeView] = []
    for entry in listing.ues:
        iperf = None
        iperf_error = ""
        if with_iperf and entry.driven:
            try:
                iperf = await client.ue_iperf(entry.ue.lower())
            except EthosNotImplemented as exc:
                # A driven UE with no adb path, the Pegatron dongle for instance.
                # Not an error: the port simply cannot be read on it.
                iperf_error = exc.message
            except EthosError as exc:
                iperf_error = exc.message
        views.append(UeView(entry=entry, iperf=iperf, iperf_error=iperf_error))
    return views, ""


@router.get("/testbed")
async def testbed(request: Request):
    client = request.app.state.client
    settings = request.app.state.settings

    lock = None
    lock_error = ""
    try:
        lock = await client.lock()
    except EthosError as exc:
        lock_error = exc.message

    views, ue_error = await _ue_views(client)

    deployed = None
    deploy_error = ""
    try:
        deployed = await client.deploy_status()
    except EthosError as exc:
        deploy_error = exc.message

    return render(
        request,
        "testbed/page.html",
        {
            "views": views,
            "ue_error": ue_error,
            "lock": lock,
            "lock_error": lock_error,
            "lock_text": holders.describe(lock, tz=settings.tz),
            "deployed": deployed,
            "deploy_error": deploy_error,
        },
    )


@router.get("/testbed/ue")
async def testbed_ue_partial(request: Request):
    """The UE table on its own, for swapping in after an action."""
    views, ue_error = await _ue_views(request.app.state.client)
    return render(request, "testbed/ue_table.html", {"views": views, "ue_error": ue_error})


@router.post("/testbed/ue/{ue}/{action:path}/preview")
async def ue_preview(request: Request, ue: str, action: str):
    """ETHOS's own description of what the action would do, in a dialog.

    Sends nothing to the handset beyond reading its current state. The token it
    returns is bound to that state, so a UE that changes before the confirmation
    arrives makes the confirmation fail rather than act on a stale picture.
    """
    if action not in ACTIONS:
        return Response(status_code=404)
    client = request.app.state.client
    try:
        preview = await client.ue_preview(ue, action)
    except EthosRefused as exc:
        return _toast(exc.message, "warning", 409)
    except EthosError as exc:
        return _toast(exc.message, "danger", exc.status or 502)
    return render(
        request,
        "testbed/ue_confirm.html",
        {"preview": preview, "ue": ue, "action": action, "action_label": ACTIONS[action]},
    )


@router.post("/testbed/ue/{ue}/{action:path}")
async def ue_act(request: Request, ue: str, action: str):
    """Do it, with the token from the preview the operator just saw.

    An attach can take minutes: ETHOS toggles the radio, waits for the handset to
    settle and reads the address back, and refuses rather than claim an attach it
    could not confirm. A 503 from it is therefore a real answer about the UE, not
    a transport problem, so its message is shown as ETHOS wrote it.
    """
    if action not in ACTIONS:
        return Response(status_code=404)
    form = await request.form()
    token = str(form.get("preview_token") or "")
    if not token:
        return _toast("That confirmation had no token; ask for the preview again.", "warning", 422)

    client = request.app.state.client
    try:
        await client.ue_act(ue, action, token)
    except EthosRefused as exc:
        detail = exc.body.get("detail", exc.body) if isinstance(exc.body, dict) else {}
        who = holders.describe(detail, tz=request.app.state.settings.tz)
        message = (
            f"The testbed is held by {who}." if who != holders.FREE else exc.message
        )
        return _toast(message, "warning", 409)
    except EthosStateChanged as exc:
        return _toast(f"{exc.message} Ask for the preview again.", "warning", 412)
    except EthosError as exc:
        # ETHOS's own status is passed on rather than flattened to 502. A 503
        # here is a considered answer about the UE ("toggled but holds no
        # address"), not a gateway problem, and a browser's network tab should
        # not say otherwise.
        return _toast(exc.message, "danger", exc.status or 502)

    client.invalidate()
    label = ACTIONS[action]
    return Response(
        status_code=204,
        headers={
            "HX-Redirect": "/testbed",
            "X-Console-Toast": f"{label} done on {ue}.",
            "X-Console-Toast-Variant": "success",
        },
    )


def _toast(message: str, variant: str, status: int) -> Response:
    return Response(
        status_code=status,
        headers={"X-Console-Toast": message, "X-Console-Toast-Variant": variant},
    )
