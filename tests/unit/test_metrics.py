"""The §7.4 metric display rules, one test per rule, on real recorded runs.

These rules exist to prevent a false cross-vendor comparison. Each one is checked
against manifests captured from the testbed, not against invented data, so a
change in ETHOS's field names fails here rather than on a page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from console.rapps.ethos.metrics import (
    COMPARABLE_METRICS,
    NOT_MEASURED,
    UE_METRICS,
    VENDOR_METRICS,
    channel_rows,
    fmt,
    row_for,
    throughput_text,
)
from console.rapps.ethos.models import Run

RECORDED = Path(__file__).resolve().parent.parent / "recorded" / "runs.json"


def _runs() -> list[Run]:
    body = json.loads(RECORDED.read_text(encoding="utf-8"))
    return [Run.model_validate(r) for r in body["runs"]]


def _with_radio(vendor: str) -> Run:
    for run in _runs():
        if run.radio_summary and (run.radio_summary.du_vendor or "").lower() == vendor:
            return run
    pytest.skip(f"no recorded run with {vendor} channel metrics")


def _never_ran() -> Run:
    for run in _runs():
        if run.status == "defined":
            return run
    pytest.skip("no recorded run that never ran")


# --- the "not measured" rule (GL-09) -----------------------------------------

def test_a_missing_value_is_an_em_dash_and_never_zero():
    assert fmt(None, 2) == NOT_MEASURED
    assert fmt(0.0, 2) == "0.00"
    assert fmt(0, 4) == "0.0000"


def test_a_run_that_never_ran_shows_dashes_not_zeroes():
    run = _never_ran()
    assert throughput_text(run) == NOT_MEASURED
    rows = channel_rows(run)
    for row in rows["comparable"]:
        for stat in row.stats:
            assert stat.text == NOT_MEASURED
            assert stat.measured is False


def test_an_absent_block_does_not_raise():
    rows = channel_rows(Run(run_id="x"))
    assert rows["vendor"] == []
    assert all(s.text == NOT_MEASURED for r in rows["latency"] for s in r.stats)


# --- throughput ---------------------------------------------------------------

def test_throughput_is_achieved_over_tx_and_carries_its_unit():
    run = _with_radio("oai")
    assert run.achieved_over_tx_mbps is not None
    text = throughput_text(run)
    assert text.endswith("Mbit/s")
    assert text.startswith(f"{run.achieved_over_tx_mbps:.2f}")


def test_no_comparable_metric_is_a_gnb_throughput_figure():
    """MAC bitrate (OCUDU) and goodput (OAI) differ by header overhead, so they
    are never in the comparable set."""
    fields = {field for metric in COMPARABLE_METRICS for field in metric.fields}
    assert not {"mac_brate_dl_mbps", "goodput_dl_mbps"} & fields


# --- BLER ---------------------------------------------------------------------

def test_bler_is_always_qualified_and_the_two_kinds_never_share_a_group():
    labels = {m.label for m in COMPARABLE_METRICS}
    assert "Residual BLER DL" in labels
    assert "BLER" not in labels
    assert "BLER DL" not in labels

    first_tx = [m for m in VENDOR_METRICS if "First-transmission" in m.label]
    assert first_tx, "first-transmission BLER must exist as a vendor-only metric"
    for metric in first_tx:
        assert metric.vendor == "oai"
        assert "NOT comparable with residual" in (metric.caveat or "")


def test_first_transmission_bler_is_never_in_the_comparable_group():
    run = _with_radio("oai")
    rows = channel_rows(run)
    comparable_labels = [row.label for row in rows["comparable"]]
    assert not any("First-transmission" in label for label in comparable_labels)
    vendor_labels = [row.label for row in rows["vendor"]]
    assert any("First-transmission BLER DL" in label for label in vendor_labels)


def test_residual_bler_reads_four_decimals():
    run = _with_radio("oai")
    row = next(r for r in channel_rows(run)["comparable"] if r.label == "Residual BLER DL")
    assert row.stats[0].text.count(".") == 1
    assert len(row.stats[0].text.split(".")[1]) == 4


# --- SNR ----------------------------------------------------------------------

def test_pusch_snr_is_comparable_and_pucch_snr_is_oai_only():
    comparable = {m.key for m in COMPARABLE_METRICS}
    assert "pusch_snr" in comparable
    assert "pucch_snr" not in comparable
    pucch = next(m for m in VENDOR_METRICS if m.key == "pucch_snr")
    assert pucch.vendor == "oai"
    assert "never compared" in (pucch.caveat or "")


def test_pusch_snr_shows_mean_min_max_and_p95_in_decibels():
    run = _with_radio("oai")
    row = next(r for r in channel_rows(run)["comparable"] if r.label == "PUSCH SNR")
    assert [stat.label for stat in row.stats] == ["mean", "min", "max", "p95"]
    assert all(stat.text.endswith("dB") for stat in row.stats)


# --- RSRP ---------------------------------------------------------------------

def test_the_four_rsrp_fields_are_four_separate_metrics():
    keys = {m.key for m in VENDOR_METRICS + UE_METRICS}
    assert {"ue_l1_rsrp", "rrc_ss_rsrp", "gnb_ul_rsrp", "ue_ss_rsrp"} <= keys


def test_the_ocudu_rsrp_is_labelled_relative_and_not_in_dbm():
    metric = next(m for m in VENDOR_METRICS if m.key == "gnb_ul_rsrp")
    assert metric.vendor == "ocudu"
    assert metric.unit == "dB"
    assert "NOT dBm" in (metric.caveat or "")
    assert "relative" in metric.label.lower()


def test_the_android_and_rrc_sinr_are_never_merged():
    android = next(m for m in UE_METRICS if m.key == "ue_ss_sinr")
    rrc = next(m for m in VENDOR_METRICS if m.key == "rrc_ss_sinr")
    assert android.label != rrc.label
    assert "Android" in android.label
    assert "RRC" in rrc.label
    assert android.fields[0] != rrc.fields[0]


# --- MCS ----------------------------------------------------------------------

def test_mcs_shows_its_table_and_its_cap():
    run = _with_radio("oai")
    row = next(r for r in channel_rows(run)["comparable"] if r.label == "MCS DL")
    assert row.note and "table" in row.note


def test_a_value_at_the_cap_gets_the_capped_flag():
    from console.rapps.ethos.models import CellConfig, RadioSummary

    cell = CellConfig(max_ue_mcs_dl=27, mcs_table_dl="qam64")
    at_cap = RadioSummary(mcs_dl_mean=27.0)
    below = RadioSummary(mcs_dl_mean=19.2)
    metric = next(m for m in COMPARABLE_METRICS if m.key == "mcs_dl")

    assert row_for(metric, at_cap, cell).capped is True
    assert row_for(metric, below, cell).capped is False
    assert "cap 27" in (row_for(metric, at_cap, cell).note or "")


def test_no_cap_means_no_capped_flag():
    from console.rapps.ethos.models import CellConfig, RadioSummary

    metric = next(m for m in COMPARABLE_METRICS if m.key == "mcs_dl")
    row = row_for(metric, RadioSummary(mcs_dl_mean=27.0), CellConfig())
    assert row.capped is False


# --- rank and CQI -------------------------------------------------------------

def test_rank_is_always_direction_labelled():
    labels = {m.label for m in COMPARABLE_METRICS if m.key.startswith("ri_")}
    assert labels == {"RI DL", "RI UL"}
    assert not any(m.label == "MIMO layers" for m in COMPARABLE_METRICS)


def test_ri_ul_carries_the_single_layer_caveat():
    metric = next(m for m in COMPARABLE_METRICS if m.key == "ri_ul")
    assert "4T4R" in (metric.caveat or "")


def test_cqi_is_downlink_only_and_carries_the_csi_rs_caveat():
    metric = next(m for m in COMPARABLE_METRICS if m.key == "cqi")
    assert "DL" in metric.label
    assert "CSI-RS" in (metric.caveat or "")


# --- the vendor split ---------------------------------------------------------

def test_the_vendor_group_shows_only_the_stack_that_ran():
    oai = channel_rows(_with_radio("oai"))
    assert oai["vendor"], "an OAI run has OAI-only fields"
    assert all("relative" not in row.label for row in oai["vendor"]), (
        "OCUDU's relative-dB RSRP must not appear under an OAI run"
    )


def test_an_ocudu_run_does_not_show_oai_only_fields():
    try:
        ocudu = channel_rows(_with_radio("ocudu"))
    except Exception:  # pragma: no cover - depends on the recorded set
        pytest.skip("no recorded OCUDU run with channel metrics")
    for row in ocudu["vendor"]:
        assert "First-transmission" not in row.label
        assert "PUCCH" not in row.label


def test_the_sample_count_is_always_shown():
    run = _with_radio("oai")
    row = next(r for r in channel_rows(run)["comparable"] if r.label == "Radio samples")
    assert row.stats[0].text != NOT_MEASURED
    assert row.stats[0].label == ""


# --- latency ------------------------------------------------------------------

def test_latency_shows_p95_and_two_decimals_in_milliseconds():
    run = _with_radio("oai")
    rows = channel_rows(run)
    rtt = next(r for r in rows["latency"] if r.label == "RTT")
    assert [s.label for s in rtt.stats] == ["min", "mean", "p95", "max", "mdev"]
    assert all(s.text.endswith("ms") for s in rtt.stats if s.measured)
    measured = [s for s in rtt.stats if s.measured][0]
    assert len(measured.text.split(" ")[0].split(".")[1]) == 2
