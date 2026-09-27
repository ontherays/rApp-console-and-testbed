"""The ETHOS client: error mapping, caching, and the read-only rule."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from tests.conftest import run_async

from console.rapps.ethos.client import (
    EthosClient,
    EthosInvalid,
    EthosNotImplemented,
    EthosRefused,
    EthosServerError,
    EthosStateChanged,
    EthosUnreachable,
)

RECORDED = Path(__file__).resolve().parent.parent / "recorded"


def run(coro):
    return run_async(coro)


def client_with(handler, **kwargs) -> EthosClient:
    return EthosClient(
        "http://ethos.test", transport=httpx.MockTransport(handler), **kwargs
    )


def test_a_501_stub_and_an_unrouted_path_both_mean_not_implemented():
    def handler(request):
        if request.url.path == "/status/devices":
            return httpx.Response(501, json={"detail": "not implemented yet"})
        return httpx.Response(404, json={"detail": "Not Found"})

    client = client_with(handler)
    for path in ("/status/devices", "/jobs"):
        with pytest.raises(EthosNotImplemented):
            run(client.call("GET", path))


def test_a_409_carries_the_holder():
    def handler(request):
        return httpx.Response(
            409,
            json={
                "error": "testbed_locked",
                "message": "held by job j-0927-1412",
                "holder": "job:j-0927-1412",
            },
        )

    with pytest.raises(EthosRefused) as raised:
        run(client_with(handler).call("POST", "/deploy"))
    assert raised.value.holder == "job:j-0927-1412"
    assert "j-0927-1412" in raised.value.message
    assert raised.value.tone == "warning"


@pytest.mark.parametrize(
    "status,expected",
    [
        (412, EthosStateChanged),
        (422, EthosInvalid),
        (428, EthosInvalid),
        (400, EthosInvalid),
        (500, EthosServerError),
        (503, EthosServerError),
    ],
)
def test_each_status_maps_to_its_own_error(status, expected):
    def handler(request):
        return httpx.Response(status, json={"message": "no"})

    with pytest.raises(expected):
        run(client_with(handler).call("GET", "/anything"))


def test_a_timeout_and_a_refused_connection_both_read_as_unreachable():
    def times_out(request):
        raise httpx.ReadTimeout("too slow", request=request)

    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    for handler in (times_out, refused):
        with pytest.raises(EthosUnreachable):
            run(client_with(handler).call("GET", "/healthz"))


def test_ethos_message_is_kept_rather_than_replaced():
    def handler(request):
        return httpx.Response(422, json={"detail": "rates must be above 0"})

    with pytest.raises(EthosInvalid) as raised:
        run(client_with(handler).call("POST", "/validate"))
    assert raised.value.message == "rates must be above 0"


def test_a_fastapi_validation_body_is_summarised():
    def handler(request):
        return httpx.Response(
            422,
            json={"detail": [{"loc": ["body", "selection"], "msg": "Field required"}]},
        )

    with pytest.raises(EthosInvalid) as raised:
        run(client_with(handler).call("POST", "/testdef/generate"))
    assert "Field required" in raised.value.message


def test_ee_kpi_is_never_read_without_persist_false():
    """The endpoint writes the manifest by default. A console read must not
    leave a fingerprint on a run record."""
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    run(client_with(handler).run_ee_kpi("20260927T0745Z-x-DL100M-001"))
    assert "persist=false" in seen[0]


def test_the_run_list_is_cached_for_its_window():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"count": 0, "filters": {}, "runs": []})

    now = [0.0]
    client = client_with(handler, runs_cache_s=20.0, clock=lambda: now[0])
    run(client.runs())
    run(client.runs())
    assert calls["n"] == 1

    now[0] = 21.0
    run(client.runs())
    assert calls["n"] == 2


def test_invalidate_drops_the_cache():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"count": 0, "filters": {}, "runs": []})

    client = client_with(handler, clock=lambda: 0.0)
    run(client.runs())
    client.invalidate("runs")
    run(client.runs())
    assert calls["n"] == 2


def test_deploy_status_unwraps_the_status_envelope():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": {
                    "namespace": "ravi-ns",
                    "releases": ["ocudu-gnb"],
                    "running_pods": ["ocudu-gnb-0"],
                    "node_free": False,
                }
            },
        )

    status = run(client_with(handler).deploy_status())
    assert status.namespace == "ravi-ns"
    assert status.anything_deployed is True


def test_deploy_status_names_the_stack_so_ethos_probes_the_node():
    """ETHOS gates the node probe on the request naming a stack. Without a
    config_id it answers "the node was not observed" having never looked, which
    reads like a failed probe and is not one."""
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        named = "config_id=" in str(request.url)
        return httpx.Response(
            200,
            json={
                "status": {
                    "namespace": "ravi-ns",
                    "releases": [],
                    "pods": [],
                    "running_pods": [],
                    "node_free": True if named else None,
                    "node_reason": (
                        "state verified: no gNB and no traffic on the node"
                        if named
                        else "the node was not observed"
                    ),
                    "node_check": {"verified": True} if named else None,
                }
            },
        )

    client = client_with(handler, clock=lambda: 0.0)
    bare = run(client.deploy_status())
    named = run(client.deploy_status(config_id="ocudu-mono_swphy_pega_samsung_o5gs_joule"))

    assert bare.node_free is None and bare.node_observed is False
    assert named.node_free is True and named.node_observed is True
    assert "config_id=ocudu-mono" in seen[1]


def test_the_two_calls_are_cached_separately():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"status": {"namespace": "ravi-ns"}})

    client = client_with(handler, clock=lambda: 0.0)
    run(client.deploy_status())
    run(client.deploy_status())
    run(client.deploy_status(config_id="a"))
    run(client.deploy_status(config_id="a"))
    run(client.deploy_status(config_id="b"))
    assert calls["n"] == 3, "one request per distinct config_id, then cached"
