# Testbed Console & Dashboard — Design

Companion to `01-requirements.md` (requirement IDs in brackets refer to it).
ETHOS-side changes are specified in `03-ethos-backend-changes.md` as B1–B15.

---

## 1. Architecture

```
 browser (lab LAN)
    │  HTTPS :8443, session cookie
    ▼
 Testbed Console  — FastAPI + Jinja2, systemd user service "testbed-console"
    │  ├─ pages (server-rendered HTML, htmx swaps, SSE relay)
    │  ├─ auth (one password, sessions, CSRF)
    │  └─ rapps/ethos/client.py  ← the ONLY code that talks to ETHOS
    │  HTTP over loopback
    ▼
 ETHOS API  127.0.0.1:8081  — systemd user service "ethos-rapp"
    ├─ lock, jobs, readiness, previews, catalogue      (B1–B8)
    ├─ runs, results, plots, UE, O1, O2 endpoints      (existing + B9–B13)
    └─ SSH / kubectl / adb / InfluxDB / SDNC           (credentials stay here)
```

Why this shape:

- **ETHOS stays on loopback.** It can deploy Helm charts, SSH to joule and change CM on a live cell, and it has no authentication. The console is the only LAN-facing process, and it has a login.
- **The console holds no testbed credentials.** It never reads `ethos.env`, never queries InfluxDB directly, and never SSHes anywhere. Everything goes through ETHOS endpoints [SE-06].
- **Safety is enforced in ETHOS, not in the page.** The lock, deploy order and confirm-before-act rules are ETHOS behaviour, so the CLI, the console and any future tool all get them [RN-01].
- **No CORS.** The browser only ever talks to the console. The console talks to ETHOS server-side.

Alternatives rejected:

| Option | Why not |
|---|---|
| UI inside the ETHOS process (the WebUI plan's option) | Ravi wants the console as its own repo. Also mixes a LAN-facing login surface into the process that holds every credential. |
| Browser calls ETHOS directly | Would require exposing ETHOS on the LAN and adding CORS to an unauthenticated API. |
| React + Vite | A build toolchain and dependency tree to maintain for a single-maintainer console. Shoelace provides the requested components without it. |
| Proxying ETHOS Swagger through the console | Swagger's "Try it out" would bypass the console's confirmation dialogs. Swagger stays reachable by SSH tunnel only. |

---

## 2. Repository layout

```
testbed-console/
├── console/
│   ├── app.py              FastAPI app, middleware, router registration
│   ├── settings.py         reads console.env
│   ├── auth.py             login, session, rate limit, CSRF
│   ├── plans.py            saved test plans (files under CONSOLE_PLANS_DIR)
│   ├── sse.py              relays ETHOS event streams to the browser
│   ├── pages/              overview, jobs, results, graphs, testbed, o1, o2
│   ├── rapps/
│   │   └── ethos/
│   │       ├── client.py   every ETHOS call, typed; timeouts; error mapping
│   │       ├── models.py   pydantic models of ETHOS responses
│   │       └── routes.py   console endpoints that call client.py
│   ├── templates/
│   │   ├── base.html       nav, status strip, toast region, breadcrumbs
│   │   ├── components/     macros: chip, stat, tile, readiness_item, confirm_dialog
│   │   └── <page>/*.html   one folder per page; partials for htmx swaps
│   └── static/
│       ├── css/console.css design tokens (§4), layout, bento grid
│       ├── js/console.js   toast helper, SSE wiring, small Alpine stores
│       └── vendor/         htmx, htmx-ext-sse, alpinejs, shoelace (pinned, vendored)
├── tests/
│   ├── fake_ethos/         a small FastAPI app replaying recorded ETHOS responses
│   ├── recorded/           JSON captured from the real ETHOS API
│   ├── unit/               client, auth, plans, readiness rendering
│   └── e2e/                Playwright flows against fake_ethos
├── deploy/
│   ├── testbed-console.service
│   └── make-cert.sh        self-signed TLS for 192.168.8.78
├── docs/                   these four documents + operator guide
├── console.env.example
├── CLAUDE.md
└── pyproject.toml
```

The `rapps/ethos/` folder is the whole ETHOS integration. A second rApp later means a sibling folder and a navigation entry; nothing else moves.

---

## 3. Stack and components

| Layer | Choice | Version policy |
|---|---|---|
| Server | Python 3.12, FastAPI, Jinja2, uvicorn (TLS) | pinned in `pyproject.toml` |
| HTTP to ETHOS | httpx (async), 10 s default timeout, 60 s for previews | |
| Live updates | htmx 2 + the htmx SSE extension; polling for the status strip | vendored, exact version |
| Components | Shoelace 2 (web components) | vendored, exact version |
| Small interactions | Alpine.js 3 | vendored |
| Auth | argon2-cffi (password hash), Starlette sessions (signed cookie) | |
| Tests | pytest, httpx, Playwright (Python) | |

### Component mapping

| Need (from Ravi's list) | Shoelace / markup | Where used |
|---|---|---|
| Radio buttons | `sl-radio-group` + `sl-radio-button` | stack, split, CU/DU vendor, L1, RU, UE, core, direction, iperf mode |
| Toasts / snackbar | `sl-alert` + `.toast()` | every action outcome [GL-04] |
| Tabs | `sl-tab-group` | run detail, config JSON/YAML, O1 FM/PM/CM |
| Accordion | `sl-details` (grouped) | job log, figure data, raw manifest blocks, vendor-only metrics |
| Chips | `sl-tag` | topology, cell config, filters, quality flags, "capped" |
| Bento grid | CSS grid (12 columns) of `sl-card` tiles | Overview |
| Breadcrumbs | `sl-breadcrumb` | every sub-page [GL-03] |
| Confirmation | `sl-dialog` | every state-changing action [GL-07] |
| Status | `sl-badge`, `sl-spinner`, `sl-progress-bar` | status strip, job steps |
| Inputs | `sl-input`, `sl-select`, `sl-switch`, `sl-textarea` | test plan, filters |
| Code / config | `<pre>` with a monospace editor area + `sl-copy-button` | config view, raw tab |
| Tooltips | `sl-tooltip` | disabled reasons, metric caveats |

---

## 4. Visual design

White, quiet, dense enough for measurement data.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#FFFFFF` | page |
| `--surface` | `#F8FAFC` | page sections, table header |
| `--card` | `#FFFFFF` + 1 px `#E5E7EB` border, radius 8 px, no shadow | tiles, panels |
| `--text` | `#111827` | body |
| `--muted` | `#6B7280` | labels, timestamps |
| `--accent` | `#2563EB` | primary buttons, links, focus ring |
| `--ok` | `#16A34A` | pass, done, free |
| `--warn` | `#D97706` | stale data, mixed configs, disabled-with-reason |
| `--bad` | `#DC2626` | failed, error, unreachable |
| `--chip` | `#F3F4F6` | neutral chips |
| Stack colours | from ETHOS `GET /plots/series` (B9) | chips and table accents match the figures |

- Font: the system UI stack; IDs, config_ids and JSON in `ui-monospace`.
- Spacing: a 4 px scale; page padding 24 px; tile gap 16 px.
- Tables: 36 px rows, numeric columns right-aligned with fixed decimals (throughput 2, dB 1, BLER 4), sticky header.
- One primary button per view (RUN, Generate, Confirm). Destructive actions (Stop, Tear down, Detach) use outlined red buttons.

---

## 5. Navigation and page map

| Nav item | Path | Breadcrumb example | Phase |
|---|---|---|---|
| Overview | `/` | — | 1 |
| Test Plan | `/plan` | Test Plan | 1 |
| Jobs | `/jobs`, `/jobs/{job_id}` | Jobs / j-0927-1412 | 1 |
| Results | `/results`, `/results/campaigns/{id}`, `/results/runs/{run_id}` | Results / sweep-0927 / …-DL100M-015 | 1 |
| Graphs | `/graphs`, `/graphs/{figure_id}` | Graphs / full-sweep | 1 |
| Testbed | `/testbed`, `/testbed/ue` | Testbed / UEs | 2 |
| O1 | `/o1/pm`, `/o1/fm`, `/o1/cm` | O1 / CM | 3 |
| O2 | `/o2/nf`, `/o2/deploy-times`, `/o2/energy`, `/o2/dms` | O2 / NF checks | 4 |
| Login | `/login` | — | 1 |

---

## 6. Pages

### 6.1 Overview [OV-01…07]

```
┌ status strip: ● Lock free │ Deployed: none │ UE Samsung: detached │ iperf: Magic iPerf, 5201 held │ ETHOS ● up ┐
│ ┌── Testbed lock ──┐ ┌── Deployed now ─────────────┐ ┌── Running job ───────────────────────┐ │
│ │  FREE            │ │ nothing deployed             │ │ none — [Plan a test]                  │ │
│ └──────────────────┘ └──────────────────────────────┘ └───────────────────────────────────────┘ │
│ ┌── UE ─────────────────────────┐ ┌── Last 5 runs ─────────────────────────────────────────────┐ │
│ │ Samsung · detached · —        │ │ 14:31 OAI CU+OCUDU DU  DL 100→99.99  0.00%  SNR 22.5 dB    │ │
│ │ 5201: app_binary (Magic iPerf)│ │ …                                                          │ │
│ └───────────────────────────────┘ └────────────────────────────────────────────────────────────┘ │
│ ┌── Data freshness ───────────────────────────┐ ┌── Links ───────────────────────────────────┐ │
│ │ throughput ● 2 h   O1 PM ● 5 d   energy ● 31 d│ │ Grafana · Docs · How to reach ETHOS Swagger│ │
│ └─────────────────────────────────────────────┘ └────────────────────────────────────────────┘ │
```

Tiles span 4/4/4, then 4/8, then 6/6 columns. Each tile is an htmx partial with its own refresh, so one slow probe never blocks the page.

### 6.2 Test Plan [TP-01…26]

```
Test Plan
┌ Topology ─────────────────────────────────────┐ ┌ Readiness ────────────────────────┐
│ gNB stack   (•) OCUDU  ( ) OAI                │ │ ✔ Topology valid and deployable   │
│ Split       ( ) Monolithic (•) CU + DU        │ │ ✔ Testbed lock free               │
│   CU        (•) OCUDU  ( ) OAI                │ │ ✔ Nothing else deployed           │
│   DU        ( ) OCUDU  (•) OAI                │ │ ✖ UE Samsung unreachable  [again] │
│ L1          (•) software PHY ( ) Aerial cuBB ⓘ│ │ ✔ iperf: 5201 held by Magic iPerf │
│ RU          (•) Pegatron ( ) Foxconn ⓘ ( ) TM500ⓘ│ ✔ Traffic plan valid              │
│ UE          (•) Samsung ( ) MTK ( ) Dongle ( ) TM500ⓘ ✔ Core reachable             │
│ Core        (•) Open5GS ( ) free5GC ⓘ         │ │                                   │
│ config_id   ocuducu-oaidu_swphy_pega_samsung_o5gs_joule (read-only) │ [ RUN ] (disabled: │
└───────────────────────────────────────────────┘ │  UE Samsung unreachable)          │
┌ Traffic ──────────────────────────────────────┐ └───────────────────────────────────┘
│ Direction (•) DL ( ) UL                       │
│ Offered   [100-1000:100]  [range builder ▾]   │   Estimated time: 1 h 12 min
│ Duration  [30s]     Repeats [1] (n ≥ 5 for papers)
│ iperf     (•) Magic iPerf ( ) ETHOS server    │
│ Label     [sweep-0927]   ☐ radio samples (debug)
└───────────────────────────────────────────────┘
[Show config ▸]  →  sl-tab-group: JSON | YAML   (editable; validated by ETHOS)
[Save plan] [Load plan ▾] [Download .json] [Download .yaml] [Upload]
```

- Disabled options carry an `ⓘ` tooltip with ETHOS's reason, e.g. "No deploy profile yet" for Foxconn.
- The readiness panel stays visible (sticky) while scrolling.
- The RUN button sits at the bottom of the readiness panel, so the reason it is disabled is always next to it.

### 6.3 Job page [RN-02…08]

```
Jobs / j-0927-1412            ● running   ocudu-mono · DL · 10 points · started 14:12 · 7 min
Cell: [n78] [100 MHz] [4T4R] [30 kHz] [7D2U]                                   [ Stop ]
┌ Steps ─────────────────────────┐ ┌ Completed points ───────────────────────────────────────┐
│ ✔ Preflight        4 s         │ │ offered achieved loss  jitter RTTp95 CQI RI    MCS  SNR BLERres│
│ ✔ Deploy          52 s         │ │ 100 M   99.99   0.00  0.23   18.9   14 4/1 27/24 30.1 0.0000│
│ ✔ Attach          11 s         │ │ 200 M  199.99   0.00  …                                   │
│ ● Point 3 of 10  (300 M, 18 s) │ │                                                           │
│ ○ Points 4–10                  │ └────────────────────────────────────────────────────────────┘
│ ○ Detach, Teardown             │  ▸ Log (accordion)
└────────────────────────────────┘
```

### 6.4 Results [RS-01…05]

A filter bar of chips above a sortable table, with a row-selection column. Selected rows enable "Compare", "Graph", "Export CSV". The "show unusable runs" switch is on the right of the filter bar.

### 6.5 Run detail [RS-06…12]

Header: run id (monospace, copy button), topology chip, cell-config chips, status badge.
Tabs: **Summary · Channel conditions · Latency · Cell config · Config · Raw** (+ **Samples** when present).

The Channel conditions tab has two parts:

- **Comparable across stacks** (always open): PUSCH SNR (mean / min / max / p95), residual BLER DL / UL (mean / max), CQI, RI DL / RI UL, MCS DL / UL with table and cap, sample count.
- **Vendor-specific** (`sl-details`, collapsed): first-transmission BLER, PUCCH SNR, UE L1-RSRP (OAI); timing advance, buffer status (OCUDU); UE-reported SS-RSRP / RSRQ / SINR from Android; RRC SS measurements (OAI).

Each metric label follows requirements §7.4 exactly, with a tooltip for its caveat.

### 6.6 Sweep view [RS-13…16]

The same table layout as the job's completed-points table, one row per offered load (repeats collapsed to mean and n, expandable). The header row of each metric column has a small "Plot" link that opens Graphs with this sweep and that metric preselected.

### 6.7 Graphs [GR-01…09]

Left: the request form (source: runs / sweep / filter; metric; kind; group by; width; label).
Right: the figure as PNG, a warning bar if the inputs are mixed [GR-09], download buttons (PNG, PDF), and a "Data" accordion with the manifest.
Below: the gallery as a card grid.

### 6.8 Testbed (Phase 2), O1 (Phase 3), O2 (Phase 4)

These follow the same patterns: status tiles at the top, a table or form below, every action through a confirmation dialog, all read paths through ETHOS. Layout details are fixed when each phase starts, against the ETHOS endpoints as they exist then.

---

## 7. Logic

### 7.1 Readiness evaluation [TP-23…26]

1. Selection or traffic plan changes → wait 500 ms (debounce) → `POST /readiness` with the full plan.
2. ETHOS returns a list of checks, each with `id`, `status` (`pass | fail | unknown`), `reason`, `checked_at`.
3. The panel renders them in ETHOS's order. **RUN is enabled only if every check is `pass`**; `unknown` counts as not passing.
4. While the page is open, readiness re-runs every 10 s, so RUN reacts to the lock being taken or released elsewhere.

The console adds no checks of its own. If a check is missing, the fix is in ETHOS (B5).

### 7.2 Starting a job [TP-25, RN-01]

1. RUN → `POST /jobs/preview` with the plan.
2. ETHOS returns the preview text and a `preview_token`. The token is a hash of the plan plus the testbed state it was computed against.
3. The console shows the preview in a dialog. Confirm → `POST /jobs` with the plan, `confirm: true` and the token.
4. ETHOS rejects the start with 409 if the lock was taken, or with 412 ("state changed since preview") if the testbed changed after the preview. The console shows the reason as a toast and refreshes readiness.
5. On success, ETHOS returns `job_id`; the console navigates to `/jobs/{job_id}`.

The same preview → confirm-with-token flow applies to deploy, teardown, attach, detach, stopping Magic iPerf, and CM apply.

### 7.3 Job states

```
created → preflight → deploying → attaching → running(point i of N)
        → detaching → tearing_down → completed

any state ──error──────────────► failed      (teardown still attempted; result recorded)
running  ──stop requested──────► stopping → detaching → tearing_down → aborted
any state ──service restarted──► interrupted (on ETHOS startup)
```

Terminal states: `completed`, `failed`, `aborted`, `interrupted`. The console renders the state from ETHOS's snapshot and events; it never infers a state itself.

### 7.4 Live updates

- **Job page:** SSE. The console opens `GET /jobs/{id}/events` on ETHOS and relays each event to the browser through `console/sse.py`. Every event carries a sequence number as its SSE `id`; after a reconnect, the browser sends `Last-Event-ID` and the stream resumes, with no duplicates or gaps [RN-07].
- **Status strip and Overview tiles:** htmx polling of the console's `/partials/status` every 5 s; the console fetches `GET /status/summary` from ETHOS [ST-02]. Polling is simpler than SSE here and costs one small request.
- **Job finished toast on any page [RN-11]:** the status poll includes the latest job's state; when a job the browser saw running becomes terminal, the page shows the toast.

### 7.5 Errors

| ETHOS response | Console behaviour |
|---|---|
| 409 (lock held, job running) | amber toast naming the holder; controls disabled until the next status poll |
| 412 (state changed since preview) | amber toast; readiness re-run; the dialog closes |
| 422 (validation) | inline error under the field or config editor; toast only if the field isn't visible |
| 5xx | red toast with ETHOS's message and the request id; logged |
| timeout or connection refused | red banner "ETHOS API unreachable"; all actions disabled [ST-04] |

---

## 8. Console ↔ ETHOS contract

All calls live in `console/rapps/ethos/client.py`. "New" means added by the listed backend change.

| Console feature | ETHOS endpoint | Status |
|---|---|---|
| Option lists with deployability | `GET /catalogue` | new (B4) |
| Validate a selection | `POST /validate` | existing |
| Generate / validate / edit a test definition | `POST /testdef/generate`, `POST /testdef/validate`, `GET/PUT /testdef/{config_id}` | existing |
| Readiness | `POST /readiness` | new (B5) |
| Start a job | `POST /jobs/preview`, `POST /jobs` | new (B2, B3) |
| Job snapshot, list, events, stop | `GET /jobs/{id}`, `GET /jobs`, `GET /jobs/{id}/events`, `POST /jobs/{id}/stop` | new (B2) |
| Lock holder | `GET /lock` | new (B1) |
| Status strip and Overview | `GET /status/summary` | new (B6) |
| Run table and CSV | `GET /runs` (filters extended), `GET /runs.csv` | extended (B10) |
| Run detail | `GET /runs/{run_id}` (includes `cell_config`, `radio_summary`, `latency`) | existing |
| Run samples | `GET /runs/{run_id}/radio-samples` | new (B10) |
| Sweep view | `GET /campaigns/{id}/summary` | new (B10) |
| Figures | `POST /plots`, `GET /plots`, `GET /plots/{id}`, `GET /plots/{id}/image.png`, `…/figure.pdf`, `GET /plots/series` | new (B9) |
| Deploy / teardown (Phase 2) | `POST /deploy/preview`, `POST /deploy`, `POST /teardown/preview`, `DELETE /deploy` | extended (B3) |
| UEs (Phase 2) | `GET /ue`, `POST /ue/{ue}/attach|detach` (+ preview), `GET /ue/{ue}/iperf`, `POST /ue/{ue}/iperf/stop` | new (B11) |
| O1 (Phase 3) | `GET /o1/freshness`, `GET /o1/alarms`, existing `/cm/*` and `/runs/{id}/o1-pm` | new + existing (B12) |
| O2 (Phase 4) | `GET /o2/nf`, `GET /o2/deploy-times`, `GET /o2/energy/freshness`, `GET /o2/dms/*` | new (B13) |

ETHOS Swagger stays on loopback. The Overview's "How to reach ETHOS Swagger" link opens a short help panel with the tunnel command:

```
ssh -L 8081:127.0.0.1:8081 oai-gnb@192.168.8.78    # then open http://127.0.0.1:8081/docs
```

---

## 9. Status sources

| Indicator | Source (via `GET /status/summary`) | Refresh |
|---|---|---|
| Lock | lock file holder (B1) | 5 s |
| Deployed topology | `/deploy/status` + Helm releases in `ravi-ns` | 5 s |
| Running job | job store (B2) | 5 s; SSE on the job page |
| UE state | UE driver status for the selected UE | 15 s (it costs an SSH round trip) |
| iperf server | `server_identity()` (`execution/traffic_launcher.py`) | 15 s |
| ETHOS API | the summary call itself | 5 s |
| Data freshness | last point per measurement in InfluxDB | 60 s |

Each indicator in the summary carries its own `checked_at` and `error`, so one failed probe shows as "unknown" without failing the rest [ST-01, ST-03].

---

## 10. Security

- **TLS:** a self-signed certificate for `192.168.8.78`, made by `deploy/make-cert.sh` (openssl, 825-day validity, SAN `IP:192.168.8.78`). The browser warns once; add the certificate to your laptop's trust store to silence it.
- **Password:** argon2id hash in `console.env` as `CONSOLE_PASSWORD_HASH`. Set it with `.venv/bin/python -m console set-password`, which prompts twice and writes the hash; the plain password is never stored or logged.
- **Session:** a signed cookie, `HttpOnly`, `Secure`, `SameSite=Strict`, secret from `CONSOLE_SESSION_SECRET` (32 random bytes). Absolute timeout 12 h, idle timeout 2 h [SE-04].
- **CSRF:** a per-session token in a `<meta>` tag; htmx sends it as the `X-CSRF-Token` header on every non-GET; the server rejects a missing or wrong token [SE-08].
- **Rate limit:** 5 failed logins in 10 minutes → login refused for 10 minutes, tracked in memory [SE-05].
- **Headers:** `Content-Security-Policy: default-src 'self'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- **Logging:** actions are logged with ETHOS's response code, never request bodies containing config files, never the cookie.

---

## 11. Configuration

`console.env` (git-ignored; `console.env.example` committed):

| Variable | Example | Meaning |
|---|---|---|
| `CONSOLE_BIND` | `0.0.0.0` | listen address |
| `CONSOLE_PORT` | `8443` | HTTPS port |
| `CONSOLE_TLS_CERT` / `CONSOLE_TLS_KEY` | `~/.config/testbed-console/tls/console.crt` / `.key` | TLS files |
| `CONSOLE_PASSWORD_HASH` | `$argon2id$…` | set by `set-password` |
| `CONSOLE_SESSION_SECRET` | 64 hex chars | cookie signing |
| `CONSOLE_ETHOS_URL` | `http://127.0.0.1:8081` | ETHOS API |
| `CONSOLE_PLANS_DIR` | `~/testbed-console-data/plans` | saved test plans (outside the repo) |
| `CONSOLE_GRAFANA_URL` | `http://192.168.8.69:30489` | link only |
| `CONSOLE_TZ` | `Asia/Taipei` | display time zone |

---

## 12. Deployment

`deploy/testbed-console.service` (user unit):

```
[Unit]
Description=Testbed Console & Dashboard
After=network.target ethos-rapp.service

[Service]
Type=simple
WorkingDirectory=/home/oai-gnb/testbed-console
EnvironmentFile=/home/oai-gnb/testbed-console/console.env
ExecStart=/home/oai-gnb/testbed-console/.venv/bin/python -m console serve
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

`python -m console serve` starts uvicorn with the TLS files, bind address and port from `console.env`. Enable linger once (`loginctl enable-linger oai-gnb`) so the service survives logout; skip it if it's already on (`loginctl show-user oai-gnb -p Linger`). If the KVM's firewall filters inbound traffic, port 8443/tcp must be opened for 192.168.8.0/24.

---

## 13. Testing approach

- **fake_ethos:** a small FastAPI app in `tests/fake_ethos/` that serves recorded ETHOS responses from `tests/recorded/`. It can simulate a job emitting SSE events, the lock being held, a 412 after a preview, and ETHOS being down. All automated console tests run against it, without the testbed [NF-07].
- **Recording:** a script, `tests/record.py`, calls the real ETHOS read-only endpoints and saves the responses, so fixtures match the real API and are refreshed when ETHOS changes.
- **Unit tests:** the ETHOS client (error mapping, timeouts), auth (hash, session expiry, rate limit, CSRF), plans (save / load / validate), and template rendering of the metric display rules [§7.4 of requirements].
- **E2E (Playwright):** login; Test Plan gating (RUN disabled with the reason, then enabled); config edit round-trip; start → live steps → stop → aborted; refresh mid-job resumes; two tabs, the second refused with the holder named; results filter → CSV; graph request → PNG download.
- **On the testbed:** the acceptance steps for each phase in `04-build-plan.md`.