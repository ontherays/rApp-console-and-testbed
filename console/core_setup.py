"""Comparing runs measured on the two different 5G cores.

Open5GS and free5GC are not two names for the same testbed: they hand out
addresses from different pools and carry traffic over different tunnel
interfaces. Putting their numbers side by side is the point of switching
between them, and is also the easiest place to move two variables at once.

This used to describe a plan's core profile and iperf setup for a panel on
the Test Plan. That panel is gone; the same facts live on each run record and
in ETHOS's own `GET /core`, which are the places they can still be read after
the fact.

Pure functions over data the pages already hold. Nothing here calls ETHOS.
"""

from __future__ import annotations

from dataclasses import dataclass

from console.rapps.ethos.metrics import NOT_MEASURED
from console.rapps.ethos.models import Run


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
