"""Figures on request (B9), through the console.

Everything runs against the fake ETHOS, which replays responses recorded from
the real B9 endpoints, so the shapes under test are the real ones.

What is being checked is the seam: that the form is built from ETHOS's own
options, that a request reaches ETHOS as the operator described it, that a
refusal is shown in ETHOS's words, and that a downloaded file arrives with the
content type and the name it should have.
"""

from __future__ import annotations

import pytest

# ETHOS's two duration refusals, verbatim. They differ in one clause and the
# console must treat them differently: one is a flag away, the other is not.
INSIDE_A_POINT = (
    "these POINTS pool runs of different durations -- "
    "ocudu-mono_swphy_pega_samsung_o5gs_joule @ 100 M: [10, 20] s. A mean "
    "across durations at one offered rate describes neither run, and "
    "--allow-mixed-durations does NOT permit it. Narrow with --min-duration, "
    "or select the runs you want with --runs."
)
ACROSS_POINTS = (
    "these series mix run durations across their points -- "
    "ocudu-mono_swphy_pega_samsung_o5gs_joule: [10, 20] s. Re-run with "
    "--min-duration to select one, or --allow-mixed-durations to accept it "
    "(the per-point durations are then recorded)."
)


# --- the form is ETHOS's own table -------------------------------------------


def test_the_form_offers_exactly_the_metrics_ethos_offers(client, ethos_url):
    body = client.get("/graphs").text
    options = ethos_url._load("plot_options")
    for metric in options["metrics"]:
        assert metric["label"] in body, metric["id"]


def test_the_form_offers_ethoss_kinds_groupings_widths_and_scales(client, ethos_url):
    body = client.get("/graphs").text
    options = ethos_url._load("plot_options")
    for value in (options["kinds"] + options["group_by"] + options["y_scales"]):
        assert f'value="{value}"' in body, value
    for width in options["widths"]:
        assert f'value="{width}"' in body, width


def test_a_metrics_caveat_is_shown_in_ethoss_words(client, ethos_url):
    """The caveats are the point: CQI against each gNB's own CSI-RS, throughput
    as the one rate comparable across stacks."""
    options = ethos_url._load("plot_options")
    cqi = next(m for m in options["metrics"] if m["id"] == "cqi")
    body = client.get("/graphs/metric-note?metric=cqi").text
    # Jinja escapes the apostrophe in "gNB's", so the tail is the stable part.
    assert cqi["note"].split("own ", 1)[1][:40] in body


def test_the_metrics_ethos_does_not_offer_are_listed_with_the_reason(client, ethos_url):
    """"Why can't I plot first-transmission BLER" is answered where somebody
    would look for it."""
    body = client.get("/graphs").text
    for item in ethos_url._load("plot_options")["not_offered"]:
        assert item["id"] in body
        assert item["reason"][:40] in body


def test_an_mcs_metric_says_its_cap_is_drawn(client):
    body = client.get("/graphs/metric-note?metric=mcs_dl").text
    assert "cap" in body.lower()


# --- making one ----------------------------------------------------------------


def test_generating_sends_the_form_as_ethos_takes_it(client, ethos_url):
    client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a run-b", "metric": "pusch_snr",
        "kind": "line", "group_by": "config", "width": "double",
        "y_scale": "log", "label": "snr", "min_duration_s": "10",
        "exclude_known_issues": "1",
    })
    sent = ethos_url.plot_requests[-1]
    assert sent["run_ids"] == ["run-a", "run-b"]
    assert sent["metric"] == "pusch_snr"
    assert sent["width"] == "double"
    assert sent["y_scale"] == "log"
    assert sent["min_duration_s"] == 10.0
    assert sent["exclude_known_issues"] is True
    # A box left alone is not sent at all, rather than sent empty.
    assert "campaign_id" not in sent
    assert "allow_mixed_durations" not in sent


def test_the_figure_its_warnings_and_its_data_come_back(client, ethos_url):
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a", "metric": "mcs_dl", "label": "mcs",
    }).text
    manifest = ethos_url._load("plot_manifest")
    assert "<img" in body
    for warning in manifest["warnings"]:
        assert warning[:40] in body
    assert "Data" in body
    assert "manifest.json" in body


def test_the_four_downloads_are_offered(client):
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a", "label": "dl",
    }).text
    for name in ("image.png", "figure.pdf", "raw.csv", "points.csv"):
        assert name in body


def test_the_dropped_runs_are_listed_with_their_reason(client, ethos_url):
    """A point missing because a run had no radio summary is a fact about the
    figure; a reader who cannot see it reads the gap as a measurement."""
    manifest = dict(ethos_url._load("plot_manifest"))
    manifest["selection"] = dict(manifest.get("selection") or {})
    manifest["selection"]["dropped"] = [
        {"run_id": "old-run-1", "reason": "no radio summary: pusch_snr_db_mean "
                                          "was not recorded"}
    ]
    ethos_url.answer("POST", "/plots", 201, {
        "figure_id": "2026-09-29__091500_line_drops", "folder": "/graphs/x",
        "warnings": [], "manifest": manifest,
    })
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a", "metric": "pusch_snr",
    }).text
    assert "old-run-1" in body
    assert "no radio summary" in body


# --- what it does with a refusal ----------------------------------------------


def test_a_refusal_is_shown_in_ethoss_own_words(client, ethos_url):
    ethos_url.refuse_next_plot("nothing to plot: 3 row(s) loaded, all 3 filtered out.")
    response = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a", "label": "empty"})
    assert response.status_code == 422
    assert "nothing to plot: 3 row(s) loaded" in response.text


def test_a_duration_refusal_lists_the_buckets(client, ethos_url):
    ethos_url.refuse_next_plot(INSIDE_A_POINT)
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "a b", "label": "mixed"}).text
    assert "10 s" in body and "20 s" in body


def test_lengths_differing_between_points_offer_the_retry(client, ethos_url):
    """The flag fixes this one, so the button is worth offering."""
    ethos_url.refuse_next_plot(ACROSS_POINTS)
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "a b", "label": "across"}).text
    assert "Retry allowing mixed durations" in body
    assert 'hx-vals=\'{"allow_mixed_durations": "1"}\'' in body


def test_two_lengths_inside_one_point_offer_no_retry(client, ethos_url):
    """ETHOS refuses that whatever the flag says, so a retry button would fail
    again in the same way and read as the console not knowing its own backend."""
    ethos_url.refuse_next_plot(INSIDE_A_POINT)
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "a b", "label": "within"}).text
    assert "Retry allowing mixed durations" not in body
    assert "does not help here" in body


def test_the_retry_sets_the_flag_explicitly(client, ethos_url):
    ethos_url.refuse_next_plot(ACROSS_POINTS)
    client.post("/graphs/make", data={"source": "runs", "run_ids": "a b"})
    client.post("/graphs/make", data={
        "source": "runs", "run_ids": "a b", "allow_mixed_durations": "1"})
    assert ethos_url.plot_requests[-1]["allow_mixed_durations"] is True


def test_a_refusal_leaves_the_form_alone(client, ethos_url):
    """Only the result panel is swapped, so what was typed is still typed.

    Re-rendering the form with the submitted values would also work, and would
    lose anything the operator changed while waiting for the answer.
    """
    ethos_url.refuse_next_plot("nothing to plot")
    body = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a run-b", "label": "kept"}).text
    assert "<form" not in body
    assert "nothing to plot" in body


def test_a_refusal_is_marked_as_one_to_swap_in_place(client, ethos_url):
    """The 422 carries the header that lets htmx swap it.

    htmx drops a 4xx body by default, which would leave the operator with a
    toast naming the status code and none of the sentence ETHOS wrote. The
    header is what console.js opts in on, so it is part of the answer rather
    than a detail of the page.
    """
    ethos_url.refuse_next_plot(ACROSS_POINTS)
    response = client.post("/graphs/make", data={
        "source": "runs", "run_ids": "run-a run-b"},
        headers={"hx-request": "true"})
    assert response.status_code == 422
    assert response.headers["x-console-inline"] == "1"


# --- the gallery -----------------------------------------------------------------


def test_the_gallery_shows_who_made_each_figure(client, ethos_url):
    body = client.get("/graphs").text
    recorded = (ethos_url._load("plots") or {})["figures"]
    assert any(f["made_by"] == "cli" for f in recorded)
    assert "CLI" in body
    # And a console-made one is chipped differently.
    client.post("/graphs/make", data={"source": "runs", "run_ids": "a",
                                      "label": "console-made"})
    assert "Console" in client.get("/graphs").text


def test_regenerating_asks_ethos_and_goes_to_the_new_figure(client, ethos_url):
    figure_id = (ethos_url._load("plots") or {})["figures"][0]["figure_id"]
    response = client.post(f"/graphs/{figure_id}/regenerate")
    assert response.status_code == 204
    assert response.headers["HX-Redirect"].startswith("/graphs/view/")
    assert response.headers["HX-Redirect"] != f"/graphs/view/{figure_id}"
    assert "Regenerated" in response.headers["X-Console-Toast"]


# --- downloads -------------------------------------------------------------------


@pytest.mark.parametrize("name,media,suffix", [
    ("image.png", "image/png", ".png"),
    ("figure.pdf", "application/pdf", ".pdf"),
    ("raw.csv", "text/csv", "raw.csv"),
    ("points.csv", "text/csv", "points.csv"),
])
def test_a_download_carries_its_type_and_a_useful_name(client, ethos_url,
                                                       name, media, suffix):
    """Named after the figure, not after the endpoint: four downloads must not
    all land as `image.png`."""
    figure_id = (ethos_url._load("plots") or {})["figures"][0]["figure_id"]
    response = client.get(f"/graphs/file/{figure_id}/{name}?label=full-sweep")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media)
    assert suffix in response.headers["content-disposition"]
    assert "full-sweep" in response.headers["content-disposition"]


def test_a_downloads_bytes_are_ethoss_own(client, ethos_url):
    from tests.fake_ethos import FakeEthos

    figure_id = (ethos_url._load("plots") or {})["figures"][0]["figure_id"]
    response = client.get(f"/graphs/file/{figure_id}/image.png")
    assert response.content == FakeEthos.FILES["image.png"][0]


def test_only_the_four_names_are_served(client, ethos_url):
    figure_id = (ethos_url._load("plots") or {})["figures"][0]["figure_id"]
    assert client.get(f"/graphs/file/{figure_id}/manifest.json").status_code == 404


# --- the entry points that prefill the form ---------------------------------------


def test_results_selection_prefills_the_runs(client):
    body = client.get("/graphs?run_id=run-a&run_id=run-b").text
    assert 'value="run-a run-b"' in body


def test_a_sweep_column_prefills_the_runs_and_the_metric(client):
    body = client.get("/graphs?source=runs&metric=pusch_snr&run_id=run-a").text
    assert 'value="run-a"' in body
    assert '<option value="pusch_snr"\n                  selected' in body \
        or 'value="pusch_snr"' in body and "selected" in body


def test_a_finished_job_prefills_its_job_id(client):
    body = client.get("/graphs?job_id=j-1&label=sweep-1").text
    assert 'value="j-1"' in body
    assert 'value="sweep-1"' in body


def test_the_sweep_view_links_each_metric_column(client, ethos_url):
    """Every column that maps to a cross-vendor metric gets a link; the
    OAI-only one does not, for the same reason ETHOS does not offer it."""
    listing = ethos_url._load("runs") or {"runs": []}
    run_id = listing["runs"][0]["run_id"]
    body = client.get(f"/results/compare?run_id={run_id}").text
    assert "metric=pusch_snr" in body
    assert "metric=mcs_dl" in body
    assert "metric=bler_dl_first_tx" not in body


def test_the_results_page_offers_graphing_the_selection(client):
    body = client.get("/results").text
    assert 'formaction="/graphs"' in body


def test_a_completed_job_offers_plotting_itself(client, ethos_url):
    job_id = "j-done"
    ethos_url.add_job(job_id, state="completed", ended="2026-09-29T09:00:00Z",
                      stop_requested=False)
    body = client.get(f"/jobs/{job_id}").text
    assert "Plot this job" in body
    assert f"job_id={job_id}" in body


def test_a_running_job_does_not_offer_it(client, ethos_url):
    """A figure of a job still running is a figure of however much of it
    happened to exist at that moment."""
    ethos_url.add_job("j-busy", state="running", ended="", stop_requested=False)
    assert "Plot this job" not in client.get("/jobs/j-busy").text


# --- the palette is ETHOS's ---------------------------------------------------------


def test_the_palette_comes_from_ethos_not_from_a_copy(client, ethos_url):
    from console.rapps.ethos.series import series_for

    served = {s["head"]: s for s in ethos_url._load("plot_series")["series"]}
    for head, entry in served.items():
        style = series_for(f"{head}_swphy_pega_samsung_o5gs_joule")
        assert style.colour == entry["colour"], head
        assert style.label == entry["label"], head
        assert style.marker == entry["marker"], head


def test_a_legacy_head_still_finds_its_colour(client, ethos_url):
    """ETHOS resolves these inside its own lookup, and its served list is keyed
    by the current heads, so the console maps them before asking."""
    from console.rapps.ethos.series import series_for

    served = {s["head"]: s for s in ethos_url._load("plot_series")["series"]}
    assert series_for("oai-mixoaiocu_x").colour == served["oaicu-ocududu"]["colour"]


def test_an_empty_palette_answer_is_ignored(client, ethos_url):
    """Blanking every chip because one response came back empty is worse than
    keeping the palette that was working a minute ago."""
    from console.rapps.ethos.models import PlotSeriesList
    from console.rapps.ethos.series import PALETTE, series_for

    before = series_for("ocudu-mono_x").colour
    PALETTE.replace(PlotSeriesList.model_validate({"series": [], "order": []}))
    assert series_for("ocudu-mono_x").colour == before


def test_a_stack_ethos_does_not_know_stays_visible(client):
    from console.rapps.ethos.series import series_for

    style = series_for("brand-new-stack_x")
    assert style.label == "Unknown stack"
    assert style.colour
