"""The Test Plan page: build one test, check what can be checked, save it.

The console never assembles a ``config_id``. The selection goes to
``POST /validate`` and then ``POST /testdef/generate``, and the id that comes
back is displayed read-only (TP-08). A hand-built id once dropped a field and
put six malformed points into the results bucket; there is one source and this
page uses it.

RUN needs ``POST /jobs`` (B2), which does not exist. Rather than a button that
fails, the page ends in **Save plan** and the exact campaign command for the plan
on screen.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from fastapi import APIRouter, Form, Request
from starlette.responses import RedirectResponse, Response

from console.plans import PlanError, PlanStore
from console.rapps.ethos.cli import campaign_command
from console.rapps.ethos.client import EthosError
from console.rapps.ethos.plan import Check, TrafficPlan
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

    # The readiness panel shows all seven checks in ETHOS's order (TP-23). Only
    # the ones ETHOS can answer today carry a verdict; the rest say what they
    # are waiting for. The console adds no check of its own, and never marks an
    # item "pass" on its own authority.
    checks: list[Check] = []

    if ethos_error:
        checks.append(Check("topology", "Topology validates", "unknown", ethos_error))
    elif validation is None:
        checks.append(Check("topology", "Topology validates", "unknown", "not checked"))
    elif validation.valid:
        note = "valid" + (" · experimental combination" if validation.experimental else "")
        if deployable is True:
            checks.append(Check("topology", "Topology validates and is deployable",
                                "pass", f"{note} · {deploy_reason}"))
        elif deployable is False:
            checks.append(Check("topology", "Topology validates and is deployable",
                                "fail", deploy_reason))
        else:
            checks.append(Check("topology", "Topology validates and is deployable",
                                "unknown", f"{note} · deployability: {deploy_reason}"))
    else:
        checks.append(
            Check("topology", "Topology validates", "fail",
                  validation.first_error or "the selection is not allowed")
        )

    checks.append(Check("lock", "Testbed lock is free", "unknown", caps.why("lock")))

    # Naming the config_id is what makes ETHOS probe the node at all: it gates
    # the probe on the request naming a stack, so a bare call comes back
    # "the node was not observed" having never looked.
    node_check = Check("node_free", "Nothing else is deployed", "unknown", "not checked")
    try:
        deployed = await client.deploy_status(config_id=config_id)
        if deployed.anything_deployed:
            node_check = Check(
                "node_free",
                "Nothing else is deployed",
                "fail",
                f"{deployed.profile or deployed.stack or 'a stack'} is deployed in "
                f"{deployed.namespace} ({len(deployed.running_pods)} pod(s) running)",
            )
        elif deployed.node_free:
            node_check = Check(
                "node_free",
                "Nothing else is deployed",
                "pass",
                f"{deployed.namespace_summary}; {deployed.node_reason}",
            )
        elif deployed.node_free is False:
            node_check = Check(
                "node_free", "Nothing else is deployed", "fail", deployed.node_reason
            )
        else:
            # The namespace was answered either way; only the on-node process
            # check is missing, and the hover says why.
            node_check = Check(
                "node_free",
                "Nothing else is deployed",
                "unknown",
                f"{deployed.namespace_summary}, but the node itself was not "
                f"checked, {deployed.node_detail}",
            )
    except EthosError as exc:
        node_check = Check("node_free", "Nothing else is deployed", "unknown", exc.message)
    checks.append(node_check)

    checks.append(Check("ue_reachable", f"UE {values['ue']} is reachable", "unknown",
                        caps.why("ue")))
    mode = "an app_binary server holds 5201" if values["iperf_server"] == "app_binary" else "port 5201 is free"
    checks.append(Check("iperf_server", f"iperf server: {mode}", "unknown", caps.why("ue")))

    if traffic.valid:
        checks.append(Check(
            "traffic_plan", "Traffic plan parses", "pass",
            f"{len(traffic.rates)} rate(s) × {traffic.repeats} repeat(s) = "
            f"{traffic.points} point(s), {traffic.duration_s:g} s each "
            "· console pre-check, not ETHOS readiness"))
    else:
        checks.append(Check("traffic_plan", "Traffic plan parses", "fail",
                            "; ".join(traffic.errors.values())))

    checks.append(Check("core", f"Core {values['core']} is reachable", "unknown",
                        caps.why("readiness")))

    document = traffic.as_document(config_id, selection)
    first_blocker = next((c for c in checks if c.status != "pass"), None)

    # RUN needs the lock (B1) and the job endpoints (B2). It is disabled with a
    # reason until the probe finds both, and lights up on its own when it does:
    # nothing here has to be edited when they land.
    run_ready = caps.ready("jobs") and caps.ready("lock")
    if not caps.ready("jobs"):
        run_reason = caps.why("jobs")
    elif not caps.ready("lock"):
        run_reason = caps.why("lock")
    elif first_blocker is not None:
        run_reason = f"{first_blocker.label}: {first_blocker.reason}"
    else:
        run_reason = ""
    can_run = run_ready and first_blocker is None

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
    """RUN. It refuses while the endpoints it needs are missing.

    The button is disabled until the probe finds them, so this is the belt to
    that brace: a stale page, a keyboard, or a second tab must not be able to
    post a start that ETHOS has no way to honour.
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
    # Unreachable until B1 and B2 land. When they do, this is where the preview
    # dialog and POST /jobs go (design section 7.2).
    return render(
        request,
        "plan/resolved.html",
        {**context, "run_error": "Starting a job is not wired up yet."},
        status_code=501,
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
