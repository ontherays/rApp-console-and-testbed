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
    FigureResult,
    FigureSummary,
    Holder,
    Job,
    JobList,
    PlotOptions,
    PlotSeriesList,
    Preview,
    QuarantineList,
    Readiness,
    Run,
    RunList,
    StatusSummary,
    TestDefGenerated,
    UeIperf,
    UeList,
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
        act_timeout_s: float = 900.0,
        runs_cache_s: float = 20.0,
        status_cache_s: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.slow_timeout_s = slow_timeout_s
        self.act_timeout_s = act_timeout_s
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
        timeout_s: float | None = None,
    ) -> Any:
        timeout = timeout_s if timeout_s else (self.slow_timeout_s if slow else self.timeout_s)
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
        one by string concatenation, a hand-built id once dropped a field and
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

    async def deploy_status(self, config_id: str | None = None) -> DeployStatus:
        """What is deployed, and whether the node is free.

        **Pass ``config_id`` whenever there is one.** ETHOS only probes the node
        when the request names a stack: ``deployment/orchestrator.py`` gates the
        probe on ``if self.prober is not None and stack``, so a bare call leaves
        ``node_free`` null and ``node_reason`` at its initialiser, "the node was
        not observed". That reads like a failure and is not one, nothing was
        asked. With a config_id the same endpoint answers
        ``node_free: true, "state verified: no gNB and no traffic on the node"``
        and a full ``node_check``.

        An SSH round trip to the deploy host either way, and a 503 when that host
        is unreachable, so it is cached per config_id and callers tolerate
        failure.
        """

        async def fetch() -> DeployStatus:
            body = await self.call(
                "GET",
                "/deploy/status",
                params={"config_id": config_id} if config_id else None,
                slow=True,
            )
            inner = body.get("status", body) if isinstance(body, dict) else {}
            return DeployStatus.model_validate(inner)

        key = f"deploy_status:{config_id or ''}"
        return await self._cached(key, self.status_cache_s, fetch)

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

    # --- the testbed lock (B1) -----------------------------------------------

    async def lock(self) -> Holder:
        """Who holds the testbed. Never cached.

        Everything else on a page can be a few seconds stale; this cannot. It is
        what decides whether an action is offered at all, and offering one that
        ETHOS will refuse is the failure this endpoint exists to prevent.
        """
        return Holder.model_validate(await self.call("GET", "/lock"))

    # --- readiness (B5) ------------------------------------------------------

    async def readiness(self, plan: dict[str, Any]) -> Readiness:
        """ETHOS's seven checks for this plan, in ETHOS's order.

        The console renders what comes back and judges nothing itself. Two
        opinions about whether the testbed is ready is worse than one, and the
        whole point of the endpoint is that the CLI and the console agree.

        Slow on purpose: it reaches the deploy host, the handset and the node.
        """
        return Readiness.model_validate(
            await self.call("POST", "/readiness", json=plan, slow=True)
        )

    # --- the status summary (B6) ---------------------------------------------

    async def status_summary(self, config_id: str | None = None) -> StatusSummary:
        """The whole status strip in one call.

        Cached briefly because the strip polls every 5 s from every open tab, and
        ETHOS's own slow parts (the handset, the port-5201 holder) are cached
        behind it too. Each part carries its own `checked_at`, so a cached answer
        still reports the age of the read it came from rather than of this
        request.
        """

        async def fetch() -> StatusSummary:
            body = await self.call(
                "GET",
                "/status/summary",
                params={"config_id": config_id} if config_id else None,
                slow=True,
            )
            return StatusSummary.model_validate(body)

        return await self._cached(f"summary:{config_id or ''}", self.status_cache_s, fetch)

    # --- jobs (B2) -----------------------------------------------------------

    async def jobs(self) -> JobList:
        return JobList.model_validate(await self.call("GET", "/jobs"))

    async def job(self, job_id: str) -> Job:
        return Job.model_validate(await self.call("GET", f"/jobs/{job_id}"))

    async def job_preview(self, plan: dict[str, Any]) -> Preview:
        """What starting this plan would do, and the token that allows it.

        Sends nothing to the testbed. The token is bound to the plan AND to the
        testbed state it was computed against, which is what makes the 412 on
        confirm meaningful.
        """
        return Preview.model_validate(
            await self.call("POST", "/jobs/preview", json=plan, slow=True)
        )

    async def job_start(self, plan: dict[str, Any], preview_token: str) -> Job:
        """Start the job the operator has just seen the preview of.

        409 and 412 are raised as `EthosRefused` and `EthosStateChanged` by
        `call`, which is what the dialog turns into a toast and a readiness
        re-run (design section 7.5).
        """
        body = {**plan, "confirm": True, "preview_token": preview_token}
        return Job.model_validate(await self.call("POST", "/jobs", json=body, slow=True))

    async def job_stop(self, job_id: str) -> Job:
        """Ask the job to stop at the next point boundary.

        Cooperative in ETHOS: the campaign finishes the point it is measuring,
        then detaches and tears down. Nothing is killed, and the points already
        measured are kept.
        """
        return Job.model_validate(
            await self.call("POST", f"/jobs/{job_id}/stop", slow=True)
        )

    def job_events_url(self, job_id: str) -> str:
        return f"{self.base_url}/jobs/{job_id}/events"

    def stream(
        self, method: str, path: str, *, headers: dict[str, str] | None = None
    ) -> Any:
        """An open response, for the SSE relay in `console/sse.py`.

        Deliberately not wrapped in the error mapping: a stream that has started
        cannot be turned into a toast, so the relay reports a broken stream to the
        browser as an event and lets htmx reconnect.
        """
        return self._client.stream(
            method, path, headers=headers or {}, timeout=None
        )

    # --- UE control (B11) ----------------------------------------------------

    async def ues(self) -> UeList:
        """Every UE ETHOS knows about, including the ones it does not drive.

        Slow: it reads each driven UE's state over adb through the lab's control
        host.
        """
        return UeList.model_validate(await self.call("GET", "/ue", slow=True))

    async def ue_iperf(self, ue: str) -> UeIperf:
        return UeIperf.model_validate(await self.call("GET", f"/ue/{ue}/iperf", slow=True))

    async def ue_signal(self, ue: str) -> dict[str, Any]:
        return await self.call("GET", f"/ue/{ue}/signal", slow=True)

    async def ue_preview(self, ue: str, action: str) -> Preview:
        """The preview for `attach`, `detach` or `iperf/stop` on one UE."""
        return Preview.model_validate(
            await self.call("POST", f"/ue/{ue}/{action}/preview", slow=True)
        )

    async def ue_act(self, ue: str, action: str, preview_token: str) -> dict[str, Any]:
        """Do it, with the token from the preview the operator just saw.

        An attach can take minutes: the driver toggles the radio, waits for the
        handset to settle and reads the address back, and ETHOS refuses rather
        than claim an attach it could not confirm. So this is a slow call.
        """
        return await self.call(
            "POST",
            f"/ue/{ue}/{action}",
            json={"confirm": True, "preview_token": preview_token},
            timeout_s=self.act_timeout_s,
        )

    # --- figures on request (B9) ---------------------------------------------

    async def plot_options(self) -> PlotOptions:
        """Every metric, kind, grouping, width and scale a figure can take.

        Cached for a long time and served straight to the form, so the console
        holds no list of its own. A list kept here would drift: it would offer a
        metric ETHOS had dropped, or hide one it had gained, and the operator
        would have no way to tell which.
        """

        async def fetch() -> PlotOptions:
            return PlotOptions.model_validate(await self.call("GET", "/plots/options"))

        return await self._cached("plot_options", 300.0, fetch)

    async def plot_series(self) -> PlotSeriesList:
        """The palette the figures are drawn with.

        Fetched rather than copied. A chip on a results page and a line in the
        figure beside it must be the same colour for the same stack, and two
        tables saying so is how they stop being.
        """

        async def fetch() -> PlotSeriesList:
            return PlotSeriesList.model_validate(await self.call("GET", "/plots/series"))

        return await self._cached("plot_series", 300.0, fetch)

    async def figures(self) -> list[FigureSummary]:
        """Every figure in ETHOS's graph directory, newest first.

        CLI-made and console-made alike: they are the same kind of thing, in the
        same place, and which one made it is a chip rather than a separate list.
        """
        body = await self.call("GET", "/plots", slow=True)
        return [FigureSummary.model_validate(f) for f in (body.get("figures") or [])]

    async def figure(self, figure_id: str) -> dict[str, Any]:
        """One figure's manifest: its inputs, filters, n per point and warnings."""
        return await self.call("GET", f"/plots/{figure_id}")

    async def quarantine(self) -> QuarantineList:
        """Which jobs are held out of normal graphs, and why.

        Cached briefly like the other read-only lists: the graph form and the
        jobs page both want it on every render, and it changes when somebody
        decides something, not on a timer.
        """
        async def fetch() -> QuarantineList:
            return QuarantineList.model_validate(await self.call("GET", "/quarantine"))

        return await self._cached("quarantine", 10.0, fetch)

    async def quarantine_preview(self, job_id: str, reason: str) -> dict[str, Any]:
        """What quarantining would hold out, and the token that allows it.

        Writes nothing. ETHOS has no endpoint here that deletes anything.
        """
        return await self.call(
            "POST", "/quarantine/preview", json={"job_id": job_id, "reason": reason}
        )

    async def quarantine_add(self, job_id: str, reason: str, preview_token: str,
                             excluded_by: str = "") -> dict[str, Any]:
        answer = await self.call("POST", "/quarantine", json={
            "job_id": job_id, "reason": reason, "excluded_by": excluded_by,
            "confirm": True, "preview_token": preview_token,
        })
        self.invalidate("quarantine")
        return answer

    async def quarantine_restore_preview(self, job_id: str) -> dict[str, Any]:
        return await self.call("POST", "/quarantine/restore", json={"job_id": job_id})

    async def quarantine_restore(self, job_id: str, preview_token: str) -> dict[str, Any]:
        answer = await self.call("POST", "/quarantine/restore", json={
            "job_id": job_id, "confirm": True, "preview_token": preview_token,
        })
        self.invalidate("quarantine")
        return answer

    async def make_figure(self, request: dict[str, Any]) -> FigureResult:
        """Draw one. Slow on purpose: matplotlib is serialised in ETHOS, so this
        can wait behind another figure as well as taking seconds itself."""
        return FigureResult.model_validate(
            await self.call("POST", "/plots", json=request, timeout_s=self.act_timeout_s)
        )

    async def regenerate_figure(self, figure_id: str) -> FigureResult:
        """Redraw a figure from its own snapshot, into a new folder.

        The published original is left exactly as it was, which is the point:
        regenerating is how a figure in a paper is checked, not how it is
        replaced.
        """
        return FigureResult.model_validate(
            await self.call("POST", f"/plots/{figure_id}/regenerate",
                            timeout_s=self.act_timeout_s)
        )

    def figure_file_stream(self, figure_id: str, name: str) -> Any:
        """An open response for one of a figure's four files.

        Streamed rather than read into memory and re-sent: the console is a
        relay here, and a PDF has no business being buffered in the web process.
        """
        return self._client.stream(
            "GET", f"/plots/{figure_id}/{name}", timeout=self.slow_timeout_s
        )
