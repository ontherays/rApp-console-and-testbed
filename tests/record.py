"""Capture ETHOS responses into ``tests/recorded/``, so the fixtures are real.

    .venv/bin/python tests/record.py                     # against 127.0.0.1:8081
    .venv/bin/python tests/record.py --api http://…

**Read-only, by construction.** The list below is explicit and holds only
endpoints that read: nothing here deploys, attaches a UE, starts traffic, writes
CM or persists to a manifest. ``GET /runs/{id}/ee-kpi`` is deliberately absent,
it writes the manifest unless told not to, and a fixture is not worth a
fingerprint on a run record.

The run list is trimmed to a handful of runs that between them exercise the
display rules: an OCUDU run, an OAI run, one with channel metrics, one that was
defined and never ran.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RECORDED = HERE / "recorded"

# (filename, method, path, body)
READS: tuple[tuple[str, str, str, dict | None], ...] = (
    ("healthz", "GET", "/healthz", None),
    ("compatibility", "GET", "/compatibility", None),
    ("deploy_status", "GET", "/deploy/status", None),
    ("status_health", "GET", "/status/health", None),
    ("cm_params_writable", "GET", "/cm/params/writable", None),
    (
        "testdef_generate",
        "POST",
        "/testdef/generate",
        {
            "selection": {
                "ue": "Samsung",
                "ru": "Pegatron",
                "gnb_stack": "OCUDU",
                "gnb_split": "monolithic",
                "l1_backend": "software-PHY",
                "core": "Open5GS",
                "server": "joule",
            }
        },
    ),
    # B1, B2, B5, B6, B11. Reads only, and the one POST among them is
    # /jobs/preview, which sends nothing to the testbed: it describes what a job
    # WOULD do and mints a token nobody uses. Recording POST /jobs would start a
    # campaign on a shared testbed, so it is deliberately absent.
    ("lock", "GET", "/lock", None),
    ("jobs", "GET", "/jobs", None),
    ("status_summary", "GET", "/status/summary", None),
    ("ue", "GET", "/ue", None),
    ("ue_iperf", "GET", "/ue/samsung/iperf", None),
    # B9. Reads only: `/plots` lists what already exists and `/plots/options`
    # and `/plots/series` are static tables. POST /plots is NOT recorded, because
    # recording it would draw a figure into the real graph directory.
    ("plots", "GET", "/plots", None),
    ("plot_options", "GET", "/plots/options", None),
    ("plot_series", "GET", "/plots/series", None),
    (
        "readiness",
        "POST",
        "/readiness",
        {
            "config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule",
            "direction": "DL",
            "rates": "100,200",
            "duration": "30s",
            "repeats": 1,
            "iperf_server": "app_binary",
        },
    ),
    (
        "job_preview",
        "POST",
        "/jobs/preview",
        {
            "config_id": "ocudu-mono_swphy_pega_samsung_o5gs_joule",
            "direction": "DL",
            "rates": "100,200",
            "duration": "30s",
            "repeats": 1,
            "iperf_server": "app_binary",
        },
    ),
)

MAX_RUNS = 12


def fetch(api: str, method: str, path: str, body: dict | None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        api.rstrip("/") + path,
        data=data,
        method=method,
        headers={"content-type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def interesting(runs: list[dict]) -> list[dict]:
    """A few runs that between them cover the display rules."""
    picked: list[dict] = []

    def take(predicate, limit=2):
        for run in sorted(runs, key=lambda r: r.get("t_created") or "", reverse=True):
            if len(picked) >= MAX_RUNS:
                return
            if run in picked:
                continue
            if predicate(run):
                picked.append(run)
                limit -= 1
                if limit <= 0:
                    return

    def vendor(run, name):
        return (run.get("config_id") or "").startswith(name)

    take(lambda r: r.get("radio_summary") and vendor(r, "oai"))
    take(lambda r: r.get("radio_summary") and vendor(r, "ocudu"))
    take(lambda r: r.get("radio_ref"))                       # a run with samples
    take(lambda r: r.get("campaign_id"), limit=4)            # something to sweep
    take(lambda r: r.get("status") == "defined")             # never ran: all nulls
    take(lambda r: r.get("direction") == "UL")
    take(lambda r: r.get("delivered_bytes"), limit=3)
    return picked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8081")
    args = parser.parse_args()

    RECORDED.mkdir(parents=True, exist_ok=True)
    for name, method, path, body in READS:
        status, payload = fetch(args.api, method, path, body)
        if status >= 300:
            print(f"  {name:22} HTTP {status}, not recorded")
            continue
        (RECORDED / f"{name}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  {name:22} HTTP {status} recorded")

    status, listing = fetch(args.api, "GET", "/runs", None)
    if status < 300 and isinstance(listing, dict):
        runs = interesting(listing.get("runs") or [])
        trimmed = {"count": len(runs), "filters": {}, "runs": runs}
        (RECORDED / "runs.json").write_text(
            json.dumps(trimmed, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  runs                   HTTP {status} recorded {len(runs)} of "
              f"{listing.get('count')}")
    else:
        print(f"  runs                   HTTP {status}, not recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
