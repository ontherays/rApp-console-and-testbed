"""What ETHOS can answer right now, and which backend change adds the rest.

The lock, jobs, readiness, the status summary, standalone UE control and figures on
request have landed (B1, B2, B5, B6, B9, B11), and the pages that needed them are
live. What is still outstanding is the catalogue (B4) and server-side results
queries (B10).

The table stays even for a change that has landed, and that is deliberate. It is
not only a gate, it is a live check: if an endpoint disappears in a rollback or a
route breaks, the probe notices within a minute and the control that depends on it
disables itself with a reason, rather than failing on click.

So every feature is declared here with the endpoint it needs and the backend
change that delivers it (B1–B15 in ``docs/03-ethos-backend-changes.md``). The
probe runs at startup and every 60 s, and classifies each feature as:

    ok            the endpoint answered
    not_built     501 stub, or not routed at all, the backend change is pending
    unreachable   ETHOS itself is down

Pages ask ``caps.ready("jobs")`` and render the gated state from ``caps.why()``.
When a backend change lands, the probe finds the endpoint and the same page lights
up with no edit here.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from console.rapps.ethos.client import EthosClient, EthosError, EthosNotImplemented


@dataclass(frozen=True)
class Feature:
    key: str
    probe: tuple[str, str]        # method, path
    change: str                   # the backend change id, e.g. "B2"
    what: str                     # what it delivers, in Ravi's words
    cli: str | None = None        # how to do it today, where there is a way
    params: dict[str, str] | None = None
    """Query parameters the probe must supply. Without them a routed endpoint
    answers 422 for a missing field, which would hide a 501 stub behind it."""
    slow: bool = False
    """True when the endpoint reaches the testbed, so the probe must allow it the
    slow timeout. `GET /ue` reads two handsets over adb through the lab's control
    host; timing it out at the ordinary read timeout would report a working
    endpoint as unreachable, and disable the controls that depend on it."""


FEATURES: tuple[Feature, ...] = (
    Feature(
        key="lock",
        probe=("GET", "/lock"),
        change="B1",
        what="the testbed lock and its holder",
    ),
    Feature(
        key="jobs",
        probe=("GET", "/jobs"),
        change="B2",
        what="starting, watching and stopping a campaign",
        cli="python -m campaign <topology> --rates <rates> --duration <duration>",
    ),
    Feature(
        key="catalogue",
        probe=("GET", "/catalogue"),
        change="B4",
        what="which options can actually be deployed, with the reason",
    ),
    Feature(
        key="readiness",
        probe=("POST", "/readiness"),
        change="B5",
        what="the seven readiness checks, judged the same way as for the CLI",
        slow=True,
    ),
    Feature(
        key="status_summary",
        probe=("GET", "/status/summary"),
        change="B6",
        what="the status strip in one call, including data freshness",
        slow=True,
    ),
    Feature(
        key="plots",
        probe=("GET", "/plots"),
        change="B9",
        what="generating a figure on request",
        cli="python -m plotting throughput --help",
    ),
    Feature(
        key="runs_csv",
        probe=("GET", "/runs.csv"),
        change="B10",
        what="server-side run filters, pagination and CSV",
    ),
    Feature(
        key="ue",
        probe=("GET", "/ue"),
        change="B11",
        what="the UE list, standalone attach and detach, the port-5201 holder",
        slow=True,
    ),
    Feature(
        key="o1_freshness",
        probe=("GET", "/o1/freshness"),
        change="B12",
        what="O1 PM freshness per managed element, and the alarm list",
    ),
    Feature(
        key="o2_nf",
        probe=("GET", "/o2/nf"),
        change="B13",
        what="NF checks, deploy timing, energy freshness and the DMS inventory",
    ),
    # Endpoints that are routed but answer 501 today. They are listed so a page
    # can say "routed, not implemented" rather than "unknown".
    Feature(
        key="testdef_validate",
        probe=("POST", "/testdef/validate"),
        change="step 4",
        what="validating an edited test definition in ETHOS",
    ),
    Feature(
        key="compare",
        probe=("GET", "/compare"),
        change="step 6",
        what="ETHOS's own A/B comparison of two runs",
        params={"a": "probe", "b": "probe"},
    ),
)

BY_KEY = {feature.key: feature for feature in FEATURES}

OK = "ok"
NOT_BUILT = "not_built"
UNREACHABLE = "unreachable"


@dataclass
class Capabilities:
    """The last probe result. Safe to read from a request handler."""

    states: dict[str, str] = field(default_factory=dict)
    checked_at: float | None = None
    ethos_up: bool = False
    ethos_detail: str = "not checked yet"

    def state(self, key: str) -> str:
        return self.states.get(key, UNREACHABLE)

    def ready(self, key: str) -> bool:
        return self.state(key) == OK

    def why(self, key: str) -> str:
        """The sentence a disabled control shows. Names the backend change."""
        feature = BY_KEY.get(key)
        if feature is None:
            return "not available"
        state = self.state(key)
        if state == OK:
            return feature.what
        if state == UNREACHABLE:
            return f"ETHOS is unreachable, {self.ethos_detail}"
        return f"needs ETHOS {feature.change}, {feature.what}"

    def cli_for(self, key: str) -> str | None:
        feature = BY_KEY.get(key)
        return feature.cli if feature else None

    def pending(self) -> list[Feature]:
        return [f for f in FEATURES if self.state(f.key) != OK]


class CapabilityProbe:
    """Probes the feature endpoints, on a period, without blocking a page."""

    def __init__(
        self,
        client: EthosClient,
        *,
        period_s: float = 60.0,
        clock=time.monotonic,
    ) -> None:
        self._client = client
        self._period_s = period_s
        self._clock = clock
        self.result = Capabilities()
        self._task: asyncio.Task[None] | None = None

    async def probe_once(self) -> Capabilities:
        states: dict[str, str] = {}
        ethos_up = False
        detail = ""
        try:
            health = await self._client.healthz()
            ethos_up = (health.status or "") == "ok"
            detail = f"{health.service} {health.version}"
        except EthosError as exc:
            detail = exc.message

        for feature in FEATURES:
            if not ethos_up:
                states[feature.key] = UNREACHABLE
                continue
            method, path = feature.probe
            try:
                # A probe must not act. GET is harmless; the one POST probe is
                # sent with an empty body, which a real endpoint rejects with
                # 422, and a 422 still proves it is there.
                await self._client.call(
                    method,
                    path,
                    json={} if method == "POST" else None,
                    params=feature.params,
                    slow=feature.slow,
                )
                states[feature.key] = OK
            except EthosNotImplemented:
                states[feature.key] = NOT_BUILT
            except EthosError as exc:
                # 422 from a real endpoint means built; anything else means the
                # feature cannot be used right now.
                states[feature.key] = OK if exc.status == 422 else UNREACHABLE

        # The figure palette comes from ETHOS, and every page that draws a chip
        # needs it synchronously. Refreshed on the probe's own schedule so the
        # first page is served with it already in hand, and so a change in
        # ETHOS's palette reaches the chips within a minute.
        if states.get("plots") == OK:
            try:
                from console.rapps.ethos.series import PALETTE

                PALETTE.replace(await self._client.plot_series())
            except Exception:  # a palette must never take the probe down
                pass

        self.result = Capabilities(
            states=states,
            checked_at=float(self._clock()),
            ethos_up=ethos_up,
            ethos_detail=detail or "no detail",
        )
        return self.result

    async def _loop(self) -> None:
        while True:
            try:
                await self.probe_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # a probe must never take the console down
                pass
            await asyncio.sleep(self._period_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
