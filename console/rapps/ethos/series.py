"""One colour per stack, matching the ETHOS figures (GL-05).

A chip on a results page and a line in a paper figure must be the same colour
for the same stack, or the page and the figure become two spellings of one
thing. These values are ETHOS's own, from ``plotting/series.py``: the Okabe-Ito
palette, with splits drawn solid and monolithic dashed so the figures still
separate in greyscale.

They are copied rather than imported, because the console does not import ETHOS
code — the two are separate processes with separate virtual environments. When
``GET /plots/series`` lands (B9) this table is replaced by that response, which
is the point at which "copied" stops being a risk.

Keyed on the config_id **head**, matched exactly. Never by prefix: the legacy
head ``oai-mixoaiocu`` starts with "oai" and was once filed as a pure-OAI run
because of it.
"""

from __future__ import annotations

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

    Derived from the head rather than from the label: four different splits
    abbreviate to "OD" from their labels, and two monolithic stacks to "OM",
    which would put the same tile on different topologies.
    """


SERIES: dict[str, Series] = {
    "oai-cudu": Series("oai-cudu", "OAI CU + OAI DU", "#0072B2", "o", "solid", "AD"),
    "oaicu-ocududu": Series("oaicu-ocududu", "OAI CU + OCUDU DU", "#009E73", "s", "solid", "AO"),
    "ocuducu-oaidu": Series("ocuducu-oaidu", "OCUDU CU + OAI DU", "#D55E00", "^", "solid", "OA"),
    "ocudu-cudu": Series("ocudu-cudu", "OCUDU CU + OCUDU DU", "#CC79A7", "D", "solid", "OD"),
    "oai-mono": Series("oai-mono", "OAI monolithic", "#E69F00", "v", "dashed", "AM"),
    "ocudu-mono": Series("ocudu-mono", "OCUDU monolithic", "#56B4E9", "h", "dashed", "OM"),
}

# The legacy heads still parse as aliases, so a run archived before the rename
# keeps its own colour instead of falling through to grey.
ALIASES: dict[str, str] = {
    "ocudu-mixocuoai": "ocuducu-oaidu",
    "oai-mixoaiocu": "oaicu-ocududu",
}

FALLBACK = Series("", "Unknown stack", "#666666", "P", "dotted", "??")

ORDER: tuple[str, ...] = (
    "ocudu-mono",
    "ocudu-cudu",
    "oai-mono",
    "oai-cudu",
    "ocuducu-oaidu",
    "oaicu-ocududu",
)


def head_of(config_id: str | None) -> str:
    return (config_id or "").split("_", 1)[0]


def series_for(config_id: str | None) -> Series:
    """The appearance for a config_id. Never raises: an unknown stack gets the
    grey fallback and stays visible, rather than disappearing from a page."""
    head = head_of(config_id)
    head = ALIASES.get(head, head)
    return SERIES.get(head, FALLBACK)


def sort_key(config_id: str | None) -> tuple[int, str]:
    head = ALIASES.get(head_of(config_id), head_of(config_id))
    try:
        return (ORDER.index(head), head)
    except ValueError:
        return (len(ORDER), head)
