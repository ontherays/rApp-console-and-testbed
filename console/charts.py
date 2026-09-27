"""The Overview's charts, drawn as inline SVG on the server.

These are **operational summaries** — how many runs, of which topology, and how
the best throughput moved day to day. They exist so the Overview answers "what
has this testbed been doing" at a glance, and they are counts and trends, not
measurements.

Measurement figures still come only from ETHOS's plotting package, on the Graphs
page. A chart library in the browser would give a second, differently-styled
rendering of numbers that are already archived with their manifest, and two
spellings of one figure is the thing that archive exists to prevent.

No chart library here either: two shapes, drawn from arithmetic, with the text
of every value also present for a screen reader.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass, field

EMPTY = "#E6E6E6"
GRID = "#EDEDED"


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


# --- the honeycomb -----------------------------------------------------------


@dataclass(frozen=True)
class HexCell:
    colour: str
    label: str


def _ring_capacity(rings: int) -> int:
    return 1 + 3 * rings * (rings + 1)


def _spiral(rings: int) -> list[tuple[int, int]]:
    """Axial coordinates from the centre outwards, so filling in order grows a
    blob rather than a corner."""
    cells: list[tuple[int, int]] = []
    for radius in range(rings + 1):
        for q in range(-radius, radius + 1):
            for r in range(-radius, radius + 1):
                if max(abs(q), abs(r), abs(-q - r)) == radius:
                    cells.append((q, r))
    return cells


def hex_grid(
    cells: list[HexCell],
    *,
    width: int = 520,
    height: int = 320,
    min_rings: int = 4,
    max_rings: int = 16,
) -> str:
    """One hexagon per item, coloured, on a grey honeycomb of empty cells.

    The grid is sized to hold what it is given, so a quiet week draws a small
    dense blob and a busy month draws a large one — the size of the coloured
    area is itself the count.
    """
    total = len(cells)
    rings = min_rings
    while _ring_capacity(rings) < total and rings < max_rings:
        rings += 1

    coords = _spiral(rings)
    # Pointy-top hexagons: width √3·s, height 2s, rows overlapping by a quarter.
    span_x = math.sqrt(3) * (2 * rings + 1)
    span_y = 1.5 * (2 * rings) + 2
    size = min(width / span_x, height / span_y)
    radius = size * 0.92  # a hairline gap between neighbours

    points = " ".join(
        f"{radius * math.sin(math.pi / 3 * i):.2f},{-radius * math.cos(math.pi / 3 * i):.2f}"
        for i in range(6)
    )

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="{total} run(s), one hexagon each, coloured by topology" '
        'preserveAspectRatio="xMidYMid meet" class="hexgrid">',
        f'<defs><polygon id="hexcell" points="{points}"/></defs>',
    ]
    centre_x, centre_y = width / 2, height / 2
    for index, (q, r) in enumerate(coords):
        x = centre_x + size * math.sqrt(3) * (q + r / 2)
        y = centre_y + size * 1.5 * r
        if x < -size or x > width + size or y < -size or y > height + size:
            continue
        if index < total:
            cell = cells[index]
            parts.append(
                f'<use href="#hexcell" x="{x:.2f}" y="{y:.2f}" fill="{_esc(cell.colour)}">'
                f"<title>{_esc(cell.label)}</title></use>"
            )
        else:
            parts.append(f'<use href="#hexcell" x="{x:.2f}" y="{y:.2f}" fill="{EMPTY}"/>')
    parts.append("</svg>")
    return "".join(parts)


# --- the dot-matrix column chart ---------------------------------------------


@dataclass
class Column:
    label: str          # the axis tick, e.g. "Sep 21"
    value: float | None  # None means nothing was measured that day
    caption: str = ""    # the hover text


@dataclass
class DotMatrix:
    svg: str
    top: float
    columns: list[Column] = field(default_factory=list)


def dot_matrix(
    columns: list[Column],
    *,
    width: int = 620,
    height: int = 260,
    rows: int = 22,
    colour: str = "#E8933A",
    unit: str = "",
) -> DotMatrix:
    """One column of dots per day, filled to that day's value.

    A day with no run is drawn as an empty column, not as zero — the console
    never shows a missing measurement as a number (GL-09).
    """
    measured = [c.value for c in columns if c.value is not None]
    top = max(measured) if measured else 0.0
    # Round the axis up to something readable rather than to the exact maximum.
    if top > 0:
        step = 10 ** math.floor(math.log10(top))
        top = math.ceil(top / (step / 2)) * (step / 2)
    if top <= 0:
        top = 1.0

    left_pad, right_pad = 46, 8
    top_pad, bottom_pad = 10, 26
    plot_w = width - left_pad - right_pad
    plot_h = height - top_pad - bottom_pad
    count = max(1, len(columns))
    col_w = plot_w / count
    row_h = plot_h / rows
    dot_r = max(1.6, min(col_w, row_h) * 0.28)

    parts: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'role="img" aria-label="best value per day, highest {top:g}{unit}" '
        'preserveAspectRatio="none" class="dotmatrix">'
    ]

    for fraction in (1.0, 0.75, 0.5, 0.25, 0.0):
        y = top_pad + plot_h * (1 - fraction)
        parts.append(
            f'<text x="{left_pad - 8}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'class="axis">{top * fraction:g}</text>'
        )

    for index, column in enumerate(columns):
        cx = left_pad + col_w * (index + 0.5)
        filled = 0
        if column.value is not None and top > 0:
            filled = int(round(column.value / top * rows))
            filled = max(1, min(rows, filled)) if column.value > 0 else 0
        title = _esc(column.caption or f"{column.label}: no run")
        parts.append(f"<g><title>{title}</title>")
        for row in range(rows):
            cy = top_pad + plot_h - row_h * (row + 0.5)
            fill = colour if row < filled else GRID
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{dot_r:.2f}" fill="{fill}"/>'
            )
        parts.append("</g>")

    ticks = [0, len(columns) // 2, len(columns) - 1] if len(columns) > 2 else range(len(columns))
    for index in sorted(set(ticks)):
        if 0 <= index < len(columns):
            cx = left_pad + col_w * (index + 0.5)
            anchor = "start" if index == 0 else ("end" if index == len(columns) - 1 else "middle")
            parts.append(
                f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="{anchor}" '
                f'class="axis">{_esc(columns[index].label)}</text>'
            )

    parts.append("</svg>")
    return DotMatrix(svg="".join(parts), top=top, columns=columns)


# --- the tick bar used in the "needs you" table ------------------------------


def tick_bar(done: int, total: int, *, ticks: int = 18, colour: str = "#E8933A") -> str:
    """Planned versus completed points, as a row of small ticks."""
    if total <= 0:
        return '<span class="tickbar" aria-hidden="true"></span>'
    filled = max(0, min(ticks, round(done / total * ticks)))
    parts = [f'<span class="tickbar" role="img" aria-label="{done} of {total} points">']
    for index in range(ticks):
        style = f"background:{colour}" if index < filled else ""
        parts.append(f'<i style="{style}"></i>')
    parts.append("</span>")
    return "".join(parts)
