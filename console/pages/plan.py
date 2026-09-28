"""The Test Plan page: build one test, check what can be checked, save it.

The console never assembles a ``config_id``. The selection goes to
``POST /validate`` and then ``POST /testdef/generate``, and the id that comes
back is displayed read-only (TP-08). A hand-built id once dropped a field and
put six malformed points into the results bucket; there is one source and this
page uses it.

Readiness is ETHOS's own: ``POST /readiness`` returns seven checks and this page
renders them in ETHOS's order, adding none of its own (TP-23). The traffic parse
stays, but only as a form hint beside the fields, so a rate ETHOS would reject is
caught while typing rather than becoming an eighth opinion about readiness.

RUN is ``POST /jobs/preview``, the preview shown in a dialog, then ``POST /jobs``
with the token it returned, then the job's page (design section 7.2).
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from fastapi import APIRouter, Form, Request
from starlette.responses import RedirectResponse, Response

from console import holders, readiness as readiness_mod
from console.plans import PlanError, PlanStore
from console.rapps.ethos.cli import campaign_command
from console.rapps.ethos.client import (
    EthosError,
    EthosRefused,
    EthosStateChanged,
)
from console.rapps.ethos.plan import TrafficPlan
from console.rapps.ethos.profiles import OPTION_REASONS, load_profiles
from console.topology import build_presets, diagram
from console.vendors import mark_for
from console.templating import render

router = APIRouter()

DEFAULTS: dict[str, str] = {
    "gnb_stack": "OCUDU",
    "split_kind": "monolithic",
    "cu_vendor": "OCUDU",
    "du_vendor": "OCUDU",
    "l1_backend": "software-PHY",
    "ru": "Pegatron",
    "ue": "Samsung",
    "core": "Open5GS",
    "server": "joule",
    "direction": "DL",
    "rates": "100-1000:100",
    "duration": "30s",
    "repeats": "1",
    "iperf_server": "app_binary",
    "label": "",
}



BLURBS: dict[tuple[str, str], str] = {
    ("gnb_stack", "OCUDU"): "The lab's own CU/DU stack",
    ("gnb_stack", "OAI"): "OpenAirInterface 5G gNB",
    ("l1_backend", "software-PHY"): "The DU runs its own L1 on the host CPU",
    ("l1_backend", "Aerial-cuBB"): "NVIDIA high-PHY over nvIPC, on the DGX-Spark",
    ("ru", "Pegatron"): "7.2x split O-RU, the lab's usual radio",
    ("ru", "Foxconn"): "7.2x split O-RU",
    ("ru", "TM500"): "RU emulated by the VIAVI instrument",
    ("ue", "Samsung"): "Android handset, driven over adb",
    ("ue", "MTK"): "MediaTek handset, driven over adb",
    ("ue", "Pegatron-Dongle"): "USB dongle UE, driven over SSH",
    ("ue", "TM500"): "UE emulated by the VIAVI instrument",
    ("core", "Open5GS"): "The core the testbed normally runs",
    ("core", "free5GC"): "An alternative 5G core",
    ("server", "joule"): "StarlingX worker, DU on socket 1",
    ("server", "DGX-Spark"): "GB10 ARM host for Aerial",
}

SPLIT_CARDS_WITH_MARK = (
    ("monolithic", "Monolithic", "", "CU and DU in one process of the gNB stack", None),
    ("CU+DU", "CU + DU", "", "CU and DU as separate releases, joined over F1", None),
)


def vendor_cards(catalogue) -> list[tuple[str, str, str, str, object]]:
    """The two vendors, as CU or DU. Same marks as the gNB stack they name."""
    return [
        (value, value, "", BLURBS.get(("gnb_stack", value), ""), mark_for("gnb_stack", value))
        for value in ("OCUDU", "OAI")
    ]


def topology_label(selection: dict[str, Any]) -> str:
    """What the chosen topology is called, from ETHOS's own series names."""
    from console.topology import HEADS, LABELS, PRESET_SELECTIONS

    split = selection.get("gnb_split")
    stack = selection.get("gnb_stack")
    for profile, wanted in PRESET_SELECTIONS.items():
        if wanted["gnb_split"] == split and wanted["gnb_stack"] == stack:
            return LABELS[profile]
    return f"{stack} {split}"


def card_list(catalogue, category: str) -> list[tuple[str, str, str, str, object]]:
    """(value, label, reason, blurb, vendor mark) for the picker's cards."""
    return [
        (
            value,
            label,
            reason,
            BLURBS.get((category, value), ""),
            mark_for(category, value),
        )
        for value, label, reason in option_list(catalogue, category)
    ]


def option_list(catalogue, category: str) -> list[tuple[str, str, str]]:
    """(value, label, reason-it-is-disabled) for one catalogue category.

    The label is always what is shown (GL-05). A reason comes from
    ``OPTION_REASONS``, every entry there was checked against the deploy
    profiles and the chart values on this host, and each one disappears as
    ``GET /catalogue`` (B4) starts carrying ETHOS's own reason per option.
    """
    if catalogue is None:
        return []
    out: list[tuple[str, str, str]] = []
    for option in catalogue.category(category):
        value = option.id or option.slug or ""
        reason = OPTION_REASONS.get((category, value), "")
        if not reason and (option.status or "") == "experimental":
            reason = ""  # experimental is selectable; it is a warning, not a block
        out.append((value, option.display, reason))
    return out


def _store(request: Request) -> PlanStore:
    return PlanStore(request.app.state.settings.plans_dir)


def _form_values(request: Request, source: dict[str, Any] | None = None) -> dict[str, Any]:
    values = dict(DEFAULTS)
    if source:
        for key in values:
            if key in source and source[key] not in (None, ""):
                values[key] = str(source[key])
        values["radio_samples"] = bool(source.get("radio_samples"))
    else:
        values["radio_samples"] = False

    # A disabled radio group submits nothing, and a group that has just become
    # selectable should start at the gNB stack's own vendor rather than at
    # whatever the previous selection left behind.
    stack = values["gnb_stack"]
    if values["split_kind"] != "CU+DU":
        values["cu_vendor"] = values["du_vendor"] = stack
    else:
        source_keys = source or {}
        if not source_keys.get("cu_vendor"):
            values["cu_vendor"] = stack
        if not source_keys.get("du_vendor"):
            values["du_vendor"] = stack
    return values


MONOLITHIC_TOOLTIP = (
    "Monolithic runs CU and DU in one process of the gNB stack"
)


def resolve_split(values: dict[str, Any]) -> tuple[str, str]:
    """The catalogue's ``gnb_split`` id, and the stack that owns the topology.

    The catalogue spells the four splits ``monolithic``, ``CU+DU``,
    ``OCUDU-CU+OAI-DU`` and ``OAI-CU+OCUDU-DU``. The form asks the question the
    way requirements TP-02 does, monolithic or CU+DU, then a CU vendor and a DU
    vendor, and this maps the answer onto the catalogue's own ids.

    Monolithic has no CU or DU vendor to choose: both halves are the gNB stack,
    in one process. The form shows them as the stack's value and disabled, and
    this ignores whatever they hold, so a vendor left over from a CU+DU
    selection cannot leak into a monolithic config_id.
    """
    kind = values.get("split_kind", "monolithic")
    stack = str(values.get("gnb_stack", "OCUDU"))
    if kind != "CU+DU":
        return "monolithic", stack

    cu = str(values.get("cu_vendor", stack))
    du = str(values.get("du_vendor", stack))
    if cu == du:
        return "CU+DU", cu
    if cu == "OCUDU" and du == "OAI":
        return "OCUDU-CU+OAI-DU", "OCUDU"
    if cu == "OAI" and du == "OCUDU":
        return "OAI-CU+OCUDU-DU", "OAI"
    return "CU+DU", stack


def vendor_fields(values: dict[str, Any]) -> dict[str, Any]:
    """How the CU and DU vendor groups are presented for this form state.

    Monolithic: both follow the gNB stack and are disabled, with the reason.
    CU + DU: both selectable, defaulting to the gNB stack's vendor, so opening
    the split does not silently propose a cross-vendor F1 nobody asked for.
    """
    stack = str(values.get("gnb_stack", "OCUDU"))
    split_is_cudu = values.get("split_kind") == "CU+DU"
    if not split_is_cudu:
        return {
            "enabled": False,
            "cu": stack,
            "du": stack,
            "reason": MONOLITHIC_TOOLTIP,
        }
    return {
        "enabled": True,
        "cu": str(values.get("cu_vendor") or stack),
        "du": str(values.get("du_vendor") or stack),
        "reason": "",
    }


def selection_from(values: dict[str, Any]) -> dict[str, str]:
    split, stack = resolve_split(values)
    return {
        "ue": str(values["ue"]),
        "ru": str(values["ru"]),
        "gnb_stack": stack,
        "gnb_split": split,
        "l1_backend": str(values["l1_backend"]),
        "core": str(values["core"]),
        "server": str(values["server"]),
    }


async def _build(request: Request, values: dict[str, Any]) -> dict[str, Any]:
    """Everything the right-hand panel shows for one form state."""
    client = request.app.state.client
    caps = request.app.state.probe.result
    settings = request.app.state.settings

    selection = selection_from(values)
    traffic = TrafficPlan(
        rates_text=str(values["rates"]),
        direction=str(values["direction"]),
        duration_text=str(values["duration"]),
        repeats=int(values["repeats"]) if str(values["repeats"]).isdigit() else 0,
        iperf_server=str(values["iperf_server"]),
        radio_samples=bool(values.get("radio_samples")),
        label=str(values["label"]),
    ).parse()

    validation = None
    generated = None
    config_id = None
    ethos_error = None
    try:
        validation = await client.validate(selection)
        if validation.valid:
            generated = await client.testdef_generate({"selection": selection})
            config_id = generated.test_definition.config_id
    except EthosError as exc:
        ethos_error = exc.message

    profiles = load_profiles(settings.deploy_profiles)
    deployable, deploy_reason = profiles.deployable(selection)
    profile = profiles.resolve(selection) if profiles.available else None

    # Readiness is ETHOS's (B5). The console renders the seven checks in the
    # order they came back and adds none of its own: `POST /readiness` exists so
    # that the CLI and the console judge readiness identically, and a check
    # invented here would be a second opinion.
    document = traffic.as_document(config_id, selection)

    lock = None
    readiness = None
    readiness_error = None
    try:
        # Uncached and separate: the lock is what decides whether RUN is offered,
        # and it is also how the holder is worded, consistently with the strip.
        lock = await client.lock()
    except EthosError as exc:
        readiness_error = exc.message

    if config_id:
        try:
            readiness = await client.readiness(document)
        except EthosError as exc:
            readiness_error = exc.message

    if readiness is not None:
        checks = readiness_mod.rows(readiness, lock, tz=settings.tz)
    elif config_id is None:
        checks = readiness_mod.unavailable(
            ethos_error or "the selection has no config_id yet, so nothing was judged"
        )
    else:
        checks = readiness_mod.unavailable(
            readiness_error or "ETHOS did not answer the readiness request"
        )
    # A FAILURE blocks; an unknown does not. That is ETHOS's own rule, and the
    # button follows it: a check that could not be made must not refuse a run
    # that would have worked.
    first_blocker = readiness_mod.first_failure(checks)
    unknowns = [row for row in checks if row.status == "unknown"]

    run_ready = caps.ready("jobs") and caps.ready("readiness")
    if not caps.ready("jobs"):
        run_reason = caps.why("jobs")
    elif not caps.ready("readiness"):
        run_reason = caps.why("readiness")
    elif readiness is None:
        run_reason = readiness_error or "readiness has not been judged for this plan"
    elif first_blocker is not None:
        run_reason = f"{first_blocker.label}: {first_blocker.reason}"
    else:
        run_reason = ""

    # The console's own parse is a FORM HINT and nothing more. It is deliberately
    # not allowed to disable RUN: its bounds are the console's, ETHOS's
    # `traffic_plan` check is the authority, and the two do not agree everywhere
    # (the console suggests a 5 s minimum; ETHOS accepts shorter). A hint that
    # blocked would refuse plans ETHOS would have run.
    can_run = bool(run_ready and readiness is not None and not run_reason)

    command = campaign_command(
        ethos_repo=settings.ethos_repo,
        topology=profile.name if profile and profile.deployable else None,
        rates=traffic.rates_text,
        direction=traffic.direction,
        duration_s=traffic.duration_s or 0,
        repeats=traffic.repeats,
        radio_samples=traffic.radio_samples,
        core=str(values["core"]),
        ue=str(values["ue"]),
    )

    catalogue = None
    catalogue_error = None
    try:
        catalogue = await client.compatibility()
    except EthosError as exc:
        catalogue_error = exc.message

    return {
        "values": values,
        "vendors": vendor_fields(values),
        "selection": selection,
        "catalogue": catalogue,
        "catalogue_error": catalogue_error,
        "options": {
            category: option_list(catalogue, category)
            for category in ("gnb_stack", "l1_backend", "ru", "ue", "core", "server")
        },
        "cards": {
            **{
                category: card_list(catalogue, category)
                for category in ("gnb_stack", "l1_backend", "ru", "ue", "core", "server")
            },
            "split": list(SPLIT_CARDS_WITH_MARK),
            "cu_vendor": vendor_cards(catalogue),
            "du_vendor": vendor_cards(catalogue),
        },
        "topology_svg": diagram(selection, split=selection["gnb_split"]),
        "topology_label": topology_label(selection),
        "traffic": traffic,
        "validation": validation,
        "generated": generated,
        "config_id": config_id,
        "ethos_error": ethos_error,
        "profiles": profiles,
        "profile": profile,
        "deployable": deployable,
        "deploy_reason": deploy_reason,
        "checks": checks,
        "readiness": readiness,
        "readiness_error": readiness_error,
        "lock": lock,
        "lock_text": holders.describe(lock, tz=settings.tz),
        "unknowns": unknowns,
        "first_blocker": first_blocker,
        "can_run": can_run,
        "run_reason": run_reason,
        "run_ready": run_ready,
        "document": document,
        "document_json": json.dumps(document, indent=2),
        "document_yaml": yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        "command": command,
    }


async def _presets(request: Request, values: dict[str, Any]) -> list:
    """The wired profiles, each with the date and result of its last run."""
    from console.rapps.ethos.client import EthosError

    settings = request.app.state.settings
    profiles = load_profiles(settings.deploy_profiles)
    runs: list = []
    try:
        runs = (await request.app.state.client.runs()).runs
    except EthosError:
        runs = []

    defaults = {
        "ue": values["ue"], "ru": values["ru"], "l1_backend": values["l1_backend"],
        "core": values["core"], "server": values["server"],
    }
    presets = build_presets(profiles, defaults, runs)
    for preset in presets:
        preset.diagram = diagram(preset.selection, split=preset.split, size="mini")
    return presets


@router.get("/plan")
async def plan_page(request: Request, load: str = ""):
    store = _store(request)
    loaded = None
    error = None
    if load:
        try:
            loaded = store.get(load)
        except PlanError as exc:
            error = str(exc)

    source: dict[str, Any] = {}
    if loaded:
        plan = loaded.plan
        source = dict(plan.get("selection") or {})
        split = source.get("gnb_split", "monolithic")
        source["split_kind"] = "monolithic" if split == "monolithic" else "CU+DU"
        if split == "OCUDU-CU+OAI-DU":
            source["cu_vendor"], source["du_vendor"] = "OCUDU", "OAI"
        elif split == "OAI-CU+OCUDU-DU":
            source["cu_vendor"], source["du_vendor"] = "OAI", "OCUDU"
        else:
            stack = source.get("gnb_stack", "OCUDU")
            source["cu_vendor"] = source["du_vendor"] = stack
        source.update(
            {
                "direction": plan.get("direction"),
                "rates": plan.get("rates"),
                "duration": plan.get("duration"),
                "repeats": plan.get("repeats"),
                "iperf_server": plan.get("iperf_server"),
                "label": plan.get("label"),
                "radio_samples": plan.get("radio_samples"),
            }
        )

    values = _form_values(request, source or None)
    context = await _build(request, values)

    context.update(
        {
            "saved": store.list(),
            "loaded": loaded,
            "load_error": error,
            "presets": await _presets(request, values),
        }
    )
    return render(request, "plan/page.html", context)


async def _values_from_request(request: Request) -> dict[str, Any]:
    form = await request.form()
    source = {key: form.get(key) for key in DEFAULTS}
    source["radio_samples"] = form.get("radio_samples") in ("1", "on", "yes", "true")
    return _form_values(request, source)


@router.post("/plan/resolve")
async def plan_resolve(request: Request):
    """Re-resolve the plan after any change: validate, generate the config_id,
    re-run what readiness can answer (TP-24's debounce lives in the page)."""
    values = await _values_from_request(request)
    context = await _build(request, values)
    return render(request, "plan/resolved.html", context)


@router.post("/plan/save")
async def plan_save(request: Request):
    form = await request.form()
    name = str(form.get("name") or "").strip()
    values = await _values_from_request(request)
    context = await _build(request, values)
    try:
        saved = _store(request).save(name or "plan", context["document"])
    except PlanError as exc:
        return render(
            request,
            "plan/resolved.html",
            {**context, "save_error": str(exc)},
            status_code=422,
        )
    return render(
        request,
        "plan/resolved.html",
        {**context, "saved_note": f"Saved as {saved.name} in {saved.path.parent}"},
        headers={
            "X-Console-Toast": f"Plan saved as {saved.name}",
            "X-Console-Toast-Variant": "success",
        },
    )


@router.post("/plan/run")
async def plan_run(request: Request):
    """RUN, step one: ask ETHOS what starting this plan would do.

    Sends nothing to the testbed. What comes back is ETHOS's own preview text and
    a token bound to the plan AND to the testbed state it was computed against,
    which is what makes the 412 on confirm meaningful (design section 7.2).

    The readiness re-check here is the belt to the disabled button's brace: a
    stale page, a keyboard or a second tab must not be able to post a start that
    ETHOS has no way to honour.
    """
    values = await _values_from_request(request)
    context = await _build(request, values)
    if not context["can_run"]:
        return render(
            request,
            "plan/resolved.html",
            {**context, "run_error": context["run_reason"]},
            status_code=409,
            headers={
                "X-Console-Toast": context["run_reason"],
                "X-Console-Toast-Variant": "warning",
            },
        )

    client = request.app.state.client
    try:
        preview = await client.job_preview(context["document"])
    except EthosRefused as exc:
        return _refused(request, context, exc)
    except EthosError as exc:
        return render(
            request,
            "plan/resolved.html",
            {**context, "run_error": exc.message},
            status_code=exc.status or 502,
            headers={
                "X-Console-Toast": exc.message,
                "X-Console-Toast-Variant": "danger",
            },
        )

    return render(
        request,
        "plan/confirm.html",
        {**context, "preview": preview},
    )


@router.post("/plan/start")
async def plan_start(request: Request):
    """RUN, step two: the operator has seen the preview and confirmed it.

    Everything that can go wrong here is ETHOS telling the console something it
    could not have known when the preview was made, and each has its own answer
    (design section 7.5):

    409, somebody took the testbed in between. An amber toast naming the holder,
    and the readiness panel re-rendered so the lock line shows it too.

    412, the testbed changed after the preview. The same, plus the reason: the
    token was bound to a state that no longer holds, and confirming it anyway
    would be confirming something other than what was shown.

    On success the job exists and has its own page, so the browser goes there.
    """
    form = await request.form()
    token = str(form.get("preview_token") or "")
    values = await _values_from_request(request)
    context = await _build(request, values)

    if not token:
        return render(
            request,
            "plan/resolved.html",
            {**context, "run_error": "That confirmation had no token; ask for the preview again."},
            status_code=422,
        )

    client = request.app.state.client
    try:
        job = await client.job_start(context["document"], token)
    except EthosRefused as exc:
        return _refused(request, context, exc)
    except EthosStateChanged as exc:
        # Readiness is re-run by _build above, so the panel in this response
        # already shows whatever changed.
        return render(
            request,
            "plan/resolved.html",
            {**context, "run_error": f"{exc.message} Readiness has been re-checked."},
            status_code=412,
            headers={
                "X-Console-Toast": exc.message,
                "X-Console-Toast-Variant": "warning",
            },
        )
    except EthosError as exc:
        return render(
            request,
            "plan/resolved.html",
            {**context, "run_error": exc.message},
            status_code=exc.status or 502,
            headers={
                "X-Console-Toast": exc.message,
                "X-Console-Toast-Variant": "danger",
            },
        )

    # The strip's cached summary would otherwise show "no job" for a few seconds
    # after starting one.
    client.invalidate()
    return Response(
        status_code=204,
        headers={
            "HX-Redirect": f"/jobs/{job.job_id}",
            "X-Console-Toast": f"Job {job.job_id} started",
            "X-Console-Toast-Variant": "success",
        },
    )


def _refused(request: Request, context: dict[str, Any], exc: EthosRefused) -> Response:
    """409: somebody else holds the testbed. Name them, in the usual wording."""
    detail = exc.body.get("detail", exc.body) if isinstance(exc.body, dict) else {}
    who = holders.describe(detail, tz=request.app.state.settings.tz)
    message = (
        f"The testbed is held by {who}."
        if who != holders.FREE
        else exc.message
    )
    return render(
        request,
        "plan/resolved.html",
        {**context, "run_error": message},
        status_code=409,
        headers={
            "X-Console-Toast": message,
            "X-Console-Toast-Variant": "warning",
        },
    )


@router.post("/plan/delete")
async def plan_delete(request: Request, name: str = Form(...)):
    try:
        _store(request).delete(name)
    except PlanError:
        pass
    return RedirectResponse("/plan", status_code=303)


@router.post("/plan/download")
async def plan_download(request: Request, fmt: str = Form(default="json")):
    values = await _values_from_request(request)
    context = await _build(request, values)
    label = context["values"]["label"] or "test-plan"
    if fmt == "yaml":
        return Response(
            context["document_yaml"],
            media_type="application/yaml",
            headers={"content-disposition": f'attachment; filename="{label}.yaml"'},
        )
    return Response(
        context["document_json"],
        media_type="application/json",
        headers={"content-disposition": f'attachment; filename="{label}.json"'},
    )
