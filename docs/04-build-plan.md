# Testbed Console & Dashboard, Build plan

Companion to `01-requirements.md`, `02-design.md`, `03-ethos-backend-changes.md`.

ETHOS changes come first (Phase 0), because the console must not ship on top of
a backend without a lock, jobs or confirmation. Each phase ends with an
acceptance check on the real testbed before the next one starts.

| Phase | Delivers | Repo |
|---|---|---|
| 0 | ETHOS foundation: lock, confirmation, jobs, catalogue, readiness, status summary, per-job iperf mode, direction/repeats, figures and results endpoints | ETHOS |
| 1 | Console MVP: login, Overview, Test Plan, Jobs, Results with channel conditions, Graphs | console |
| 2 | Testbed control and UEs | both |
| 3 | O1: PM, FM, CM, CM-driven tests | both |
| 4 | O2: NF checks, deploy timing, energy, DMS | both |

---

## Where the documents go

Copy the four documents to the KVM once, from the folder they're in on your laptop:

```bash
scp 0*-*.md oai-gnb@192.168.8.78:/home/oai-gnb/ravi-ethos-rApp-doc/docs/testbed-console/
```

(Create the folder first: `ssh oai-gnb@192.168.8.78 mkdir -p ~/ravi-ethos-rApp-doc/docs/testbed-console`.)
Task 1a copies them into the new console repo's `docs/`.

---

## Rules for every task

Each brief below starts with `[rules block]`. Replace it with this block when you send the brief:

```
Follow ~/.claude/skills/ravi-rules/SKILL.md (branches, commits, reports).
Design documents: ~/ravi-ethos-rApp-doc/docs/testbed-console/01–04. Read the
sections named in this brief before writing code; requirement IDs (TP-04,
RS-12, …) and backend IDs (B1–B15) refer to them. If a document is wrong or
impossible to follow, stop and tell me rather than working around it.
Never print tokens or passwords. Report plain text, with real output.
Check no campaign/job is running before restarting ethos-rapp, and tell me
when you restart it.
```

---

## Phase 0, ETHOS foundation

### Task 0a, lock and confirmation (B1, B3)

```
[rules block]

Implement B1 (testbed lock) and B3 (preview → confirm with token) in ETHOS,
as specified in 03-ethos-backend-changes.md.

1. Before changing enforcement, list every caller of the state-changing
   endpoints B3 covers (campaign runner, scripts, tests, docs), with
   file:line. Show me the list before switching enforcement on.
2. Implement the lock (flock + holder sidecar, GET /lock, 409 body, the
   job lock token header) and the preview/token mechanism (5-minute
   tokens, 412 on state change, 428 without confirmation, the job-token
   exception).
3. Migrate every caller from step 1 in the same branch. The campaign CLI
   must keep working end to end.
4. Tests as listed under B1 and B3, plus a regression run of the full suite.

Verification on the testbed (one at a time):
- campaign ocudu-mono --rates 100 --duration 10s  → completes unchanged
- while it runs, a second campaign → refused, holder named
- curl POST /deploy without confirmation → 428
- preview, take the lock with another action, then act → 412

Report: caller list, files changed, test count before/after, the
verification output, branch and merge command.
```

### Task 0b, jobs (B2)

```
[rules block]

Implement B2: the job model, the endpoints in the B2 table, persistence
under $ETHOS_RUNS_ROOT/../jobs/, startup reconciliation to "interrupted",
and the CLI as a job client (same printed output as today; source: cli).
POST /campaigns/{id}/run and GET /campaigns/{id}/status stop returning 501.
Campaign sequencing code stays unchanged; the job injects a transport
(runner.py:397).

Tests as listed under B2.

Verification on the testbed:
- CLI: campaign oai-mono --rates 100,200 --duration 10s → same output as
  before; GET /jobs shows it with source cli
- API: POST /jobs/preview then POST /jobs for ocudu-mono 100 M 10 s; follow
  /jobs/{id}/events with curl -N; disconnect and reconnect with
  Last-Event-ID → no gap, no duplicate
- stop a 3-rate job during rate 2 → aborted, 1–2 points kept, torn down
- restart ethos-rapp during a job (tell me first) → interrupted, and
  /status shows what is deployed

Report as in 0a.
```

### Task 0c, catalogue, readiness, status, iperf mode, direction and repeats (B4–B8)

```
[rules block]

Implement B4 (GET /catalogue), B5 (POST /readiness, and switch the CLI
preflight to the same function), B6 (GET /status/summary with per-part
checked_at/error and the stated cache times), B7 (iperf_server per job,
ETHOS_IPERF_SERVER stays the default).

B8: first report whether the campaign runner supports UL and repeats today,
with evidence. Then add what is missing, as specified.

Verification on the testbed:
- GET /catalogue: show the deployable flag and reason for every RU, UE,
  core and L1 option
- POST /readiness with Magic iPerf running and mode app_binary → all pass;
  same plan with mode ethos → iperf_server fails with a reason
- a job with iperf_server=ethos while the drop-in says app_binary → the
  runs record server_owner ethos
- a job with direction UL, rates 50, repeats 3, duration 10s → 3 runs,
  repeat_index 1..3

Report as in 0a.
```

### Task 0d, figures, results, cell-config fixes (B9, B10, B14, B15)

```
[rules block]

Implement B9 (POST/GET /plots, image and PDF, GET /plots/series, the
metric parameter in build_figure with the listed metrics, MCS cap lines,
mixed-input warnings), B10 (GET /runs filters, GET /runs.csv,
GET /campaigns/{id}/summary, GET /runs/{id}/radio-samples), B14 (derived
n_prb) and B15 (test-definition radio parameters from the chart
configuration, or null with a reason).

The existing plotting CLI must produce byte-identical throughput figures
from an existing snapshot (check with --from-snapshot and md5).

Verification on the testbed (no new campaigns needed; use existing runs):
- POST /plots for the last full sweep: throughput, then pusch_snr, then
  mcs_dl (cap lines visible) → show the PNG paths
- GET /campaigns/{id}/summary for that sweep
- GET /runs.csv with a date filter → row count matches GET /runs
- POST /testdef/generate for ocudu-mono → 100 MHz and 7D2U, or null with
  a reason

Report as in 0a, plus the three PNGs.
```

### Phase 0 acceptance

On the testbed, by you:

1. Start a CLI campaign, and in a second terminal try another → refused with the holder named.
2. `curl -s 127.0.0.1:8081/status/summary | python3 -m json.tool` → lock, deployed, latest job, UE, iperf, freshness all present.
3. `curl -s -X POST 127.0.0.1:8081/readiness -H 'content-type: application/json' -d @plan.json` → seven checks with statuses.
4. The full test suite is green, and the count is reported.

---

## Phase 1, Console MVP

### Task 1a, scaffold, security, layout, Overview

```
[rules block]

Create the console repo at ~/testbed-console (git init; no remote yet),
per 02-design.md §2, §3, §10, §11, §12. Copy the four design documents into
docs/. Add a CLAUDE.md pointing to ~/.claude/skills/ravi-rules/SKILL.md and
to docs/.

Build:
- settings, `python -m console serve`, `python -m console set-password`
- TLS via deploy/make-cert.sh; HTTPS only on 8443
- login, sessions (12 h / 2 h idle), rate limit, CSRF, security headers
- base layout: left nav (later sections disabled with their phase),
  status strip (polls /partials/status every 5 s from GET /status/summary),
  breadcrumbs, toast region
- Overview bento grid (OV-01…07), each tile its own htmx partial
- rapps/ethos/client.py with error mapping per design §7.5
- vendored htmx, htmx SSE extension, Alpine.js, Shoelace (exact versions,
  recorded in docs/vendor-versions.md)
- tests/fake_ethos and tests/record.py; unit tests for auth and client
- the systemd user unit, installed and running

Verification:
- from your laptop: https://192.168.8.78:8443 → login → Overview with live
  status strip; stop ethos-rapp briefly (tell me first) → red banner and
  disabled actions; start it → recovers within 5 s
- wrong password 5 times → locked out for 10 minutes

Report: tree, test count, screenshots of login, Overview, and the banner
(Playwright can capture them), branch and merge command.
```

### Task 1b, Test Plan

```
[rules block]

Build the Test Plan page: TP-01…26, design §6.2, §7.1, §7.2.
Option lists from GET /catalogue; validation and config_id only through
ETHOS; editable JSON/YAML config view validated by ETHOS; save/load/upload/
download of plans (CONSOLE_PLANS_DIR); readiness panel (debounced
POST /readiness, re-run every 10 s); RUN → preview dialog → POST /jobs with
the token → job page.

E2E tests against fake_ethos: RUN disabled with the first failing reason;
enabled when all pass; config edit round-trip (valid and invalid); 412
after preview shows a toast and re-runs readiness.

Verification on the testbed: plan ocudu-mono DL 100 M 10 s with Magic
iPerf on → all checks pass → RUN → preview shows releases, UE, rates →
confirm → job starts. Screenshots of the page, the config view and the
preview dialog.
```

### Task 1c, Jobs

```
[rules block]

Build the jobs list and job page: RN-01…11, design §6.3, §7.3, §7.4.
SSE relay (console/sse.py) with Last-Event-ID resume; steps; completed
points table; cell-config chips; log accordion; Stop with confirmation;
interrupted-job view with a confirmed teardown; job-finished toast on any
page.

E2E against fake_ethos: live steps; refresh mid-job resumes without
duplicates; two tabs, second start refused naming the holder; stop →
aborted.

Verification on the testbed: a 3-rate job from the console; refresh during
rate 2; stop during rate 3; then the same from the CLI appears in the
jobs list as CLI.
```

### Task 1d, Results

```
[rules block]

Build Results: RS-01…16 and the metric display rules in requirements §7.4
exactly: labels, separate fields, "n/a" for not measured, capped chip, TDD
chip). Run table with filters and CSV; run detail tabs (Summary, Channel
conditions, Latency, Cell config, Config, Raw, Samples when present); sweep
view with repeats collapsed and "Plot" links.

Unit tests for every §7.4 rule, using recorded run.json from both stacks
(OCUDU and OAI, including a run with radio samples and a noTraffic run).

Verification: open the last full sweep and one OCUDU and one OAI run;
screenshots of each tab and the sweep view.
```

### Task 1e, Graphs

```
[rules block]

Build Graphs: GR-01…09, design §6.7. Requests through POST /plots; PNG
shown in page; PNG and PDF download; manifest accordion; mixed-input
warning bar; gallery with regenerate.

Verification: from the sweep view, plot throughput, PUSCH SNR and MCS DL
(cap lines); download the PNG; regenerate one gallery figure and confirm
its md5 is unchanged.
```

### Phase 1 acceptance

By you, from your laptop:

1. Log in at `https://192.168.8.78:8443`.
2. Plan `oai-cu-ocudu-du`, DL, `100-300:100`, 30 s, 2 repeats, Magic iPerf mode. Every readiness check passes. RUN → confirm.
3. Watch the job live; refresh once midway; it continues.
4. Open the sweep view: 3 rows, n = 2 each, cell-config chips with the TDD pattern.
5. Open one run's Channel conditions tab: residual BLER and PUSCH SNR in the comparable part; the OAI-only fields in the vendor accordion.
6. Plot PUSCH SNR vs offered load for the sweep; download the PNG.
7. While a job runs, try to start another from a second tab → refused with the holder named.

Then write `docs/operator-guide.md` in the console repo: start/stop the service, set the password, the certificate, and every page's purpose. Current instructions only.

---

## Phase 2, Testbed control and UEs

Before it starts: switch `iapc` to SSH-key login (open item 4).

- **Task 2a (ETHOS):** B11 endpoints; standalone deploy/teardown previews wired through B3.
- **Task 2b (console):** Testbed and UE pages (TB-01…03, UE-01…05).
- **Acceptance:** deploy `ocudu-mono` from the console without traffic; attach Samsung; read its signal; check Magic iPerf; stop Magic iPerf; detach; tear down. Every step shows a preview first and is refused while a job holds the lock.

## Phase 3, O1

- **Task 3a (investigation):** where FM events land today in the ONAP / SDNC / VES chain; PM freshness per managed element; SDNC mount state. Report only.
- **Task 3b (ETHOS):** B12.
- **Task 3c (console):** O1 pages (O1-01…08) and the CM step / CM sweep options in the Test Plan.
- **Acceptance:** a CM sweep over one writable parameter at 3 values, DL 100 M 30 s each, with results grouped by value; the alarm list shows an alarm raised during the test, if one is raised.

## Phase 4, O2

- **Task 4a:** the RAPL shipper fix (separate from the console; `ocloud_power` has had no data since 2026-08-27).
- **Task 4b (ETHOS):** B13 (NF checks, deploy timing on every deploy, energy freshness; DMS once the client certificate exists).
- **Task 4c (console):** O2 pages (O2-01…04).
- **Acceptance:** deploy timings for all six topologies from one sweep; an EE-KPI shown for a new run; the DMS inventory listed, if the certificate is in place.

---

## Status checks at any time

| Question | Console | Shell on the KVM |
|---|---|---|
| Is the testbed free? | status strip | `curl -s 127.0.0.1:8081/lock` |
| What is running? | Overview → Running job | `curl -s '127.0.0.1:8081/jobs?state=running'` |
| What is deployed? | Overview → Deployed now | `curl -s 127.0.0.1:8081/deploy/status` |
| Is the console up? |, | `systemctl --user status testbed-console` |
| Is ETHOS up? | red banner if not | `systemctl --user status ethos-rapp` |
| Console logs |, | `journalctl --user -u testbed-console -n 100` |