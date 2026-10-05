"""Filtering, sorting, paging and CSV over the run list, in the console.

``GET /runs`` accepts three filters, no limit and no offset, and re-reads every
manifest on disk for each request, 528 runs is 1.1 MB today and grows. So the
console fetches the list once per cache window and does the rest here. Backend
change B10 moves this to ETHOS (with ``GET /runs.csv``); this module is then
deleted rather than kept as a second implementation.

Nothing here computes a measurement. It selects, orders and formats what ETHOS
recorded.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from console.rapps.ethos.models import Run
from console.rapps.ethos.series import series_for, sort_key


@dataclass
class Filters:
    """What the chip bar above the run table selects (RS-02)."""

    config_id: str = ""
    direction: str = ""
    #: Which 5G core served the run (RS-02, extended for core switching). Not
    #: the same as picking a config_id: a core is comparable across topologies
    #: and a config_id is not.
    core: str = ""
    campaign_id: str = ""
    server_owner: str = ""
    band: str = ""
    bandwidth_mhz: str = ""
    tdd_pattern: str = ""
    rate: str = ""
    since: str = ""
    until: str = ""
    status: str = ""
    has_flags: bool = False
    # Runs that cannot be analysed are hidden by default (RS-05).
    usable_only: bool = True

    def active(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for name in (
            "config_id",
            "direction",
            "core",
            "campaign_id",
            "server_owner",
            "band",
            "bandwidth_mhz",
            "tdd_pattern",
            "rate",
            "since",
            "until",
            "status",
        ):
            value = getattr(self, name)
            if value:
                out.append((name, value))
        if self.has_flags:
            out.append(("has_flags", "yes"))
        if not self.usable_only:
            out.append(("usable_only", "no"))
        return out

    def query(self, **overrides: Any) -> str:
        parts: list[str] = []
        values = {name: value for name, value in self.active()}
        values.update({k: v for k, v in overrides.items() if v not in (None, "")})
        for name, value in values.items():
            parts.append(f"{name}={value}")
        return "&".join(parts)


def _cell(run: Run, field_name: str) -> Any:
    return getattr(run.cell_config, field_name, None) if run.cell_config else None


def _matches(run: Run, filters: Filters) -> bool:
    if filters.config_id and run.config_id != filters.config_id:
        return False
    if filters.direction and (run.direction or "") != filters.direction:
        return False
    if filters.core and (run.core or "") != filters.core:
        return False
    if filters.campaign_id and (run.campaign_id or "") != filters.campaign_id:
        return False
    if filters.server_owner and (run.server_owner or "") != filters.server_owner:
        return False
    if filters.status and (run.status or "") != filters.status:
        return False
    if filters.band and str(_cell(run, "band") or "") != filters.band:
        return False
    if filters.bandwidth_mhz:
        value = _cell(run, "bandwidth_mhz")
        if value is None or f"{value:g}" != filters.bandwidth_mhz:
            return False
    if filters.tdd_pattern and str(_cell(run, "tdd_pattern") or "") != filters.tdd_pattern:
        return False
    if filters.rate:
        try:
            wanted = float(filters.rate)
        except ValueError:
            return False
        if run.offered_mbps is None or abs(run.offered_mbps - wanted) > 0.001:
            return False
    if filters.since and (run.t_created or "") < filters.since:
        return False
    if filters.until and (run.t_created or "") > filters.until + "T23:59:59Z":
        return False
    if filters.has_flags and not run.flag_names:
        return False
    if filters.usable_only and not run.usable:
        return False
    return True


SORTS: dict[str, Any] = {
    "time": lambda r: (r.t_created or "", r.run_id),
    "stack": lambda r: (sort_key(r.config_id), r.t_created or ""),
    "offered": lambda r: (r.offered_mbps if r.offered_mbps is not None else -1,),
    "achieved": lambda r: (
        r.achieved_over_tx_mbps if r.achieved_over_tx_mbps is not None else -1,
    ),
    "loss": lambda r: (r.loss_pct if r.loss_pct is not None else -1,),
    "snr": lambda r: (
        r.radio_summary.pusch_snr_db_mean
        if r.radio_summary and r.radio_summary.pusch_snr_db_mean is not None
        else -999,
    ),
}


@dataclass
class Page:
    rows: list[Run]
    total: int
    matched: int
    offset: int
    limit: int
    sort: str
    descending: bool

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.rows) < self.matched

    @property
    def page_number(self) -> int:
        return self.offset // self.limit + 1 if self.limit else 1

    @property
    def page_count(self) -> int:
        if not self.limit:
            return 1
        return max(1, -(-self.matched // self.limit))


def select(
    runs: Sequence[Run],
    filters: Filters,
    *,
    sort: str = "time",
    descending: bool = True,
    offset: int = 0,
    limit: int = 50,
) -> Page:
    matched = [run for run in runs if _matches(run, filters)]
    key = SORTS.get(sort, SORTS["time"])
    matched.sort(key=key, reverse=descending)
    window = matched[offset : offset + limit] if limit else matched
    return Page(
        rows=window,
        total=len(runs),
        matched=len(matched),
        offset=offset,
        limit=limit,
        sort=sort,
        descending=descending,
    )


def facets(runs: Iterable[Run]) -> dict[str, list[str]]:
    """The values worth offering as filter chips, taken from the runs present."""
    found: dict[str, set[str]] = {
        "config_id": set(),
        "direction": set(),
        "core": set(),
        "campaign_id": set(),
        "server_owner": set(),
        "band": set(),
        "bandwidth_mhz": set(),
        "tdd_pattern": set(),
        "status": set(),
        "rate": set(),
    }
    for run in runs:
        if run.config_id:
            found["config_id"].add(run.config_id)
        if run.direction:
            found["direction"].add(run.direction)
        if run.core:
            found["core"].add(run.core)
        if run.campaign_id:
            found["campaign_id"].add(run.campaign_id)
        if run.server_owner:
            found["server_owner"].add(run.server_owner)
        if run.status:
            found["status"].add(run.status)
        if run.offered_mbps is not None:
            found["rate"].add(f"{run.offered_mbps:g}")
        if run.cell_config:
            if run.cell_config.band:
                found["band"].add(run.cell_config.band)
            if run.cell_config.bandwidth_mhz is not None:
                found["bandwidth_mhz"].add(f"{run.cell_config.bandwidth_mhz:g}")
            if run.cell_config.tdd_pattern:
                found["tdd_pattern"].add(run.cell_config.tdd_pattern)

    out: dict[str, list[str]] = {}
    for name, values in found.items():
        if name == "rate":
            out[name] = sorted(values, key=lambda v: float(v))
        elif name == "config_id":
            out[name] = sorted(values, key=sort_key)
        else:
            out[name] = sorted(values)
    return out


CSV_COLUMNS: tuple[str, ...] = (
    "run_id",
    "config_id",
    "stack_label",
    "config_hash",
    "campaign_id",
    "direction",
    "t_created",
    "t_traffic_start",
    "t_traffic_end",
    "status",
    "condition",
    "offered_mbps",
    "achieved_over_tx_mbps",
    "achieved_mbps",
    "loss_pct",
    "loss_pct_vs_offered",
    "delivered_bytes",
    "duration_requested_s",
    "tx_duration_s",
    "rx_duration_s",
    "rx_tx_ratio",
    "server_owner",
    "core",
    "core_confirmed",
    "traffic_mode",
    "traffic_receiver_role",
    "band",
    "bandwidth_mhz",
    "n_prb",
    "scs_khz",
    "antenna_config",
    "tdd_pattern",
    "mcs_table_dl",
    "max_ue_mcs_dl",
    "max_ue_mcs_ul",
    "cell_config_source",
    "radio_sample_count",
    "pusch_snr_db_mean",
    "pusch_snr_db_min",
    "pusch_snr_db_max",
    "pusch_snr_db_p95",
    "cqi_mean",
    "ri_dl_mean",
    "ri_ul_mean",
    "mcs_dl_mean",
    "mcs_ul_mean",
    "bler_dl_residual_mean",
    "bler_dl_residual_max",
    "bler_ul_residual_mean",
    "bler_ul_residual_max",
    "bler_dl_first_tx_mean",
    "pucch_snr_db_mean",
    "ue_l1_rsrp_dbm_mean",
    "gnb_ul_rsrp_db_mean",
    "ue_ss_rsrp_dbm",
    "ue_ss_sinr_db",
    "rtt_ms_min",
    "rtt_ms_mean",
    "rtt_ms_p95",
    "rtt_ms_max",
    "rtt_ms_mdev",
    "rtt_loss_pct",
    "rtt_count",
    "pkg1_w",
    "pkg0_w",
    "ee_kpi_total_mbit_per_w",
    "quality_flags",
)


def csv_rows(runs: Sequence[Run]) -> str:
    """One row per run, every summary field, UTC timestamps as recorded (RS-04).

    A value that was not measured is an empty cell. It is never written as 0,
    a spreadsheet that reads 0 dB of SNR as a measurement is worse than a blank.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for run in runs:
        cell = run.cell_config
        radio = run.radio_summary
        latency = run.latency
        values: dict[str, Any] = {
            "stack_label": series_for(run.config_id).label,
            "quality_flags": " ".join(run.flag_names),
        }
        row: list[Any] = []
        for column in CSV_COLUMNS:
            if column in values:
                row.append(values[column])
                continue
            if column == "band":
                row.append(getattr(cell, "band", None))
                continue
            if column == "cell_config_source":
                row.append(getattr(cell, "source", None))
                continue
            for source in (run, cell, radio, latency):
                if source is not None and hasattr(source, column):
                    row.append(getattr(source, column))
                    break
            else:
                row.append(None)
        writer.writerow(["" if v is None else v for v in row])
    return buffer.getvalue()


# --- the sweep view ----------------------------------------------------------

@dataclass
class SweepRow:
    """One offered load, with its repeats collapsed to a mean and an n (RS-16)."""

    offered_mbps: float | None
    runs: list[Run] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.runs)

    def mean(self, getter) -> float | None:
        values = [
            value
            for value in (getter(run) for run in self.runs)
            if value is not None
        ]
        return sum(values) / len(values) if values else None

    def field_mean(self, block: str, name: str) -> float | None:
        def getter(run: Run) -> Any:
            source = run if block == "run" else getattr(run, block, None)
            return getattr(source, name, None) if source is not None else None

        return self.mean(getter)

    @property
    def cell_configs(self) -> list[str]:
        seen: list[str] = []
        for run in self.runs:
            chips = " · ".join(run.cell_config.chips) if run.cell_config else ""
            if chips and chips not in seen:
                seen.append(chips)
        return seen


def sweep(runs: Sequence[Run]) -> list[SweepRow]:
    """Group by offered load, ordered by it (RS-13)."""
    grouped: dict[Any, SweepRow] = {}
    for run in runs:
        key = run.offered_mbps
        grouped.setdefault(key, SweepRow(offered_mbps=key)).runs.append(run)
    return [
        grouped[key]
        for key in sorted(grouped, key=lambda k: (k is None, k if k is not None else 0))
    ]


def cell_config_consistent(runs: Sequence[Run]) -> tuple[bool, list[str]]:
    """Whether every run in a group ran the same cell configuration (RS-15).

    A sweep that mixes TDD patterns or bandwidths is not one sweep, and saying so
    in amber is cheaper than a wrong conclusion drawn from its figure.
    """
    seen: list[str] = []
    for run in runs:
        chips = " · ".join(run.cell_config.chips) if run.cell_config else "no cell config"
        if chips not in seen:
            seen.append(chips)
    return (len(seen) <= 1, seen)
