# Testbed Console & Dashboard — Requirements

Owner: Ravi (NTUST BMW Lab). Written 2026-09-27.
Companion documents: `02-design.md`, `03-ethos-backend-changes.md`, `04-build-plan.md`.

The Testbed Console is a web application for planning, running, watching and
reviewing tests on the BMW Lab O-RAN testbed. ETHOS is the first rApp it drives;
the console is a separate repository and a separate service, and ETHOS stays the
component that touches the testbed.

Every requirement has an ID (`TP-04`, `RS-12`, …). The build plan and the
acceptance tests refer to these IDs.

---

## 1. Decisions already made

| Topic | Decision |
|---|---|
| Name | **Testbed Console & Dashboard**. Short name "Testbed Console". Repo `testbed-console`. |
| Repository | Separate from ETHOS: `~/testbed-console` on the KVM, its own git history. |
| Host | ETHOS host `oai-gnb-KVM`, 192.168.8.78. |
| Reachability | Open on the lab LAN (192.168.8.0/24), HTTPS on port 8443: `https://192.168.8.78:8443`. |
| Users | One user (Ravi). Login with a single password. No user accounts. |
| Relation to the CLI | Sits **beside** the CLI. Both use the same ETHOS API and the same testbed lock. |
| Where safety lives | In ETHOS. Locking, deploy order, confirmation and validation are enforced by the ETHOS backend; the console only presents them. |
| Stack | FastAPI + Jinja2 server-rendered pages, htmx for live updates, Shoelace web components, Alpine.js for small interactions. No JavaScript build step. |
| Visual style | Clean white background. Tabs, radio groups, toasts/snackbars, accordions, chips, breadcrumbs, bento-grid overview. |
| Grafana | Linked, never embedded or modified. It is shared with other users. |
| Energy / EE-KPI | Not in the first phase. The RAPL power data stopped on 2026-08-27; the fix is scheduled after Phase 1. |
| O1 | FM, PM and CM, including tests driven by CM changes. Phase 3. |
| O2 | Energy, pod deployment duration, DMS services, NF checks. Phase 4. |
| Channel metrics | Summary per run only (no per-second data by default). Collected by ETHOS on every run since `feat/radio-channel-metrics`. |

---

## 2. Access and security (SE)

- **SE-01** The console serves HTTPS only, on port 8443. HTTP requests are not served.
- **SE-02** Every page and every endpoint except the login page requires a logged-in session.
- **SE-03** Login uses one password, stored only as a hash in the console's git-ignored env file. The plain password never appears in files, logs or responses.
- **SE-04** Sessions expire after 12 hours, and after 2 hours without activity.
- **SE-05** After 5 wrong passwords in 10 minutes, login is refused for 10 minutes.
- **SE-06** No ETHOS credential (InfluxDB token, `SSHPASS`, SSH keys, the future O2 client certificate) is ever held by the console or sent to the browser. The console reaches data only through the ETHOS API.
- **SE-07** ETHOS keeps listening on 127.0.0.1:8081 only. The console reaches it over loopback. Nothing about ETHOS's exposure changes.
- **SE-08** State-changing requests from the browser carry a CSRF token.
- **SE-09** All JavaScript, CSS and fonts are served from the console itself. No CDN, so the console works without internet and loads no third-party code.

---

## 3. Global layout and behaviour (GL)

- **GL-01** Left navigation with these sections: Overview, Test Plan, Jobs, Results, Graphs, Testbed, O1, O2. Sections not yet built are shown disabled with the phase they arrive in.
- **GL-02** A **status strip** across the top of every page (details in ST-01). It shows at a glance whether the testbed is free, what is deployed, and whether a job is running.
- **GL-03** Breadcrumbs on every page below the top level, e.g. `Results / Campaign sweep-0927 / Run 20260927T0745Z-…-DL100M-015`.
- **GL-04** Every action's outcome is announced by a toast: success (green, 4 s), warning (amber, 8 s), error (red, stays until closed). Errors show ETHOS's own message.
- **GL-05** Options are shown by their **label** from the ETHOS catalogue (e.g. "OAI CU + OCUDU DU"), never the internal slug (`mixoaiocu`). The same stack uses the same colour everywhere, matching the ETHOS figure colours.
- **GL-06** Times are displayed in Asia/Taipei with the offset shown on hover; everything stored and exchanged is UTC.
- **GL-07** Any state-changing action (run, stop, deploy, teardown, attach, detach, stop Magic iPerf, CM apply) opens a confirmation dialog showing ETHOS's preview of exactly what will happen. Nothing acts on a single click.
- **GL-08** When the testbed lock is held, every state-changing control is disabled and its tooltip names the holder, e.g. "Locked by job j-0927-1412 (running ocudu-mono) since 14:12".
- **GL-09** A value that was not measured shows as "—" with a tooltip giving the reason when known. It is never shown as 0.

---

## 4. Overview (OV)

A bento-grid dashboard. Each tile answers one question and links to the page with details.

- **OV-01** Testbed lock: free, or who holds it and since when.
- **OV-02** What is deployed now: topology label, releases, pod status, cell-config chips (`n78 · 100 MHz · 4T4R · 30 kHz · 7D2U`).
- **OV-03** Running job: topology, current step, progress (points done / total), elapsed time, a link to the job.
- **OV-04** UE: which UE is selected, attached or not, its IP, and the iperf server situation (port 5201 holder and mode: ETHOS / Magic iPerf).
- **OV-05** Last 5 runs: time, topology, offered → achieved, loss, one channel indicator (PUSCH SNR).
- **OV-06** Data freshness: the last point time for throughput (`ethos_iperf_v2`), O1 PM (`ran-pm-metrics`) and energy (`ocloud_power`), each coloured green (< 1 day), amber (< 7 days), red (older).
- **OV-07** Links: Grafana (`http://192.168.8.69:30489`), the docs, and a help panel with the SSH tunnel command for ETHOS Swagger. Swagger itself is not served through the console (design §1, §8).

---

## 5. Test Plan (TP)

The Test Plan page builds one test: a topology, a traffic plan and run options.
It is a form with a live readiness checklist and a RUN button.

### 5.1 Topology selection

Every option list comes from the ETHOS catalogue (`GET /catalogue`, backend change B4).
Options the catalogue marks undeployable are shown disabled, with the reason as a tooltip.

- **TP-01** gNB stack: OCUDU / OAI (radio group).
- **TP-02** Split: Monolithic / CU + DU (radio group). For CU + DU: CU vendor and DU vendor as two radio groups, which allows the two cross-vendor splits.
- **TP-03** L1: software PHY / NVIDIA Aerial cuBB. Aerial requires the DGX-Spark host (catalogue coupling RULE-7); selecting one without the other is impossible.
- **TP-04** RU: Pegatron / Foxconn / TM500.
- **TP-05** UE: Samsung / MTK / Pegatron dongle / TM500. The TM500 UE requires the TM500 RU and vice versa (coupling RULE-1).
- **TP-06** Core network: Open5GS / free5GC. free5GC stays disabled until the core check (open item 3) confirms it runs and the subscriber is provisioned.
- **TP-07** Server: joule / DGX-Spark (follows from the L1 choice).
- **TP-08** Every time the selection changes, the console asks ETHOS to validate it (`POST /validate`), then generates the test definition (`POST /testdef/generate`). The resulting **config_id** is shown read-only. The console never builds a config_id itself.

### 5.2 Traffic plan

- **TP-09** Direction: DL / UL (radio group).
- **TP-10** Offered load: a single rate, a list, or a range, in the same syntax as the CLI (`500`, `100,200,300`, `100-1000:100`). Accepted range 1–10000 Mbit/s. The form also offers a range builder (start, stop, step) that writes this syntax.
- **TP-11** Duration per rate: `10s`, `30s`, `5m`, … Minimum 5 s. Durations above 10 minutes show a warning with the total estimated time.
- **TP-12** Repeats: 1–20 per rate (default 1). A hint appears under the field: "Paper figures need n ≥ 5".
- **TP-13** iperf server mode for this test: ETHOS server / Magic iPerf app (`app_binary`). Chosen per test, not per service (backend change B7).
- **TP-14** Collect per-second radio samples: off by default (maps to `--radio-samples`). Labelled "for debugging".
- **TP-15** Label: an optional free-text name, used as the campaign id prefix and the figure label.
- **TP-16** Estimated total time, shown live: rates × repeats × (duration + per-point overhead) + deploy and teardown time. The overhead values come from ETHOS's recent job history once jobs exist; before that, fixed defaults.

### 5.3 Config view (editable)

- **TP-17** A "Show config" toggle reveals the full test plan as JSON or YAML (a tab switch between the two). It is hidden until clicked.
- **TP-18** The config view shows two parts: the ETHOS test definition for the config_id, and the traffic plan and run options.
- **TP-19** The config is editable. On edit, the console validates it through ETHOS (`POST /testdef/validate`) and updates the form. Invalid edits show ETHOS's error inline, and the form keeps the last valid state.
- **TP-20** The test definition's radio parameters (bandwidth, TDD pattern, antennas) are labelled "planned". The values that actually ran are the cell config ETHOS reads from the pod at deploy time (RS-09). The generator's defaults are known to be wrong for OCUDU (80 MHz / DDDSU instead of 100 MHz / 7D2U; backend follow-up B15).
- **TP-21** Download the test plan as a `.json` or `.yaml` file. Upload a saved plan file to fill the form.
- **TP-22** Saved plans: save the current plan under a name on the console host; list, load, rename and delete saved plans.

### 5.4 Readiness and RUN

- **TP-23** A readiness checklist beside the form, each item with a status icon, a reason when failing, and a "Check again" button. RUN is enabled only when every item passes:
  1. Topology is complete, validated, and deployable (catalogue + `POST /validate`).
  2. The testbed lock is free.
  3. Nothing unexpected is deployed (no other topology occupies joule).
  4. The selected UE is reachable over its control path.
  5. The iperf server situation matches the chosen mode: in ETHOS mode port 5201 is free; in Magic iPerf mode an `app_binary` server holds 5201.
  6. Rates, duration, direction and repeats are valid.
  7. The core network is reachable.
- **TP-24** The readiness result comes from one ETHOS call (`POST /readiness`, backend change B5), so the console and the CLI judge readiness identically.
- **TP-25** RUN opens a confirmation dialog with ETHOS's preview: the releases to deploy in order, the UE, the rate list, total points, estimated duration, the iperf mode, and what will be torn down afterwards. Confirm starts the job and opens the job page.
- **TP-26** When RUN is disabled, its tooltip names the first failing readiness item.

---

## 6. Jobs: running and watching (RN)

A **job** is one campaign execution started from the console or the CLI.

- **RN-01** One job at a time on the testbed. A second start is refused, naming the running job (ETHOS returns 409).
- **RN-02** The job page shows live progress without reloading: a step list (preflight, deploy, attach, each rate point, detach, teardown), each step with a state (pending / running / done / failed / skipped) and its duration.
- **RN-03** Completed points appear in a table as they finish: offered, achieved, loss, jitter, RTT p95, CQI, RI DL/UL, MCS DL/UL, PUSCH SNR, residual BLER DL. This matches the CLI's end-of-campaign summary.
- **RN-04** The cell config chips of the deployed topology appear once deploy finishes.
- **RN-05** A live log panel (accordion, collapsed by default) shows ETHOS's progress messages for the job.
- **RN-06** **Stop**, with confirmation: the job stops at the next boundary between rate points, never in the middle of a measurement, then detaches the UE and tears down DU before CU. The job ends as "aborted", and completed points are kept.
- **RN-07** A browser refresh, a closed tab, or a second tab never affects the job. Reopening the job page resumes the live view from where the stream left off.
- **RN-08** If the ETHOS service restarts during a job, the job is marked "interrupted" on restart, and the job page shows what is still deployed with a "Tear down" action (confirmation required).
- **RN-09** Jobs started from the CLI appear in the jobs list too, marked "CLI". This requires the CLI to run campaigns through the same ETHOS job endpoint (backend change B2).
- **RN-10** A jobs list: newest first, with state, topology, label, start time, duration, and points done / total; filterable by state and topology.
- **RN-11** When a job finishes, a toast appears on whatever console page is open, with a link to the results.

---

## 7. Results (RS)

### 7.1 Run table

- **RS-01** A table of runs from ETHOS, newest first. Columns: time, topology (chip), direction, offered, achieved (`achieved_over_tx_mbps`), loss %, jitter, RTT p95, PUSCH SNR mean, residual BLER DL, duration, iperf server (ETHOS / Magic iPerf), quality flags.
- **RS-02** Filters as chips: topology, date range, rate, direction, campaign/job, iperf server, cell config (band / bandwidth / TDD pattern), and "has quality flags".
- **RS-03** Select several runs to compare them or send them to Graphs.
- **RS-04** CSV export of the filtered table, including every summary field shown in RS-10.
- **RS-05** Runs that are not usable for analysis (`has_delivered` false, or server owner foreign/unknown) are hidden by default, with a switch to show them greyed out.

### 7.2 Run detail

Tabs:

- **RS-06 Summary tab.** Offered vs achieved, loss, jitter, duration, state, run id, config_id, campaign/job, iperf server owner and versions, quality flags with their descriptions.
- **RS-07 Channel conditions tab.** From `run.json → radio_summary`, following the display rules in §7.4.
- **RS-08 Latency tab.** RTT min / mean / max / p95 / mdev, loss, and probe count (`run.json → latency`). For noTraffic runs the same values are labelled "idle baseline".
- **RS-09 Cell config tab.** Every `cell_config` field, plus where it was read from and when (`source`, `read_at`), and whether the startup log confirmed it.
- **RS-10 Config tab.** The run's test definition and traffic plan as JSON/YAML (read-only here), with download.
- **RS-11 Raw tab.** The whole `run.json`, collapsible by block, with a copy button.
- **RS-12 Samples.** If the run was made with radio samples on, a "Samples" tab shows the per-second rows. Otherwise the tab is absent.

### 7.3 Sweep view (channel conditions across a sweep)

- **RS-13** A campaign or job page listing all its runs as rows ordered by offered load, with the same columns as the run table plus CQI, RI DL/UL, MCS DL/UL with table and cap, and first-transmission BLER (OAI).
- **RS-14** Buttons on the sweep view to plot any listed metric against offered load (hands off to Graphs with the runs preselected).
- **RS-15** The sweep view header shows the cell config chips; if runs in the sweep have different cell configs, it says so in amber.
- **RS-16** Repeats of the same (topology, rate) are shown as one row with mean and n; the row expands to show the individual runs.

### 7.4 Metric display rules

These come from the channel-metrics investigation (2026-09-27) and prevent false
cross-vendor comparisons.

| Metric | Show as | Rule |
|---|---|---|
| Throughput | `achieved_over_tx_mbps` | The only throughput compared across stacks. gNB MAC bitrate (OCUDU) and goodput (OAI) appear only on the Samples tab. |
| BLER | "Residual BLER" (both stacks); "First-transmission BLER" (OAI only) | Never labelled plain "BLER". The two never share an axis or a column. |
| SNR | "PUSCH SNR" (both stacks); "PUCCH SNR" (OAI only) | Only PUSCH SNR is compared across stacks. |
| SINR | "UE SS-SINR (Android)" and "UE SS-SINR (gNB RRC report, OAI)" | Separate fields; they differ by ~10 dB on the same UE and are never merged. |
| RSRP | "UE SS-RSRP (Android)", "UE L1-RSRP (OAI)", "gNB UL RSRP (OCUDU, relative dB)" | The OCUDU value is relative, not dBm, and never shares an axis with dBm values. |
| MCS | index + table (e.g. `27 · qam64`) | Shown with the cap when the stack has one; a value at the cap gets a "capped" chip. |
| Rank | "RI DL" and "RI UL" | Always direction-labelled. OCUDU values are averages, OAI values instantaneous. |
| CQI | DL only | A cross-vendor CQI difference carries a tooltip: "CQI is reported against each gNB's own CSI-RS configuration". |
| TDD pattern | chip beside every result | Always visible; OCUDU (7D2U, 5 ms) and OAI (DDDSU, 2.5 ms) differ. |
| Not measured | "—" | Never 0 (GL-09). |

---

## 8. Graphs (GR)

- **GR-01** Build a figure from: selected runs, a sweep, or a filter (topology + date range + rates).
- **GR-02** Metric: throughput (default), loss, RTT p95, PUSCH SNR, residual BLER DL/UL, MCS DL/UL, CQI, RI DL.
- **GR-03** Kind: auto / line (metric vs offered load) / bar (per stack at one rate). Group by stack (repeats averaged, 95 % CI) or by run (repeats separate).
- **GR-04** Width: single column (3.5 in) or double column (7.16 in), IEEE style, as the ETHOS plotting package does now.
- **GR-05** Generating shows the figure in the page; download as **PNG** and PDF.
- **GR-06** Every figure keeps its manifest (runs, filters, n per point, git commit). A "Data" accordion under the figure shows it.
- **GR-07** A gallery of previously generated figures, newest first, with label, date, kind and metric; open, download or regenerate any of them.
- **GR-08** Figures are generated by ETHOS (backend change B9), so a figure from the console and the same request from the CLI are identical.
- **GR-09** A figure whose runs mix cell configs, iperf server modes or durations shows a warning above it, naming what differs.

---

## 9. Testbed control and UEs (TB, UE) — Phase 2

- **TB-01** Deploy a chosen topology and leave it running, without traffic. Confirmation shows the releases in order and the node state.
- **TB-02** Tear down whatever is deployed, DU before CU. Confirmation lists what will be removed.
- **TB-03** The deployed topology panel shows releases, pods, restarts, age, and the cell config read at deploy.
- **UE-01** A list of the testbed's UEs (from ETHOS's UE registry) with driver, control path, reachability, attach state, IP and the time of the last check.
- **UE-02** Select a UE, then Attach / Detach (airplane mode off / on), each confirmed, each refused while the lock is held.
- **UE-03** Magic iPerf status for the selected UE: whether an `app_binary` server holds port 5201, its PID, and its app package; with a confirmed "Stop Magic iPerf" button.
- **UE-04** The UE's current signal reading (SS-RSRP / RSRQ / SINR from Android), with a "Read now" button.
- **UE-05** Prerequisite: the UE laptop (`iapc`) uses SSH-key login, so ETHOS needs no stored password for UE actions (open item 4).

---

## 10. O1 (O1) — Phase 3

- **O1-01** PM freshness per vendor and cell: the last point time from `ran-pm-metrics`, filtered to this testbed's managed elements (the bucket also holds an unrelated satellite-simulator project's measurements).
- **O1-02** PM per run: the run's O1 counters, per vendor. OCUDU and OAI share no counters, so there is no combined O1 chart.
- **O1-03** FM: an active-alarms list (severity, source, time, text) and an alarm history filter, read from the existing ONAP/VES path.
- **O1-04** CM read: the current CM of the deployed gNB (`GET /cm/{config_id}`).
- **O1-05** CM change: pick a writable parameter (`GET /cm/params/writable`, with its safe range), preview (`POST /runs/{id}/cm/preview`), confirm (`/cm/apply?confirm=true`). The preview's content is shown in the confirmation dialog.
- **O1-06** CM-driven test: a Test Plan option adds a CM step before traffic (set a value, then run the rate list).
- **O1-07** CM sweep: run the same rate list at several values of one CM parameter, one job, with results grouped by the CM value.
- **O1-08** Before O1-06/07 can run, readiness adds three checks: the O1 adapter is deployed, PM data is fresh, and the SDNC mount is connected.

---

## 11. O2 (O2) — Phase 4

- **O2-01** NF checks: Helm releases and pods in `ravi-ns` with status, restarts, age and readiness; one panel per deployed topology.
- **O2-02** Pod deployment duration per deploy: time from `helm install` to all pods ready, recorded by ETHOS on every deploy and shown per run and as a trend per topology.
- **O2-03** Energy per run: O-Cloud power and EE-KPI (bits per joule). Enabled only after the RAPL shipper fix; until then the panel says "no energy data since 2026-08-27". Never shown for Aerial runs (ARM host, no RAPL).
- **O2-04** DMS services: inventory and deployment managers from the StarlingX O2 IMS/DMS API (`https://192.168.206.82:30205`, `pti-o2imsdms` 2.0.4). Needs a client certificate held by ETHOS; until then the panel says so.

---

## 12. Status indicators (ST)

- **ST-01** The status strip shows: lock (free / holder), deployed topology, UE (attached / detached / unreachable), iperf server (mode, 5201 holder), ETHOS API (up / down), and the running job's progress. Each item shows "unknown" if its probe fails, without breaking the page.
- **ST-02** The status strip updates within 5 seconds of a change while the page is open.
- **ST-03** Every status item shows when it was last checked, on hover.
- **ST-04** If the ETHOS API is unreachable, a red banner says so, and every action is disabled.

---

## 13. Non-functional (NF)

- **NF-01** Pages load in under 1 s on the lab LAN when ETHOS responds normally.
- **NF-02** Desktop first (1280 px and wider). Usable down to 1024 px. Phone layout is out of scope.
- **NF-03** Runs as a systemd user service (`testbed-console`) on the KVM, restarting on failure and surviving logout (linger enabled).
- **NF-04** The console keeps no copy of results. Its own storage is: saved test plans, its env file (password hash, session secret), and logs.
- **NF-05** Console logs record every state-changing action with time, action and ETHOS's response, never secrets.
- **NF-06** Keyboard navigation works for every form control; every icon-only button has a text label for screen readers.
- **NF-07** Console tests run without the testbed, against a fake ETHOS that replays recorded responses.
- **NF-08** Git rules as for ETHOS: branch per change, plain lowercase commit subjects, Ravi as sole author, no pushes unless asked.

---

## 14. Out of scope

- Multiple users, roles, accounts, testbed booking.
- A job queue. A second job is refused, not queued.
- Changing Grafana, embedding Grafana panels.
- A plugin framework for other rApps. The console's navigation and API client are organised per rApp (ETHOS first) so a second rApp can be added later, but nothing more is built for it.
- Phone layout.

---

## 15. Open items

1. **Deadline.** No date given yet. It decides how much of Phase 1 is required at first release.
2. **Campaign direction and repeats.** Whether the campaign runner supports UL and repeats today must be confirmed in Phase 0; if not, backend change B8 adds them.
3. **Core network check.** Where Open5GS and free5GC run, whether ETHOS can switch between them, and whether the UE's subscriber exists in each. Not yet investigated. TP-06 keeps free5GC disabled until done.
4. **`iapc` SSH-key login.** Recommended before Phase 2 so no password is stored for UE control.
5. **Grafana admin password.** It was shared in a chat; rotate it. The console never needs it.
6. **OCUDU `n_prb` and max MIMO layers.** Null today because OCUDU's config doesn't state them. `n_prb` can be derived (100 MHz at 30 kHz = 273 PRB), marked as derived (backend change B14).