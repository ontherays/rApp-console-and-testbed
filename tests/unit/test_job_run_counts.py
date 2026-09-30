"""What `X/Y runs` in the sweep picker means.

The two numbers answer one question each, and both come from the job's points,
which is the set ETHOS resolves `job_ids` to:

    numerator    runs that recorded a measurement
    denominator  runs eligible to be drawn

`run_ids` is deliberately not the denominator. A sweep also creates a run it
abandons before any traffic, so counting it read `10/11` for a job that offers
a figure ten runs and has nothing else to give.
"""

from __future__ import annotations

import pytest

from console.rapps.ethos.models import Job


def job(points, run_ids=None, **over):
    """A job from (run_id, achieved_mbps) pairs; None means it measured nothing."""
    return Job.model_validate({
        "job_id": "j-20260929T075656Z",
        "state": "completed",
        "config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule",
        "created": "2026-09-29T07:56:56Z",
        "plan": {"rates": "100-1000", "direction": "DL"},
        "run_ids": run_ids if run_ids is not None else [r for r, _ in points],
        "points": [{"run_id": r, "offered_mbps": 100.0, "achieved_mbps": a,
                    "status": "ok" if a is not None else "failed"}
                   for r, a in points],
        **over,
    })


# --- the model is the single definition -------------------------------------


def test_the_abandoned_run_is_not_graph_eligible():
    """A sweep of ten measured points also creates one run it never measures."""
    measured = [(f"r{i}", 100.0 + i) for i in range(10)]
    j = job(measured, run_ids=["preflight", *[r for r, _ in measured]])

    assert len(j.run_ids) == 11
    assert len(j.graph_run_ids) == 10
    assert len(j.measured_run_ids) == 10
    assert "preflight" not in j.graph_run_ids


def test_one_measured_run_of_two_run_ids_is_one_of_one():
    j = job([("r1", 99.9)], run_ids=["preflight", "r1"])
    assert (len(j.measured_run_ids), len(j.graph_run_ids)) == (1, 1)


def test_a_point_with_no_measurement_is_eligible_but_not_measured():
    """The case that must not be tidied away: the run was drawn from, and
    recorded nothing."""
    j = job([("r1", 99.9), ("r2", None)])
    assert len(j.graph_run_ids) == 2
    assert j.measured_run_ids == ["r1"]


def test_a_job_that_measured_nothing_reads_zero():
    j = job([("r1", None)], run_ids=["preflight", "r1"])
    assert (len(j.measured_run_ids), len(j.graph_run_ids)) == (0, 1)


def test_a_job_with_no_points_offers_a_figure_nothing():
    j = job([], run_ids=["preflight", "r1"])
    assert j.graph_run_ids == [] and j.measured_run_ids == []


def test_points_keep_their_order_and_de_duplicate():
    j = job([("r2", 1.0), ("r1", 2.0), ("r2", 3.0)])
    assert j.graph_run_ids == ["r2", "r1"]


def test_a_point_without_a_run_id_is_ignored():
    j = Job.model_validate({
        "job_id": "j-1",
        "run_ids": ["r1"],
        "points": [{"offered_mbps": 100.0, "achieved_mbps": 99.0},
                   {"run_id": None, "achieved_mbps": 99.0},
                   {"run_id": "r1", "achieved_mbps": 99.0}],
    })
    assert j.graph_run_ids == ["r1"] and j.measured_run_ids == ["r1"]


# --- and what the picker renders from it ------------------------------------


@pytest.mark.parametrize("points, run_ids, shown", [
    ([(f"r{i}", 100.0) for i in range(10)], ["pre"] + [f"r{i}" for i in range(10)], "10/10 runs"),
    ([("r1", 99.9)], ["pre", "r1"], "1/1 runs"),
    ([("r1", 99.9), ("r2", 88.0)], ["r1", "r2"], "2/2 runs"),
    ([("r1", 99.9), ("r2", None)], ["pre", "r1", "r2"], "1/2 runs"),
])
def test_the_picker_renders_measured_over_eligible(client, ethos_url, points,
                                                   run_ids, shown):
    ethos_url.answer("GET", "/jobs", 200, {
        "count": 1, "jobs": [job(points, run_ids=run_ids).model_dump(mode="json")]})
    body = client.get("/graphs/jobs").text
    assert shown in body


def test_a_short_measured_sweep_is_marked_and_explained(client, ethos_url):
    """Not hidden: the row says so and the hover says by how much."""
    ethos_url.answer("GET", "/jobs", 200, {
        "count": 1,
        "jobs": [job([("r1", 99.9), ("r2", None), ("r3", None)],
                     run_ids=["pre", "r1", "r2", "r3"]).model_dump(mode="json")]})
    body = client.get("/graphs/jobs").text
    assert "1/3 runs" in body
    assert "runs-short" in body
    assert "2 of this sweep's runs recorded no measurement" in body


def test_a_fully_measured_sweep_is_not_marked(client, ethos_url):
    ethos_url.answer("GET", "/jobs", 200, {
        "count": 1, "jobs": [job([("r1", 99.9), ("r2", 88.0)]).model_dump(mode="json")]})
    body = client.get("/graphs/jobs").text
    assert "2/2 runs" in body
    assert "runs-short" not in body
