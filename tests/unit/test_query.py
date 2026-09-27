"""Filtering, sorting, paging, CSV and the sweep grouping."""

from __future__ import annotations

import json
from pathlib import Path

from console.rapps.ethos.models import Run
from console.rapps.ethos.query import (
    CSV_COLUMNS,
    Filters,
    cell_config_consistent,
    csv_rows,
    facets,
    select,
    sweep,
)

RECORDED = Path(__file__).resolve().parent.parent / "recorded" / "runs.json"


def runs() -> list[Run]:
    body = json.loads(RECORDED.read_text(encoding="utf-8"))
    return [Run.model_validate(r) for r in body["runs"]]


def test_unusable_runs_are_hidden_by_default():
    all_runs = runs()
    hidden = select(all_runs, Filters(), limit=0)
    shown = select(all_runs, Filters(usable_only=False), limit=0)
    assert hidden.matched < shown.matched
    assert all(run.usable for run in hidden.rows)


def test_a_run_with_no_delivered_bytes_is_not_usable():
    run = Run(run_id="x", delivered_bytes=None, server_owner="app_binary")
    assert run.usable is False


def test_a_run_from_an_unrecognised_server_is_not_usable():
    run = Run(run_id="x", delivered_bytes=1000, server_owner="foreign")
    assert run.usable is False


def test_filtering_by_topology_direction_and_rate():
    all_runs = runs()
    target = next(r for r in all_runs if r.config_id and r.offered_mbps)
    page = select(
        all_runs,
        Filters(
            config_id=target.config_id,
            usable_only=False,
            rate=f"{target.offered_mbps:g}",
        ),
        limit=0,
    )
    assert page.rows
    for run in page.rows:
        assert run.config_id == target.config_id
        assert run.offered_mbps == target.offered_mbps


def test_filtering_by_tdd_pattern_uses_the_cell_config():
    all_runs = runs()
    patterns = facets(all_runs)["tdd_pattern"]
    if not patterns:
        return
    page = select(all_runs, Filters(tdd_pattern=patterns[0], usable_only=False), limit=0)
    assert page.rows
    assert all(r.cell_config.tdd_pattern == patterns[0] for r in page.rows)


def test_the_date_filter_is_inclusive_of_the_until_day():
    all_runs = runs()
    day = (all_runs[0].t_created or "")[:10]
    page = select(all_runs, Filters(since=day, until=day, usable_only=False), limit=0)
    assert page.rows
    assert all((r.t_created or "").startswith(day) for r in page.rows)


def test_sorting_newest_first_and_oldest_first():
    all_runs = runs()
    newest = select(all_runs, Filters(usable_only=False), limit=0).rows
    oldest = select(all_runs, Filters(usable_only=False), descending=False, limit=0).rows
    assert newest[0].t_created >= newest[-1].t_created
    assert oldest == list(reversed(newest))


def test_sorting_by_a_metric_puts_unmeasured_runs_last():
    all_runs = runs()
    rows = select(all_runs, Filters(usable_only=False), sort="snr", limit=0).rows
    seen_missing = False
    for run in rows:
        has = run.radio_summary and run.radio_summary.pusch_snr_db_mean is not None
        if not has:
            seen_missing = True
        elif seen_missing:
            raise AssertionError("a measured run sorted below an unmeasured one")


def test_paging_walks_the_matched_set_without_gaps():
    all_runs = runs()
    first = select(all_runs, Filters(usable_only=False), limit=3, offset=0)
    second = select(all_runs, Filters(usable_only=False), limit=3, offset=3)
    assert first.page_number == 1 and second.page_number == 2
    assert {r.run_id for r in first.rows} & {r.run_id for r in second.rows} == set()
    assert first.matched == second.matched


def test_the_csv_has_one_header_and_one_row_per_run():
    rows = select(runs(), Filters(usable_only=False), limit=0).rows
    text = csv_rows(rows)
    lines = text.strip().splitlines()
    assert lines[0].split(",") == list(CSV_COLUMNS)
    assert len(lines) == len(rows) + 1


def test_the_csv_writes_a_blank_for_a_value_that_was_not_measured():
    run = Run(run_id="x", config_id="oai-mono_x", offered_mbps=100.0)
    line = csv_rows([run]).strip().splitlines()[1]
    cells = line.split(",")
    snr = cells[CSV_COLUMNS.index("pusch_snr_db_mean")]
    assert snr == "", "an unmeasured value must be blank, never 0"


def test_the_csv_carries_the_stack_label_and_the_flags():
    run = Run(run_id="x", config_id="oai-mixoaiocu_swphy_pega_samsung_o5gs_joule",
              quality_flags=["saturation"])
    line = csv_rows([run]).strip().splitlines()[1]
    assert "OAI CU + OCUDU DU" in line
    assert "saturation" in line


def test_the_sweep_groups_repeats_of_one_offered_load():
    group = [
        Run(run_id="a", offered_mbps=100.0, achieved_over_tx_mbps=99.0),
        Run(run_id="b", offered_mbps=100.0, achieved_over_tx_mbps=101.0),
        Run(run_id="c", offered_mbps=200.0, achieved_over_tx_mbps=199.0),
    ]
    rows = sweep(group)
    assert [row.offered_mbps for row in rows] == [100.0, 200.0]
    assert rows[0].n == 2
    assert rows[0].field_mean("run", "achieved_over_tx_mbps") == 100.0


def test_a_sweep_mean_ignores_the_runs_that_did_not_measure():
    group = [
        Run(run_id="a", offered_mbps=100.0, achieved_over_tx_mbps=99.0),
        Run(run_id="b", offered_mbps=100.0, achieved_over_tx_mbps=None),
    ]
    row = sweep(group)[0]
    assert row.n == 2
    assert row.field_mean("run", "achieved_over_tx_mbps") == 99.0


def test_a_sweep_mean_of_nothing_measured_is_none_not_zero():
    row = sweep([Run(run_id="a", offered_mbps=100.0)])[0]
    assert row.field_mean("run", "achieved_over_tx_mbps") is None


def test_mixed_cell_configs_are_reported_as_inconsistent():
    from console.rapps.ethos.models import CellConfig

    same = [
        Run(run_id="a", cell_config=CellConfig(band="n78", tdd_pattern="7D2U")),
        Run(run_id="b", cell_config=CellConfig(band="n78", tdd_pattern="7D2U")),
    ]
    mixed = [
        Run(run_id="a", cell_config=CellConfig(band="n78", tdd_pattern="7D2U")),
        Run(run_id="b", cell_config=CellConfig(band="n78", tdd_pattern="3D1U")),
    ]
    assert cell_config_consistent(same)[0] is True
    consistent, seen = cell_config_consistent(mixed)
    assert consistent is False
    assert len(seen) == 2


def test_facets_offer_only_values_that_are_present():
    found = facets(runs())
    assert found["direction"]
    assert all(value for value in found["config_id"])
    assert found["rate"] == sorted(found["rate"], key=float)


class TestNodeObservation:
    """``node_free`` is null both when the probe failed and when it was never
    attempted. Those are different facts and must not read the same."""

    def _status(self, **fields):
        from console.rapps.ethos.models import DeployStatus

        base = {
            "namespace": "ravi-ns",
            "releases": [],
            "pods": [],
            "running_pods": [],
            "node_free": None,
            "node_reason": "the node was not observed",
            "node_check": None,
            "warnings": [],
        }
        base.update(fields)
        return DeployStatus.model_validate(base)

    def test_an_unattempted_probe_says_it_was_never_looked_at(self):
        status = self._status()
        assert status.node_observed is False
        assert "never looked at" in status.node_detail
        assert "Select a topology" in status.node_detail

    def test_a_failed_probe_shows_its_real_error(self):
        status = self._status(
            warnings=["node state unavailable: ssh: connect to host 192.168.206.82 port 22: No route to host"]
        )
        assert "No route to host" in status.node_detail
        assert "never looked at" not in status.node_detail

    def test_a_successful_probe_shows_what_it_verified(self):
        status = self._status(
            node_free=True,
            node_reason="state verified: no gNB and no traffic on the node",
            node_check={"verified": True},
        )
        assert status.node_observed is True
        assert status.node_detail == "state verified: no gNB and no traffic on the node"

    def test_the_namespace_is_summarised_either_way(self):
        assert "no Helm release and no pod in ravi-ns" == self._status().namespace_summary
        busy = self._status(releases=["ocudu-gnb"], running_pods=["ocudu-gnb-0"])
        assert "1 release(s) and 1 running pod(s) in ravi-ns" == busy.namespace_summary
