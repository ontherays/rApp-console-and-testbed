"""The capability probe: what is built, and what each gap is waiting for."""

from __future__ import annotations

import httpx

from console.capabilities import BY_KEY, FEATURES, NOT_BUILT, OK, UNREACHABLE, CapabilityProbe
from console.rapps.ethos.client import EthosClient
from tests.conftest import run_async


def probe_against(handler) -> CapabilityProbe:
    client = EthosClient("http://ethos.test", transport=httpx.MockTransport(handler))
    return CapabilityProbe(client)


def test_an_absent_endpoint_names_its_backend_change():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "service": "ethos-rApp"})
        return httpx.Response(404, json={"detail": "Not Found"})

    result = run_async(probe_against(handler).probe_once())
    assert result.ethos_up is True
    assert result.state("jobs") == NOT_BUILT
    assert result.ready("jobs") is False
    assert "B2" in result.why("jobs")
    assert "B9" in result.why("plots")


def test_a_501_stub_is_also_not_built():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "service": "ethos-rApp"})
        return httpx.Response(501, json={"detail": "not implemented yet"})

    result = run_async(probe_against(handler).probe_once())
    assert result.state("compare") == NOT_BUILT


def test_a_probe_that_needs_query_parameters_still_sees_the_stub():
    """``/compare`` answers 422 for missing parameters, which would hide the 501
    behind it — so the probe supplies them."""
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "service": "ethos-rApp"})
        if request.url.path == "/compare" and "a=" not in str(request.url):
            return httpx.Response(422, json={"detail": "Field required"})
        return httpx.Response(501, json={"detail": "not implemented yet"})

    result = run_async(probe_against(handler).probe_once())
    assert result.state("compare") == NOT_BUILT
    assert any("/compare?a=" in url for url in seen)


def test_everything_is_unreachable_when_ethos_is_down():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    result = run_async(probe_against(handler).probe_once())
    assert result.ethos_up is False
    for feature in FEATURES:
        assert result.state(feature.key) == UNREACHABLE
        assert "unreachable" in result.why(feature.key)


def test_a_built_endpoint_reports_ok():
    def handler(request):
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "service": "ethos-rApp"})
        return httpx.Response(200, json={})

    result = run_async(probe_against(handler).probe_once())
    assert result.state("jobs") == OK
    assert result.ready("jobs") is True
    assert result.pending() == []


def test_every_feature_declares_a_backend_change_and_a_probe():
    for feature in FEATURES:
        assert feature.change, f"{feature.key} has no backend change id"
        assert feature.what, f"{feature.key} does not say what it delivers"
        method, path = feature.probe
        assert method in ("GET", "POST")
        assert path.startswith("/")
    assert set(BY_KEY) == {f.key for f in FEATURES}


def test_an_unknown_key_is_not_ready_and_says_so():
    result = run_async(
        probe_against(lambda r: httpx.Response(200, json={"status": "ok"})).probe_once()
    )
    assert result.ready("no-such-feature") is False
    assert result.why("no-such-feature") == "not available"
