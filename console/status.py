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
from console.rapps.ethos.models import CoreStale, StatusSummary

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
    when: str | None = None
    """The instant this item's value refers to, when it refers to one. Shown
    beside the value in the display zone, with the UTC original in the
    tooltip, so a time on the strip reads the same as a time in a banner."""


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
    core_stale: CoreStale | None = None
    """Set when ETHOS reports a core a dead campaign left behind. A banner on
    every page, because the person who can fix it is whoever next opens one,
    and the fix is a command on the core host rather than anything here."""


def _now_text() -> str:
    """This read's instant, in UTC, for the template to localise (GL-06).

    Never formatted here. The strip used to print "08:24:17Z" while a banner
    two lines down printed "since 16:27", which is the same moment written
    two ways on one screen.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _clock(value: str | None, fallback: str) -> str:
    """The part's own timestamp, or this request's when it carries none.

    Returned as the raw instant: the template formats it, so every time on
    every page goes through one helper.
    """
    return str(value) if value else fallback


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


#: How old the newest measurement may be before the strip stops calling it
#: current. A sweep publishes a point every few seconds while it runs, so
#: anything inside SIX HOURS is this working session or the last one. Up to a
#: WEEK is an ordinary gap: overnight, a weekend, a quiet few days, and the
#: number is still worth reading as long as you know its age. Past a week the
#: only reason there is a figure at all is the 30-day lookback, and a graph
#: drawn from it is history rather than the state of the testbed.
FRESH_OK_S = 6 * 3600
FRESH_WARN_S = 7 * 24 * 3600


def _age(last_point: str | None, now: datetime | None = None) -> float | None:
    """Seconds since *last_point*, or None if it cannot be read."""
    if not last_point:
        return None
    try:
        when = datetime.fromisoformat(str(last_point).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - when).total_seconds()


def _age_text(seconds: float | None) -> str:
    """An age a person reads: "1 h 24 min ago"."""
    if seconds is None:
        return ""
    seconds = max(0.0, seconds)
    if seconds < 90:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {minutes} min ago" if minutes else f"{hours} h ago"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h ago" if hours else f"{days} d ago"


def _newest_data_item(summary: StatusSummary, checked: str) -> Item:
    """When measurement data last landed in InfluxDB.

    Not when the page was loaded and not when the testbed was last looked at:
    the newest `_time` ETHOS can find, within a 30-day lookback, across three
    independent sources. Results (`ethos_iperf_v2` in the results bucket) is
    the one that moves during a sweep; O1 PM and O2 power are separate
    pipelines and one being silent says nothing about the others.

    It was called "Freshness", which named the quality rather than the thing,
    so nobody could tell what it was measuring without reading the code.
    """
    part = summary.freshness
    at = _clock(part.checked_at, checked)
    if part.error:
        return Item("Newest data", "unknown", UNKNOWN, part.error, at)

    sources = (
        ("iperf results", part.results),
        ("O1 PM", part.o1_pm),
        ("O2 power", part.o2_power),
    )
    details: list[str] = []
    newest: str | None = None
    for name, source in sources:
        if source.error:
            details.append(f"{name}: {source.error}")
            continue
        if source.last_point:
            details.append(f"{name}: {_age_text(_age(source.last_point))}")
            newest = max(newest or "", source.last_point)
        else:
            details.append(f"{name}: nothing in the last 30 days")

    if not newest:
        return Item(
            "Newest data", "none", UNKNOWN,
            "no measurement in the last 30 days. " + "; ".join(details), at,
        )

    seconds = _age(newest)
    state = OK if (seconds or 0) < FRESH_OK_S else (
        WARN if (seconds or 0) < FRESH_WARN_S else BAD
    )
    return Item(
        "Newest data",
        _age_text(seconds),
        state,
        "the newest measurement ETHOS can find in InfluxDB, over a 30-day "
        "lookback. " + "; ".join(details),
        at,
        when=newest,
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
                    "Lock", "Deployed", "Job", "UE", "iperf 5201", "Core", "Newest data"
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
                    "Lock", "Deployed", "Job", "UE", "iperf 5201", "Core", "Newest data"
                )
            ],
        )

    return Status(
        ethos_up=True,
        ethos_detail=ethos_detail,
        as_of=checked,
        job_id=summary.latest_job.job_id,
        job_state=summary.latest_job.state,
        core_stale=summary.core.stale if summary.core.stale.is_stale else None,
        items=[
            ethos_item,
            _lock_item(summary, checked),
            _deployed_item(summary, checked),
            _job_item(summary, checked),
            _ue_item(summary, checked),
            _iperf_item(summary, checked),
            _core_item(summary, checked),
            _newest_data_item(summary, checked),
        ],
    )
