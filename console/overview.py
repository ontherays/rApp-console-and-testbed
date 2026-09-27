"""What the Overview shows, computed from the run archive.

Every number here is a count, a maximum or a median of what ETHOS recorded. The
console measures nothing: where a value was not measured it stays absent rather
than becoming a zero, and a comparison with no previous period says so instead
of showing a change against nothing.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from console.rapps.ethos.models import Run
from console.rapps.ethos.series import series_for, sort_key

PERIODS: dict[str, tuple[str, timedelta]] = {
    "24h": ("Last 24 hours", timedelta(hours=24)),
    "7d": ("Last 7 days", timedelta(days=7)),
    "30d": ("Last 30 days", timedelta(days=30)),
}
DEFAULT_PERIOD = "30d"

KINDS: dict[str, str] = {
    "all": "All runs",
    "DL": "DL",
    "UL": "UL",
    "flagged": "Needs attention",
}
DEFAULT_KIND = "all"


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Change:
    """A movement against the previous period of the same length."""

    direction: str   # up | down | flat
    text: str

    @staticmethod
    def between(now: float | None, before: float | None, *, decimals: int = 0,
                unit: str = "", as_percent: bool = False) -> "Change | None":
        if now is None or before is None:
            return None
        difference = now - before
        if abs(difference) < 10 ** -(decimals + 2):
            return Change("flat", "No change")
        if as_percent and before:
            pct = difference / before * 100
            return Change(
                "up" if difference > 0 else "down", f"{pct:+.1f}%".replace("+-", "-")
            )
        text = f"{difference:+.{decimals}f}".rstrip("0").rstrip(".") if decimals else f"{difference:+.0f}"
        return Change("up" if difference > 0 else "down", f"{text}{(' ' + unit) if unit else ''}")


@dataclass
class Slice:
    """The runs of one period, and the same length of time before it."""

    period: str
    kind: str
    now: datetime
    current: list[Run] = field(default_factory=list)
    previous: list[Run] = field(default_factory=list)
    all_runs: list[Run] = field(default_factory=list)

    @property
    def label(self) -> str:
        return PERIODS[self.period][0]

    @property
    def span(self) -> timedelta:
        return PERIODS[self.period][1]


def _matches_kind(run: Run, kind: str) -> bool:
    if kind == "all":
        return True
    if kind == "flagged":
        return bool(run.flag_names)
    return (run.direction or "") == kind


def slice_runs(runs: list[Run], period: str, kind: str, *, now: datetime | None = None) -> Slice:
    now = now or datetime.now(timezone.utc)
    span = PERIODS.get(period, PERIODS[DEFAULT_PERIOD])[1]
    start = now - span
    earlier = start - span

    current: list[Run] = []
    previous: list[Run] = []
    for run in runs:
        created = parse_utc(run.t_created)
        if created is None or not _matches_kind(run, kind):
            continue
        if created >= start:
            current.append(run)
        elif created >= earlier:
            previous.append(run)

    current.sort(key=lambda r: r.t_created or "")
    return Slice(
        period=period, kind=kind, now=now,
        current=current, previous=previous, all_runs=runs,
    )


def any_flagged(runs: list[Run]) -> bool:
    return any(run.flag_names for run in runs)


# --- the KPI values ----------------------------------------------------------

def best_at(runs: list[Run], rate: float, direction: str = "DL") -> float | None:
    values = [
        run.achieved_over_tx_mbps
        for run in runs
        if run.achieved_over_tx_mbps is not None
        and run.offered_mbps == rate
        and (run.direction or "") == direction
    ]
    return max(values) if values else None


def median_snr(runs: list[Run]) -> float | None:
    values = [
        run.radio_summary.pusch_snr_db_mean
        for run in runs
        if run.radio_summary and run.radio_summary.pusch_snr_db_mean is not None
    ]
    return statistics.median(values) if values else None


def newest(runs: list[Run]) -> Run | None:
    dated = [run for run in runs if run.t_created]
    return max(dated, key=lambda r: r.t_created or "") if dated else None


# --- runs by topology --------------------------------------------------------

@dataclass
class TopologyShare:
    config_id: str
    label: str
    colour: str
    count: int
    share: float
    ambiguous: bool = False
    """True when another config_id in the same view carries this label.

    Two rows reading "OCUDU monolithic" are two different configurations — a
    different UE, or a legacy head that aliases onto the same stack — and a
    legend that does not say so invites adding them together.
    """


def by_topology(runs: list[Run]) -> list[TopologyShare]:
    counts: dict[str, int] = {}
    for run in runs:
        if run.config_id:
            counts[run.config_id] = counts.get(run.config_id, 0) + 1
    total = sum(counts.values()) or 1
    shares = [
        TopologyShare(
            config_id=config_id,
            label=series_for(config_id).label,
            colour=series_for(config_id).colour,
            count=count,
            share=count / total * 100,
        )
        for config_id, count in counts.items()
    ]
    shares.sort(key=lambda s: (-s.count, sort_key(s.config_id)))

    seen: dict[str, int] = {}
    for share in shares:
        seen[share.label] = seen.get(share.label, 0) + 1
    for share in shares:
        share.ambiguous = seen[share.label] > 1
    return shares


# --- throughput per day ------------------------------------------------------

@dataclass
class Day:
    date: str
    label: str
    best: float | None
    runs: int


def best_per_day(slice_: Slice) -> list[Day]:
    """The best achieved throughput on each day of the period.

    A day with no run keeps ``best`` as None. It is drawn as an empty column,
    never as zero — a day nobody ran is not a day of zero throughput.
    """
    days: dict[str, list[Run]] = {}
    span_days = max(1, slice_.span.days or 1)
    for offset in range(span_days):
        day = (slice_.now - timedelta(days=span_days - 1 - offset)).date().isoformat()
        days[day] = []

    for run in slice_.current:
        created = parse_utc(run.t_created)
        if created is None:
            continue
        key = created.date().isoformat()
        if key in days:
            days[key].append(run)

    out: list[Day] = []
    for date, runs in days.items():
        values = [r.achieved_over_tx_mbps for r in runs if r.achieved_over_tx_mbps is not None]
        stamp = datetime.fromisoformat(date)
        out.append(
            Day(
                date=date,
                label=stamp.strftime("%b %-d"),
                best=max(values) if values else None,
                runs=len(runs),
            )
        )
    return out


# --- topologies that need you ------------------------------------------------

@dataclass
class TopologyRow:
    config_id: str
    label: str
    colour: str
    initials: str
    runs: int
    delivered: int
    last_seen: str | None
    last_state: str
    latest_campaign: str | None
    planned: int
    completed: int
    best_1000: float | None
    change: Change | None


def topologies_needing_you(slice_: Slice) -> list[TopologyRow]:
    """One row per topology seen in the period, worst first.

    "Needs you" is ordered by what is unfinished: a sweep with points missing,
    then runs that delivered nothing, then everything else.
    """
    grouped: dict[str, list[Run]] = {}
    for run in slice_.current:
        if run.config_id:
            grouped.setdefault(run.config_id, []).append(run)

    rows: list[TopologyRow] = []
    for config_id, runs in grouped.items():
        series = series_for(config_id)
        runs.sort(key=lambda r: r.t_created or "")
        delivered = [r for r in runs if r.has_delivered]

        # The latest *sweep*: a campaign of more than one run. A campaign with a
        # single run is a one-off, and showing "0 of 1 points" for a topology
        # with 138 runs in the period would say nothing useful. With no sweep,
        # the bar falls back to the period's own runs, delivered against total.
        sweeps: dict[str, list[Run]] = {}
        for run in runs:
            if run.campaign_id:
                sweeps.setdefault(run.campaign_id, []).append(run)
        multi = {name: rs for name, rs in sweeps.items() if len(rs) > 1}
        latest_campaign = None
        if multi:
            latest_campaign = max(
                multi, key=lambda name: max(r.t_created or "" for r in multi[name])
            )
        in_scope = multi[latest_campaign] if latest_campaign else runs
        planned = len(in_scope)
        completed = len([r for r in in_scope if r.has_delivered])

        last = runs[-1]
        if last.status == "done":
            state = "completed"
        elif last.status == "defined":
            state = "defined, no traffic"
        else:
            state = last.status or "unknown"

        current_best = best_at(runs, 1000.0)
        previous_runs = [r for r in slice_.previous if r.config_id == config_id]
        rows.append(
            TopologyRow(
                config_id=config_id,
                label=series.label,
                colour=series.colour,
                initials=series.code,
                runs=len(runs),
                delivered=len(delivered),
                last_seen=last.t_created,
                last_state=state,
                latest_campaign=latest_campaign,
                planned=planned,
                completed=completed,
                best_1000=current_best,
                change=Change.between(
                    current_best, best_at(previous_runs, 1000.0), decimals=1, unit="Mbit/s"
                ),
            )
        )

    rows.sort(key=lambda r: (r.completed / r.planned if r.planned else 1.0, -r.runs))
    return rows
