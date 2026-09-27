"""A fake ETHOS that replays recorded responses.

Every console test runs against this, never against the testbed (NF-07). It
answers from the JSON in ``tests/recorded/``, which ``tests/record.py`` captured
from the real API — so the fixtures are the real shapes, including the 501 bodies
of the endpoints that are still stubs.

It can also be made to fail on purpose: a 409 naming a holder, a 412, a 422, or
ETHOS being down altogether. Those paths are the ones a page must render well,
and they are the hardest to produce on a real testbed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

# The endpoints that do not exist yet. A console that gates on capability must
# see the real difference between "routed but 501" and "not routed at all".
NOT_ROUTED = (
    "/jobs",
    "/lock",
    "/readiness",
    "/catalogue",
    "/status/summary",
    "/plots",
    "/runs.csv",
    "/ue",
    "/o1/freshness",
    "/o2/nf",
)

STUB_501 = (
    "/status/devices",
    "/status/resources",
    "/compare",
    "/results/ladder",
    "/testdef/validate",
    "/testdef/run",
    "/campaigns",
)


class FakeEthos:
    def __init__(self, recorded: Path) -> None:
        self.recorded = recorded
        self.down = False
        self.refuse_with: tuple[int, dict[str, Any]] | None = None
        self.calls: list[tuple[str, str]] = []

    # --- what a test sets up -------------------------------------------------

    def go_down(self) -> None:
        self.down = True

    def come_back(self) -> None:
        self.down = False

    def refuse(self, status: int, body: dict[str, Any]) -> None:
        self.refuse_with = (status, body)

    # --- the transport -------------------------------------------------------

    def _load(self, name: str) -> Any:
        path = self.recorded / f"{name}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))

        if self.down:
            raise httpx.ConnectError("connection refused", request=request)

        if self.refuse_with is not None:
            status, body = self.refuse_with
            return httpx.Response(status, json=body, request=request)

        for prefix in NOT_ROUTED:
            if path == prefix or path.startswith(prefix + "/"):
                return httpx.Response(404, json={"detail": "Not Found"}, request=request)

        for prefix in STUB_501:
            if path == prefix or path.startswith(prefix + "/"):
                return httpx.Response(
                    501,
                    json={
                        "detail": f"{path} is not implemented yet.",
                        "endpoint": path,
                        "implemented_in": "a later build step",
                    },
                    request=request,
                )

        if path == "/healthz":
            return httpx.Response(
                200,
                json={"status": "ok", "service": "ethos-rApp", "version": "0.1.0"},
                request=request,
            )
        if path == "/compatibility":
            return httpx.Response(200, json=self._load("compatibility"), request=request)
        if path == "/validate":
            body = json.loads(request.content or b"{}")
            return httpx.Response(200, json=self._validate(body), request=request)
        if path == "/testdef/generate":
            return httpx.Response(200, json=self._load("testdef_generate"), request=request)
        if path == "/deploy/status":
            return httpx.Response(200, json=self._load("deploy_status"), request=request)
        if path == "/status/health":
            return httpx.Response(200, json=self._load("status_health"), request=request)
        if path == "/runs":
            return httpx.Response(200, json=self._load("runs"), request=request)
        if path.startswith("/runs/"):
            run_id = path.split("/")[2]
            listing = self._load("runs") or {"runs": []}
            for run in listing["runs"]:
                if run.get("run_id") == run_id:
                    return httpx.Response(200, json=run, request=request)
            return httpx.Response(
                404, json={"detail": f"no run {run_id}"}, request=request
            )

        return httpx.Response(404, json={"detail": "Not Found"}, request=request)

    def _validate(self, selection: dict[str, Any]) -> dict[str, Any]:
        """The couplings the real ETHOS enforces, for the combinations a test uses."""
        reasons: list[dict[str, Any]] = []
        if selection.get("ue") == "TM500" and selection.get("ru") != "TM500":
            reasons.append(
                {
                    "code": "COUPLING_CONFLICT",
                    "severity": "error",
                    "message": "ue=TM500 requires ru=TM500, but ru="
                    f"{selection.get('ru')} was selected.",
                    "rule": "RULE-1",
                    "fields": ["ru", "ue"],
                }
            )
        experimental = selection.get("gnb_split", "") in (
            "OCUDU-CU+OAI-DU",
            "OAI-CU+OCUDU-DU",
        )
        return {
            "valid": not reasons,
            "experimental": experimental,
            "resolved_selection": selection,
            "reasons": reasons,
        }

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)
