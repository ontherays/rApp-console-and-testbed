"""Search over the run archive."""

from __future__ import annotations


def test_an_empty_search_explains_the_shortcut(client):
    body = client.get("/search").text
    assert "Press" in body and "/" in body


def test_an_exact_run_id_goes_straight_to_that_run(client):
    listing = client.get("/results?usable_only=no").text
    import re

    run_id = re.search(r'/results/runs/([\w\-.]+)"', listing).group(1)
    response = client.get(f"/search?q={run_id}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/results/runs/{run_id}"


def test_a_partial_run_id_lists_the_matches(client):
    body = client.get("/search?q=20260927").text
    assert "Runs" in body


def test_a_config_id_fragment_finds_the_configuration(client):
    body = client.get("/search?q=ocudu-mono").text
    assert "Configurations" in body
    assert "OCUDU (monolithic)" in body


def test_a_campaign_name_finds_the_campaign(client):
    body = client.get("/search?q=chanmetrics").text
    assert "Campaigns" in body
    assert "Open sweep" in body


def test_nothing_matching_says_so_rather_than_showing_an_empty_table(client):
    body = client.get("/search?q=zzzznotathing").text
    assert "Nothing in the archive matches" in body


def test_search_survives_ethos_being_down(client, ethos_url):
    ethos_url.go_down()
    response = client.get("/search?q=ocudu")
    assert response.status_code == 200
    assert "unreachable" in response.text.lower()
