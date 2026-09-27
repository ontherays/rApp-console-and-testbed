# What the console is waiting for from ETHOS

The console is specified against an ETHOS that has a testbed lock, a job model, a
readiness endpoint and figure generation. None of that exists yet, and this
console was built without changing ETHOS at all.

Rather than buttons that look live and fail on click, every such control is
disabled and names the backend change that delivers it. This is the list, and it
is also the order of work in `04-build-plan.md`.

Checked against the live API on 127.0.0.1:8081 on 2026-09-27.

---

## How the gating works

`console/capabilities.py` declares each feature with the endpoint it needs and its
backend-change id. It probes them at startup and every 60 seconds, and classifies
each as:

- `ok`: the endpoint answered
- `not_built`: a 501 stub, or not routed at all
- `unreachable`: ETHOS itself is down

A page asks `caps.ready("jobs")` and renders the gated state from `caps.why()`.
**When a backend change lands, the probe finds the endpoint and the page lights up
on its own.** Removing the entry from the table is the last step, not the first.

---

## The endpoints, as they answered

| Endpoint | Today | Needed for |
|---|---|---|
| `GET /compatibility` | **works** | the Test Plan option lists |
| `POST /validate` | **works** | validating a selection |
| `POST /testdef/generate` | **works** | the `config_id` |
| `GET /runs`, `GET /runs/{id}` | **works** | Results, run detail, sweeps |
| `GET /deploy/status` | **works** | what is deployed |
| `GET /status/health` | **works** | the telemetry agent tile |
| `GET /runs/{id}/o1-pm`, `/cm`, `/correlated`, `/throughput` | **works** | per-run O1 |
| `GET /cm/params/writable` | **works** | the future CM page |
| `GET /status/devices` | 501 | UE / RU / gNB reachability |
| `GET /status/resources` | 501 | O-Cloud CPU and memory |
| `GET /runs/{id}/plots` | 501 | per-run figures |
| `GET /compare` | 501 | ETHOS's own A/B comparison |
| `GET /results/ladder` | 501 | the energy ladder |
| `POST /testdef/validate` | 501 | an editable config view |
| `POST /campaigns`, `POST /campaigns/{id}/run`, `GET /campaigns/{id}/status` | 501 | running a campaign |
| `GET /lock` | not routed | B1 |
| `GET /jobs`, `POST /jobs`, `POST /jobs/preview`, `GET /jobs/{id}/events` | not routed | B2 |
| `GET /catalogue` | not routed | B4 |
| `POST /readiness` | not routed | B5 |
| `GET /status/summary` | not routed | B6 |
| `POST /plots`, `GET /plots`, `GET /plots/series` | not routed | B9 |
| `GET /runs.csv`, `GET /campaigns/{id}/summary`, `GET /runs/{id}/radio-samples` | not routed | B10 |
| `GET /ue`, `POST /ue/{ue}/attach`, `GET /ue/{ue}/iperf` | not routed | B11 |
| `GET /o1/freshness`, `GET /o1/alarms` | not routed | B12 |
| `GET /o2/nf`, `GET /o2/deploy-times`, `GET /o2/dms/*` | not routed | B13 |

---

## What each change unlocks, and what to delete when it lands

### B1, testbed lock

Gated: the Overview's lock tile, the readiness panel's `lock` line, and the
status strip's `Lock` item. All three read `unknown` today, which is the honest
answer, an item that said "free" because nothing answered would be worse than no
item at all.

When it lands: add `lock()` to `client.py`; the tile and the strip read it. Remove
the `lock` entry from `FEATURES`.

### B2, jobs

Gated: the RUN button, the whole Jobs page, and the Overview's running-job tile.

The console deliberately does **not** run campaigns itself. It has the same API
the CLI drives, so it could, and that is the reason not to: a second campaign
executor, with the lock living in the LAN-facing web process instead of in ETHOS,
is what the design rules out. One executor, in ETHOS.

When it lands: `POST /jobs/preview` fills the confirmation dialog the plan page
already has a place for, `POST /jobs` replaces the "Save plan" primary action, and
the Jobs page gains the SSE relay (`console/sse.py`, not yet written: there is
nothing to relay).

### B3, preview, then act with a token

Nothing in the console acts on the testbed today, so nothing is gated on this
directly. It is the prerequisite for Phase 2: deploy, teardown and UE attach act
on the first call in ETHOS today, with no preview, which is why the Testbed page
is a description rather than a control panel.

### B4, catalogue with deployability

**Standing in today:** `console/rapps/ethos/profiles.py` reads ETHOS's
`deployment/deploy_profiles.yaml` directly, a plain data file on this host, read
and never written, holding no credential, and joins it with `/compatibility`
itself. That is what makes the Test Plan disable TM500 with "Deploy profile
ocudu-mono-tm500 is a placeholder" instead of validating happily and failing at
deploy.

Reasons that are hard-coded in `OPTION_REASONS` (Foxconn, TM500, the Pegatron
dongle, Aerial, DGX-Spark, free5GC) each came from the profiles and chart values
on this host. **They are the weakest part of the console**, they will drift.

When it lands: delete `profiles.py`, delete `OPTION_REASONS`, drop
`CONSOLE_DEPLOY_PROFILES`, and read `deployable` and `reason` per option from
`/catalogue`.

### B5, readiness

Gated: four of the seven readiness lines (`lock`, `ue_reachable`, `iperf_server`,
`core`). `topology` and `node_free` are answered today from `/validate` and
`/deploy/status`, and `traffic_plan` is a **console pre-check**, labelled as such:
it parses rates and duration with the CLI's own grammar so a plan that cannot be
expressed as a campaign is caught before it is saved.

The console adds no readiness check of its own beyond that, because the point of
`POST /readiness` is that the CLI and the console judge readiness identically.

When it lands: replace the whole list with ETHOS's, rendered in its order. Delete
the pre-check's "console pre-check" label, or keep the parse as a form hint only.

### B6, status summary

Gated: the `Lock`, `Job`, `UE` and `iperf 5201` items in the status strip, and the
Overview's data-freshness tile. Freshness needs InfluxDB, and the console holds no
database token, this one cannot be worked around, only waited for.

When it lands: `build_status()` in `console/status.py` becomes one call.

### B7, iperf server mode per job

Not gated, but recorded: the plan carries `iperf_server`, and the mode is
service-wide in ETHOS today (`ETHOS_IPERF_SERVER` in a systemd drop-in, currently
`app_binary`). The plan page says so.

### B8, direction and repeats

`--direction` exists in the campaign CLI; `--repeats` does not. A plan with more
than one repeat says so, and the copy-able command explains that repeats mean
running it that many times.

### B9, figures on request

**Standing in today:** the Graphs page is a read-only gallery over
`ETHOS_GRAPH_DIR`, listing each figure with its manifest, PNG and PDF. The
console does not draw its own chart from the same numbers, that would be a
second, differently-styled rendering of one figure, and the archive exists to
stop exactly that.

When it lands: `POST /plots` behind the form the page already has disabled, and
`GET /plots/series` replaces the copied palette in
`console/rapps/ethos/series.py`. Drop `CONSOLE_GRAPH_DIR`.

### B10, results queries

**Standing in today:** `console/rapps/ethos/query.py` does the filtering,
sorting, paging, CSV and sweep grouping in the console, because `GET /runs` takes
no limit and re-reads all 528 manifests per request (1.1 MB today, growing). The
run list is cached for `CONSOLE_RUNS_CACHE_S`.

The Samples tab names the archived `radio.json` path rather than showing rows,
because `GET /runs/{id}/radio-samples` does not exist and inventing its contents
is not an option.

When it lands: delete `query.py`, pass the filters through, use `GET /runs.csv`
and `GET /campaigns/{id}/summary`.

### B11, standalone UE control

Gated: the whole Testbed page's UE half, the Overview's UE tile, the
`ue_reachable` and `iperf_server` readiness lines. ETHOS's UE endpoints are
scoped to a run today, which is right for the record but means there is no
standalone panel, and the console will not create a run just to read a UE's
state.

### B12, O1 freshness, alarms, CM-driven tests
### B13, O2 NF checks, deploy timing, energy, DMS

Gated: the O1 and O2 pages. Each lists its requirement ids and what stands today.

### B14, derived cell-config fields

The Cell config tab shows `,` where OCUDU's configuration does not state a value,
and says that deriving `n_prb` is B14. It does not derive it itself: a number the
console computed and ETHOS did not would appear in a screenshot as if it had been
measured.

### B15, test-definition radio parameters

`POST /testdef/generate` reports 80 MHz and DDDSU for OCUDU, which runs 100 MHz
and 7D2U. The plan page labels those values **planned** and points at the run's
Cell config tab for what actually ran.

---

## Things the console will never do, whatever ETHOS gains

- Query InfluxDB, SSH anywhere, or run `kubectl` or `adb`. Every fact comes
  through an ETHOS endpoint, because ETHOS holds the credentials (SE-06).
- Assemble a `config_id`. `POST /testdef/generate` is the only source.
- Call `GET /runs/{id}/ee-kpi` without `persist=false`. That endpoint writes the
  manifest by default, and a console read must leave no fingerprint on a run.
- Act on one click. Every state-changing action goes through a confirmation
  showing ETHOS's own preview (GL-07).
- Add a readiness check of its own. Two opinions about whether the testbed is
  ready is worse than one.
