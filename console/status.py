"""The status strip, assembled from what ETHOS can answer today.

Requirements ST-01 asks for six indicators. Three of them — the testbed lock,
the running job and the UE / port-5201 situation — need endpoints that do not
exist yet, and the design's own answer for a failed probe applies equally to a
missing one: **show "unknown", never a guess.** An item that says "free" because
nothing answered would be worse than no strip at all.

Each item therefore carries its own state, its own value, its own detail and the
time it was checked (ST-03), and one failing probe never fails the response
(ST-01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from console.capabilities import Capabilities
from console.rapps.ethos.client import EthosClient, EthosError

OK = "ok"
WARN = "warn"
BAD = "bad"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Item:
    label: str
    value: str
    state: str = UNKNOWN
    detail: str = ""
    checked_at: str | None = None


@dataclass
class Status:
    ethos_up: bool = False
    ethos_detail: str = ""
    items: list[Item] = field(default_factory=list)
    as_of: str = ""


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


async def build_status(client: EthosClient, caps: Capabilities) -> Status:
    checked = _now_text()
    items: list[Item] = []

    # --- ETHOS itself ---------------------------------------------------------
    ethos_up = False
    ethos_detail = ""
    try:
        health = await client.healthz()
        ethos_up = (health.status or "") == "ok"
        ethos_detail = f"{health.service} {health.version} on {client.base_url}"
    except EthosError as exc:
        ethos_detail = exc.message

    items.append(
        Item(
            label="ETHOS",
            value="up" if ethos_up else "down",
            state=OK if ethos_up else BAD,
            detail=ethos_detail,
            checked_at=checked,
        )
    )

    # --- the testbed lock (B1) -----------------------------------------------
    items.append(
        Item(
            label="Lock",
            value="unknown",
            state=UNKNOWN,
            detail=caps.why("lock"),
            checked_at=checked,
        )
    )

    # --- what is deployed ----------------------------------------------------
    if ethos_up:
        try:
            # No config_id here on purpose: the strip is on every page and must
            # not assume a topology. That means ETHOS answers the namespace but
            # never probes the node, so the strip reports the namespace — which
            # is what it actually knows — and the hover says the rest.
            deployed = await client.deploy_status()
            if deployed.anything_deployed:
                label = deployed.profile or deployed.config_id or deployed.stack or "something"
                value = f"{label} ({len(deployed.running_pods)} pod(s) running)"
                state = OK
                detail = f"namespace {deployed.namespace}, releases: " + (
                    ", ".join(str(r) for r in deployed.releases) or "none reported"
                )
            elif deployed.node_free is False:
                value, state, detail = "node busy", WARN, deployed.node_reason
            else:
                value = "nothing deployed"
                state = OK
                detail = f"{deployed.namespace_summary}. {deployed.node_detail}"
            items.append(
                Item(
                    label="Deployed",
                    value=value,
                    state=state,
                    detail=detail,
                    checked_at=checked,
                )
            )
        except EthosError as exc:
            items.append(
                Item(
                    label="Deployed",
                    value="unknown",
                    state=UNKNOWN,
                    detail=exc.message,
                    checked_at=checked,
                )
            )
    else:
        items.append(Item("Deployed", "unknown", UNKNOWN, ethos_detail, checked))

    # --- the running job (B2) and the UE / iperf server (B11) ----------------
    items.append(
        Item("Job", "unknown", UNKNOWN, caps.why("jobs"), checked)
    )
    items.append(
        Item("UE", "unknown", UNKNOWN, caps.why("ue"), checked)
    )
    items.append(
        Item("iperf 5201", "unknown", UNKNOWN, caps.why("ue"), checked)
    )

    return Status(
        ethos_up=ethos_up,
        ethos_detail=ethos_detail,
        items=items,
        as_of=checked,
    )
