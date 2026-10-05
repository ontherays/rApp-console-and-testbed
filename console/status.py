"""The status strip, from ETHOS's own summary (B6).

Requirements ST-01 asks for six indicators, and `GET /status/summary` answers all
of them in one call. A seventh was added with core switching (B18): two 5G cores
take turns on one host, so which one is serving is not decoration, it decides
whether a run may start at all. That matters more than saving a request: ETHOS gathers each
part separately, so one failing probe never fails the response, and the console
renders that same way. A part that carries an error shows the error against its
own item and nothing else on the strip changes (ST-01).

Each item keeps the `checked_at` of the read it came from, not of this request
(ST-03), so a part ETHOS served from its own cache reports an honest age rather
than looking fresher than it is.

Where a value is genuinely not known the item says `unknown`. An item that said
"free" because nothing answered would be worse than no item at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from console import holders
from console.capabilities import Capabilities
from console.rapps.ethos.client import EthosClient, EthosError
from console.rapps.ethos.models import StatusSummary

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
    href: str | None = None
    """Where the item leads, when there is somewhere useful. A running job's
    item links to that job's page, which is the thing an operator wants next."""


@dataclass
class Status:
    ethos_up: bool = False
    ethos_detail: str = ""
    items: list[Item] = field(default_factory=list)
    as_of: str = ""
    job_id: str | None = None
    job_state: str | None = None
    """The latest job, so any page can raise the finished toast (RN-11) when a
    job the browser saw running has reached a terminal state."""


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def _clock(value: str | None, fallback: str) -> str:
    """The part's own timestamp, shortened for the hover, or this request's."""
    if not value:
        return fallback
    text = str(value)
    return text[11:19] + "Z" if len(text) >= 19 and text[10:11] == "T" else text


def _lock_item(summary: StatusSummary, checked: str) -> Item:
    part = summary.lock
    at = _clock(part.checked_at, checked)
    if part.error:
        return Item("Lock", "unknown", UNKNOWN, part.error, at)
    if not part.held:
        return Item("Lock", holders.FREE, OK, "nothing holds the testbed", at)
    return Item(
        "Lock",
        holders.short(part),
        WARN,
        holders.describe(part),
        at,
        href=f"/jobs/{part.job_id}" if part.is_job and part.job_id else None,
    )


def _deployed_item(summary: StatusSummary, checked: str) -> Item:
    part = summary.deployed
    at = _clock(part.checked_at, checked)
    if part.error:
        return Item("Deployed", "unknown", UNKNOWN, part.error, at)
    if part.anything_deployed:
        # Without a config_id ETHOS names no profile, but it does name the
        # releases it found. That is what was observed, so that is what is shown.
        label = part.profile or part.stack or ", ".join(
            str(r) for r in part.releases
        ) or "something"
        return Item(
            "Deployed",
            f"{label} ({len(part.running_pods)} pod(s) running)",
            OK,
            f"namespace {part.namespace}, releases: "
            + (", ".join(str(r) for r in part.releases) or "none reported"),
            at,
        )
    if part.node_free is False:
        return Item("Deployed", "node busy", WARN, part.node_reason, at)
    # The namespace is answered either way. The on-node process check is not: the
    # strip is on every page and names no topology, and ETHOS only probes the node
    # when the request names a stack. Saying so beats reporting its initialiser.
    detail = f"no Helm release and no pod in {part.namespace}"
    if part.node_free is None:
        detail += (
            "; the node itself was not checked, because the strip names no "
            "topology. The Test Plan's readiness checks it."
        )
    else:
        detail += f"; {part.node_reason}"
    return Item("Deployed", "nothing deployed", OK, detail, at)


def _job_item(summary: StatusSummary, checked: str) -> Item:
    part = summary.latest_job
    at = _clock(part.checked_at, checked)
    if part.error:
        return Item("Job", "unknown", UNKNOWN, part.error, at)
    if not part.job_id:
        return Item("Job", "none", OK, "no job has been started", at)
    detail = ", ".join(
        bit for bit in (part.label, part.config_id, part.progress and f"{part.progress} points")
        if bit
    )
    return Item(
        "Job",
        part.state or "unknown",
        OK if part.finished else WARN,
        f"{part.job_id}{': ' + detail if detail else ''}",
        at,
        href=f"/jobs/{part.job_id}",
    )


def _ue_item(summary: StatusSummary, checked: str) -> Item:
    part = summary.ue
    at = _clock(part.checked_at, checked)
    name = part.ue or "UE"
    if part.error:
        return Item("UE", "unknown", UNKNOWN, f"{name}: {part.error}", at)
    if part.reachable is None:
        return Item("UE", "unknown", UNKNOWN, f"{name} did not answer", at)
    if part.attached:
        return Item("UE", f"{name} attached", OK, part.ip or "attached", at, href="/testbed")
    if part.attached is None:
        return Item(
            "UE", f"{name} reachable", OK,
            "reachable; whether it holds an address was not read", at, href="/testbed",
        )
    return Item("UE", f"{name} detached", OK, "reachable, holding no address", at, href="/testbed")


def _iperf_item(summary: StatusSummary, checked: str) -> Item:
    part = summary.iperf_server
    at = _clock(part.checked_at, checked)
    if part.error:
        return Item("iperf 5201", "unknown", UNKNOWN, part.error, at)
    mode = f"default mode {part.default_mode}" if part.default_mode else "no default mode"
    if not part.held:
        return Item("iperf 5201", "free", OK, f"nothing is listening, {mode}", at, href="/testbed")
    holder = part.holder or {}
    return Item(
        "iperf 5201",
        part.owner,
        OK,
        f"pid {holder.get('pid') or '?'}, uid {holder.get('uid') or '?'}, {mode}",
        at,
        href="/testbed",
    )


def _core_item(summary: StatusSummary, checked: str) -> Item:
    """Which 5G core is serving, and whether it is settled.

    Two cores take turns on one host, so this is not decoration: a run
    measured while the host is half-switched is a number attributed to the
    wrong core, and that is the one error the archive cannot repair later.
    """
    part = summary.core
    at = _clock(part.checked_at, checked)
    if not part.enabled:
        return Item("Core", "not switched", OK, "ETHOS does not switch cores here", at)
    if part.error:
        return Item("Core", "unknown", UNKNOWN, part.error, at)
    if not part.known:
        return Item("Core", "unknown", UNKNOWN, "the host named no core", at)

    name = (part.profile.display if part.profile else None) or part.core
    if part.disagreement:
        return Item("Core", f"{part.core}, mid-switch", BAD, part.disagreement, at)
    if part.health.ok is False:
        return Item("Core", f"{name}, not serving", BAD, part.health.summary, at)
    if part.health.ok is None:
        return Item("Core", name or "unknown", UNKNOWN, "health was not reported", at)

    detail = f"{part.health.summary}; NGAP: {part.health.peer_text}"
    if part.activity.findings:
        return Item("Core", name or "", WARN, f"{detail}; {part.activity.findings[0]}", at)
    return Item("Core", name or "", OK, detail, at)


def _freshness_item(summary: StatusSummary, checked: str) -> Item:
    """The newest thing any data source has said.

    Three sources, reported together because the strip has one slot: the newest
    of them is the honest headline, and the hover names each one. A source that
    has never landed anything stays absent rather than reading as stale.
    """
    part = summary.freshness
    at = _clock(part.checked_at, checked)
    if part.error:
        return Item("Freshness", "unknown", UNKNOWN, part.error, at)

    sources = (("results", part.results), ("O1 PM", part.o1_pm), ("O2 power", part.o2_power))
    details = []
    newest: str | None = None
    for name, source in sources:
        if source.error:
            details.append(f"{name}: {source.error}")
            continue
        if source.last_point:
            details.append(f"{name}: {source.last_point[:19]}Z")
            newest = max(newest or "", source.last_point)
        else:
            details.append(f"{name}: nothing in the window")
    value = newest[11:16] + "Z" if newest and len(newest) >= 16 else "none"
    return Item(
        "Freshness", value, OK if newest else UNKNOWN, "; ".join(details), at
    )


async def build_status(client: EthosClient, caps: Capabilities) -> Status:
    """The strip. One call to ETHOS, and one degraded shape when it is down."""
    checked = _now_text()

    ethos_up = False
    ethos_detail = ""
    try:
        health = await client.healthz()
        ethos_up = (health.status or "") == "ok"
        ethos_detail = f"{health.service} {health.version} on {client.base_url}"
    except EthosError as exc:
        ethos_detail = exc.message

    ethos_item = Item(
        label="ETHOS",
        value="up" if ethos_up else "down",
        state=OK if ethos_up else BAD,
        detail=ethos_detail,
        checked_at=checked,
    )

    if not ethos_up:
        # ST-04: every action is disabled, and no item pretends to know anything.
        return Status(
            ethos_up=False,
            ethos_detail=ethos_detail,
            as_of=checked,
            items=[ethos_item]
            + [
                Item(label, "unknown", UNKNOWN, ethos_detail, checked)
                for label in (
                    "Lock", "Deployed", "Job", "UE", "iperf 5201", "Core", "Freshness"
                )
            ],
        )

    try:
        summary = await client.status_summary()
    except EthosError as exc:
        return Status(
            ethos_up=True,
            ethos_detail=ethos_detail,
            as_of=checked,
            items=[ethos_item]
            + [
                Item(label, "unknown", UNKNOWN, exc.message, checked)
                for label in (
                    "Lock", "Deployed", "Job", "UE", "iperf 5201", "Core", "Freshness"
                )
            ],
        )

    return Status(
        ethos_up=True,
        ethos_detail=ethos_detail,
        as_of=checked,
        job_id=summary.latest_job.job_id,
        job_state=summary.latest_job.state,
        items=[
            ethos_item,
            _lock_item(summary, checked),
            _deployed_item(summary, checked),
            _job_item(summary, checked),
            _ue_item(summary, checked),
            _iperf_item(summary, checked),
            _core_item(summary, checked),
            _freshness_item(summary, checked),
        ],
    )
