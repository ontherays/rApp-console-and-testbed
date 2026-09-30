# testbed-console, implementer constraints (read before coding)

## What this is
The **Testbed Console & Dashboard**: a web console for planning, running,
watching and reviewing tests on the BMW Lab O-RAN testbed. ETHOS is the first
rApp it drives. Python 3.12 + FastAPI + Jinja2, server-rendered, htmx for live
updates, Shoelace components, no JavaScript build step.

Runs as the systemd user service `testbed-console` on the KVM host
(192.168.8.78), HTTPS on 8443, one password.

Standing rules for commits, branches, guides and reports:
`~/.claude/skills/ravi-rules/SKILL.md`.
The contract: `docs/01-requirements.md` … `docs/04-build-plan.md`. Requirement ids
(`TP-04`, `RS-12`, `GL-09`) and backend-change ids (`B1`–`B16`) refer to them.

## Hard rules (never violate)
- **The console presents; ETHOS acts.** No InfluxDB query, no SSH, no kubectl, no
  adb, no helm, not "just for one panel". Every fact comes through an ETHOS
  endpoint, because ETHOS holds every credential (SE-06). ETHOS stays on
  127.0.0.1:8081 (SE-07).
- **`console/rapps/ethos/client.py` is the only file that talks to ETHOS.** A page
  never builds a URL.
- **Never call `GET /runs/{id}/ee-kpi` without `persist=false`.** It writes the
  manifest by default; a console read must leave no fingerprint on a run record.
- **Never assemble a `config_id`.** `POST /testdef/generate` is the only source.
  Never derive a vendor by prefix-matching one either, `oai-mixoaiocu` starts
  with "oai" and is not a pure-OAI run. Match the head exactly, via
  `rapps/ethos/series.py`.
- **A value that was not measured renders ",", never 0** (GL-09). A stack that has
  no such counter and a counter that was not measured are both absences.
- **Nothing acts on one click** (GL-07). Every state-changing action goes through a
  confirmation that shows ETHOS's own preview.
- **The console adds no readiness check of its own.** `POST /readiness` (B5) exists
  so the CLI and the console judge readiness identically; a second opinion is
  worse than one. The traffic-plan parse is a *pre-check* and is labelled as one.
- **Never invent a second campaign executor.** The console has the same API the
  CLI drives, and running campaigns from the web process, with the lock outside
  ETHOS: is exactly what the design forbids. One executor, in ETHOS (B2).
- **Show the option `label`, never the `slug`** (GL-05). The split slugs
  `mixocuoai` / `mixoaiocu` no longer match any `config_id` head.
- **No CDN** (SE-09). Every asset is vendored under `static/vendor/`, recorded in
  `docs/vendor-versions.md`, and the CSP is `default-src 'self'`.
- **No CORS middleware, ever.** The browser talks only to the console; the console
  talks to ETHOS server-side.
- **Never use an em dash.** Not in a template, not in a Python string that reaches
  the screen, not in `docs/`. A comma, a colon, a full stop or brackets instead.
  `tests/unit/test_no_em_dash.py` fails on one. The "not measured" marker is the
  word `n/a`, defined once as `metrics.NOT_MEASURED`, because GL-09 spells it as
  a dash and this rule outranks that.
- **A selected option is styled from its own `:checked` state, never from a class
  the server wrote.** Most option groups sit in cards the form does not
  re-render, so a server-written class stays on whichever option was selected
  when the page loaded, and two options look selected at once.

## The capability gate (this is the shape of the whole thing)
Every feature the console offers depends on an ETHOS endpoint, and not all of them
exist. `console/capabilities.py` declares each one with the endpoint it needs and
its `B`-number, probes them every 60 s, and a page renders
`caps.ready(key)` / `caps.why(key)`. The catalogue (B4) and server-side results
queries (B10) are the ones still outstanding.

**A feature that is not built is a disabled control that names its backend change,
never a button that fails on click and never a silently missing panel.** When a
change lands the probe finds the endpoint and the page lights up; deleting the
entry from `FEATURES` is the last step. `docs/ethos-backlog.md` is the full list.

## The read-only stand-ins (delete, do not extend)
Two files read ETHOS's data directly because the endpoint that should serve it
does not exist. Both are plain data files on this host, read and never written,
holding no credential. **Neither is a pattern to copy.** Delete each one when its
backend change lands, as `rapps/ethos/figures.py` was deleted when B9 did.
- `rapps/ethos/profiles.py` reads `deployment/deploy_profiles.yaml` for
  deployability → deleted when `GET /catalogue` lands (B4). Its `OPTION_REASONS`
  table is hard-coded prose and is the weakest part of the console.
- `rapps/ethos/query.py` filters, sorts, pages and writes CSV in the console
  because `GET /runs` takes no limit and re-reads every manifest → deleted when
  B10 lands.

## Metric display (`rapps/ethos/metrics.py`), requirements §7.4
The rules are **a data table, not template conditionals**, and each row has a
test against a recorded manifest from both stacks. They exist to prevent a false
cross-vendor comparison:
- Throughput is `achieved_over_tx_mbps`. MAC bitrate (OCUDU) and goodput (OAI)
  differ by header overhead and never share the column.
- "Residual BLER" (both stacks) and "First-transmission BLER" (OAI only) never
  share a column or an axis. Never plain "BLER". First-tx read 0.46 on an idle
  link whose residual BLER was 0.
- Only PUSCH SNR is compared across stacks. PUCCH SNR is a different channel.
- Four fields are called RSRP and stay four fields. OCUDU's `gnb_ul_rsrp_db` is
  *relative* dB, not dBm, about −11 where the dBm values read −69.
- MCS carries its table and its cap; at the cap it is marked "capped". OCUDU
  clamps at 27 DL / 24 UL, OAI sets none.
- RI is always direction-labelled. RI UL reads 1 on both stacks despite 4T4R.
- CQI is DL only, with the CSI-RS caveat: OCUDU read 14 where OAI read 11 under
  the same conditions, and that is not a channel difference.
- The TDD pattern is a chip on every result: OCUDU 7D2U over 5 ms, OAI DDDSU over
  2.5 ms.

## Configuration
`console/settings.py` declares every `CONSOLE_*` name as an `ENV_*` constant;
`console/variables.py` derives the list by importing it, and a test compares it
against `console.env.example` **in both directions**. Adding a variable means
adding it to the example.

The real environment always wins over the file. **A comment goes on its own line**:
systemd's `EnvironmentFile=` keeps a trailing `# comment` as part of the value,
which once made uvicorn refuse to start with `KeyError: 'info  # uvicorn log
level'`. A test enforces it. Blanks are `KEY=""`, never bare.

## Tests
`.venv/bin/python -m pytest -q`. Everything runs against `tests/fake_ethos`,
which replays `tests/recorded/`, captured from the real API by `tests/record.py`,
read-only endpoints only (NF-07). No test touches the testbed.
`tests/conftest.py` pins `CONSOLE_ENV_FILE` to a nonexistent path before any
console import, so a real `console.env` can never change what the suite sees.

## Restarting
Restarting the console never disturbs a campaign: it holds no testbed state,
starts no traffic and runs no job. Restarting `ethos-rapp` does, check no
campaign is running first, and say so.
