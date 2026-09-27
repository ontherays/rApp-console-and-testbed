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



def option_list(catalogue, category: str) -> list[tuple[str, str, str]]:
    """(value, label, reason-it-is-disabled) for one catalogue category.

    The label is always what is shown (GL-05). A reason comes from
    ``OPTION_REASONS`` — every entry there was checked against the deploy
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
    return values


def resolve_split(values: dict[str, Any]) -> tuple[str, str]:
    """The catalogue's ``gnb_split`` id, and the stack that owns the topology.

    The catalogue spells the four splits ``monolithic``, ``CU+DU``,
    ``OCUDU-CU+OAI-DU`` and ``OAI-CU+OCUDU-DU``. The form asks the question the
    way requirements TP-02 does — monolithic or CU+DU, then a CU vendor and a DU
    vendor — and this maps the answer onto the catalogue's own ids.
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

    node_check = Check("node_free", "Nothing else is deployed", "unknown", "not checked")
    try:
        deployed = await client.deploy_status()
        if deployed.anything_deployed:
            node_check = Check(
                "node_free",
                "Nothing else is deployed",
                "fail",
                f"{deployed.profile or deployed.stack or 'a stack'} is deployed in "
                f"{deployed.namespace} ({len(deployed.running_pods)} pod(s) running)",
            )
        elif deployed.node_free:
            node_check = Check("node_free", "Nothing else is deployed", "pass",
                               deployed.node_reason or "the namespace is empty and no gNB process runs")
        else:
            node_check = Check("node_free", "Nothing else is deployed", "unknown",
                               deployed.node_reason or "the node was not observed")
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

    command = campaign_command(
        ethos_repo=settings.ethos_repo,
        topology=profile.name if profile and profile.deployable else None,
        rates=traffic.rates_text,
        direction=traffic.direction,
        duration=traffic.duration_text,
        repeats=traffic.repeats,
        radio_samples=traffic.radio_samples,
        core="open5gs" if values["core"] == "Open5GS" else "free5gc",
        ue=str(values["ue"]).lower(),
    )

    catalogue = None
    catalogue_error = None
    try:
        catalogue = await client.compatibility()
    except EthosError as exc:
        catalogue_error = exc.message

    return {
        "values": values,
        "selection": selection,
        "catalogue": catalogue,
        "catalogue_error": catalogue_error,
        "options": {
            category: option_list(catalogue, category)
            for category in ("gnb_stack", "l1_backend", "ru", "ue", "core", "server")
        },
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
        "document": document,
        "document_json": json.dumps(document, indent=2),
        "document_yaml": yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        "command": command,
    }


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
