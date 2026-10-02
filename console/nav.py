"""The navigation, its badges, and the backend-readiness card.

The sidebar is grouped because the console does four different jobs, plan a
test, read what came out, look after the testbed, and read the documentation,
and a flat list of nine items hides that.

A badge is only shown when it counts something real. A count that could not be
made stays absent rather than showing 0: "0" reads as "nothing is running", which
is a claim a console that could not ask has no business making.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The six changes the Overview's readiness card tracks. They are the ones that
# turn the console from a viewer into a control surface.
TRACKED = ("lock", "jobs", "catalogue", "readiness", "status_summary", "plots")


@dataclass(frozen=True)
class Item:
    label: str
    href: str
    icon: str
    phase: str = ""            # set when the section is not built yet
    badge_key: str = ""        # which count to show, if any


@dataclass(frozen=True)
class Group:
    name: str
    items: tuple[Item, ...]
    open: bool = True


GROUPS: tuple[Group, ...] = (
    Group(
        "Essentials",
        (
            Item("Overview", "/", "overview"),
            Item("Test Plan", "/plan", "plan"),
            Item("Jobs", "/jobs", "jobs", badge_key="jobs"),
        ),
    ),
    Group(
        "Measure",
        (
            Item("Results", "/results", "results", badge_key="new_runs"),
            Item("Graphs", "/graphs", "graphs"),
        ),
    ),
    Group(
        "Network",
        (
            Item("Testbed", "/testbed", "testbed"),
            Item("O1", "/o1", "o1", phase="Phase 3", badge_key="alarms"),
            Item("O2", "/o2", "o2", phase="Phase 4"),
        ),
    ),
    Group(
        "System",
        (
            Item("GitHub", "/publication", "export"),
            Item("Docs", "/docs", "docs"),
        ),
    ),
)


@dataclass
class Badges:
    """Counts for the sidebar. ``None`` means "could not be counted"."""

    jobs: int | None = None
    new_runs: int | None = None
    alarms: int | None = None

    def get(self, key: str) -> int | None:
        return getattr(self, key, None) if key else None

    def tone(self, key: str) -> str:
        return "grey" if key == "new_runs" else ""


@dataclass
class BackendReadiness:
    """How much of the ETHOS backend the console is waiting for.

    It fills in by itself: the capability probe finds each endpoint as it lands,
    and this reads the probe rather than a list anyone has to maintain.
    """

    ready: int
    total: int
    pending: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.ready >= self.total

    @property
    def fraction(self) -> float:
        return self.ready / self.total if self.total else 1.0

    @property
    def summary(self) -> str:
        return f"{self.ready} of {self.total} ready"

    @property
    def next_up(self) -> str:
        return self.pending[0] if self.pending else ""


def backend_readiness(caps) -> BackendReadiness:
    from console.capabilities import BY_KEY

    ready = [key for key in TRACKED if caps.ready(key)]
    pending = [
        f"{BY_KEY[key].change}, {BY_KEY[key].what}"
        for key in TRACKED
        if not caps.ready(key) and key in BY_KEY
    ]
    return BackendReadiness(ready=len(ready), total=len(TRACKED), pending=pending)
