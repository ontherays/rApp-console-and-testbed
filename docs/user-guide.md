# Testbed Console User Guide

For anyone with access to the Testbed Console who wants to run a test on the
BMW Lab O-RAN testbed and look at the results.

You do not need to install or configure anything. The console runs on the lab
host; you use it from a browser.

---

## 1. Login

1. Open `https://192.168.8.78:8443` in a browser on the lab network.
2. The browser warns that the certificate is not trusted. Accept it once.
3. Enter the console password and select **Log in**.

After login you land on **Overview**.

If the password is wrong, the page says `That password is not correct.` and how
many attempts are left. After five failed attempts login is refused for ten
minutes and the password box is disabled until then.

Your session ends 12 hours after login, or after 2 hours without activity. The
login page says which. **Log out** is at the foot of the left sidebar.

### Getting around

The sidebar is grouped:

| Group | Pages |
|---|---|
| Essentials | Overview, Test Plan, Jobs |
| Measure | Results, Graphs |
| Network | Testbed, O1, O2 |
| System | Docs |

O1 and O2 are marked with the phase they arrive in and hold no data yet.

Two things sit beside the list:

- **Search**, at the top. Type a run id to open that run, or anything else to
  list matching configurations, campaigns and runs. Press <kbd>/</kbd> anywhere
  to jump into it.
- **ETHOS backend**, at the foot, for example `5 of 6 ready`. ETHOS is the
  service that runs the tests. When something it provides is not available, the
  control that needs it is disabled and says so instead of failing when you
  select it.

**New test** in the page header takes you to Test Plan from anywhere.

---

## 2. Overview

What the testbed has been doing, and whether it is free right now.

Two selectors at the top control everything below them:

- Period: **24 hours**, **7 days**, **30 days**.
- Subset: **All runs**, **DL**, **UL**, **Needs attention**.

The page shows:

- **Testbed lock**, **Deployed now** and **Latest job**. Check these before
  starting a test. A held lock means somebody else is using the testbed.
- Four figures for the period: runs, best DL throughput, median PUSCH SNR and
  data freshness, each with its change against the previous period.
- **Runs by topology**, one hexagon per run.
- **Throughput over time**, the best achieved rate of each day. A day with no
  run is an empty column, not a zero.
- **Topologies that need you**, least complete first. **Review** opens that
  topology's latest sweep.

**Export** downloads the runs behind the current selection.

---

## 3. Test Plan

A test plan is one test: what to run it on, what traffic to send, and what to
call it. Open **Test Plan**.

### Choose the topology

1. Select **Change topology**.
2. On the **Presets** tab, select a card. Each shows the chain end to end, when
   it last ran and what it achieved. One click selects it.
3. For a combination with no preset, use the **Custom** tab and pick each
   component. Options that cannot be deployed are greyed out with the reason.
4. Close the panel. The topology card shows the chain, its status chips and the
   generated `config_id`.

On **Custom**, the CU and DU vendor groups follow the split. With *Monolithic*
selected they are fixed and disabled. Choose *CU + DU* to set them separately.

### Set the traffic

- **Direction**: *Downlink, core to UE* or *Uplink, UE to core*.
- **Offered load**, in Mbit/s. One rate (`500`), a list (`100,200`) or a range
  (`100-1000:100`).
- **Duration per rate**, in seconds. Minimum 5 s.
- **Repeats**, 1 to 20 per rate.
- **iperf server**: *Magic iPerf app on the UE* or *ETHOS server*. This chooses
  which end holds port 5201 for this job.

### Options

- **Label**. Used as the campaign id prefix and the figure label.
- **Radio samples**. Keeps per-second samples. Off by default, for debugging.

### Check readiness, then run

The **Readiness** panel on the right judges the plan against the testbed and
lists seven checks. Below it, the estimate, for example
`10 point(s), about 13 min` including deploy and teardown.

1. Read the checks. A **failed** check disables **RUN** and the RUN tooltip
   names it. A check that could not be made is reported but does not block.
2. Select **RUN**, in the page header or at the foot of the readiness panel.
3. A dialog shows what will happen, in the words of the service that will do it.
   Nothing has been sent yet.
4. Confirm to start the job. You are taken to its live page.

### Saving a plan

- **Save as** names it, then **Save plan** keeps it on the console host.
- Saved plans are listed under **Saved plans**. Select one to load it back.
- **Download .json** and **Download .yaml** save the plan document to your
  machine.

**Plan document** shows exactly what RUN will send, as **JSON**, **YAML** or an
**ETHOS test definition**. The radio parameters there are *planned* values; what
actually ran appears on each run's **Cell config** tab.

---

## 4. Jobs

A job is one execution of a test plan: a sweep that deploys the topology, sends
traffic at each rate, then tears down. Each rate produces one **point**, and
each point is one **run**.

Open **Jobs** for every job, newest first.

The table gives the job id, state, topology, plan, points (for example
`10 of 10`), and when it started and ended. States you will see are `running`,
`completed`, `aborted` and `interrupted`.

### Watching a job

1. Select **Open** on the job.
2. The page shows its state, its steps as each finishes, its points as each is
   measured, and a live log.
3. **Stop** asks the job to stop at the next point boundary, behind a
   confirmation. The point being measured finishes and is kept; nothing already
   measured is thrown away. The job ends `aborted`.

The log survives a page refresh and resumes where it left off.

### From a job to its data

- **Plot this job** on the job page opens Graphs with that job already selected.
- Results holds every run the job produced.

### Campaigns

Below the job list, runs that carry a campaign id are grouped by campaign, with
**Review** to open the sweep. A campaign id is a label you set through the plan's
**Label** field. Runs without one do not group here; they are all under Results.

### Holding a sweep out of graphs

If a sweep was invalid, for example because the UE detached partway, you can
keep it out of new figures without losing it.

1. Select **Hold out** on the job row.
2. The dialog shows the job and its run counts, and asks for a reason. The
   reason is required.
3. Confirm.

Nothing is deleted. The runs, the results and every figure already drawn stay
exactly as they were. Held-out sweeps are listed under **Held out of graphs**
with the reason and the date, and **Restore** puts one back.

---

## 5. Results

Every run the testbed has archived. Open **Results**.

A run is one measurement: one offered load, one direction, one repetition.

### Finding runs

Set the filters, then select **Apply**. **Clear all** resets them.

- **Topology**, **Direction**, **Offered**, **TDD**, **Bandwidth**, **Campaign**
- **From (UTC)** and **To (UTC)**
- **Include**: *has quality flags*, *show unusable runs*

The header shows how many runs match, for example
`272 run(s) of 788 archived · page 1 of 6`.

Unusable runs are hidden by default. A run with no delivered bytes, or one whose
iperf server is unrecognised, cannot be analysed. Tick **show unusable runs** to
see them. **If the table looks empty, check this first.**

**Export** downloads the filtered set as CSV.

### Reading one run

Select **open** on a row. The run page has six tabs:

| Tab | What it holds |
|---|---|
| Summary | Offered and achieved throughput, loss, delivered bytes, durations, timing |
| Channel conditions | SNR, BLER, MCS, CQI, RI |
| Latency | RTT |
| Cell config | What the cell actually ran, as measured |
| Config | The configuration the run used |
| Raw | The full record |

Two conventions apply everywhere:

- Achieved throughput is `achieved_over_tx_mbps`. It is the only throughput
  comparable across stacks.
- A value that was not measured shows `n/a`, never 0.

A job with no result usually means it was stopped or failed before any point was
measured. Its job page says what happened.

---

## 6. Graphs

Figures are drawn by the service that ran the tests, so a figure from here and
the same request from the command line are identical. Open **Graphs**.

The form is **Request a figure**. Work down it.

### Time range

Set **Since** and **Until** as `YYYY-MM-DD`. Changing either re-lists the sweeps
below. Both ends are included.

### Sweeps

One row per job that ran in that window, showing its id, its topology, its
offered range, its run count and its state.

- Tick the sweeps to draw. Several ticked sweeps are combined into one figure.
- **Select all** ticks every sweep that is not held out.
- **Clear** unticks everything.
- Leave every box clear to plot the whole date range instead.

**Reading the run count.** `10/10 runs` means ten runs recorded a measurement
and ten are available to draw. The two numbers are usually the same. When they
differ, for example `6/10 runs`, that sweep finished with runs that recorded
nothing; the count is highlighted and the hover says how many.

**Held-out sweeps** appear greyed with the reason they were held out, and cannot
be ticked. To use one anyway, tick **Include quarantined jobs**; the rows become
selectable and the figure records that they were included.

### Naming runs directly

Under **Name a campaign, job or run directly** you can give **Run ids**, a
**Campaign** or a **Job** by name. These fill in automatically when you arrive
from Results, from a sweep or from **Plot this job**. A job named here is added
to whatever is ticked above.

**Filter instead** offers **Configurations**, **Offered loads** and
**Direction** as an alternative to naming anything.

### What to draw

- **Metric**: Received throughput (Mbit/s), Loss (%), RTT p95 (ms), PUSCH SNR
  (dB), Residual BLER DL, Residual BLER UL, MCS DL (index), MCS UL (index), CQI
  (index), RI DL (layers). The note under it carries any caveat for the metric
  you chose.
- **Label**: what to call the figure.

Some metrics are deliberately not offered, and the page lists them with the
reason. First-transmission BLER and PUCCH SNR are available on one stack only,
so they cannot be compared across stacks.

### How it looks

- **Kind**: `auto`, `line` or `bar`.
- **Group by**: `config` pools repeats into a mean, `run` keeps each run
  separate.
- **Width**: single or double column.
- **Y scale**: `auto`, `linear` or `log`. `auto` uses the metric's own default.

### Which runs are allowed in

- **Minimum duration (s)**: excludes shorter runs.
- **Allow run lengths to differ between points**.
- **Exclude stacks with a known defect**.
- **Include runs whose serving binary is unrecorded**.

### Generate

Select **Generate figure**. Figures are made one at a time, so there may be a
short wait.

When it finishes you get the image, any caveats as a bar above it, a **Data**
section with the points, the number of runs behind each one and every dropped
run with its reason, and downloads for **PNG**, **PDF**, **raw.csv** and
**points.csv**.

If the request cannot produce a figure, the refusal explains why. One case has a
shortcut: if run lengths differ *between* points, the panel offers **Retry
allowing mixed durations**. Two different lengths *inside* one point are always
refused, because an average across them describes neither run; narrow the
selection with a minimum duration, or name the runs you want.

Below the form is the gallery of existing figures, newest first, each marked
**CLI** or **Console**, with **Open**, **PNG** and **Regenerate**.

**Regenerate** redraws a figure from the data stored with it, so it reproduces
the original. Figures do not change afterwards: holding a sweep out tomorrow
does not alter a figure drawn today. To apply a new selection, generate a new
figure.

---

## 7. Testbed

What the testbed is made of right now. Open **Testbed**.

### UEs

A table of the handsets and dongles, with driver, state, data-plane address and
who holds port 5201. **Re-read** refreshes it.

Each UE that can be driven offers:

- **Attach**, to bring it onto the network.
- **Detach**, to take it off.
- **Free 5201**, when something is holding the iperf port.

Every action shows a preview first and is refused while somebody else holds the
testbed.

An attach is confirmed by the UE getting a `10.45.x` address. With no gNB
deployed there is no cell to register on, so an attach will correctly report
that it found no address.

Not every UE can be driven. The TM500 is attached and detached from its own
chassis, and the page says so on its row.

### Deployed now

What is installed on the testbed. Normally nothing: a job deploys what its plan
needs and tears it down afterwards.

Deploying on its own is not offered. RUN already deploys what the plan needs, so
a separate deploy would occupy the shared testbed with no test to account for it.

---

## 8. Typical workflow

1. Log in. On **Overview**, check **Testbed lock** and **Deployed now** are free.
2. Open **Test Plan**. Select **Change topology** and pick a preset.
3. Set direction, offered load, duration and repeats.
4. Read the **Readiness** panel. Fix anything that failed.
5. Select **RUN** and confirm the preview.
6. Watch the job on its page until it completes.
7. Open **Results** to read the individual runs, or **Plot this job** to go
   straight to Graphs with the sweep selected.
8. On **Graphs**, choose a metric, then **Generate figure**.
9. Download the PNG or PDF.

If a sweep turns out to be invalid, open **Jobs**, select **Hold out** on it and
give a reason. It stays in Results and in any figure already drawn, and is left
out of new ones.
