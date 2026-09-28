"""ETHOS's readiness verdict, ready to render.

**The console judges nothing here.** `POST /readiness` returns seven checks with a
status and a reason each, and this turns them into rows in the order ETHOS sent
them. It never upgrades an `unknown` to a pass, never downgrades one to a
failure, and never adds an eighth check of its own: two opinions about whether the
testbed is ready is worse than one, and the endpoint exists precisely so that the
CLI and the console agree.

Two things are the console's to supply, because they are presentation rather than
judgement:

* a **label** per check id, so a row reads "Nothing else is deployed" instead of
  `node_free`; and
* the **holder wording**, so a lock held by a shell campaign reads
  "CLI campaign ..." here exactly as it does in the status strip. ETHOS's own
  sentence names `cli:<pid>`, which means nothing to somebody who did not start
  it.
"""

from __future__ import annotations

from dataclasses import dataclass

from console import holders
from console.rapps.ethos.models import Readiness, ReadinessCheck

#: What each check is called on screen. A check id ETHOS adds later still renders,
#: under its own id, rather than being dropped for want of a label here.
#:
#: A label names what is being checked, never the outcome it hopes for: "Testbed
#: lock is free" followed by the reason "held by CLI campaign ..." contradicted
#: itself on screen.
LABELS: dict[str, str] = {
    "topology": "Topology validates and is deployable",
    "lock": "Testbed lock",
    "node_free": "Nothing else is deployed",
    "ue_reachable": "The UE answers on its control path",
    "iperf_server": "The iperf server is in the state this plan needs",
    "traffic_plan": "The traffic plan parses and is in range",
    "core": "The core answers from the node",
}

PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Row:
    """One readiness check, as a row. Shaped for `check_item` in the macros."""

    id: str
    label: str
    status: str
    reason: str
    checked_at: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def failed(self) -> bool:
        return self.status == FAIL


def label_for(check_id: str) -> str:
    return LABELS.get(check_id, check_id.replace("_", " "))


def rows(readiness: Readiness, lock=None, *, tz: str = "Asia/Taipei") -> list[Row]:
    """ETHOS's checks as rows, in ETHOS's order.

    *lock* is the `/lock` body when there is one. It is used for one thing: to
    word the `lock` row the way every other holder is worded. ETHOS's reason is
    kept when there is no holder to name, so nothing is invented if the two
    disagree about whether the testbed is held.
    """
    out: list[Row] = []
    for check in readiness.checks:
        reason = check.reason
        if check.id == "lock" and check.failed and holders.describe(lock, tz=tz) != holders.FREE:
            reason = f"held by {holders.describe(lock, tz=tz)}"
        out.append(
            Row(
                id=check.id,
                label=label_for(check.id),
                status=check.status,
                reason=reason,
                checked_at=check.checked_at,
            )
        )
    return out


def unavailable(reason: str) -> list[Row]:
    """The panel when ETHOS could not be asked at all.

    Every check reads `unknown` with the same reason, which is the truth: nothing
    was judged. A panel of passes drawn from a failed request would be the worst
    possible outcome here.
    """
    return [
        Row(id=check_id, label=label_for(check_id), status=UNKNOWN, reason=reason)
        for check_id in LABELS
    ]


def first_failure(rows_: list[Row]) -> Row | None:
    """The reason a disabled RUN gives. A failure, never merely an unknown.

    ETHOS blocks on a failure and surfaces an unknown without blocking, and the
    button follows that: a check that could not be made must not stop a run that
    would have worked.
    """
    return next((row for row in rows_ if row.failed), None)
