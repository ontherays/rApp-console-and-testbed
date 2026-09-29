"""One colour per stack, taken from ETHOS rather than copied (GL-05).

A chip on a results page and a line in the figure beside it must be the same
colour for the same stack, or the page and the figure become two spellings of
one thing. This used to hold its own copy of ETHOS's table, which was honest
about being a risk. `GET /plots/series` ended that: the palette is fetched, held
in one cache, and refreshed by the capability probe, so there is no second
table to drift.

**What is still the console's.** ETHOS says how a stack is DRAWN: colour,
marker, line style, hatch, label and order. It does not know about the
two-letter tile this console puts beside a run, nor about the legacy head
spellings, because its own lookup resolves those internally and its served list
is keyed by the current heads. Both stay here, and both are presentation rather
than measurement.

**When ETHOS has not answered.** Every stack renders in the neutral fallback
and says "unknown stack". That is deliberate: a remembered palette would be a
second table again, and a wrong colour is worse than an obviously absent one.
The status strip already says ETHOS is unreachable, so the grey is explained.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class Series:
    head: str
    label: str
    colour: str
    marker: str
    linestyle: str
    code: str
    """Two letters for a tile, unique per head.

    The console's own, because ETHOS has no such concept. Derived from the head
    rather than from the label: four different splits abbreviate to "OD" from
    their labels, and two monolithic stacks to "OM", which would put the same
    tile on different topologies.
    """
    hatch: str = ""
    note: str = ""
    order: int = 99


#: Legacy head spellings. ETHOS resolves these inside `series_for`, but its
#: served list is keyed by the current heads, so a run archived before the
#: rename is mapped here and keeps its own colour instead of falling to grey.
ALIASES: dict[str, str] = {
    "ocudu-mixocuoai": "ocuducu-oaidu",
    "oai-mixoaiocu": "oaicu-ocududu",
}

FALLBACK = Series("", "Unknown stack", "#666666", "P", "dotted", "??")

#: Two letters per head. Fixed here so a tile cannot change when ETHOS relabels
#: a stack, and unique by construction.
CODES: dict[str, str] = {
    "oai-cudu": "AD",
    "oaicu-ocududu": "AO",
    "ocuducu-oaidu": "OA",
    "ocudu-cudu": "OD",
    "oai-mono": "AM",
    "ocudu-mono": "OM",
}


class Palette:
    """The fetched palette, read from request handlers and templates.

    Held behind a lock because the capability probe replaces it on its own task
    while pages read it. Replaced wholesale rather than mutated, so a reader
    always sees one consistent table.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_head: dict[str, Series] = {}
        self._order: tuple[str, ...] = ()
        self.fetched = False

    def replace(self, payload) -> None:
        """Take ETHOS's answer as the whole truth about how stacks look.

        An answer carrying no series is ignored rather than applied. Blanking
        every chip on every page because one response came back empty is worse
        than showing the palette that was working a minute ago, and an empty
        palette is not something ETHOS has any reason to send.
        """
        if not getattr(payload, "series", None):
            return
        by_head: dict[str, Series] = {}
        for entry in payload.series:
            by_head[entry.head] = Series(
                head=entry.head,
                label=entry.label,
                colour=entry.colour,
                marker=entry.marker,
                linestyle=entry.linestyle,
                code=CODES.get(entry.head, entry.head[:2].upper() or "??"),
                hatch=entry.hatch,
                note=entry.note,
                order=entry.order,
            )
        with self._lock:
            self._by_head = by_head
            self._order = tuple(payload.order or list(by_head))
            self.fetched = True

    def get(self, config_id: str | None) -> Series:
        head = ALIASES.get(head_of(config_id), head_of(config_id))
        with self._lock:
            return self._by_head.get(head, FALLBACK)

    def rank(self, config_id: str | None) -> tuple[int, str]:
        head = ALIASES.get(head_of(config_id), head_of(config_id))
        with self._lock:
            order = self._order
        try:
            return (order.index(head), head)
        except ValueError:
            return (len(order), head)

    def all(self) -> list[Series]:
        with self._lock:
            return [self._by_head[h] for h in self._order if h in self._by_head]


#: One palette per process. The probe fills it; everything else reads it.
PALETTE = Palette()


def head_of(config_id: str | None) -> str:
    return (config_id or "").split("_", 1)[0]


def series_for(config_id: str | None) -> Series:
    """The appearance for a config_id. Never raises: an unknown stack, or one
    seen before ETHOS answered, gets the grey fallback and stays visible rather
    than disappearing from a page."""
    return PALETTE.get(config_id)


def sort_key(config_id: str | None) -> tuple[int, str]:
    """ETHOS's own legend order, so a table and a figure agree on it."""
    return PALETTE.rank(config_id)
