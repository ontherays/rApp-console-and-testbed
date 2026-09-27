"""The figure gallery, read from ETHOS's graph directory.

ETHOS's plotting package already writes every figure as a folder holding the
PNG, the PDF, ``points.csv``, ``raw.csv`` and a ``manifest.json`` that records
the filters, the run ids, n per point and the git commit. That is a better
archive than a console could invent, and it is the same image that goes into a
paper, so the console lists and serves it rather than drawing its own chart.

Generation is not here. ``POST /plots`` is backend change B9, and until it
exists a new figure comes from ``python -m plotting``; the Graphs page shows
that command. Rendering the same numbers a second way in the browser would
produce two spellings of one figure, which is the thing the archive exists to
prevent.

Read-only: nothing in this file writes to the graph directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PNG_NAMES = ("dl_throughput.png", "figure.png")
PDF_NAMES = ("dl_throughput.pdf", "figure.pdf")


@dataclass(frozen=True)
class Figure:
    folder: str                   # "<date>/<HHMMSS>_<kind>_<label>", the id in a URL
    date: str
    label: str
    kind: str
    metric: str | None
    generated_at: str | None
    width: str | None
    png: Path | None
    pdf: Path | None
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def config_ids(self) -> list[str]:
        filters = (self.manifest.get("selection") or {}).get("filters") or {}
        ids = filters.get("config_ids") or []
        return [str(i) for i in ids]

    @property
    def n_summary(self) -> Any:
        return self.manifest.get("n_summary")

    @property
    def run_count(self) -> int | None:
        selection = self.manifest.get("selection") or {}
        rows = selection.get("rows_out")
        return int(rows) if isinstance(rows, (int, float)) else None

    @property
    def warnings(self) -> list[str]:
        """What the inputs mix (GR-09). Read from the figure's own manifest, so
        the warning on the page and the figure's provenance cannot disagree."""
        out: list[str] = []
        selection = self.manifest.get("selection") or {}
        filters = selection.get("filters") or {}

        durations = _distinct(self.manifest, "durations_s")
        if len(durations) > 1:
            out.append(
                "the runs mix traffic durations: "
                + ", ".join(f"{d:g} s" for d in sorted(durations))
            )
        if filters.get("allow_mixed_durations"):
            out.append("mixed durations were explicitly allowed for this figure")
        if filters.get("allow_unknown_server"):
            out.append("runs with an unknown iperf server were included")

        dropped = selection.get("dropped_count")
        if isinstance(dropped, (int, float)) and dropped:
            out.append(f"{int(dropped)} run(s) were dropped by the filters")
        return out


def _distinct(manifest: dict[str, Any], key: str) -> set[float]:
    found: set[float] = set()
    for point in manifest.get("points") or []:
        if not isinstance(point, dict):
            continue
        value = point.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, (int, float)):
                found.add(float(item))
    return found


def _first_existing(folder: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    # Fall back to whatever single image or pdf is there, so a renamed stem
    # still shows rather than silently disappearing.
    suffix = ".png" if names is PNG_NAMES else ".pdf"
    found = sorted(folder.glob(f"*{suffix}"))
    return found[0] if found else None


def _read_figure(date_dir: Path, folder: Path) -> Figure | None:
    manifest: dict[str, Any] = {}
    manifest_path = folder / "manifest.json"
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except (OSError, ValueError):
            manifest = {}

    # The folder name is "<HHMMSS>_<kind>_<label>".
    parts = folder.name.split("_", 2)
    kind = manifest.get("kind") or (parts[1] if len(parts) > 2 else "")
    label = parts[2] if len(parts) > 2 else folder.name

    png = _first_existing(folder, PNG_NAMES)
    pdf = _first_existing(folder, PDF_NAMES)
    if png is None and pdf is None and not manifest:
        return None

    return Figure(
        folder=f"{date_dir.name}/{folder.name}",
        date=date_dir.name,
        label=label,
        kind=str(kind),
        metric=manifest.get("metric"),
        generated_at=manifest.get("generated_at_taipei"),
        width=manifest.get("width"),
        png=png,
        pdf=pdf,
        manifest=manifest,
    )


def list_figures(graph_dir: Path | None, limit: int | None = None) -> list[Figure]:
    """Every archived figure, newest first (GR-07)."""
    if graph_dir is None or not graph_dir.is_dir():
        return []
    found: list[Figure] = []
    for date_dir in sorted(
        (d for d in graph_dir.iterdir() if d.is_dir()), reverse=True
    ):
        for folder in sorted(
            (f for f in date_dir.iterdir() if f.is_dir()), reverse=True
        ):
            figure = _read_figure(date_dir, folder)
            if figure is not None:
                found.append(figure)
                if limit is not None and len(found) >= limit:
                    return found
    return found


def get_figure(graph_dir: Path | None, folder_id: str) -> Figure | None:
    """One figure by its ``<date>/<folder>`` id.

    The id comes from a URL, so it is resolved and then checked to be inside the
    graph directory, a ``..`` segment must not reach another part of the disk.
    """
    if graph_dir is None or not graph_dir.is_dir():
        return None
    candidate = (graph_dir / folder_id).resolve()
    root = graph_dir.resolve()
    if not candidate.is_dir() or root not in candidate.parents:
        return None
    return _read_figure(candidate.parent, candidate)
