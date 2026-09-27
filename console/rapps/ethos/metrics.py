"""The channel-condition display rules (requirements §7.4), as data.

These rules exist to stop a false comparison, so they are a table rather than a
pile of template conditionals: a label, a source field, a unit, a number of
decimals, and who may be compared with whom. Each row is covered by a test.

What the rules protect against, concretely:

* **BLER.** "Residual BLER" is what survived HARQ and both stacks measure it.
  OAI also reports first-transmission BLER, which read 0.46 on an idle link
  whose residual BLER was 0. Neither is ever labelled plain "BLER", and the two
  never share a column or an axis.
* **SNR.** PUSCH SNR is the only SNR both stacks measure the same way. OAI's
  PUCCH SNR is a different channel and is never compared with it.
* **RSRP.** Four different things are called RSRP. Three are UE-reported values
  in dBm (OAI's L1 print, the RRC L3 report, and the handset's own reading via
  adb); OCUDU's ``gnb_ul_rsrp_db`` is a *relative* dB figure that reads about
  −11 where the dBm values read −69. It never shares an axis with them.
* **MCS.** An index means nothing without its table — MCS 19 in qam64 and in
  qam256 are different modulations — and nothing without the cap. OCUDU clamps
  at 27 DL / 24 UL and sits on the cap under load; OAI configures no cap and
  chose 19 by link adaptation. A value at the cap is marked.
* **Rank.** Always direction-labelled. RI UL reads 1 on both stacks despite
  4T4R, so a column labelled just "MIMO layers" would imply a UL 4x4 that never
  happened.
* **CQI.** Comparable as a field, but each gNB reports it against its own CSI-RS
  configuration — OCUDU read 14 where OAI read 11 under the same conditions,
  and that is not a channel difference.
* **Not measured.** ``None`` renders "—", never 0 (GL-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DASH = "—"  # em dash: the one and only "not measured" rendering

COMPARABLE = "comparable"
VENDOR = "vendor"
UE_REPORTED = "ue_reported"
LATENCY = "latency"


@dataclass(frozen=True)
class Metric:
    """One row of the channel-conditions table."""

    key: str
    label: str
    fields: tuple[str, ...]        # mean, then min/max/p95 where they exist
    decimals: int
    unit: str = ""
    group: str = COMPARABLE
    vendor: str | None = None      # None = both stacks
    caveat: str | None = None      # the tooltip
    stat_labels: tuple[str, ...] = ("mean",)


def fmt(value: Any, decimals: int, unit: str = "") -> str:
    """A number, or "—". Never 0 for a missing value (GL-09)."""
    if value is None:
        return DASH
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        text = f"{value:.{decimals}f}"
        return f"{text} {unit}".strip() if unit else text
    text = str(value).strip()
    return text or DASH


# --- comparable across OCUDU and OAI -----------------------------------------

COMPARABLE_METRICS: tuple[Metric, ...] = (
    Metric(
        key="pusch_snr",
        label="PUSCH SNR",
        fields=("pusch_snr_db_mean", "pusch_snr_db_min", "pusch_snr_db_max", "pusch_snr_db_p95"),
        stat_labels=("mean", "min", "max", "p95"),
        decimals=1,
        unit="dB",
        caveat="Measured at the gNB on the uplink shared channel. The only SNR "
               "both stacks measure the same way.",
    ),
    Metric(
        key="bler_dl_residual",
        label="Residual BLER DL",
        fields=("bler_dl_residual_mean", "bler_dl_residual_max"),
        stat_labels=("mean", "max"),
        decimals=4,
        caveat="Errors that survived HARQ retransmission. The comparable BLER. "
               "Idle-link BLER from either stack is not a meaningful channel "
               "statistic.",
    ),
    Metric(
        key="bler_ul_residual",
        label="Residual BLER UL",
        fields=("bler_ul_residual_mean", "bler_ul_residual_max"),
        stat_labels=("mean", "max"),
        decimals=4,
        caveat="Errors that survived HARQ retransmission.",
    ),
    Metric(
        key="cqi",
        label="CQI (DL)",
        fields=("cqi_mean", "cqi_min", "cqi_max", "cqi_p95"),
        stat_labels=("mean", "min", "max", "p95"),
        decimals=1,
        caveat="UE-reported index 0–15. CQI is reported against each gNB's own "
               "CSI-RS configuration, so a difference between stacks is not "
               "necessarily a channel difference.",
    ),
    Metric(
        key="ri_dl",
        label="RI DL",
        fields=("ri_dl_mean",),
        decimals=2,
        unit="layers",
        caveat="OCUDU reports an average, OAI an instantaneous value.",
    ),
    Metric(
        key="ri_ul",
        label="RI UL",
        fields=("ri_ul_mean",),
        decimals=2,
        unit="layers",
        caveat="Reads 1 on both stacks despite 4T4R — the uplink ran one layer.",
    ),
    Metric(
        key="mcs_dl",
        label="MCS DL",
        fields=("mcs_dl_mean",),
        decimals=1,
        caveat="Shown with its MCS table and, where the stack sets one, its cap. "
               "MCS 19 in qam64 and in qam256 are different modulations.",
    ),
    Metric(
        key="mcs_ul",
        label="MCS UL",
        fields=("mcs_ul_mean",),
        decimals=1,
        caveat="Shown with its MCS table and, where the stack sets one, its cap.",
    ),
    Metric(
        key="phr",
        label="Power headroom",
        fields=("phr_db_mean",),
        decimals=1,
        unit="dB",
    ),
    Metric(
        key="radio_sample_count",
        label="Radio samples",
        fields=("radio_sample_count",),
        stat_labels=("",),
        decimals=0,
        caveat="A mean over three samples and a mean over sixty must not look "
               "alike, so the count is always shown.",
    ),
)

# --- vendor-specific: collapsed, and never mixed with the above ---------------

VENDOR_METRICS: tuple[Metric, ...] = (
    Metric(
        key="bler_dl_first_tx",
        label="First-transmission BLER DL",
        fields=("bler_dl_first_tx_mean", "bler_dl_first_tx_max"),
        stat_labels=("mean", "max"),
        decimals=4,
        group=VENDOR,
        vendor="oai",
        caveat="OAI only, and NOT comparable with residual BLER: it counts "
               "first-attempt failures, and read 0.46 on an idle link whose "
               "residual BLER was 0.",
    ),
    Metric(
        key="bler_ul_first_tx",
        label="First-transmission BLER UL",
        fields=("bler_ul_first_tx_mean", "bler_ul_first_tx_max"),
        stat_labels=("mean", "max"),
        decimals=4,
        group=VENDOR,
        vendor="oai",
        caveat="OAI only, and NOT comparable with residual BLER.",
    ),
    Metric(
        key="pucch_snr",
        label="PUCCH SNR",
        fields=("pucch_snr_db_mean",),
        decimals=1,
        unit="dB",
        group=VENDOR,
        vendor="oai",
        caveat="OAI only. A different channel from PUSCH SNR; never compared "
               "with it.",
    ),
    Metric(
        key="ue_l1_rsrp",
        label="UE L1-RSRP",
        fields=("ue_l1_rsrp_dbm_mean",),
        decimals=1,
        unit="dBm",
        group=VENDOR,
        vendor="oai",
        caveat="OAI only. UE-reported SSB L1 RSRP averaged over one print "
               "interval — a UE measurement, not a gNB one, despite OAI "
               "printing it as \"average RSRP\".",
    ),
    Metric(
        key="rrc_ss_rsrp",
        label="UE SS-RSRP (gNB RRC report)",
        fields=("rrc_ss_rsrp_dbm",),
        decimals=1,
        unit="dBm",
        group=VENDOR,
        vendor="oai",
        caveat="OAI only. The L3 resultSSB the UE reported, read from the CU.",
    ),
    Metric(
        key="rrc_ss_rsrq",
        label="UE SS-RSRQ (gNB RRC report)",
        fields=("rrc_ss_rsrq_db",),
        decimals=1,
        unit="dB",
        group=VENDOR,
        vendor="oai",
    ),
    Metric(
        key="rrc_ss_sinr",
        label="UE SS-SINR (gNB RRC report)",
        fields=("rrc_ss_sinr_db",),
        decimals=1,
        unit="dB",
        group=VENDOR,
        vendor="oai",
        caveat="OAI only. Differs from the handset's own SS-SINR by roughly "
               "10 dB on the same UE; the two are separate fields and are "
               "never merged.",
    ),
    Metric(
        key="gnb_ul_rsrp",
        label="gNB UL RSRP (relative)",
        fields=("gnb_ul_rsrp_db_mean",),
        decimals=1,
        unit="dB",
        group=VENDOR,
        vendor="ocudu",
        caveat="OCUDU only, and relative dB — NOT dBm. It reads about −11 where "
               "the dBm figures read −69, so it never shares an axis with them.",
    ),
    Metric(
        key="ta_ns",
        label="Timing advance",
        fields=("ta_ns_mean",),
        decimals=0,
        unit="ns",
        group=VENDOR,
        vendor="ocudu",
        caveat="OCUDU only. OAI exposes a different representation.",
    ),
    Metric(
        key="dl_buffer",
        label="DL buffer",
        fields=("dl_buffer_bytes_mean",),
        decimals=0,
        unit="bytes",
        group=VENDOR,
        vendor="ocudu",
    ),
    Metric(
        key="ul_bsr",
        label="UL buffer status report",
        fields=("ul_bsr_bytes_mean",),
        decimals=0,
        unit="bytes",
        group=VENDOR,
        vendor="ocudu",
    ),
)

# --- read from the handset over adb, either stack -----------------------------

UE_METRICS: tuple[Metric, ...] = (
    Metric(
        key="ue_ss_rsrp",
        label="UE SS-RSRP (Android)",
        fields=("ue_ss_rsrp_dbm", "ue_ss_rsrp_dbm_end"),
        stat_labels=("start", "end"),
        decimals=1,
        unit="dBm",
        group=UE_REPORTED,
        caveat="Read from the handset. Updates slowly and did not move between "
               "idle and 500 Mbit/s — a coarse cross-check, not a load-sensitive "
               "measurement.",
    ),
    Metric(
        key="ue_ss_rsrq",
        label="UE SS-RSRQ (Android)",
        fields=("ue_ss_rsrq_db", "ue_ss_rsrq_db_end"),
        stat_labels=("start", "end"),
        decimals=1,
        unit="dB",
        group=UE_REPORTED,
    ),
    Metric(
        key="ue_ss_sinr",
        label="UE SS-SINR (Android)",
        fields=("ue_ss_sinr_db", "ue_ss_sinr_db_end"),
        stat_labels=("start", "end"),
        decimals=1,
        unit="dB",
        group=UE_REPORTED,
        caveat="Read from the handset, and about 10 dB from the gNB's RRC-reported "
               "SINR on the same UE. The two are never merged.",
    ),
)

LATENCY_METRICS: tuple[Metric, ...] = (
    Metric(
        key="rtt",
        label="RTT",
        fields=("rtt_ms_min", "rtt_ms_mean", "rtt_ms_p95", "rtt_ms_max", "rtt_ms_mdev"),
        stat_labels=("min", "mean", "p95", "max", "mdev"),
        decimals=2,
        unit="ms",
        group=LATENCY,
        caveat="p95 is shown because RTT is long-tailed: the mean moved under "
               "2 ms from idle to 500 Mbit/s while the maximum roughly doubled.",
    ),
    Metric(
        key="rtt_loss",
        label="Probe loss",
        fields=("rtt_loss_pct",),
        stat_labels=("",),
        decimals=1,
        unit="%",
        group=LATENCY,
    ),
    Metric(
        key="rtt_count",
        label="Probes",
        fields=("rtt_count",),
        stat_labels=("",),
        decimals=0,
        group=LATENCY,
    ),
)

ALL_METRICS = COMPARABLE_METRICS + VENDOR_METRICS + UE_METRICS + LATENCY_METRICS
BY_KEY = {m.key: m for m in ALL_METRICS}


@dataclass(frozen=True)
class Stat:
    label: str
    text: str
    measured: bool


@dataclass(frozen=True)
class Row:
    """One rendered row: the label, its statistics, its caveat, its extras."""

    metric: Metric
    stats: tuple[Stat, ...]
    note: str | None = None      # e.g. the MCS table and cap
    capped: bool = False

    @property
    def label(self) -> str:
        return self.metric.label

    @property
    def caveat(self) -> str | None:
        return self.metric.caveat

    @property
    def measured(self) -> bool:
        return any(stat.measured for stat in self.stats)


def _get(source: Any, field: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


def row_for(metric: Metric, source: Any, cell_config: Any = None) -> Row:
    stats: list[Stat] = []
    for index, field in enumerate(metric.fields):
        value = _get(source, field)
        label = (
            metric.stat_labels[index]
            if index < len(metric.stat_labels)
            else field
        )
        stats.append(
            Stat(label=label, text=fmt(value, metric.decimals, metric.unit),
                 measured=value is not None)
        )

    note: str | None = None
    capped = False
    if metric.key in ("mcs_dl", "mcs_ul"):
        direction = metric.key[-2:]
        table = _get(source, f"mcs_table_{direction}") or _get(
            cell_config, f"mcs_table_{direction}"
        )
        cap = _get(cell_config, f"max_ue_mcs_{direction}")
        parts: list[str] = []
        if table:
            parts.append(f"table {table}")
        if cap is not None:
            parts.append(f"cap {cap}")
            value = _get(source, metric.fields[0])
            # Sitting within a tenth of the cap is sitting on the cap.
            capped = value is not None and value >= float(cap) - 0.1
        note = " · ".join(parts) or None

    return Row(metric=metric, stats=tuple(stats), note=note, capped=capped)


def _vendor_of(radio_summary: Any, run: Any = None) -> str | None:
    vendor = _get(radio_summary, "du_vendor")
    if vendor:
        return str(vendor).lower()
    vendor = _get(_get(run, "cell_config"), "vendor")
    return str(vendor).lower() if vendor else None


def channel_rows(run: Any) -> dict[str, list[Row]]:
    """The Channel conditions tab (RS-07), split the way §7.4 requires.

    ``comparable`` is always open. ``vendor`` is collapsed and shows only the
    fields the stack that ran actually reports — a vendor's absent counter is
    an absence, not a zero, and listing another vendor's fields under it would
    read as "not measured" when the truth is "does not exist here".
    """
    summary = _get(run, "radio_summary")
    latency = _get(run, "latency")
    cell = _get(run, "cell_config")
    vendor = _vendor_of(summary, run)

    comparable = [row_for(m, summary, cell) for m in COMPARABLE_METRICS]
    vendor_rows = [
        row_for(m, summary, cell)
        for m in VENDOR_METRICS
        if vendor is None or m.vendor == vendor
    ]
    ue_rows = [row_for(m, summary, cell) for m in UE_METRICS]
    latency_rows = [row_for(m, latency, cell) for m in LATENCY_METRICS]

    return {
        "comparable": comparable,
        "vendor": [r for r in vendor_rows if r.measured],
        "ue_reported": [r for r in ue_rows if r.measured],
        "latency": latency_rows,
    }


# --- the run table's throughput column ---------------------------------------

def throughput_text(run: Any) -> str:
    """``achieved_over_tx_mbps`` is the only throughput compared across stacks.
    The gNB's own MAC bitrate (OCUDU) and application goodput (OAI) differ by
    header overhead and belong on the Samples tab, never in this column."""
    return fmt(_get(run, "achieved_over_tx_mbps"), 2, "Mbit/s")
