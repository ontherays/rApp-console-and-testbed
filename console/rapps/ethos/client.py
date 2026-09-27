"""The only code in the console that talks to ETHOS.

Two rules this file exists to keep:

**Nothing here reaches the testbed directly.** No InfluxDB query, no SSH, no
kubectl, no adb (SE-06). Every fact the console shows comes back through an
ETHOS endpoint, because ETHOS is the component that holds the credentials and
the component that is allowed to act.

**A read stays a read.** ``GET /runs/{id}/ee-kpi`` persists to the manifest
unless it is asked not to, so this client always sends ``persist=false``. The
console must never leave a fingerprint on a run record.

Failures are mapped once, here, into the shapes the pages render (design §7.5):
a refusal that names its holder, a validation error to show inline, and an
unreachable ETHOS that disables every action (ST-04).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from console.rapps.ethos.models import (
    Catalogue,
    DeployStatus,
    EthosHealth,
    Run,
    RunList,
    TestDefGenerated,
    ValidationResult,
)


class EthosError(Exception):
    """Base class. ``message`` is ETHOS's own text where there is one."""

    kind = "error"
    tone = "error"

    def __init__(self, message: str, *, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


class EthosUnreachable(EthosError):
    """Timed out, or the connection was refused. Actions are disabled (ST-04)."""

    kind = "unreachable"


class EthosNotImplemented(EthosError):
    """A 501 stub, or an endpoint that is not routed at all. The console shows
    which backend change adds it rather than an empty panel."""

    kind = "not_implemented"
    tone = "info"


class EthosRefused(EthosError):
    """409. Something else holds the testbed; the holder is named."""

    kind = "refused"
    tone = "warning"

    def __init__(self, message: str, *, holder: str | None = None, **kw: Any):
        super().__init__(message, **kw)
        self.holder = holder


class EthosStateChanged(EthosError):
    """412. The testbed changed after the preview was computed."""

    kind = "state_changed"
    tone = "warning"


class EthosInvalid(EthosError):
    """422. Shown inline against the field, not only as a toast."""

    kind = "invalid"
    tone = "warning"


class EthosServerError(EthosError):
    """5xx. ETHOS's message is shown as-is; guessing at the cause helps nobody."""

    kind = "server_error"


def _message_from(body: Any, fallback: str) -> str:
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, list) and value:
                return "; ".join(str(v.get("msg", v)) for v in value)
    return fallback


@dataclass
class _Cached:
    value: Any
    at: float


class EthosClient:
    """One client per app. Async, because a page fans out to several endpoints."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 10.0,
        slow_timeout_s: float = 60.0,
        runs_cache_s: float = 20.0,
        status_cache_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.slow_timeout_s = slow_timeout_s
        self.runs_cache_s = runs_cache_s
        self.status_cache_s = status_cache_s
        self._clock = clock
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_s,
            transport=transport,
            headers={"accept": "application/json"},
        )
        self._cache: dict[str, _Cached] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- the one place a request is made -------------------------------------

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        slow: bool = False,
    ) -> Any:
        timeout = self.slow_timeout_s if slow else self.timeout_s
        try:
            response = await self._client.request(
                method, path, json=json, params=params, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise EthosUnreachable(
                f"ETHOS did not answer {method} {path} within {timeout:g}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise EthosUnreachable(f"ETHOS is unreachable: {exc}") from exc

        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text

        status = response.status_code
        if status < 300:
            return body
        if status in (404, 405) or status == 501:
            raise EthosNotImplemented(
                _message_from(body, f"{method} {path} is not available in ETHOS"),
                status=status,
                body=body,
            )
        if status == 409:
            holder = body.get("holder") if isinstance(body, dict) else None
            raise EthosRefused(
                _message_from(body, "the testbed is busy"),
                holder=str(holder) if holder else None,
                status=status,
                body=body,
            )
        if status == 412:
            raise EthosStateChanged(
                _message_from(body, "the testbed changed since the preview"),
                status=status,
                body=body,
            )
        if status in (400, 422, 428):
            raise EthosInvalid(
                _message_from(body, "ETHOS rejected the request"),
                status=status,
                body=body,
            )
        raise EthosServerError(
            _message_from(body, f"ETHOS returned HTTP {status}"),
            status=status,
            body=body,
        )

    async def _cached(self, key: str, ttl: float, coro_factory: Any) -> Any:
        hit = self._cache.get(key)
        now = float(self._clock())
        if hit is not None and now - hit.at < ttl:
            return hit.value
        value = await coro_factory()
        self._cache[key] = _Cached(value=value, at=now)
        return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    # --- reads that work today ----------------------------------------------

    async def healthz(self) -> EthosHealth:
        return EthosHealth.model_validate(await self.call("GET", "/healthz"))

    async def compatibility(self) -> Catalogue:
        async def fetch() -> Catalogue:
            return Catalogue.model_validate(await self.call("GET", "/compatibility"))

        return await self._cached("compatibility", 300.0, fetch)

    async def validate(self, selection: dict[str, Any]) -> ValidationResult:
        return ValidationResult.model_validate(
            await self.call("POST", "/validate", json=selection)
        )

    async def testdef_generate(self, body: dict[str, Any]) -> TestDefGenerated:
        """The only sanctioned source of a config_id. The console never builds
        one by string concatenation — a hand-built id once dropped a field and
        put malformed points in the results bucket."""
        return TestDefGenerated.model_validate(
            await self.call("POST", "/testdef/generate", json=body)
        )

    async def runs(self) -> RunList:
        """Every run. ``GET /runs`` takes no limit and re-reads every manifest on
        disk per request, so this is cached and the console filters, sorts and
        paginates in Python. ``GET /runs.csv`` and real pagination arrive with
        B10."""

        async def fetch() -> RunList:
            return RunList.model_validate(await self.call("GET", "/runs", slow=True))

        return await self._cached("runs", self.runs_cache_s, fetch)

    async def run(self, run_id: str) -> Run:
        return Run.model_validate(await self.call("GET", f"/runs/{run_id}"))

    async def deploy_status(self) -> DeployStatus:
        """An SSH round trip to the deploy host, and a 503 when that host is
        unreachable, so it is cached and every caller tolerates failure."""

        async def fetch() -> DeployStatus:
            body = await self.call("GET", "/deploy/status", slow=True)
            inner = body.get("status", body) if isinstance(body, dict) else {}
            return DeployStatus.model_validate(inner)

        return await self._cached("deploy_status", self.status_cache_s, fetch)

    async def status_health(self) -> dict[str, Any]:
        async def fetch() -> dict[str, Any]:
            return await self.call("GET", "/status/health", slow=True)

        return await self._cached("status_health", self.status_cache_s, fetch)

    async def run_o1_pm(self, run_id: str) -> dict[str, Any]:
        return await self.call("GET", f"/runs/{run_id}/o1-pm", slow=True)

    async def run_throughput(self, run_id: str) -> dict[str, Any]:
        return await self.call("GET", f"/runs/{run_id}/throughput", slow=True)

    async def cm_writable_params(self) -> dict[str, Any]:
        return await self.call("GET", "/cm/params/writable")

    async def run_ee_kpi(self, run_id: str) -> dict[str, Any]:
        """Always ``persist=false``: the endpoint writes the manifest by
        default, and a console read must not modify a run record."""
        return await self.call(
            "GET", f"/runs/{run_id}/ee-kpi", params={"persist": "false"}, slow=True
        )
