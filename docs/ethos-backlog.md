# What the console is waiting for from ETHOS

The testbed lock, the job model, preview-then-confirm, readiness, the status
summary, the per-job iperf mode, standalone UE control and figures on request have
landed (B1, B2, B3, B5, B6, B7, B9, B11), and the console uses all of them. What is
left is the catalogue (B4) and server-side results queries (B10), plus the O1 and
O2 phases.

Rather than buttons that look live and fail on click, a control that still needs a
backend change is disabled and names it. This is the list, and it is also the
order of work in `04-build-plan.md`.

Checked against the live API on 127.0.0.1:8081 on 2026-09-29.

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
on its own**, with no edit to the page.

An entry stays in the table after its change lands, and that is deliberate: it is
then a live check rather than a gate. If an endpoint disappears in a rollback or a
route breaks, the probe notices within a minute and the control that depends on it
disables itself with a reason instead of failing on click.

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
| `GET /lock` | **works** | the status strip, the Overview tile, the readiness line |
| `GET /jobs`, `POST /jobs`, `POST /jobs/preview`, `POST /jobs/{id}/stop`, `GET /jobs/{id}/events` | **works** | RUN, the Jobs page, the live job page |
| `POST /readiness` | **works** | the readiness panel, and whether RUN is offered |
| `GET /status/summary` | **works** | the status strip and the Overview tiles |
| `GET /ue`, `GET /ue/{ue}/iperf`, `GET /ue/{ue}/signal`, the attach, detach and iperf-stop pairs | **works** | the Testbed page's UE panel |
| `GET /catalogue` | not routed | B4 |
| `GET /plots/options`, `GET /plots/series`, `GET /plots`, `POST /plots`, `GET /plots/{id}`, its four files, `POST /plots/{id}/regenerate` | **works** | the Graphs page, and the palette on every page that draws a chip |
| `GET /runs.csv`, `GET /campaigns/{id}/summary`, `GET /runs/{id}/radio-samples` | not routed | B10 |
| `GET /o1/freshness`, `GET /o1/alarms` | not routed | B12 |
| `GET /o2/nf`, `GET /o2/deploy-times`, `GET /o2/dms/*` | not routed | B13 |

---

## What each change unlocks, and what to delete when it lands

### B1, testbed lock, done

`GET /lock` is read in three places and worded the same in all of them by
`console/holders.py`: the status strip, the Overview's lock tile and the readiness
panel's `lock` line. A holder is named rather than reduced to "busy", and a shell
campaign reads **CLI campaign `<what>` since `<time>`**, because `cli:3340113`
means nothing to somebody who did not start it.

The lock is the one read that is never cached. Everything else on a page can be a
few seconds stale; this decides whether an action is offered at all.

### B2, jobs, done

RUN is `POST /jobs/preview`, then ETHOS's preview shown in a dialog, then
`POST /jobs` with the token, then `/jobs/{job_id}` (design 7.2). 409 names the
holder in a toast and 412 says the state changed and re-runs readiness (7.5).

The job page is a snapshot plus an SSE relay. Both are needed: the snapshot is
what makes opening the page halfway through a job useful, and the stream carries on
from wherever ETHOS's replay left off. `console/sse.py` adds nothing to the events
except forwarding `Last-Event-ID`, which is the whole of the resume mechanism, so a
refresh loses nothing.

Stopping goes through its own confirmation. ETHOS has no preview endpoint for a
stop, so that text is the console's, and it describes what ETHOS does rather than
guessing: the point being measured finishes, the stack is torn down, and the job
ends `aborted` keeping every point it measured.

The console still runs no campaign itself. It has the same API the CLI drives, and
that is exactly why it must not: one executor, in ETHOS.

### B3, preview, then act with a token, done

Every state-changing call the console makes carries a token from a preview the
operator saw: starting a job, attaching a UE, detaching one, and stopping the iperf
app. Nothing acts on one click (GL-07).

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

### B5, readiness, done

`POST /readiness` replaces the list the console used to assemble. All seven checks
are ETHOS's, rendered in ETHOS's order by `console/readiness.py`, and the console
adds none of its own: the point of the endpoint is that the CLI and the console
judge readiness identically.

Two rules the panel follows because ETHOS does:

- an `unknown` stays an unknown. It is never upgraded to a pass, never downgraded
  to a failure, and it is surfaced with a count rather than hidden;
- only a **failure** disables RUN. A check that could not be made must not refuse
  a run that would have worked.

The traffic parse survives as a **form hint** beside the fields, which is all it
ever was useful for: catching a rate that cannot be expressed while it is being
typed. It is not a readiness check and no longer appears in the panel.

The `lock` line is reworded from `/lock` so a holder reads the same there as in the
strip. Everything else is ETHOS's own sentence.

### B6, status summary, done

`build_status()` in `console/status.py` is one call. Each part carries its own
`checked_at` and `error`, so a probe that failed inside ETHOS greys out one item
and the rest of the strip still draws, and a part ETHOS served from its own cache
reports the age of the read it came from rather than of the request.

The Overview's lock, deployed, latest-job, UE and freshness tiles come from the
same object. Freshness names all three sources, and a source that has never landed
a point says so rather than reading as stale: never and old are different.

### B7, iperf server mode per job, done

The plan carries `iperf_server`, and it is now this job's choice rather than a note
about a service-wide setting. ETHOS applies it to that job's runs and each run
records which binary served it. The readiness panel's `iperf_server` check judges
the mode chosen on the form, which matters because the two modes want opposite
things of port 5201: `app_binary` needs a server already listening, `ethos` needs
the port free.

### B8, direction and repeats

`--direction` exists in the campaign CLI; `--repeats` does not. A plan with more
than one repeat says so, and the copy-able command explains that repeats mean
running it that many times.

### B9, figures on request, done

The Graphs page asks for figures now, and the console still draws none of its own:
the image on the page is the file ETHOS's plotting package wrote, served from the
archive beside its manifest, `points.csv` and `raw.csv`. A figure the CLI made and
one the page asked for are the same kind of thing in the same list, so the gallery
chips which asked for it rather than splitting them apart.

The form is built from `GET /plots/options`, every control of it: the metrics with
their units, the kinds, the groupings, the widths, the y scales, the default
metric, and the note ETHOS attaches to a metric that is not comparable across
stacks. Nothing in it is a list kept here, so a metric ETHOS adds appears on the
next probe and one it drops disappears. If that call fails the form is not built at
all, because a form assembled from a remembered table would offer something ETHOS
may no longer plot.

A 422 is shown in ETHOS's own words. It says precisely what is wrong with the
selection, and a reworded version would be a vaguer second explanation in front of
an accurate one. Where the refusal is about run lengths the buckets are listed as
chips, and the retry button appears **only** where the flag actually helps:

- lengths differing **between** points are one flag away, so "Retry allowing mixed
  durations" is offered and sets `allow_mixed_durations` explicitly;
- two lengths **inside** one point are refused whatever the flag says, and ETHOS
  says so in the same sentence. A button there would fail the same way, so the
  panel lists the buckets and points at a minimum duration instead.

**What this replaced.** `console/rapps/ethos/figures.py` read the graph folder
directly and is deleted, along with `CONSOLE_GRAPH_DIR` in settings,
`console.env.example` and the guide. `console/rapps/ethos/series.py` no longer
holds a copy of ETHOS's palette: it is fetched from `GET /plots/series` by the
capability probe, so a chip beside a run and a line in the figure next to it cannot
drift apart. What stays local is the two-letter tile, which ETHOS has no concept
of, and the two legacy head spellings, whose runs would otherwise fall to grey.

An unfetched palette renders grey and says "unknown stack". That is deliberate: a
remembered palette would be the second table again, and the status strip already
explains an unreachable ETHOS.

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

### B11, standalone UE control, done

The Testbed page has a live UE panel: every UE ETHOS knows about with its driver,
control path, reachability, attach state and address, the port-5201 holder beside
it, and attach, detach and "free 5201" each behind a dialog showing ETHOS's own
preview.

What the panel is careful about is the same thing ETHOS is careful about.
`unknown` is a state and is drawn as one: an unreachable handset is never shown as
"detached", because one is a device that did not answer and the other is a device
that answered and is idle. A UE ETHOS does not drive is listed with its reason
rather than hidden.

Deploy and teardown are still not offered here, and that is a choice rather than a
gap. A deploy occupies a shared testbed for minutes, and RUN already deploys
exactly what the plan it is running needs and tears it down afterwards. A
standalone button would be a second way to occupy the testbed with no run to
attribute it to.

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
