"""What differs between the two cores, laid out for the Show config panel.

Open5GS and free5GC are not two names for the same testbed. They hand out
addresses from different pools, answer iperf on different addresses, and carry
traffic over different tunnel interfaces, so a plan's configuration is not
fully stated until it says which core it is for.

The iperf half is here for the same reason. Which end holds port 5201, and
which binary answers on it, changes the number that comes back: the Magic
iPerf app on the handset and ETHOS's own server do not report the same rate
for the same link. A plan that differs from the runs it will be compared with
says so here, before it runs, rather than in an argument about the graph
afterwards.

Pure functions over data the pages already hold. Nothing here calls ETHOS.
"""

from __future__ import annotations

from dataclasses import dataclass

from console.rapps.ethos.metrics import NOT_MEASURED
from console.rapps.ethos.models import CoreState, Run, StatusSummary

#: Port 5201, named once. The console does not choose it; it reports it.
IPERF_PORT = 5201

#: What each `iperf_server` choice in the plan means on the wire, and the
#: `server_owner` a run served that way records. The console shows the label,
#: never the slug (GL-05).
SERVER_CHOICES: dict[str, tuple[str, str]] = {
    "app_binary": ("Magic iPerf app on the UE", "app_binary"),
    "ethos": ("ETHOS's own iperf3 server", "ethos"),
}

#: The direction each traffic mode names, in ETHOS's words.
TRAFFIC_MODES: dict[str, str] = {
    "ue_server": "iperf3 -s on the handset, client on the core",
    "ue_client_reverse": "handset is the client, downlink via -R",
}


@dataclass(frozen=True)
class Row:
    """One labelled fact in the panel. An empty value renders as n/a (GL-09)."""

    label: str
    value: str = ""
    hint: str = ""
    state: str = ""          # "" | "warn", for the one row that can be wrong

    @property
    def shown(self) -> str:
        return self.value or NOT_MEASURED


def core_rows(core: CoreState, planned: str | None) -> list[Row]:
    """The profile of the core this plan is for, whether or not it is running.

    Keyed off the PLAN, not off the host: a plan for free5GC written while the
    host runs Open5GS must show free5GC's pool, because that is what its runs
    will use once ETHOS switches.
    """
    name = _core_name(planned)
    profile = core.profile_for(name)
    if profile is None:
        return [
            Row(
                "Core",
                name or "",
                "ETHOS has no profile for this core, so its pool and data "
                "address are not known here",
            )
        ]

    running = core.core == profile.name
    return [
        Row("Core", profile.display or profile.name,
            "running now" if running else "ETHOS switches the host to it before the runs"),
        Row("UE pool", profile.ue_pool or "",
            "a UE address outside this pool is not an attach on this core"),
        Row("Core data IP", profile.core_data_ip or "",
            "the address iperf is served on, and the uplink client's target"),
        Row("Tunnel", profile.tunnel_iface or "",
            "the interface user-plane traffic crosses on the core host"),
        Row("AMF N2", profile.amf_n2 or "", "where the gNB sets up NGAP"),
        Row("Subscriber DB", profile.subscriber_db or "",
            "the two cores keep their subscribers separately"),
    ]


def iperf_rows(
    *,
    iperf_server: str,
    core: CoreState,
    planned: str | None,
    summary: StatusSummary | None = None,
) -> list[Row]:
    """How the traffic will be set up, and on which address.

    The bind address comes from the core profile rather than from a constant:
    it is 10.45.0.1 on Open5GS and the host's own address on free5GC, and
    getting that wrong measures the management path instead of the data one.
    """
    label, owner = SERVER_CHOICES.get(
        iperf_server, (iperf_server or "the service default", "")
    )
    profile = core.profile_for(_core_name(planned))
    mode = (summary.iperf_server.default_mode if summary else None) or ""

    rows = [
        Row("Traffic mode", TRAFFIC_MODES.get(mode, mode),
            "which end is the iperf3 server for this run"),
        Row("UE-side server", label, "the binary that answers on the handset"),
        Row("Recorded as", owner, "the server_owner each run will carry"),
        Row("Port", str(IPERF_PORT), "one iperf3 at a time holds it"),
        Row("Client bind address", (profile.core_data_ip if profile else "") or "",
            "the core side of the data path, from the core profile"),
    ]
    if summary is not None and summary.iperf_server.held:
        rows.append(
            Row("Holding it now", summary.iperf_server.owner,
                "something is already listening on the port")
        )
    return rows


# --- the comparison warning --------------------------------------------------

def reference_owner(runs: list[Run], core: str = "open5gs") -> tuple[str, int]:
    """Which server served most of the archived runs on *core*, and how many.

    Read from the archive rather than written down here. The reference is
    whatever the runs an operator will be comparing against actually used, and
    that is a fact about the data, not a constant to keep in step with it.
    """
    counts: dict[str, int] = {}
    for run in runs:
        if run.core != core:
            continue
        owner = (run.server_owner or "").strip()
        if owner:
            counts[owner] = counts.get(owner, 0) + 1
    if not counts:
        return "", 0
    best = max(counts.items(), key=lambda item: (item[1], item[0]))
    return best


def owner_warning(
    *, iperf_server: str, runs: list[Run], planned: str | None
) -> str:
    """A sentence when this plan would not be comparable, or "".

    Only raised for a plan on the OTHER core: comparing free5GC with Open5GS
    is the whole point of switching, and a different iperf server underneath
    that comparison would be a second variable in a two-core experiment.
    """
    if _core_name(planned) == "open5gs":
        return ""
    _label, owner = SERVER_CHOICES.get(iperf_server, ("", ""))
    reference, count = reference_owner(runs, "open5gs")
    if not owner or not reference or owner == reference:
        return ""
    return (
        f"the {count} Open5GS run(s) in the archive were served by "
        f"{_owner_label(reference)}, and this plan uses {_owner_label(owner)}. "
        f"The two do not report the same rate for the same link, so a "
        f"free5GC against Open5GS comparison would be measuring both at once."
    )


def _owner_label(owner: str) -> str:
    for label, slug in SERVER_CHOICES.values():
        if slug == owner:
            return label
    return owner or NOT_MEASURED


def _core_name(planned: str | None) -> str:
    """A plan's core label (`free5GC`) as the profile name (`free5gc`).

    The form holds the label, never the slug (GL-05), and the profiles are
    keyed by the slug. Lowercasing is the whole of the mapping, and it is done
    here rather than in six templates.
    """
    return str(planned or "").strip().lower()


# --- comparing the two cores -------------------------------------------------

#: What must match before two groups of runs differ only by their core. The
#: list is deliberately short: these are the things that change the number,
#: and anything else (the time of day, the campaign id) does not.
COMPARISON_KEYS: tuple[tuple[str, str], ...] = (
    ("topology", "gNB stack"),
    ("ue", "UE"),
    ("direction", "direction"),
    ("rates", "offered rates"),
    ("server_owner", "iperf server"),
    ("duration", "duration"),
)


@dataclass(frozen=True)
class CoreComparison:
    """Two sets of runs, one per core, and whether they may be compared.

    An Open5GS run beside a free5GC run is the whole point of core switching.
    It is also the easiest place to compare two things at once by accident: a
    different handset or a different iperf server underneath the two sides
    would show up as a core difference and be read as one.
    """

    by_core: dict[str, list[Run]]
    differences: list[str]
    unknown: list[Run]

    @property
    def cores(self) -> list[str]:
        return sorted(self.by_core)

    @property
    def is_cross_core(self) -> bool:
        return len(self.by_core) > 1

    @property
    def comparable(self) -> bool:
        return self.is_cross_core and not self.differences and not self.unknown


def compare_cores(runs: list[Run]) -> CoreComparison:
    """Group runs by the core that served them, and say what else differs.

    A run whose core was never confirmed goes in `unknown` and is counted
    against comparability rather than assigned to a side. Guessing it would
    put a number in the series it is most likely to be wrong in.
    """
    by_core: dict[str, list[Run]] = {}
    unknown: list[Run] = []
    for run in runs:
        name = run.core
        if not name:
            unknown.append(run)
            continue
        by_core.setdefault(name, []).append(run)

    differences: list[str] = []
    if len(by_core) > 1:
        for key, label in COMPARISON_KEYS:
            seen = {_facet(group, key) for group in by_core.values()}
            if len(seen) > 1:
                differences.append(
                    f"{label} differs between the cores: "
                    + " against ".join(sorted(value or NOT_MEASURED for value in seen))
                )
    return CoreComparison(by_core=by_core, differences=differences, unknown=unknown)


def _facet(runs: list[Run], key: str) -> str:
    """One group's value for a comparison key, as a stable string."""
    if key == "topology":
        return ",".join(sorted({run.head for run in runs if run.head}))
    if key == "ue":
        return ",".join(sorted({_field(run.config_id, 3) for run in runs}))
    if key == "direction":
        return ",".join(sorted({run.direction or "" for run in runs}))
    if key == "rates":
        return ",".join(
            sorted(f"{run.offered_mbps:g}" for run in runs if run.offered_mbps is not None)
        )
    if key == "server_owner":
        return ",".join(sorted({run.server_owner or "" for run in runs}))
    if key == "duration":
        return ",".join(
            sorted(
                f"{run.duration_requested_s:g}"
                for run in runs
                if run.duration_requested_s is not None
            )
        )
    return ""


def _field(config_id: str | None, index: int) -> str:
    fields = (config_id or "").split("_")
    return fields[index] if len(fields) > index else ""
