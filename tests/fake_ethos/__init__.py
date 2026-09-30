"""A fake ETHOS that replays recorded responses.

Every console test runs against this, never against the testbed (NF-07). It
answers from the JSON in ``tests/recorded/``, which ``tests/record.py`` captured
from the real API, so the fixtures are the real shapes, including the 501 bodies
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
#
# B1, B2, B5, B6 and B11 have landed, so the lock, jobs, readiness, the summary
# and the UEs are answered below from recordings of the real API rather than
# refused here.
NOT_ROUTED = (
    "/catalogue",
    "/runs.csv",
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
        #: Overrides a test installs for one endpoint, by "METHOD /path".
        self.answers: dict[str, tuple[int, Any]] = {}
        #: The jobs this fake has, by id. A started job is added here.
        self.jobs: dict[str, dict[str, Any]] = {}
        #: The events each job has emitted, in order, numbered from 1.
        self.events: dict[str, list[dict[str, Any]]] = {}
        #: The last Last-Event-ID a stream was asked to resume from, so a test
        #: can prove the relay forwarded the browser's header.
        self.resumed_from: str | None = None
        self.started_plans: list[dict[str, Any]] = []
        #: Figures this fake has drawn, by id, and the bodies it was asked for.
        self.figures: dict[str, dict[str, Any]] = {}
        self.plot_requests: list[dict[str, Any]] = []
        #: A 422 a test wants the next POST /plots to answer with.
        self.refuse_plot: str | None = None
        #: Jobs held out of graphs, by id. Seeded from `recorded/quarantine.json`
        #: on first read, then mutated by the quarantine endpoints so a test can
        #: hold a job out and see the page change.
        self.quarantined: dict[str, dict[str, Any]] | None = None

    # --- what a test sets up -------------------------------------------------

    def go_down(self) -> None:
        self.down = True

    def come_back(self) -> None:
        self.down = False

    def refuse(self, status: int, body: dict[str, Any]) -> None:
        self.refuse_with = (status, body)

    def answer(self, method: str, path: str, status: int, body: Any) -> None:
        """Override ONE endpoint, leaving the rest of the fake as it is.

        `refuse` makes every call fail, which is right for "ETHOS is unwell" and
        wrong for "the lock is held": a page that reads the lock and then the UEs
        must be able to see a 409 from the act and real answers from the reads.
        """
        self.answers[f"{method.upper()} {path}"] = (status, body)

    def hold_lock(self, holder: str, what: str, since: str = "2026-09-28T09:32:58Z") -> None:
        """Make the testbed held, everywhere ETHOS would report it.

        `/lock` and `/status/summary` both carry the lock in ETHOS, and different
        pages read different ones: the Test Plan reads `/lock`, the strip and the
        Overview read the summary. Overriding only one would let a test pass while
        half the console still showed the testbed free.
        """
        held = {"held": True, "holder": holder, "what": what, "since": since}
        self.answer("GET", "/lock", 200, dict(held))
        summary = dict(self._load("status_summary") or {})
        summary["lock"] = {**held, "error": "", "checked_at": since}
        self.answer("GET", "/status/summary", 200, summary)
        self.locked_by = {"holder": holder, "what": what, "since": since}

    #: Set by `hold_lock`; makes the acting endpoints answer 409 like ETHOS does.
    locked_by: dict[str, Any] | None = None

    def add_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        """A job that already exists, for the list and the job page."""
        job = dict(self._load("jobs")["jobs"][0]) if (self._load("jobs") or {}).get("jobs") else {}
        job.update({"job_id": job_id, **fields})
        self.jobs[job_id] = job
        return job

    def refuse_next_plot(self, detail: str) -> None:
        """Make the next figure request fail with ETHOS's own wording.

        Used for the two duration refusals, which differ in one clause and lead
        the console to offer different things.
        """
        self.refuse_plot = detail

    def emit(self, job_id: str, event: str, **data: Any) -> None:
        """One event on a job's stream, numbered as ETHOS numbers them.

        The sequence is dense and starts at 1, which is what makes
        `Last-Event-ID` resumable without a gap or a duplicate.
        """
        history = self.events.setdefault(job_id, [])
        history.append({"seq": len(history) + 1, "event": event, "data": data})

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

        override = self.answers.get(f"{request.method.upper()} {path}")
        if override is not None:
            status, body = override
            return httpx.Response(status, json=body, request=request)

        answered = self._new_endpoints(request, path)
        if answered is not None:
            return answered

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
            body = json.loads(request.content or b"{}")
            return httpx.Response(
                200, json=self._testdef(body.get("selection") or {}), request=request
            )
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

    def _locked(self, request: httpx.Request) -> httpx.Response:
        """A 409 in ETHOS's own shape, naming the holder."""
        held = self.locked_by or {}
        return httpx.Response(
            409,
            json={
                "detail": {
                    "error": "testbed_locked",
                    "message": (
                        f"testbed busy: {held.get('what', 'an action')} "
                        f"(holder {held.get('holder', 'someone')})"
                    ),
                    **held,
                }
            },
            request=request,
        )

    def _new_endpoints(self, request: httpx.Request, path: str) -> httpx.Response | None:
        """B1, B2, B5, B6 and B11, from the recorded shapes.

        An act (starting a job, stopping one, a UE action) is refused with 409
        while `hold_lock` is in force, which is what ETHOS does and what the pages
        have to render.
        """
        method = request.method.upper()

        if path == "/lock" and method == "GET":
            return httpx.Response(200, json=self._load("lock"), request=request)

        if path == "/readiness" and method == "POST":
            body = json.loads(request.content or b"{}")
            if not body.get("config_id"):
                return httpx.Response(
                    422, json={"detail": "config_id is required"}, request=request
                )
            return httpx.Response(200, json=self._load("readiness"), request=request)

        if path == "/status/summary" and method == "GET":
            return httpx.Response(200, json=self._load("status_summary"), request=request)

        if path == "/jobs/preview" and method == "POST":
            return httpx.Response(200, json=self._load("job_preview"), request=request)

        if path == "/jobs" and method == "POST":
            if self.locked_by:
                return self._locked(request)
            body = json.loads(request.content or b"{}")
            if not body.get("confirm") or not body.get("preview_token"):
                return httpx.Response(
                    428,
                    json={"detail": {"error": "confirmation_required", "action": "job"}},
                    request=request,
                )
            self.started_plans.append(body)
            job_id = f"j-fake{len(self.started_plans):03d}"
            job = {
                "job_id": job_id,
                "state": "preflight",
                "source": "api",
                "plan": body,
                "config_id": body.get("config_id"),
                "created": "2026-09-28T12:00:00Z",
                "started": "2026-09-28T12:00:00Z",
                "ended": "",
                "steps": [],
                "points": [],
                "run_ids": [],
                "outcome": "",
                "error": "",
                "stop_requested": False,
            }
            self.jobs[job_id] = job
            self.emit(job_id, "state", state="preflight", detail="starting")
            return httpx.Response(201, json=job, request=request)

        if path == "/jobs" and method == "GET":
            recorded = self._load("jobs") or {"count": 0, "jobs": []}
            jobs = list(self.jobs.values()) + list(recorded.get("jobs") or [])
            return httpx.Response(
                200, json={"count": len(jobs), "jobs": jobs}, request=request
            )

        if path.startswith("/jobs/") and path.endswith("/stop") and method == "POST":
            job_id = path.split("/")[2]
            job = self.jobs.get(job_id)
            if job is None:
                return httpx.Response(404, json={"detail": "no such job"}, request=request)
            job["stop_requested"] = True
            self.emit(job_id, "stop_requested", at="2026-09-28T12:01:00Z")
            return httpx.Response(200, json=job, request=request)

        if path.startswith("/jobs/") and path.endswith("/events") and method == "GET":
            return self._events(request, path.split("/")[2])

        if path.startswith("/jobs/") and method == "GET":
            job_id = path.split("/")[2]
            job = self.jobs.get(job_id)
            if job is not None:
                return httpx.Response(200, json=job, request=request)
            for candidate in (self._load("jobs") or {}).get("jobs") or []:
                if candidate.get("job_id") == job_id:
                    return httpx.Response(200, json=candidate, request=request)
            return httpx.Response(
                404, json={"detail": f"no job {job_id}"}, request=request
            )

        if path == "/plots/options" and method == "GET":
            return httpx.Response(200, json=self._load("plot_options"), request=request)

        if path == "/plots/series" and method == "GET":
            return httpx.Response(200, json=self._load("plot_series"), request=request)

        if path == "/quarantine" and method == "GET":
            return httpx.Response(200, json=self._quarantine_body(), request=request)

        if path == "/quarantine/preview" and method == "POST":
            body = json.loads(request.content or b"{}")
            job_id = body.get("job_id") or ""
            held = self._held()
            if job_id in held:
                return httpx.Response(200, request=request, json={
                    "job_id": job_id, "already_quarantined": True,
                    "quarantined": False, "entry": held[job_id]})
            return httpx.Response(200, request=request, json={
                "job_id": job_id, "already_quarantined": False,
                "quarantined": False, "plottable": 10, "total": 11,
                "would_hold_out": [f"r{i}" for i in range(11)],
                "preview_token": "fake-quarantine-token",
                "reason": body.get("reason") or ""})

        if path == "/quarantine" and method == "POST":
            body = json.loads(request.content or b"{}")
            if not body.get("confirm") or not body.get("preview_token"):
                return httpx.Response(428, request=request, json={
                    "detail": {"error": "confirmation_required",
                               "message": "ask for a preview first",
                               "action": "quarantine"}})
            if not (body.get("reason") or "").strip():
                return httpx.Response(422, request=request,
                                      json={"detail": "a quarantine needs a reason"})
            job_id = body["job_id"]
            held = self._held()
            entry = {"job_id": job_id, "reason": body["reason"],
                     "excluded_at": "2026-09-30T08:00:00+00:00",
                     "excluded_by": body.get("excluded_by") or "",
                     "run_ids": [f"r{i}" for i in range(11)],
                     "campaign_id": None, "config_id": "ocudu-mono_x",
                     "state": "completed", "rates": "100-1000"}
            changed = job_id not in held
            held.setdefault(job_id, entry)
            return httpx.Response(200, request=request, json={
                "job_id": job_id, "quarantined": True, "changed": changed,
                "entry": held[job_id], "runs_held_out": len(held[job_id]["run_ids"]),
                "detail": "nothing was deleted"})

        if path == "/quarantine/restore" and method == "POST":
            body = json.loads(request.content or b"{}")
            job_id = body.get("job_id") or ""
            held = self._held()
            if job_id not in held:
                return httpx.Response(200, request=request, json={
                    "job_id": job_id, "quarantined": False, "changed": False,
                    "detail": f"{job_id} is not quarantined"})
            if not body.get("confirm"):
                return httpx.Response(200, request=request, json={
                    **held[job_id], "quarantined": True, "changed": False,
                    "would_restore": len(held[job_id]["run_ids"]),
                    "preview_token": "fake-restore-token"})
            removed = held.pop(job_id)
            return httpx.Response(200, request=request, json={
                "job_id": job_id, "quarantined": False, "changed": True,
                "runs_restored": len(removed["run_ids"]),
                "detail": "these runs appear in figures drawn from now on"})

        if path == "/plots" and method == "GET":
            recorded = self._load("plots") or {"count": 0, "figures": []}
            figures = [f["summary"] for f in self.figures.values()]
            figures += list(recorded.get("figures") or [])
            return httpx.Response(
                200, json={"count": len(figures), "figures": figures}, request=request
            )

        if path == "/plots" and method == "POST":
            body = json.loads(request.content or b"{}")
            self.plot_requests.append(body)
            if self.refuse_plot:
                detail, self.refuse_plot = self.refuse_plot, None
                return httpx.Response(422, json={"detail": detail}, request=request)
            return httpx.Response(201, json=self._draw(body), request=request)

        if path.startswith("/plots/") and path.endswith("/regenerate") and method == "POST":
            source = path.split("/")[2]
            body = self._draw({"label": f"{source}-again"}, regenerated_from=source)
            return httpx.Response(201, json=body, request=request)

        if path.startswith("/plots/") and method == "GET":
            parts = path.split("/")
            figure_id = parts[2]
            if len(parts) == 4:
                return self._figure_file(request, figure_id, parts[3])
            drawn = self.figures.get(figure_id)
            if drawn is not None:
                return httpx.Response(200, json=drawn["manifest"], request=request)
            recorded = self._load("plots") or {"figures": []}
            if any(f["figure_id"] == figure_id for f in recorded.get("figures") or []):
                manifest = dict(self._load("plot_manifest") or {})
                manifest["label"] = figure_id.split("_", 2)[-1]
                return httpx.Response(200, json=manifest, request=request)
            return httpx.Response(
                404, json={"detail": f"no figure {figure_id!r}"}, request=request
            )

        if path == "/ue" and method == "GET":
            return httpx.Response(200, json=self._load("ue"), request=request)

        if path.startswith("/ue/") and path.endswith("/iperf") and method == "GET":
            return httpx.Response(200, json=self._load("ue_iperf"), request=request)

        if path.startswith("/ue/") and path.endswith("/preview") and method == "POST":
            action = path.rsplit("/", 2)[1]
            return httpx.Response(
                200,
                json={
                    "action": f"ue_{action}",
                    "summary": [
                        f"bring the {path.split('/')[2]} UE online through "
                        f"SamsungUeDriver(Samsung via adb-iapc)",
                        "an attach is confirmed by a 10.45.x address, never by an exit code",
                        "this holds the testbed lock while it runs, so a campaign "
                        "cannot overlap it",
                    ],
                    "preview_token": "fake-ue-token",
                    "expires_in_s": 300,
                    "state": {},
                },
                request=request,
            )

        if path.startswith("/ue/") and method == "POST":
            if self.locked_by:
                return self._locked(request)
            body = json.loads(request.content or b"{}")
            if not body.get("confirm") or not body.get("preview_token"):
                return httpx.Response(
                    428,
                    json={"detail": {"error": "confirmation_required", "action": "ue"}},
                    request=request,
                )
            ue = path.split("/")[2]
            action = path.rsplit("/", 1)[1]
            return httpx.Response(
                200,
                json={
                    "ue": ue,
                    "action": action,
                    "state": {"reachable": True, "attached": action == "attach"},
                    "ip": "10.45.0.78" if action == "attach" else None,
                    "attached": action == "attach",
                    "detail": f"{ue}: {action} done",
                },
                request=request,
            )

        return None

    #: What each served name contains, so a test can check the console passed the
    #: content type and the bytes through rather than inventing either.
    FILES: dict[str, tuple[bytes, str]] = {
        "image.png": (b"\x89PNG\r\n\x1a\nFAKE-PNG-BYTES", "image/png"),
        "figure.pdf": (b"%PDF-1.4 FAKE-PDF-BYTES", "application/pdf"),
        "raw.csv": (b"run_id,offered_mbps\nr-1,100.0\n", "text/csv"),
        "points.csv": (b"config_id,mean_mbps\nocudu-mono_x,99.9\n", "text/csv"),
    }

    def _figure_file(self, request: httpx.Request, figure_id: str,
                     name: str) -> httpx.Response:
        if name not in self.FILES:
            return httpx.Response(
                404, json={"detail": f"a figure does not serve {name!r}"},
                request=request,
            )
        content, media = self.FILES[name]
        return httpx.Response(200, content=content,
                              headers={"content-type": media}, request=request)

    def _draw(self, body: dict[str, Any],
              regenerated_from: str | None = None) -> dict[str, Any]:
        """A figure, shaped exactly as the real POST /plots answers.

        The manifest comes from a recording of a real one, with the request's
        own metric and label put back, so a test reads the shapes ETHOS
        actually produces rather than shapes invented here.
        """
        index = len(self.figures) + 1
        figure_id = f"2026-09-29__09{index:02d}00_line_{body.get('label') or 'figure'}"
        manifest = dict(self._load("plot_manifest") or {})
        manifest.update({
            "label": body.get("label") or "figure",
            "metric": body.get("metric") or "throughput",
            "kind": body.get("kind") if body.get("kind") not in (None, "auto") else "line",
            "y_scale": body.get("y_scale") if body.get("y_scale") not in (None, "auto")
                       else "linear",
            "made_by": "api",
        })
        warnings = list(manifest.get("warnings") or [])
        summary = {
            "figure_id": figure_id,
            "label": manifest["label"],
            "kind": manifest["kind"],
            "metric": manifest["metric"],
            "width": manifest.get("width") or "single",
            "created": f"2026-09-29T09:{index:02d}:00+08:00",
            "made_by": "api",
            "n_points": len(manifest.get("points") or []),
            "warnings": warnings,
            "folder": f"/graphs/{figure_id}",
        }
        self.figures[figure_id] = {"manifest": manifest, "summary": summary}
        answer = {
            "figure_id": figure_id,
            "folder": summary["folder"],
            "warnings": warnings,
            "manifest": manifest,
        }
        if regenerated_from:
            answer["regenerated_from"] = regenerated_from
        return answer

    def _events(self, request: httpx.Request, job_id: str) -> httpx.Response:
        """The SSE stream, numbered and resumable exactly as ETHOS numbers it.

        `Last-Event-ID` is honoured by replaying only what comes AFTER it, which is
        what lets a test prove the relay forwarded the header: resume from 2 and
        the body must start at id 3.
        """
        last = request.headers.get("Last-Event-ID")
        self.resumed_from = last
        try:
            after = int(last) if last else 0
        except ValueError:
            after = 0

        lines: list[str] = []
        for item in self.events.get(job_id, []):
            if item["seq"] <= after:
                continue
            payload = json.dumps({"seq": item["seq"], **item["data"]})
            lines.append(f"id: {item['seq']}\nevent: {item['event']}\ndata: {payload}\n\n")
        return httpx.Response(
            200,
            content="".join(lines).encode(),
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    # The head ETHOS builds for each split, from identity/topology.py's rules.
    HEADS = {
        ("OCUDU", "monolithic"): "ocudu-mono",
        ("OAI", "monolithic"): "oai-mono",
        ("OCUDU", "CU+DU"): "ocudu-cudu",
        ("OAI", "CU+DU"): "oai-cudu",
        ("OCUDU", "OCUDU-CU+OAI-DU"): "ocuducu-oaidu",
        ("OAI", "OCUDU-CU+OAI-DU"): "ocuducu-oaidu",
        ("OCUDU", "OAI-CU+OCUDU-DU"): "oaicu-ocududu",
        ("OAI", "OAI-CU+OCUDU-DU"): "oaicu-ocududu",
    }
    SLUGS = {
        "Samsung": "samsung", "MTK": "mtk", "TM500": "tm500",
        "Pegatron-Dongle": "pegadongle", "Pegatron": "pega", "Foxconn": "foxconn",
        "software-PHY": "swphy", "Aerial-cuBB": "aerial",
        "Open5GS": "o5gs", "free5GC": "f5gc", "joule": "joule", "DGX-Spark": "dgxspark",
    }

    def _testdef(self, selection: dict[str, Any]) -> dict[str, Any]:
        """A generated test definition, keyed on the selection.

        The recorded response is one topology's, and every page that changes a
        topology would otherwise see that same answer come back. The fake builds
        the config_id the way ETHOS documents it, so a test can tell one
        selection from another. The console still never builds one itself: it
        reads whatever this endpoint returns.
        """
        recorded = self._load("testdef_generate") or {}
        head = self.HEADS.get(
            (selection.get("gnb_stack", ""), selection.get("gnb_split", "")), "unknown"
        )
        parts = [
            head,
            self.SLUGS.get(selection.get("l1_backend", ""), "swphy"),
            self.SLUGS.get(selection.get("ru", ""), "pega"),
            self.SLUGS.get(selection.get("ue", ""), "samsung"),
            self.SLUGS.get(selection.get("core", ""), "o5gs"),
            self.SLUGS.get(selection.get("server", ""), "joule"),
        ]
        config_id = "_".join(parts)

        definition = dict(recorded.get("test_definition") or {})
        definition["config_id"] = config_id
        definition["selection"] = selection
        return {
            "test_definition": definition,
            "sample_run_id": f"20260927T1200Z-{config_id}-DL100M-001",
            "validation": self._validate(selection),
        }

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

    # --- quarantine ----------------------------------------------------------

    def _held(self) -> dict[str, Any]:
        """The held-out jobs, seeded once from the recorded fixture."""
        if self.quarantined is None:
            recorded = self._load("quarantine") or {"jobs": []}
            self.quarantined = {entry["job_id"]: entry
                                for entry in (recorded.get("jobs") or [])}
        return self.quarantined

    def _quarantine_body(self) -> dict[str, Any]:
        held = self._held()
        excluded: list[str] = []
        for entry in held.values():
            for run_id in entry.get("run_ids") or []:
                if run_id not in excluded:
                    excluded.append(run_id)
        return {"version": 1, "count": len(held), "jobs": list(held.values()),
                "excluded_run_ids": excluded,
                "note": "quarantine deletes nothing"}
