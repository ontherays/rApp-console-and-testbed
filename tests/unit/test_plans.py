"""Saved plans, and the traffic-plan grammar."""

from __future__ import annotations

import pytest

from console.plans import PlanError, PlanStore, slug
from console.rapps.ethos.plan import (
    MAX_REPEATS,
    PlanInvalid,
    TrafficPlan,
    parse_duration,
    parse_rates,
)


# --- the CLI's own grammar ----------------------------------------------------

def test_a_single_rate_a_list_and_a_range_all_parse():
    assert parse_rates("500") == [500.0]
    assert parse_rates("100,200,300") == [100.0, 200.0, 300.0]
    assert parse_rates("100-1000:100") == [float(r) for r in range(100, 1001, 100)]


def test_a_range_without_a_step_steps_by_one_hundred():
    assert parse_rates("100-300") == [100.0, 200.0, 300.0]


@pytest.mark.parametrize(
    "text", ["", "abc", "0", "10001", "100-50:10", "100-200:0", "100,abc"]
)
def test_a_rate_outside_the_grammar_or_the_range_is_refused(text):
    with pytest.raises(PlanInvalid):
        parse_rates(text)


def test_durations_take_a_suffix_or_bare_seconds():
    assert parse_duration("30s") == 30.0
    assert parse_duration("5m") == 300.0
    assert parse_duration("45") == 45.0
    assert parse_duration("1h") == 3600.0


@pytest.mark.parametrize("text", ["", "4s", "abc", "-10"])
def test_a_duration_below_the_minimum_or_unparseable_is_refused(text):
    with pytest.raises(PlanInvalid):
        parse_duration(text)


def test_a_plan_counts_its_points_and_estimates_its_time():
    plan = TrafficPlan(rates_text="100,200", duration_text="30s", repeats=3).parse()
    assert plan.valid
    assert plan.points == 6
    assert plan.estimated_seconds(gap_s=30.0, overhead_s=180.0) == 6 * 60 + 180


def test_every_traffic_error_is_reported_at_once():
    plan = TrafficPlan(
        rates_text="nope", duration_text="1s", repeats=MAX_REPEATS + 1, direction="XL"
    ).parse()
    assert not plan.valid
    assert set(plan.errors) == {"rates", "duration", "repeats", "direction"}


def test_the_plan_document_has_the_shape_the_jobs_endpoint_will_take():
    plan = TrafficPlan(rates_text="100", duration_text="30s", label="sweep").parse()
    document = plan.as_document("ocudu-mono_x", {"gnb_stack": "OCUDU"})
    assert set(document) == {
        "selection", "config_id", "direction", "rates", "duration", "repeats",
        "iperf_server", "radio_samples", "label", "cm_steps", "cm_sweep",
    }
    assert document["config_id"] == "ocudu-mono_x"
    assert document["cm_steps"] == [] and document["cm_sweep"] is None


# --- saved plans --------------------------------------------------------------

def test_a_plan_saves_loads_and_lists(tmp_path):
    store = PlanStore(tmp_path)
    store.save("sweep 0927", {"direction": "DL", "rates": "100"})
    loaded = store.get("sweep-0927")
    assert loaded.plan["rates"] == "100"
    assert [p.name for p in store.list()] == ["sweep-0927"]


def test_a_plan_name_cannot_escape_the_plans_directory(tmp_path):
    store = PlanStore(tmp_path)
    saved = store.save("../../escape", {"a": 1})
    assert saved.path.parent == tmp_path.resolve()
    assert not (tmp_path.parent / "escape.json").exists()


def test_an_empty_name_is_refused(tmp_path):
    with pytest.raises(PlanError):
        PlanStore(tmp_path).save("///", {})


def test_a_missing_plan_says_so(tmp_path):
    with pytest.raises(PlanError):
        PlanStore(tmp_path).get("never-saved")


def test_deleting_a_plan_that_is_not_there_is_not_an_error(tmp_path):
    PlanStore(tmp_path).delete("never-saved")


def test_listing_an_absent_directory_is_empty(tmp_path):
    assert PlanStore(tmp_path / "nope").list() == []


def test_a_slug_keeps_letters_digits_dash_and_underscore():
    assert slug("Sweep 09/27 (DL)") == "Sweep-09-27-DL"
