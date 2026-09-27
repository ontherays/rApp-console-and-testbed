"""The Overview's arithmetic: periods, comparisons, shares and per-day bests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from console.charts import Column, HexCell, dot_matrix, hex_grid, tick_bar
from console.overview import (
    Change,
    any_flagged,
    best_at,
    best_per_day,
    by_topology,
    median_snr,
    newest,
    slice_runs,
    topologies_needing_you,
)
from console.rapps.ethos.models import RadioSummary, Run

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def run_at(hours_ago: float, **fields) -> Run:
    stamp = (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")
    base = {"run_id": f"r{hours_ago}", "t_created": stamp,
            "config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule"}
    base.update(fields)
    return Run.model_validate(base)


class TestSlicing:
    def test_a_period_splits_into_now_and_the_same_span_before(self):
        runs = [run_at(1), run_at(20), run_at(30), run_at(47), run_at(100)]
        window = slice_runs(runs, "24h", "all", now=NOW)
        assert len(window.current) == 2       # 1 h and 20 h ago
        assert len(window.previous) == 2      # 30 h and 47 h ago
        assert window.label == "Last 24 hours"

    def test_direction_filters_both_halves(self):
        runs = [run_at(1, direction="DL"), run_at(2, direction="UL"),
                run_at(30, direction="DL")]
        window = slice_runs(runs, "24h", "DL", now=NOW)
        assert len(window.current) == 1
        assert len(window.previous) == 1

    def test_needs_attention_selects_flagged_runs(self):
        runs = [run_at(1), run_at(2, quality_flags=["saturation"])]
        window = slice_runs(runs, "24h", "flagged", now=NOW)
        assert len(window.current) == 1
        assert any_flagged(runs) is True
        assert any_flagged([run_at(1)]) is False

    def test_a_run_with_no_timestamp_is_left_out_rather_than_guessed(self):
        runs = [Run(run_id="x"), run_at(1)]
        assert len(slice_runs(runs, "24h", "all", now=NOW).current) == 1


class TestChange:
    def test_a_rise_and_a_fall_carry_their_direction(self):
        assert Change.between(10.0, 8.0).direction == "up"
        assert Change.between(8.0, 10.0).direction == "down"

    def test_equal_values_are_flat_and_say_so(self):
        change = Change.between(10.0, 10.0)
        assert change.direction == "flat"
        assert change.text == "No change"

    def test_no_previous_value_means_no_comparison_at_all(self):
        """A change against nothing is not zero change."""
        assert Change.between(10.0, None) is None
        assert Change.between(None, 10.0) is None

    def test_a_percentage_comparison_reads_as_a_percentage(self):
        change = Change.between(120.0, 100.0, as_percent=True)
        assert change.text == "+20.0%"


class TestValues:
    def test_best_at_a_rate_ignores_other_rates_and_directions(self):
        runs = [
            run_at(1, offered_mbps=1000.0, direction="DL", achieved_over_tx_mbps=900.0),
            run_at(2, offered_mbps=1000.0, direction="DL", achieved_over_tx_mbps=935.0),
            run_at(3, offered_mbps=1000.0, direction="UL", achieved_over_tx_mbps=999.0),
            run_at(4, offered_mbps=500.0, direction="DL", achieved_over_tx_mbps=999.0),
        ]
        assert best_at(runs, 1000.0) == 935.0

    def test_best_at_a_rate_nobody_ran_is_none_not_zero(self):
        assert best_at([run_at(1, offered_mbps=500.0)], 1000.0) is None

    def test_the_median_snr_ignores_runs_that_measured_none(self):
        runs = [
            run_at(1, radio_summary=RadioSummary(pusch_snr_db_mean=20.0).model_dump()),
            run_at(2, radio_summary=RadioSummary(pusch_snr_db_mean=24.0).model_dump()),
            run_at(3),
        ]
        assert median_snr(runs) == 22.0
        assert median_snr([run_at(1)]) is None

    def test_newest_picks_the_latest_timestamp(self):
        assert newest([run_at(5), run_at(1), run_at(9)]).t_created == run_at(1).t_created


class TestShares:
    def test_shares_sum_to_a_hundred_and_are_ordered_by_count(self):
        runs = [run_at(1)] * 3 + [
            run_at(2, config_id="oai-mono_swphy_pega_samsung_o5gs_joule")
        ]
        shares = by_topology(runs)
        assert [s.count for s in shares] == [3, 1]
        assert round(sum(s.share for s in shares)) == 100
        assert shares[0].label == "OCUDU monolithic"

    def test_a_run_with_no_config_id_is_not_counted(self):
        assert by_topology([Run(run_id="x")]) == []


class TestPerDay:
    def test_one_column_per_day_of_the_period(self):
        window = slice_runs([run_at(1, achieved_over_tx_mbps=900.0)], "7d", "all", now=NOW)
        days = best_per_day(window)
        assert len(days) == 7
        assert days[-1].best == 900.0

    def test_a_day_with_no_run_is_none_never_zero(self):
        window = slice_runs([run_at(1, achieved_over_tx_mbps=900.0)], "7d", "all", now=NOW)
        days = best_per_day(window)
        assert days[0].best is None
        assert days[0].runs == 0

    def test_the_best_of_a_day_is_its_maximum(self):
        runs = [run_at(1, achieved_over_tx_mbps=500.0), run_at(2, achieved_over_tx_mbps=900.0)]
        days = best_per_day(slice_runs(runs, "24h", "all", now=NOW))
        assert max(d.best for d in days if d.best is not None) == 900.0


class TestNeedsYou:
    def test_least_complete_topology_comes_first(self):
        runs = [
            run_at(1, run_id="a", delivered_bytes=None),
            run_at(2, run_id="b", config_id="oai-mono_swphy_pega_samsung_o5gs_joule",
                   delivered_bytes=1000),
        ]
        rows = topologies_needing_you(slice_runs(runs, "24h", "all", now=NOW))
        assert rows[0].label == "OCUDU monolithic"
        assert rows[0].completed == 0

    def test_a_single_run_campaign_is_not_treated_as_a_sweep(self):
        """"0 of 1 points" for a topology with many runs says nothing useful."""
        runs = [run_at(i, run_id=f"r{i}", delivered_bytes=1000) for i in range(1, 6)]
        runs.append(run_at(0.5, run_id="lone", campaign_id="doccheck"))
        rows = topologies_needing_you(slice_runs(runs, "24h", "all", now=NOW))
        assert rows[0].latest_campaign is None
        assert rows[0].planned == 6

    def test_a_real_sweep_is_used_for_the_bar(self):
        runs = [
            run_at(3, run_id="s1", campaign_id="sweep", delivered_bytes=1000),
            run_at(2, run_id="s2", campaign_id="sweep", delivered_bytes=1000),
            run_at(1, run_id="s3", campaign_id="sweep"),
        ]
        rows = topologies_needing_you(slice_runs(runs, "24h", "all", now=NOW))
        assert rows[0].latest_campaign == "sweep"
        assert (rows[0].completed, rows[0].planned) == (2, 3)

    def test_each_topology_carries_its_config_id_and_a_unique_code(self):
        """Two config_ids can share a label, ocudu-mono with a Samsung and with
        an MTK UE both read "OCUDU monolithic"."""
        runs = [
            run_at(1, run_id="a"),
            run_at(2, run_id="b", config_id="ocudu-mono_swphy_pega_mtk_o5gs_joule"),
        ]
        rows = topologies_needing_you(slice_runs(runs, "24h", "all", now=NOW))
        assert len({r.config_id for r in rows}) == 2
        assert all(r.initials == "OM" for r in rows)


class TestCharts:
    def test_the_hex_grid_draws_one_coloured_cell_per_item(self):
        svg = hex_grid([HexCell("#0072B2", "run a"), HexCell("#E69F00", "run b")])
        assert svg.count("#0072B2") == 1
        assert svg.count("#E69F00") == 1
        assert "<title>run a</title>" in svg

    def test_the_hex_grid_fills_the_rest_with_empty_cells(self):
        svg = hex_grid([HexCell("#0072B2", "one")])
        assert svg.count("<use") > 10

    def test_an_empty_grid_still_draws(self):
        assert "<svg" in hex_grid([])

    def test_the_dot_matrix_scales_to_the_largest_value(self):
        matrix = dot_matrix([Column("a", 100.0), Column("b", 50.0)])
        assert matrix.top >= 100.0

    def test_a_column_with_no_value_is_drawn_empty(self):
        matrix = dot_matrix([Column("a", 100.0), Column("b", None, "b: no run")])
        assert "b: no run" in matrix.svg

    def test_the_dot_matrix_survives_having_nothing_to_draw(self):
        matrix = dot_matrix([Column("a", None)])
        assert matrix.top == 1.0
        assert "<svg" in matrix.svg

    def test_the_tick_bar_fills_in_proportion(self):
        assert tick_bar(0, 10).count("background:") == 0
        assert tick_bar(10, 10).count("background:") == 18
        assert "9 of 10" in tick_bar(9, 10)

    def test_a_tick_bar_with_no_total_draws_nothing(self):
        assert "<i" not in tick_bar(0, 0)


class TestAmbiguousLabels:
    """Two config_ids can carry the same label. The legend must say which is
    which, or the two rows read as one topology counted twice."""

    def test_same_label_different_config_marks_both_ambiguous(self):
        runs = [
            run_at(1, run_id="a", config_id="ocudu-mono_swphy_pega_samsung_o5gs_joule"),
            run_at(2, run_id="b", config_id="ocudu-mono_swphy_pega_mtk_o5gs_joule"),
        ]
        shares = by_topology(runs)
        assert len(shares) == 2
        assert all(share.ambiguous for share in shares)
        assert len({share.config_id for share in shares}) == 2

    def test_a_legacy_head_aliases_onto_the_same_stack_but_stays_its_own_row(self):
        """``ocudu-mixocuoai`` and ``ocuducu-oaidu`` are the same topology under
        two spellings; they share a colour and a label, and are different
        config_ids in the archive."""
        runs = [
            run_at(1, run_id="a", config_id="ocuducu-oaidu_swphy_pega_samsung_o5gs_joule"),
            run_at(2, run_id="b", config_id="ocudu-mixocuoai_swphy_pega_samsung_o5gs_joule"),
        ]
        shares = by_topology(runs)
        assert len(shares) == 2
        assert {share.label for share in shares} == {"OCUDU CU + OAI DU"}
        assert {share.colour for share in shares} == {"#D55E00"}
        assert all(share.ambiguous for share in shares)

    def test_a_unique_label_is_not_marked(self):
        runs = [run_at(1, config_id="oai-mono_swphy_pega_samsung_o5gs_joule")]
        assert by_topology(runs)[0].ambiguous is False
