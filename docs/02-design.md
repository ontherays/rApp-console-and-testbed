# Testbed Console & Dashboard, Design

Companion to `01-requirements.md` (requirement IDs in brackets refer to it).
ETHOS-side changes are specified in `03-ethos-backend-changes.md` as B1–B15.

---

## 1. Architecture

```
 browser (lab LAN)
    │  HTTPS :8443, session cookie
    ▼
 Testbed Console : FastAPI + Jinja2, systemd user service "testbed-console"
    │  ├─ pages (server-rendered HTML, htmx swaps, SSE relay)
    │  ├─ auth (one password, sessions, CSRF)
    │  └─ rapps/ethos/client.py  ← the ONLY code that talks to ETHOS
    │  HTTP over loopback
    ▼
 ETHOS API  127.0.0.1:8081 , systemd user service "ethos-rapp"
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

A light grey canvas with white cards floating on it. Large numerals for the
values that matter, small muted labels around them, and enough density that a
table of measurements still reads as measurement data.

**Colour is never the only signal.** Every coloured chip also carries text or an
icon, every change chip carries an arrow and a word, and every status dot sits
beside its label, so a state survives greyscale and colour blindness.

| Token | Value | Use |
|---|---|---|
| `--canvas` | `#F2F2F2` | the page behind everything |
| `--card` | `#FFFFFF`, radius 14 px, `0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)` | every panel; no borders, a very soft shadow instead |
| `--line` | `#EAEAEA` | dividers inside a card, table rules |
| `--text` | `#16181D` | body |
| `--muted` | `#6B7280` | secondary text |
| `--faint` | `#9AA1AC` | labels, timestamps, units |
| `--accent` | `#2563EB` | the one primary button per page, links, focus ring |
| `--ok` / `--warn` / `--bad` | `#15803D` / `#B45309` / `#DC2626` | pass, caution, failure, always with a word |
| Stack colours | from `plotting/series.py`, replaced by `GET /plots/series` (B9) | chips, legend swatches, initials tiles |

**Icon tiles.** Every KPI card, every page header and every topology row carries
a 32 px rounded tile (radius 9 px) in its own muted accent: blue `#2F6FED` on
`#E8F0FF`, orange `#D9822B` on `#FDF0E2`, teal `#0F9B8E` on `#E3F6F3`, purple
`#7C5CFC` on `#EFEBFF`, red `#DC2626` on `#FDEAEA`, slate `#55606F` on `#EEF1F5`.
The tile is what makes a row scannable; the colour carries no meaning on its own.

**Type scale.** Page title 26 px/600, section 16 px/600, card title 15 px/600,
body 13.5 px, label 13 px/500, eyebrow 11 px/600 uppercase, and the numerals:
34 px/600 with `-0.03em` tracking for a KPI, 22 px for a smaller one. IDs,
config_ids and JSON in `ui-monospace`.

**Spacing.** A 4 px scale. 16 px between cards, 20 px inside one, 24 px for a
page section. Radius 14 px on cards, 10 px on controls and tiles, 999 px on chips.

**Grouping.** Related cards share one rounded container with 1 px dividers
between them rather than floating separately, the Overview's KPI row is one
card holding six, which reads as one row of facts instead of six objects.

**Tables.** 13 px, rows about 40 px, numeric columns right-aligned with tabular
figures and fixed decimals (throughput 2, dB 1, BLER 4), sticky header on
`#FBFBFC`, no vertical rules. A cell may carry a small muted sub-line under its
value, a count under a bar, a config_id under a label.

**Icons.** One set, drawn for this console: 24 px grid, 1.5 px stroke, round
joins, `currentColor`, in the flat line style of O-RAN architecture diagrams.
`docs/design/icons.md` shows every one. Vendors get a wordmark rather than their
logo, for the reasons in `console/vendors.py`.

**No em dash.** Not in a template, not in a Python string that reaches the
screen, not in this folder. A comma, a colon, a full stop or brackets. The "not
measured" marker is the word `n/a`, which also settles GL-09's spelling of it.

**Selected state.** An option's highlight comes from its own `:checked` state in
CSS, never from a class the server wrote: most groups sit in cards the form does
not re-render, so a written class would stay on the option that was selected
when the page loaded.

**Buttons.** One blue primary per page. Secondary buttons are white with a
`#DEDEDE` border; destructive ones are white with a red border and red text.
A disabled control keeps its shape and gains a tooltip saying why.

---

## 5. Navigation and page map

The sidebar groups the four things the console does: plan a test, read what came
out, look after the testbed, and read the documentation.

| Group | Nav item | Path | Breadcrumb example | Phase |
|---|---|---|---|---|
| Essentials | Overview | `/` |, | 1 |
| Essentials | Test Plan | `/plan` | Test Plan | 1 |
| Essentials | Jobs | `/jobs`, `/jobs/{job_id}` | Jobs / j-0927-1412 | 1 |
| Measure | Results | `/results`, `/results/campaigns/{id}`, `/results/runs/{run_id}` | Results / sweep-0927 / …-DL100M-015 | 1 |
| Measure | Graphs | `/graphs`, `/graphs/view/{date}/{folder}` | Graphs / full-sweep | 1 |
| Network | Testbed | `/testbed` | Testbed | 2 |
| Network | O1 | `/o1` | O1 | 3 |
| Network | O2 | `/o2` | O2 | 4 |
| System | Docs | `/docs`, `/docs/{slug}` | Documentation / Requirements | 1 |
|, | Search | `/search?q=` | Search | 1 |
| (| Login | `/login` |) | 1 |

---

## 6. Pages

Every page is built from the same three parts: a **page header** (icon, title,
breadcrumbs, actions, filters, status strip), one or more **cards**, and tables
or forms inside them.

### 6.0 The shell

**Sidebar**: a white card on the canvas, sticky, full height. Top to bottom:
the brand; a search box with a `/` shortcut that finds a run_id, a config_id or
a campaign; then collapsible groups with small muted headings:

| Group | Items |
|---|---|
| Essentials | Overview, Test Plan, Jobs |
| Measure | Results, Graphs |
| Network | Testbed *(Phase 2)*, O1 *(Phase 3)*, O2 *(Phase 4)* |
| System | Docs |

Each item has an icon. A badge appears only where it counts something real:
"new runs since your last visit" on Results today, running jobs once B2 lands,
active alarms once B12 does. **A badge is never shown as 0**, a zero beside
Jobs would read as "nothing is running" on a console that cannot tell.

At the foot, a **backend-readiness card**: "ETHOS backend, n of 6 ready" over
B1, B2, B4, B5, B6 and B9, with a progress ring, the next change named, and a
link to `docs/ethos-backlog.md`. It fills in by itself as the capability probe
finds each endpoint.

**Page header**: the page's icon tile and title on the left, breadcrumbs above
it where there is a hierarchy. On the right: a notification bell, a secondary
**Export** where the page has data, and at most **one blue primary button**
("New test" on Overview, Results, Jobs and Graphs). Filters sit below the title,
and the status strip (ST-01…04) runs along the bottom of the header on every
page.

### 6.1 Overview [OV-01…07]

Two segmented controls: the period (**24 hours / 7 days / 30 days**) and the
subset (**All runs / DL / UL / Needs attention**, the last with a red dot when
any run in the archive carries a quality flag).

**KPI row**: six cards in one container, each with its icon tile, a large
numeral, and a change chip against the *previous period of the same length*:
testbed lock, deployed now, runs in the period, best DL at 1000 M, median PUSCH
SNR, and data freshness. A comparison with no previous period says "no previous
run" rather than showing a change against nothing.

**Runs by topology**: a honeycomb with one hexagon per run in the period,
coloured by stack in the figure colours, on a grey grid of empty cells; the size
of the coloured area is itself the count. Below it, one legend row per topology
with its share and run count. Two config_ids can carry the same label, OCUDU
monolithic with a Samsung and with an MTK UE, so an ambiguous row shows its
config_id underneath.

**Throughput over time**: a dot-matrix column chart of the best
`achieved_over_tx_mbps` of each day, with a chip naming the source
(`from run.json`). **A day with no run is an empty column, not a zero.**

**Topologies that need you**: least complete first: a coloured initials tile
per topology (a unique two-letter code per stack head), its config_id, a chip
for the last state, the run count, a tick-style bar of points delivered against
planned for its latest sweep, the best DL at 1000 M with a change chip, when it
last ran, and a **Review** button opening that sweep.

Below: running job and UE tiles naming their backend change, and links.

**Charts are inline SVG rendered on the server, with no chart library.** They
are operational summaries, counts and trends. Measurement figures still come
only from ETHOS's plotting package on the Graphs page: a chart library in the
browser would produce a second, differently-styled rendering of numbers already
archived with their manifest.

### 6.2 Test Plan [TP-01…26]

Two columns: the form on the left, saved plans on the right.

**Topology** card: gNB stack, split, CU and DU vendor, L1, RU, UE, core, server
each a row of selectable chips showing the catalogue's **label**, never its
slug. An option that cannot be deployed is dimmed with the reason on hover.

**CU and DU vendor follow the split.** With *Monolithic* selected both groups are
disabled and show the gNB stack's own value, with the tooltip "Monolithic runs
CU and DU in one process of the gNB stack". Choosing *CU + DU* makes both
selectable, defaulting to the stack's vendor, opening a split must not silently
propose a cross-vendor F1 nobody asked for. Setting them to different vendors
selects one of the cross-vendor splits. The groups are re-rendered by the same
request that re-resolves the plan and swapped in out of band, so the gating
stays on the server.

**Traffic** card: direction, offered load, duration, repeats, iperf mode, label,
radio samples. Then **Identity** (the config_id ETHOS generated, read-only),
**Readiness** (all seven checks, with RUN below naming its first blocker),
**Run it** (the campaign command for this plan), the config view, and save.

### 6.3 Jobs [RN-01…11]

The gated explanation of B2, then the campaigns the run archive knows about,
each row with its initials tile, topologies, counts, span and a **Review**
button. The live job page arrives with B2.

### 6.4 Results [RS-01…05]

A filter card of selects and toggles, then one card holding the run table with a
selection column, sortable headers, and paging. Selected rows go to **Compare**.
**Export** in the page header downloads the filtered set as CSV.

### 6.5 Run detail [RS-06…12]

The run id and its chips in the page header, a copy row, then tabs: **Summary ·
Channel conditions · Latency · Cell config · Config · Raw** (+ **Samples** when
present). Channel conditions keeps §7.4 exactly: comparable metrics always open,
vendor-specific and handset-reported collapsed beneath.

### 6.6 Sweep view [RS-13…16]

One row per offered load with repeats collapsed to a mean and an n, expandable
to the runs. An amber banner when the runs do not share one cell configuration.

### 6.7 Graphs [GR-01…09]

The gated request form, then the gallery as cards. A figure's own page shows the
image, PNG and PDF in the header, its warnings as a banner, and its manifest.

### 6.8 Search

Reached from the sidebar or by pressing `/`. An exact run_id goes straight to
that run; anything else lists matching configurations, campaigns and runs.

### 6.9 Testbed (Phase 2), O1 (Phase 3), O2 (Phase 4)

Each says what it will show, with its requirement ids, the backend change it
waits for, and where things stand today.

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