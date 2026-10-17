"""What each O-Cloud is doing, for the card both pages show.

joule and the DGX Spark are deployed by different mechanisms and so say
different things: joule has helm releases and pods, the Spark has an op phase
and a lease. One card shape, two readings, and a reading that did not happen
is never reported as free or down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from console.rapps.ethos.client import EthosClient, EthosError

#: The console's own chip tones: green for up and free, amber for busy and
#: for a phase on the way, grey for down, red for a reading that failed. The
#: word is always shown, so the state never depends on seeing a colour.
OK = "ok"
BUSY = "warn"
WAIT = "warn"
IDLE = ""
BAD = "bad"

#: The configuration each card reads its O-Cloud through. Any config_id of
#: that O-Cloud answers the same question, so one per host is enough.
JOULE_CONFIG_ID = "ocudu-mono_swphy_pega_samsung_o5gs_joule"
SPARK_CONFIG_ID = "ocudu-mono_aerial_pega_samsung_o5gs_dgxspark"

#: Spark op phases that mean "on the way up", shown amber.
IN_FLIGHT = ("starting", "verifying", "ru_gap", "precheck", "queued",
             "recovery_cycle", "stopping", "post_stop")


@dataclass
class Row:
    label: str
    value: str


@dataclass
class OCloud:
    name: str
    word: str
    tone: str
    rows: list[Row] = field(default_factory=list)
    reason: str = ""

    @property
    def unreadable(self) -> bool:
        return self.tone == BAD


def _unreadable(name: str, reason: str) -> OCloud:
    return OCloud(name=name, word="can't read status", tone=BAD, reason=reason)


def joule_card(status: Any) -> OCloud:
    """free or busy, with the releases and pods that make it busy."""
    releases = [str(r) for r in (getattr(status, "releases", None) or [])]
    running = [str(p) for p in (getattr(status, "running_pods", None) or [])]
    free = bool(getattr(status, "node_free", False)) and not releases
    card = OCloud(name="joule", word="free" if free else "busy",
                  tone=OK if free else BUSY)
    card.rows = [
        Row("gNB release", ", ".join(releases) if releases else "none"),
        Row("pods running", str(len(running)) if running else "0"),
        Row("traffic", "running" if running and not free else "none"),
    ]
    reason = getattr(status, "node_reason", "") or ""
    if reason:
        card.rows.append(Row("node", reason))
    return card


def spark_card(status: Any) -> OCloud:
    """The op phase, the run holding it, and whether ETHOS holds the lease."""
    record = getattr(status, "ran_mode", None) or {}
    if not record.get("read_ok", False):
        return _unreadable("DGX Spark", record.get("reason") or "the Spark was not read")

    phase = str(record.get("phase") or "down")
    if phase == "up":
        word, tone = "up", OK
    elif phase in IN_FLIGHT:
        word, tone = phase, WAIT
    else:
        word, tone = "down", IDLE

    holder = record.get("holder")
    beat = record.get("heartbeat") or {}
    if holder and beat:
        last = beat.get("last_ok_at") or "not yet"
        lease = f"held by ETHOS, last beat {last}"
    elif holder:
        lease = "held, not by this process"
    else:
        lease = "free"

    card = OCloud(name="DGX Spark", word=word, tone=tone)
    card.rows = [
        Row("mode", str(record.get("mode") or "none")),
        Row("holder", str(holder) if holder else "none"),
        Row("lease", lease),
    ]
    drift = record.get("drift") or []
    if drift:
        card.rows.append(Row("drift", f"{len(drift)} finding(s)"))
    return card


#: What the plan form calls each O-Cloud, against what the cards call it.
SERVER_NAMES = {"joule": "joule", "dgx-spark": "DGX Spark"}


def card_for_server(cards: list[OCloud], server: str) -> OCloud | None:
    """The card for the O-Cloud a selection names, if it is one of these two."""
    wanted = SERVER_NAMES.get(str(server or "").strip().lower())
    if not wanted:
        return None
    return next((card for card in cards if card.name == wanted), None)


async def build_oclouds(client: EthosClient) -> list[OCloud]:
    """Both cards, each read on its own so one failure cannot hide the other."""
    cards = []
    for name, config_id, build in (
        ("joule", JOULE_CONFIG_ID, joule_card),
        ("DGX Spark", SPARK_CONFIG_ID, spark_card),
    ):
        try:
            cards.append(build(await client.deploy_status(config_id)))
        except EthosError as exc:
            cards.append(_unreadable(name, exc.message))
        except Exception as exc:                          # noqa: BLE001
            cards.append(_unreadable(name, str(exc)))
    return cards
