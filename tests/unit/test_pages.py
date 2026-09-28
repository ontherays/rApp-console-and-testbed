"""Every page, against the fake ETHOS. No testbed is touched (NF-07)."""

from __future__ import annotations

import pytest

from console.auth import SESSION_COOKIE


PAGES = [
    "/",
    "/?period=24h",
    "/?period=7d&kind=DL",
    "/?kind=flagged",
    "/plan",
    "/jobs",
    "/results",
    "/graphs",
    "/testbed",
    "/o1",
    "/o2",
    "/docs",
    "/search",
    "/search?q=ocudu",
    "/partials/status",
]


@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text[:800]
    assert response.content


def test_every_response_carries_the_security_headers(client):
    response = client.get("/")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    # Every asset is vendored, so no host may be reachable from a page.
    assert "http" not in response.headers["content-security-policy"].replace("https:", "")


def test_a_page_loads_no_third_party_asset(client):
    """SE-09: no CDN, so the console works with no internet and runs no
    third-party code."""
    body = client.get("/").text
    for marker in ("//unpkg.com", "//cdn.", "https://cdn", "googleapis"):
        assert marker not in body


class TestLogin:
    def test_a_page_without_a_session_redirects_to_login(self, client):
        client.cookies.clear()
        response = client.get("/results", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")
        assert "next=/results" in response.headers["location"]

    def test_an_htmx_request_without_a_session_gets_401_not_a_redirect(self, client):
        """A redirect would swap the login form into a panel."""
        client.cookies.clear()
        response = client.get("/partials/status", headers={"HX-Request": "true"})
        assert response.status_code == 401
        assert response.json()["error"] == "login_required"

    def test_the_login_page_is_public(self, client):
        client.cookies.clear()
        response = client.get("/login")
        assert response.status_code == 200
        assert "Password" in response.text

    def test_a_wrong_password_is_refused_and_counts_towards_the_lockout(self, client, monkeypatch):
        from console.auth import hash_password

        client.app.state.settings = client.app.state.settings.__class__(
            **{
                **client.app.state.settings.__dict__,
                "password_hash": hash_password("the right password"),
            }
        )
        client.cookies.clear()
        for attempt in range(5):
            response = client.post(
                "/login", data={"password": "wrong", "next": "/"},
                follow_redirects=False,
            )
            assert response.status_code == 401, attempt
        response = client.post(
            "/login", data={"password": "the right password", "next": "/"},
            follow_redirects=False,
        )
        assert response.status_code == 429
        assert "refused" in response.text

    def test_the_right_password_starts_a_session(self, client):
        from console.auth import hash_password

        client.app.state.settings = client.app.state.settings.__class__(
            **{
                **client.app.state.settings.__dict__,
                "password_hash": hash_password("the right password"),
            }
        )
        client.app.state.limiter.record_success()
        client.cookies.clear()
        response = client.post(
            "/login", data={"password": "the right password", "next": "/results"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/results"
        assert SESSION_COOKIE in response.cookies

    def test_login_says_so_when_no_password_is_configured(self, client):
        client.cookies.clear()
        response = client.post("/login", data={"password": "anything"})
        assert response.status_code == 503
        assert "set-password" in response.text

    def test_logout_clears_the_session(self, client):
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")


class TestCsrf:
    def test_a_post_without_the_token_is_refused(self, client):
        del client.headers["X-CSRF-Token"]
        response = client.post("/plan/resolve", data={})
        assert response.status_code == 403
        assert response.json()["error"] == "csrf_failed"

    def test_a_post_with_a_wrong_token_is_refused(self, client):
        client.headers["X-CSRF-Token"] = "not-the-token"
        response = client.post("/plan/resolve", data={})
        assert response.status_code == 403

    def test_a_post_with_the_token_is_accepted(self, client):
        response = client.post("/plan/resolve", data={})
        assert response.status_code == 200


class TestEthosDown:
    def test_the_strip_says_ethos_is_unreachable(self, client, ethos_url):
        ethos_url.go_down()
        response = client.get("/partials/status")
        assert response.status_code == 200
        assert "unreachable" in response.text

    def test_the_results_page_reports_the_failure_rather_than_an_empty_table(
        self, client, ethos_url
    ):
        ethos_url.go_down()
        response = client.get("/results")
        assert response.status_code == 200
        assert "unreachable" in response.text.lower()

    def test_every_page_still_renders(self, client, ethos_url):
        """A console that cannot read ETHOS still has to draw its own pages, or
        an outage looks like a crash."""
        ethos_url.go_down()
        for path in ("/", "/plan", "/results", "/jobs", "/graphs", "/search?q=x"):
            assert client.get(path).status_code == 200, path

    def test_the_console_reports_itself_up_while_ethos_is_down(self, client, ethos_url):
        ethos_url.go_down()
        response = client.get("/healthz")
        assert response.json()["status"] == "ok"


class TestGatedFeatures:
    """What is still gated, and what no longer is.

    B1, B2, B5, B6, B7 and B11 have landed, so the lock, jobs, readiness, the
    summary and the UEs are live and must NOT name a backend change any more. B4,
    B9 and B10 have not, so those still do.
    """

    def test_the_overview_reads_the_lock_rather_than_naming_b1(self, client):
        body = client.get("/").text
        assert "needs ETHOS B1" not in body
        assert "Testbed lock" in body

    def test_the_jobs_page_lists_jobs_rather_than_naming_b2(self, client):
        body = client.get("/jobs").text
        assert "needs ETHOS B2" not in body
        assert "Jobs" in body

    def test_the_testbed_page_lists_ues_rather_than_naming_b11(self, client):
        body = client.get("/testbed").text
        assert "needs ETHOS B11" not in body
        assert "UEs" in body

    def test_the_graphs_page_names_b9(self, client):
        assert "needs ETHOS B9" in client.get("/graphs").text


class TestPlanPage:
    def _post(self, client, **overrides):
        data = {
            "gnb_stack": "OCUDU", "split_kind": "monolithic",
            "cu_vendor": "OCUDU", "du_vendor": "OCUDU",
            "l1_backend": "software-PHY", "ru": "Pegatron", "ue": "Samsung",
            "core": "Open5GS", "server": "joule", "direction": "DL",
            "rates": "100-1000:100", "duration": "30s", "repeats": "1",
            "iperf_server": "app_binary", "label": "test",
        }
        data.update(overrides)
        return client.post("/plan/resolve", data=data)

    def test_the_config_id_comes_from_ethos(self, client, ethos_url):
        response = self._post(client)
        assert response.status_code == 200
        assert "ocudu-mono_swphy_pega_samsung_o5gs_joule" in response.text
        assert ("POST", "/testdef/generate") in ethos_url.calls

    def test_the_console_never_asks_for_a_config_id_it_built_itself(self, client, ethos_url):
        self._post(client)
        posts = [path for method, path in ethos_url.calls if method == "POST"]
        assert "/testdef/generate" in posts

    def test_an_undeployable_selection_is_reported_with_its_reason(self, client):
        response = self._post(client, ue="TM500", ru="TM500")
        assert "not deployable" in response.text or "placeholder" in response.text

    def test_a_coupling_conflict_shows_ethos_own_message(self, client):
        response = self._post(client, ue="TM500", ru="Pegatron")
        assert "requires ru=TM500" in response.text

    def test_a_cross_vendor_split_resolves_to_the_catalogue_id(self, client):
        response = self._post(client, split_kind="CU+DU", cu_vendor="OAI", du_vendor="OCUDU")
        assert "experimental" in response.text

    def test_an_invalid_traffic_plan_is_reported_inline(self, client):
        response = self._post(client, rates="nope")
        assert "is not a rate in Mbit/s" in response.text

    def test_a_plan_saves_and_reloads(self, client):
        response = client.post(
            "/plan/save",
            data={
                "name": "smoke-plan", "gnb_stack": "OCUDU", "split_kind": "monolithic",
                "cu_vendor": "OCUDU", "du_vendor": "OCUDU",
                "l1_backend": "software-PHY", "ru": "Pegatron", "ue": "Samsung",
                "core": "Open5GS", "server": "joule", "direction": "DL",
                "rates": "100", "duration": "30s", "repeats": "1",
                "iperf_server": "app_binary", "label": "smoke",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("X-Console-Toast")
        assert "smoke-plan" in client.get("/plan").text
        assert "rates" in client.get("/plan?load=smoke-plan").text

    def test_downloading_the_plan_gives_json_and_yaml(self, client):
        base = {
            "gnb_stack": "OCUDU", "split_kind": "monolithic", "cu_vendor": "OCUDU",
            "du_vendor": "OCUDU", "l1_backend": "software-PHY", "ru": "Pegatron",
            "ue": "Samsung", "core": "Open5GS", "server": "joule", "direction": "DL",
            "rates": "100", "duration": "30s", "repeats": "1",
            "iperf_server": "app_binary", "label": "dl",
        }
        as_json = client.post("/plan/download", data={**base, "fmt": "json"})
        as_yaml = client.post("/plan/download", data={**base, "fmt": "yaml"})
        assert as_json.headers["content-type"].startswith("application/json")
        assert "config_id" in as_json.text
        assert "direction: DL" in as_yaml.text


class TestResults:
    def test_the_table_lists_runs_and_hides_the_unusable_by_default(self, client):
        shown = client.get("/results").text
        all_runs = client.get("/results?usable_only=no").text
        assert "unusable runs hidden" in shown
        assert len(all_runs) > len(shown)

    def test_the_csv_carries_the_filtered_rows(self, client):
        response = client.get("/results/export.csv?usable_only=no")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"].endswith('"ethos-runs.csv"')
        rows = int(response.headers["x-console-rows"])
        assert rows > 0
        assert len(response.text.strip().splitlines()) == rows + 1

    def test_a_run_detail_page_shows_every_tab(self, client):
        listing = client.get("/results?usable_only=no").text
        import re

        run_id = re.search(r'/results/runs/([\w\-.]+)"', listing).group(1)
        body = client.get(f"/results/runs/{run_id}").text
        for tab in ("Summary", "Channel conditions", "Latency", "Cell config", "Raw"):
            assert tab in body

    def test_a_missing_run_reports_ethos_message(self, client):
        response = client.get("/results/runs/20990101T0000Z-nope_x-DL100M-001")
        assert response.status_code == 200
        assert "no run" in response.text

    def test_the_sweep_view_groups_a_campaign(self, client):
        response = client.get("/results/campaigns/chanmetrics-addendum")
        assert response.status_code == 200
        assert "offered" in response.text

    def test_comparing_selected_runs_uses_the_same_view(self, client):
        listing = client.get("/results?usable_only=no").text
        import re

        ids = re.findall(r'/results/runs/([\w\-.]+)"', listing)[:2]
        query = "&".join(f"run_id={i}" for i in ids)
        response = client.get(f"/results/compare?{query}")
        assert response.status_code == 200
        assert "Comparison" in response.text


class TestGraphs:
    def test_the_gallery_lists_the_archived_figures(self, client):
        body = client.get("/graphs").text
        assert "full-sweep" in body

    def test_a_figure_page_shows_its_manifest(self, client):
        body = client.get("/graphs/view/2026-09-25/185503_line_full-sweep").text
        assert "achieved_over_tx_mbps" in body
        assert "n=5 per point" in body

    def test_a_figure_whose_inputs_mix_durations_warns(self, client):
        body = client.get("/graphs/view/2026-09-25/190000_bar_mixed").text
        assert "mix traffic durations" in body or "mixed durations" in body

    def test_the_png_and_pdf_download(self, client):
        base = "/graphs/file/2026-09-25/185503_line_full-sweep"
        png = client.get(f"{base}/png")
        pdf = client.get(f"{base}/pdf")
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"

    def test_a_path_outside_the_graph_directory_is_refused(self, client):
        assert client.get("/graphs/view/../../etc/passwd").status_code == 404
        assert client.get("/graphs/file/2026-09-25/nope/png").status_code == 404


class TestDocs:
    def test_the_documents_are_listed_and_rendered(self, client):
        index = client.get("/docs").text
        assert "running-guide" in index or "Requirements" in index

    def test_an_unknown_document_is_a_404(self, client):
        assert client.get("/docs/no-such-doc").status_code == 404
