# Testbed Console, running guide

Install, configure, run and use the console on the KVM host (`oai-gnb-KVM`,
192.168.8.78). Every command below was run on that host on 2026-09-30 and the
output shown is what it returned.

The console **presents** the testbed. ETHOS is the component that touches it,
and the console reaches ETHOS over loopback, so no credential (the InfluxDB
token, the SSH keys, the SDNC password) is ever held here or sent to a browser.

```
browser (lab LAN) ──HTTPS :8443, one password──► Testbed Console
                                                      │ HTTP over loopback
                                                      ▼
                                                 ETHOS API 127.0.0.1:8081
                                                      │
                                    SSH · kubectl · adb · InfluxDB · SDNC
```

Two consequences follow from that split, and they explain most of what the
console does:

- The console runs nothing. Deploys, traffic, captures and figures all happen
  inside ETHOS, driven by the same API the ETHOS CLI drives.
- A feature ETHOS has not built yet is a **disabled control that names the
  backend change it needs**, never a button that fails on click.
  `docs/ethos-backlog.md` is the full list.

---

## 1. Is it already running?

```bash
systemctl --user is-active testbed-console ethos-rapp
```

```
active
active
```

Both active: go to §5. Console inactive: §2 to §4. ETHOS inactive: the console
still serves, but every page reports it unreachable and every control that acts
is disabled.

---

## 2. Install

Python 3.12 and `openssl` are already on this host.

```bash
cd ~/testbed-console
python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
```

`requirements.txt` holds exact pins; `pyproject.toml` holds the loose ranges
they satisfy. Install the pins for a reproducible environment.

---

## 3. Configure

### 3.1 The certificate

The console serves HTTPS only. One self-signed certificate, valid for this
host's LAN address:

```bash
./deploy/make-cert.sh 192.168.8.78
```

```
subject=CN = 192.168.8.78, O = BMW Lab Testbed Console
notBefore=Sep 27 12:08:20 2026 GMT
notAfter=Dec 30 12:08:20 2028 GMT
X509v3 Subject Alternative Name:
    IP Address:192.168.8.78, IP Address:127.0.0.1, DNS:localhost

Put these in console.env:
  CONSOLE_TLS_CERT=/home/oai-gnb/.config/testbed-console/tls/console.crt
  CONSOLE_TLS_KEY=/home/oai-gnb/.config/testbed-console/tls/console.key
```

The browser warns once on the first visit because nothing signed this
certificate. To silence the warning, add `console.crt` to your laptop's trust
store. The key is `chmod 600` and lives outside the repository; `*.crt` and
`*.key` are git-ignored.

### 3.2 The environment file

```bash
cp console.env.example console.env
chmod 600 console.env
```

Then edit it: the TLS paths from §3.1, and the password hash from §3.3.
`console.env` is git-ignored because it holds the password hash and the session
secret. Two rules about its format, both of which have broken this service once:

- **A comment goes on its own line, above the variable.** systemd's
  `EnvironmentFile=` keeps a trailing `# comment` as part of the value, so
  `CONSOLE_LOG_LEVEL=info  # the level` makes uvicorn refuse to start with
  `KeyError: 'info  # the level'`. A test enforces this on the example file.
- **A blank is `KEY=""`, never bare.** Empty means unset, which means the
  documented default or the documented refusal.

The real environment always wins over this file, so a systemd `Environment=`
line or a shell `export` overrides it.

`console.env.example` declares every `CONSOLE_*` variable the code reads. A test
compares the example against the code in both directions, so the example is
always the complete list.

### 3.3 The password

One password, stored only as an argon2id hash. The plain password is never
written to a file, never logged, and never echoed back to the browser.

```bash
.venv/bin/python -m console set-password
```

It prompts twice and prints the line to paste into `console.env`. Restart the
service afterwards (§4).

### 3.4 Check what the console resolved

```bash
.venv/bin/python -m console check
```

```
console.env: applied 17, kept 0 already in the environment
bind            0.0.0.0:8443
ethos           http://127.0.0.1:8081
tls             ready
login           configured
plans           /home/oai-gnb/testbed-console-data/plans
deploy profiles /home/oai-gnb/ravi-ethos-rApp/deployment/deploy_profiles.yaml
time zone       Asia/Taipei

no problems found
```

"applied 17, kept 0" counts names, never values. Anything missing is listed
under `problems:` with the command that fixes it.

---

## 4. Run it as a service

```bash
cp deploy/testbed-console.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now testbed-console
```

So the service survives logout, linger must be on. It is:

```bash
loginctl show-user oai-gnb -p Linger
```

```
Linger=yes
```

This applies to every user service, so `ethos-rapp` survives logout too.

Day to day:

```bash
systemctl --user status testbed-console       # is it up
systemctl --user restart testbed-console      # after editing console.env or the code
systemctl --user stop testbed-console         # take it down
journalctl --user -u testbed-console -n 100   # its log
journalctl --user -u testbed-console -f       # follow it
```

```
● testbed-console.service - Testbed Console & Dashboard
     Loaded: loaded (/home/oai-gnb/.config/systemd/user/testbed-console.service; enabled; preset: enabled)
     Active: active (running) since Wed 2026-09-30 20:57:27 CST; 32min ago
       Docs: file:///home/oai-gnb/testbed-console/docs/running-guide.md
   Main PID: 76983 (python)
```

**Restarting the console never disturbs a campaign**: it holds no testbed
state, starts no traffic and runs no job. Restarting `ethos-rapp` does, so check
no campaign is running first and say so.

---

## 5. Reach it

From your laptop on the lab LAN:

```
https://192.168.8.78:8443
```

Accept the certificate warning once, then log in with the password from §3.3.

Checks from a shell on the host:

```bash
curl -sk -o /dev/null -w 'HTTP %{http_code}\n' https://127.0.0.1:8443/login
curl -s  -m 5 -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8443/login
```

```
HTTP 200
HTTP 000
```

The second is 000 because nothing answers on plain HTTP, which is the intent.
An unauthenticated page redirects rather than serving:

```bash
curl -sk -o /dev/null -w 'HTTP %{http_code} -> %{redirect_url}\n' https://127.0.0.1:8443/
```

```
HTTP 303 -> https://127.0.0.1:8443/login?reason=please+log+in
```

The console reports its own health without authentication, and reports itself
healthy even when ETHOS is down:

```bash
curl -sk https://127.0.0.1:8443/healthz
```

```
{"status":"ok","service":"testbed-console","ethos_url":"http://127.0.0.1:8081"}
```

Five wrong passwords in ten minutes stop login for ten minutes. A session ends
12 hours after login, or after 2 hours of inactivity, and says which.

### Without opening the LAN

Set `CONSOLE_BIND=127.0.0.1`, restart, and from your laptop:

```bash
ssh -N -L 8443:127.0.0.1:8443 oai-gnb@192.168.8.78
# then open https://127.0.0.1:8443
```

The certificate already covers `127.0.0.1`. The login still applies; the tunnel
replaces the LAN exposure, not the authentication.

### If the LAN address does not answer

```bash
ss -lntp | grep 8443
```

```
LISTEN 0      2048         0.0.0.0:8443       0.0.0.0:*    users:(("python",pid=76983,fd=7))
```

If it listens but your laptop cannot connect, a firewall on this host is
filtering it. Open the port for the lab subnet only:

```bash
sudo ufw allow from 192.168.8.0/24 to any port 8443 proto tcp
```

---

## 6. The pages

| Page | What it does |
|---|---|
| **Overview** | Pick a period (24 hours / 7 days / 30 days) and a subset (all runs / DL / UL / needs attention). Six KPI cards with their change against the previous period; a honeycomb of one hexagon per run coloured by topology; the best throughput of each day as a dot-matrix chart; and "topologies that need you", least complete first, each with a Review button onto its latest sweep. The lock, deployed, latest-job, UE and freshness tiles come from `GET /status/summary`, each with its own timestamp, so a probe that failed inside ETHOS greys out one tile and no more. |
| **Test Plan** | Builds one test. The topology is a summary card with **Change topology** opening a side panel: **Presets**, one card per wired deploy profile; and **Custom**, every component as a group of cards, undeployable options greyed out with the reason. CU and DU vendor follow the split: monolithic disables both, CU + DU makes both selectable. Readiness is in the right-hand column with RUN at its foot. The seven checks are ETHOS's own, from `POST /readiness`: a failure disables RUN and names itself, while a check ETHOS could not make is surfaced as unknown and does not block. RUN asks ETHOS for a preview and only confirming it starts the job. |
| **Jobs** | Every job ETHOS knows about, newest first, then the campaigns in the run archive grouped by `campaign_id`, then the sweeps held out of graphs. A job's own page shows its steps, its points as each finishes, and its live log; **Stop** asks it to stop at the next point boundary, behind a confirmation. The log survives a refresh: each event carries a sequence number and the browser resumes from the last one it saw. §8 covers holding a sweep out and restoring it. |
| **Results** | Every archived run, with filters, sortable columns, CSV export of the filtered set, and a detail page per run: Summary, Channel conditions, Latency, Cell config, Config, Raw. Runs that cannot be analysed are hidden behind a toggle. |
| **Sweep / Compare** | One row per offered load with repeats collapsed to a mean and an n, expandable to the individual runs. Amber warning when the runs do not share one cell configuration. |
| **Graphs** | Asks ETHOS for a figure and lists the ones that exist. §7 is the workflow. |
| **Search** | In the sidebar, or press <kbd>/</kbd> anywhere. An exact run id opens that run; anything else lists matching configurations, campaigns and runs. |
| **Testbed** | The testbed's UEs with driver, control path, state, address and who holds port 5201, and **Attach**, **Detach** and **Free 5201** for each one ETHOS drives, every one behind a dialog showing ETHOS's own preview. Below that, what is deployed. Deploying on its own is deliberately not offered: RUN already deploys what its plan needs and tears it down. |
| **O1 / O2** | What each will show, its requirement ids, and where things stand. |
| **Docs** | These documents, served from `docs/`. |

The sidebar's foot shows **ETHOS backend: n of 6 ready**, counting B1 (lock),
B2 (jobs), B4 (catalogue), B5 (readiness), B6 (status summary) and B9 (figures).
All but B4 answer today, so it reads 5 of 6. The capability probe runs every 60
seconds, so an endpoint that disappears in a rollback disables the controls that
need it rather than letting them fail on click.

The charts on the Overview are drawn as SVG by the console itself. They are
operational summaries, counts and trends. **Paper figures come only from ETHOS's
plotting package**, on the Graphs page.

### Reading the numbers

- **Achieved throughput is `achieved_over_tx_mbps`.** It is the only throughput
  compared across stacks; the gNB's own MAC bitrate (OCUDU) and application
  goodput (OAI) differ by header overhead.
- **A value that was not measured shows `n/a`, never 0.** A stack that has no
  such counter and a counter that was not measured are both absences.
- **BLER is always qualified.** "Residual BLER" is what survived HARQ and both
  stacks report it. "First-transmission BLER" is OAI-only, read 0.46 on an idle
  link whose residual BLER was 0, and never shares a column with it.
- **Only PUSCH SNR is compared across stacks.** PUCCH SNR is a different channel.
- **Four things are called RSRP** and are four separate fields. OCUDU's
  `gnb_ul_rsrp_db` is *relative* dB, not dBm: it reads about −11 where the dBm
  values read −69.
- **MCS carries its table and its cap.** OCUDU clamps at 27 DL / 24 UL and sits
  on the cap under load; OAI sets no cap. A value at the cap is marked "capped".
- **The TDD pattern is on every result.** OCUDU runs 7D2U over 5 ms and OAI
  DDDSU over 2.5 ms, so a comparison between them is partly a comparison of two
  TDD configurations.
- **No EE-KPI is shown anywhere.** O-Cloud power (`ocloud_power`) has had no
  point since 2026-08-27, so every value would be null with a reason.

---

## 7. Making a figure

### 7.1 The vocabulary

These four are not interchangeable, and the Graphs page uses each for a
different thing.

| Term | What it identifies | Where it comes from |
|---|---|---|
| **Run** / `run_id` | One measurement: one offered load, one direction, one repetition. `20260929T0757Z-ocudu-mono_..._joule-DL100M-092` | ETHOS mints it; it is the identity the archive, InfluxDB, every figure and the published results all key on. |
| **Job** / `job_id` | One execution: a sweep the console or the CLI started. `j-20260929T075656Z` | ETHOS's job record. A job knows its runs; a run does not know its job. |
| **Campaign** / `campaign_id` | A label grouping runs by intent. | An optional field on a run, set by hand. Jobs do not set it, so most runs have none. The Jobs page groups whatever carries one. |
| **Quarantined job** | A sweep held out of normal graph generation. | An entry in ETHOS's quarantine record. §8. |

A job contributes the runs that **produced a measurement**. A sweep also creates
one run it never measures, so the picker shows two numbers, for example
`10/11 runs`: ten are plottable, eleven exist. Figures are drawn from the ten.

### 7.2 The workflow

```
Time range  (Since / Until)
    ↓
Sweeps      (tick the jobs that ran in that window)
    ↓
Job → runs  (ETHOS resolves each job to its plottable run ids, unioned)
    ↓
Filters     (metric, kind, grouping, width, scale, which runs are allowed in)
    ↓
Generate
```

**Time range.** Since and Until are `YYYY-MM-DD`. Changing either re-lists the
sweeps below without reloading the page. Both bounds are inclusive when
filtering the sweep list.

**Sweeps.** Each row is one job: its id, its configuration, its offered range,
its plottable and total run counts, and its state. Tick the ones to draw.
**Select all** ticks every row that is not held out; **Clear** unticks
everything. Several ticked jobs are combined into one figure: ETHOS unions their
runs in selection order, de-duplicated, so the same selection always produces
the same figure.

Leave every box clear to plot the whole window instead. That is the difference
between the two modes:

| Boxes ticked | What is drawn | Where the data comes from |
|---|---|---|
| One or more sweeps | exactly those jobs' plottable runs | the run archive |
| None | everything in the date range that passes the filters | InfluxDB |

**Naming runs directly.** Under "Name a campaign, job or run directly" are the
Campaign, Job and Run ids fields. They are how a link from Results or from a
finished job arrives, and they still work: a job named there is added to
whatever is ticked above. Landing on `/graphs?job_id=j-...` prefills the Job
field and opens that block.

**Filters.** Metric, kind, grouping, width and y scale all come from
`GET /plots/options`, so the form can only offer what ETHOS can actually draw.
"Which runs are allowed in" holds the minimum duration and the three
inclusion switches.

**Generate** shows a spinner, then the figure, a bar per warning in its
manifest, a **Data** accordion with the points, the n behind each one and every
dropped run with its reason, and downloads for the PNG, the PDF, `raw.csv` and
`points.csv`. A refusal is shown in ETHOS's own words.

### 7.3 What a figure is

A figure is a folder ETHOS writes: the PNG, the PDF, `raw.csv` (every row that
went into it), `points.csv` (the values drawn) and `manifest.json` (the
selection, the filters, the n behind each point, every dropped run with its
reason, and the ETHOS commit it was drawn at). The gallery below the form chips
each one **CLI** or **Console** and offers open, download and regenerate.

**A figure is a snapshot and never changes.** Quarantining a sweep tomorrow does
not alter a figure drawn today. **Regenerate** redraws a figure from its own
`raw.csv` into a new folder, which reproduces the original exactly and is
therefore not affected by the quarantine either. Drawing a **new** figure from
the same runs does honour it. That distinction is the point: an archived figure
stays reproducible, and the current selection applies to new work.

The manifest records the selection under `selection_by`: which jobs were ticked,
which jobs were quarantined at the moment it was drawn, which runs were actually
excluded, and whether quarantine was overridden. A reader a year later can tell
"this sweep was not selected" from "this sweep was held out, for this reason".

---

## 8. Holding a failed sweep out of graphs

A sweep can be invalid for a reason the numbers do not show: the UE detached,
the deployment was wrong, the testbed was in a state nobody intended. Quarantine
keeps it out of new figures without destroying it.

**Quarantine deletes nothing.** The runs, their manifests, the InfluxDB points,
every figure already drawn and the published results archive are all untouched.
It is one entry in one file, and restoring removes the entry.

### From the console

On **Jobs**, a finished sweep has a **Hold out** button. It opens ETHOS's own
preview: the job, its plottable and total run counts, and a required reason.
Confirming adds the entry. Held-out sweeps are listed in their own panel with
the reason, the date and a **Restore** button, so a sweep missing from a figure
can always be accounted for.

On **Graphs**, a held-out sweep still appears in the picker, greyed with its
reason, and its box is disabled. It is excluded from new figures by default.

A reason is required. In six months the runs will still be there and that
sentence is the only thing that will say why they stopped appearing.

### Including one deliberately

**Include quarantined jobs** in the picker's toolbar re-enables the held-out
rows so they can be ticked. Use it to reproduce or inspect data that is normally
held out. The figure's manifest records `include_quarantined: true`, so a figure
that contains held-out data says so.

The override applies to quarantine and nothing else. Every other rule (the
metric, the direction, the offered rates, the minimum duration, the serving
binary, the identity check) still runs on every row.

### From the ETHOS host

The console drives ETHOS's endpoints; the same thing is available as a CLI in
the ETHOS repository. `exclude` and `restore` are dry runs until `--confirm`.

```bash
cd ~/ravi-ethos-rApp
.venv/bin/python -m quarantine list
```

```
record   /home/oai-gnb/ravi-ethos-rApp-run/state/quarantine.json
nothing is quarantined
```

```bash
.venv/bin/python -m quarantine exclude --job j-20260929T131849Z --reason "UE detached during sweep"
.venv/bin/python -m quarantine exclude --job j-20260929T131849Z --reason "UE detached during sweep" --confirm
.venv/bin/python -m quarantine restore --job j-20260929T131849Z --confirm
```

The record lives beside ETHOS's run archive, outside every git repository, so
quarantining is not a commit and the published results archive never carries it.

---

## 9. Tests

They run against a fake ETHOS that replays recorded responses, so no testbed is
touched:

```bash
cd ~/testbed-console
.venv/bin/python -m pytest
```

```
599 passed, 1 warning in 210.38s (0:03:30)
```

That is 534 server tests and 65 browser tests. The browser tests start a console
process of their own, with ETHOS deliberately unreachable, and drive it with
Chromium. They check what a status code cannot: that the vendored components
upgrade under the Content-Security-Policy, that no page reaches outside the
console, that every action is disabled with its reason when ETHOS is down, and
that the Graphs picker's scripted controls actually work. They need the optional
extra, which is already installed here:

```bash
.venv/bin/python -m pip install -e '.[e2e]'
.venv/bin/playwright install chromium
```

Without it they skip themselves and the 534 server tests still run.

Anything scripted in the browser needs a browser test. The console's CSP is
`script-src 'self'`, which blocks inline `onclick` handlers outright, so a
button wired that way renders correctly and does nothing; only a browser test
catches it.

To refresh the fixtures from the real API, read-only endpoints only, and never
`ee-kpi`, which writes the manifest:

```bash
.venv/bin/python tests/record.py
```

The run list is trimmed to twelve runs that between them exercise the display
rules: an OCUDU run and an OAI run with channel metrics, one that was defined
and never ran, an uplink run, and a few that carry a campaign id.

---

## 10. Changing the console

`CLAUDE.md` holds the rules. The ones that bite most often:

- **Only `console/rapps/ethos/client.py` talks to ETHOS.** A page never builds
  a URL.
- **Adding a `CONSOLE_*` variable means adding it to `console.env.example`.** A
  test compares the two in both directions.
- **No em dash anywhere**, including in `docs/`. `tests/unit/test_no_em_dash.py`
  fails on one.
- **A selected option is styled from its own `:checked` state**, never from a
  class the server wrote. Option groups sit in cards the form does not
  re-render, so a server-written class is left behind on the wrong row.
- **No CDN.** Every asset is vendored under `console/static/vendor/` and
  recorded in `docs/vendor-versions.md`.

After editing templates, CSS or JavaScript, restart the service to serve them:

```bash
systemctl --user restart testbed-console
```

---

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Every page shows a red "ETHOS API unreachable" banner | ETHOS is down or not listening. `systemctl --user status ethos-rapp`, then `curl -s 127.0.0.1:8081/healthz`. The console stays up and reports itself healthy; it must not claim to be down because the thing it displays is. |
| The service will not start | `journalctl --user -u testbed-console -n 40`. Usually `console.env`: a trailing `# comment` after a value (§3.2), or a TLS path that does not exist. `.venv/bin/python -m console check` names both. |
| "This page's security token was missing or stale." | The session was replaced while the page was open. Reload. |
| Logged out unexpectedly | 12 hours since login, or 2 hours idle; the login page says which. Restarting the service does not log you out, but changing `CONSOLE_SESSION_SECRET` does: every existing cookie becomes unreadable. |
| Locked out of login | Five wrong passwords in ten minutes. Wait ten minutes, or restart the service; the counter is in memory. |
| The certificate warning is back | The certificate was regenerated, or you are reaching the console by a name it does not cover. It covers `192.168.8.78`, `127.0.0.1` and `localhost`. |
| The Results table is empty | Unusable runs are hidden by default: a run with no delivered bytes, or one whose iperf server ETHOS does not recognise, cannot be analysed. Tick "show unusable runs". |
| The figure form is not there | ETHOS did not answer `GET /plots/options`. The form is built from that response rather than from a list kept in the console, so there is nothing to fall back to. |
| The sweep list is empty | No job was created between Since and Until. Widen the range, or clear both and use the filters instead. |
| A sweep you expected is greyed out | It is held out of graphs. Its row carries the reason. Tick "Include quarantined jobs" to select it anyway, or restore it from the Jobs page. |
| A figure is refused as mixing run durations | ETHOS refuses two things by that name. Lengths differing **between** points are accepted once you say so, and the panel offers "Retry allowing mixed durations". Two lengths **inside** one point are refused whatever the flag says, because a mean across them describes neither run: set a minimum duration, or name the runs you want. |
| The RUN button will not light up | Its tooltip says why. Most often a readiness check failed: the lock is held by somebody else, or something is already deployed. A check that merely could not be made does not disable it. If the tooltip names a backend change, the probe enables the button within a minute of the endpoint appearing. |
| The core readiness check says unknown | Correct rather than broken: ETHOS probes the core from the node, joule has no interface on the core's subnet, and the gNB reaches the AMF over the interface its pod holds, which does not exist before a deploy. An unknown does not block RUN. |
| A Test Plan option is disabled and you expect it to work | Its tooltip gives the reason, read from ETHOS's `deploy_profiles.yaml`. A profile whose status is `todo` has no chart paths, so ETHOS would refuse the deploy rather than guess. |
| The CU and DU vendor groups will not change | They follow the split. With *Monolithic* selected, CU and DU are one process of the gNB stack, so both groups show that stack and are disabled. Choose *CU + DU*. |
| Readiness says "the node was not checked" | ETHOS probes the node only when the request names a stack, so the check needs a valid topology selected. If it still says so with a `config_id` on screen, the hover carries the real error from ETHOS, usually the SSH path to joule. |

---

## 12. Quick reference

```bash
# state
systemctl --user is-active testbed-console ethos-rapp
systemctl --user status testbed-console
curl -sk https://127.0.0.1:8443/healthz
.venv/bin/python -m console check

# lifecycle
systemctl --user restart testbed-console
journalctl --user -u testbed-console -f

# tests
.venv/bin/python -m pytest

# quarantine, from the ETHOS repo
cd ~/ravi-ethos-rApp && .venv/bin/python -m quarantine list
```

| Where | Path |
|---|---|
| Console repository | `~/testbed-console` |
| Console configuration | `~/testbed-console/console.env` |
| TLS certificate and key | `~/.config/testbed-console/tls/` |
| Saved test plans | `~/testbed-console-data/plans` |
| systemd unit | `~/.config/systemd/user/testbed-console.service` |
| ETHOS repository | `~/ravi-ethos-rApp` |
| ETHOS run archive | `~/ravi-ethos-rApp-run/runs` |
| ETHOS figures | `~/ravi-ethos-rApp-graph` |
| Quarantine record | `~/ravi-ethos-rApp-run/state/quarantine.json` |
