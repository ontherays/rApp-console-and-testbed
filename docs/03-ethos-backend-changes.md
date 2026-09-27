# ETHOS changes required by the Testbed Console

Repo: `~/ravi-ethos-rApp`. Companion to `01-requirements.md` and `02-design.md`.

The console only presents. Everything that keeps the testbed safe or makes a
result trustworthy is built here, in ETHOS, so the CLI gets the same behaviour.
Each change is numbered B1–B15; the build plan schedules them.

## Conventions for every new endpoint

- No `/ui/` prefix. These are ETHOS API endpoints; the console is one client.
- ETHOS keeps binding 127.0.0.1:8081 only.
- Timestamps are UTC ISO-8601 with `Z`.
- Errors return `{"error": "<code>", "message": "<text>", …}`. Lock refusals add `holder` (B1).
- Every new endpoint appears in `/openapi.json` with request and response models.
- Every state-changing endpoint follows the confirmation rule in B3.
- Storage for new state lives beside the runs archive: `$ETHOS_RUNS_ROOT/../state/` and `$ETHOS_RUNS_ROOT/../jobs/` (today `/home/oai-gnb/ravi-ethos-rApp-run/`).

---

## B1 — Testbed lock

**Why.** Nothing stops two campaigns, or a campaign and a manual deploy, from acting on joule at once. The investigation found no lock anywhere in `api/`, `campaign/`, `deployment/` or `execution/`; the only guard is a node-free `ps` check that two callers can race.

**Behaviour.**
- One lock file: `$ETHOS_RUNS_ROOT/../state/testbed.lock`, held with `fcntl.flock(LOCK_EX | LOCK_NB)`. A dead holder releases it automatically.
- A sidecar `testbed.lock.json` records the holder: `{"holder": "job:<job_id>" | "cli:<pid>" | "action:<name>", "what": "<human text>", "since": "<utc>"}`.
- Taken by: a job for its whole life; a standalone deploy, teardown, UE attach/detach, Magic iPerf stop, or CM apply for the duration of that action.
- A refused request gets **409** with `{"error": "testbed_locked", "holder": …, "what": …, "since": …}`. No queue.
- **Inner calls of a running job.** The job's campaign code calls ETHOS endpoints that also take the lock. The job therefore gets a lock token, and its transport sends it as the `X-Ethos-Lock-Token` header. A request carrying the current holder's token passes the lock check.
- `GET /lock` → holder record, or `{"holder": null}`.

**CLI.** `python -m campaign` takes the same lock (through B2, since the CLI becomes a job client). A second CLI run while one is active exits with the holder named.

**Tests.** Two concurrent job starts: exactly one succeeds, the other gets 409 naming the first. A lock held by a killed process is free afterwards. An inner call with the token passes; without it, it gets 409.

---

## B2 — Jobs: one campaign executor

**Why.** Campaigns only run from `python -m campaign` today; `POST /campaigns/{id}/run` and `GET /campaigns/{id}/status` return 501. The console needs to start a campaign, watch it, stop it, and survive a browser refresh.

**Behaviour.**
- A job wraps `campaign.runner.Campaign` **unchanged**, running it in a background task with an injected transport (`runner.py:397`) that makes the API calls and emits progress events. No sequencing logic is duplicated.
- Persisted under `$ETHOS_RUNS_ROOT/../jobs/<job_id>/`: `job.json` (plan, state, steps, run_ids, timing, outcome, `source: console | cli`) and `events.jsonl` (append-only, one event per line, sequence-numbered).
- States: `created, preflight, deploying, attaching, running, stopping, detaching, tearing_down, completed, failed, aborted, interrupted` (design §7.3).
- On ETHOS startup, any job not in a terminal state becomes `interrupted`, with an event recording what was deployed at that moment.

**Endpoints.**

| Endpoint | Behaviour |
|---|---|
| `POST /jobs/preview` | plan → human-readable preview + `preview_token` (B3). Sends nothing to the testbed. |
| `POST /jobs` | plan + `confirm: true` + `preview_token` → 201 `{job_id}`; 409 if locked; 412 if the state changed since the preview. |
| `GET /jobs` | newest first; filters `state`, `config_id`, `source`, `since`, `until`; paginated. |
| `GET /jobs/{job_id}` | the snapshot: state, current step, steps with timings, completed points with their summaries, cell config once known. |
| `GET /jobs/{job_id}/events` | `text/event-stream`. Event `id` is the sequence number; `Last-Event-ID` replays from `events.jsonl`. Event types: `state`, `step`, `point_started`, `point_finished` (with the same summary fields the CLI prints), `log`, `finished`. |
| `POST /jobs/{job_id}/stop` | cooperative: sets a stop flag; the campaign finishes the current point, then detaches and tears down (DU before CU). The job ends `aborted`. |
| `POST /campaigns/{id}/run`, `GET /campaigns/{id}/status` | stop returning 501; thin wrappers over the job endpoints. |

**The plan document** (the body of `/jobs/preview` and `/jobs`):

```json
{
  "selection": { "...": "what POST /validate takes" },
  "config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule",
  "direction": "DL",
  "rates": "100-1000:100",
  "duration": "30s",
  "repeats": 1,
  "iperf_server": "app_binary",
  "radio_samples": false,
  "label": "sweep-0927",
  "cm_steps": [],
  "cm_sweep": null
}
```

`config_id` must be one returned by `POST /testdef/generate`; the job endpoints reject anything else. `cm_steps` and `cm_sweep` stay empty until B12.

**CLI.** `python -m campaign` submits a job and follows its events, printing the same step lines and end-of-campaign summary as today. CLI jobs appear in `GET /jobs` with `source: cli`. The CLI's current flags keep working; `--rates`, `--duration`, `--radio-samples` map onto the plan.

**Tests.** A job runs a fake campaign to completion; events replay after a simulated reconnect with no gaps or duplicates; stop during point 3 of 5 gives `aborted` with 3 points and a teardown; a restart mid-job gives `interrupted`; the CLI output is unchanged against a recorded campaign.

---

## B3 — Confirmation: preview, then act with a token

**Why.** Deploy, teardown, UE attach/detach and traffic act on the first call today. Only CM writes have preview → `confirm=true` (`o1/cm_writer.py`), which the investigation rated the strongest discipline in the codebase.

**Behaviour.**
- Every state-changing action gets a preview endpoint that returns what would happen, given the current testbed state, plus a `preview_token`.
- The token is a hash of (the request, the lock holder, the deployed releases, the UE attach state, the port-5201 holder). It is valid for 5 minutes.
- The act call must carry `confirm: true` and the token. If the state no longer matches the token → **412** `{"error": "state_changed", "message": "<what changed>"}`.
- **Exception:** calls carrying the running job's lock token (B1) skip the preview requirement. They are steps of an already-confirmed job.
- A call with neither a lock token nor confirm + token → **428** `{"error": "confirmation_required"}`.

**Actions covered.** Job start; standalone deploy (`POST /deploy`, `POST /runs/{id}/deploy`); teardown (`DELETE /deploy`, `DELETE /deploy/{config_id}`); UE attach and detach (existing run-scoped and new B11); Magic iPerf stop (B11); CM apply (keeps its existing `confirm=true`, gains the token).

**Migration.** Before switching enforcement on, list every existing caller of these endpoints (campaign runner, scripts, tests, docs) and move each to either the job path or preview + confirm. Enforcement ships in the same change as the migration.

**Tests.** Act without confirmation → 428; with a stale token after the lock was taken → 412; with a valid token → acts; a job's inner calls → act without a preview.

---

## B4 — Catalogue with deployability

**Why.** `GET /compatibility` says what is *compatible*, not what can be *deployed*. TM500, Foxconn and Aerial validate and then fail at deploy with `TODO(Ravi)` (investigation risk R8).

**Endpoint.** `GET /catalogue` = `/compatibility` joined with `deployment/deploy_profiles.yaml`. Every option carries: `slug`, `label`, `status` (supported / experimental), `deployable` (true / false), `reason` when not deployable, and the couplings (RULE-1 TM500 UE ⟺ TM500 RU, RULE-7 Aerial ⟺ DGX-Spark).

**Where each reason comes from:**
- RU: deployable only where the charts have a values set for that RU (today Pegatron, e.g. `values-pegatron.yaml`). Foxconn and TM500: "No chart configuration for this RU yet."
- UE: deployable only where `ue/registry.py` has a working driver. Report the registry's answer per UE (Samsung and MTK have been attached on this testbed; Pegatron dongle and TM500 UE must be checked, not assumed).
- Aerial cuBB / DGX-Spark: "Requires the DGX-Spark GB10 host; no deploy profile yet."
- free5GC: "Not verified on this testbed" until the core check is done.
- `ocudu-mono-tm500`: profile status `todo`.

The console displays `label`, never `slug` (the split slugs `mixocuoai` / `mixoaiocu` no longer match the config_id heads).

---

## B5 — Readiness

**Endpoint.** `POST /readiness` with a plan (B2 format) → an ordered list of checks:

| id | Passes when |
|---|---|
| `topology` | the selection validates and every option is deployable |
| `lock` | the lock is free |
| `node_free` | nothing is deployed in `ravi-ns` and no gNB process runs on joule |
| `ue_reachable` | the selected UE answers on its control path (for Samsung: SSH to `iapc`, then adb `device`) |
| `iperf_server` | mode `ethos`: port 5201 on the UE is free. Mode `app_binary`: an `app_binary` server holds 5201. |
| `traffic_plan` | rates, duration, repeats and direction parse and are in range |
| `core` | the selected core's AMF answers from joule's network |

Each check returns `status` (`pass | fail | unknown`), `reason`, and `checked_at`, with a per-check timeout of 5 s (`unknown` on timeout). The CLI's preflight uses the same function, so the console and the CLI judge readiness identically.

---

## B6 — Status summary

**Endpoint.** `GET /status/summary` → one object for the status strip and the Overview:

`lock`, `deployed` (topology label, releases, pod states, cell config), `latest_job` (id, state, progress), `ue` (selected UE, attach state, IP), `iperf_server` (mode default, port-5201 holder), `freshness` (last point of `ethos_iperf_v2`, the testbed's `ran-pm-metrics` managed elements, `ocloud_power`), and `api` (version, uptime).

Each part has its own `checked_at` and `error`; one failing probe never fails the whole response. Slow probes (UE, 5201 holder) are cached for 15 s, freshness for 60 s.

---

## B7 — iperf server mode per job

**Why.** The mode is service-wide today, set by `ETHOS_IPERF_SERVER` in a systemd drop-in, and changing it needs a restart.

**Behaviour.** The plan carries `iperf_server: "ethos" | "app_binary"`. The value applies to that job's runs only and is recorded on each run as now (`server_owner`). `ETHOS_IPERF_SERVER` remains the default when the plan omits it, so the CLI keeps working unchanged. The drop-in can stay or go; document which.

---

## B8 — Direction and repeats

**Check first.** Confirm whether the campaign runner already supports UL and repeated runs per rate. The channel-metrics investigation ran UL 50 M through the API, not through `python -m campaign`.

**If missing, add:**
- `direction: DL | UL` on the plan and a `--direction` CLI flag.
- `repeats: 1–20`. Order: rates outer, repeats inner (100 M ×5, then 200 M ×5, …). Each repeat is its own run with `repeat_index` (1-based) on the manifest.

---

## B9 — Figures on request, including channel metrics

**Endpoints.**

| Endpoint | Behaviour |
|---|---|
| `POST /plots` | `{source: {run_ids} | {campaign_id} | {filter}, metric, kind: auto|line|bar, group_by: config|run, width: single|double, label}` → `{figure_id}` after running `plotting.build_figure`. |
| `GET /plots` | previously generated figures, newest first. |
| `GET /plots/{figure_id}` | the manifest: inputs, n per point, warnings, git commit. |
| `GET /plots/{figure_id}/image.png`, `/figure.pdf` | files from `ETHOS_GRAPH_DIR`. |
| `GET /plots/series` | each stack's label, colour, marker, line style and order, from `plotting/series.py`, so the console's chips match the figures. |

**Plotting extension.** Add a `metric` parameter to `build_figure`: `throughput` (today's behaviour, the default), `loss`, `rtt_p95`, `pusch_snr`, `bler_dl_residual`, `bler_ul_residual`, `mcs_dl`, `mcs_ul`, `cqi`, `ri_dl`. Axis labels use the names from requirements §7.4. MCS figures draw each stack's cap as a dashed line where one exists. Metrics that aren't comparable across stacks (first-transmission BLER, PUCCH SNR) are not offered.

**Warnings in the manifest** (shown by the console above the figure): the inputs mix cell configs (TDD pattern, bandwidth), iperf server modes, or durations.

The `plotting runs` CLI and `python -m plotting throughput` keep working unchanged.

---

## B10 — Results queries

| Endpoint | Behaviour |
|---|---|
| `GET /runs` (extended) | filters: `config_id`, `since`, `until`, `rates`, `direction`, `campaign_id`, `job_id`, `server_owner`, `band`, `bandwidth_mhz`, `tdd_pattern`, `has_quality_flags`, `usable` (default true: `has_delivered` and server owner `ethos` or `app_binary`); `limit`, `offset`; newest first. Each row carries the summary fields the run table shows. |
| `GET /runs.csv` | the same filters; one row per run, every summary field, UTC timestamps. |
| `GET /campaigns/{id}/summary` | one row per offered load: repeats aggregated (mean, n, 95 % CI), channel means, and `cell_config_consistent: true | false`. Also accepts a job id. |
| `GET /runs/{run_id}/radio-samples` | the per-second rows from `radio.json`; 404 with `{"error": "no_samples"}` when the run was made without `--radio-samples`. |

Source: the run archive (`run.json`), which is the source of truth; InfluxDB is not required for these endpoints.

---

## B11 — Standalone UE control (Phase 2)

**Prerequisite.** Switch `iapc` to SSH-key login, so the long-running service needs no password for UE actions.

| Endpoint | Behaviour |
|---|---|
| `GET /ue` | every UE in `ue/registry.py`: driver, control path, reachable, attach state, IP, `checked_at`. |
| `POST /ue/{ue}/attach/preview`, `POST /ue/{ue}/attach` | lock-gated, confirm-gated (B1, B3). |
| `POST /ue/{ue}/detach/preview`, `POST /ue/{ue}/detach` | same. |
| `GET /ue/{ue}/iperf` | the port-5201 holder: owner (`ethos | app_binary | foreign | unknown`), PID, package. |
| `POST /ue/{ue}/iperf/stop/preview`, `POST /ue/{ue}/iperf/stop` | force-stops `com.nextdoordeveloper.miperf.miperf`; confirm-gated. |
| `GET /ue/{ue}/signal` | SS-RSRP / RSRQ / SINR from `dumpsys telephony.registry`, with the Android sentinel mapped to null. |

These use `ue.driver.UeDriver` and `ue.registry`, the same code the planned UE toolkit will use.

---

## B12 — O1: freshness, alarms, CM-driven tests (Phase 3)

- `GET /o1/freshness`: the last PM point per managed element **of this testbed** (`ManagedElement=ocududu,…` and `ManagedElement=oai-gnb-mono,…`). Never enumerate `ran-pm-metrics`; it also holds an unrelated satellite-simulator project's measurements.
- `GET /o1/alarms`: active alarms and history from the existing ONAP / VES path. Phase 3 starts with a short investigation of where FM events land today (VES collector → which topic or store).
- CM in jobs: the plan's `cm_steps` (`[{param, value}]`, applied in order before traffic) and `cm_sweep` (`{param, values}`, running the rate list once per value). Every change goes through the existing `cm/preview` → `cm/apply?confirm=true` path inside the job. The job's own preview (B3) lists every CM change, so one confirmation covers them. Parameters and ranges come only from `GET /cm/params/writable`.
- New readiness checks when a plan has CM content: `o1_adapter` (deployed with the gNB), `pm_fresh` (a PM point within 2 granularity periods), `sdnc_mount` (the NETCONF mount is connected).

---

## B13 — O2 (Phase 4)

- `GET /o2/nf`: Helm releases and pods in `ravi-ns` with status, readiness, restarts, age.
- **Deploy timing.** On every deploy, record the time from `helm install` of the first release to all pods Ready, per release and in total. Store it on the deployment record, copy `deploy_duration_s` onto each run of that deployment, and expose `GET /o2/deploy-times?config_id=…`.
- **Energy.** `GET /o2/energy/freshness` now; EE-KPI panels only after the RAPL shipper fix (separate task; `ocloud_power` has had no point since 2026-08-27).
- **DMS.** The StarlingX `oran-o2` application (`pti-o2imsdms` 2.0.4) answers at `https://192.168.206.82:30205` and requires a client certificate. Store the certificate, key and CA in ETHOS's environment (`ETHOS_O2_CLIENT_CERT`, `ETHOS_O2_CLIENT_KEY`, `ETHOS_O2_CA`), never in a response, then add read-only `GET /o2/dms/inventory` and `GET /o2/dms/deployments`.

---

## B14 — Derived cell-config fields

OCUDU's config doesn't state `n_prb` or max MIMO layers, so `cell_config` has nulls where OAI has numbers. Derive `n_prb` from bandwidth and SCS using 3GPP TS 38.101-1 Table 5.3.2-1 (100 MHz at 30 kHz → 273), and add `derived_fields: ["n_prb"]` so the console can mark it "derived". Leave max MIMO layers null; there is no reliable derivation.

---

## B15 — Test-definition radio parameters

`POST /testdef/generate` returns `bandwidth_mhz: 80` and `tdd_pattern: "DDDSU"` for OCUDU, while OCUDU runs 100 MHz and 7D2U. The console labels these values "planned" (requirements TP-20) and shows measured cell config from the run. Fix the source: fill the test definition's radio parameters from the topology's chart configuration (`values-pegatron.yaml` for OCUDU, `config.yaml` for OAI), or return them as null with a reason. Never return a hard-coded default as if it described the topology.