"""Graphs: the archive of figures ETHOS's plotting package produced.

Requesting a new figure is ``POST /plots`` (B9). Until it exists the console does
not draw its own chart from the same numbers: the plotting package's figures are
IEEE-styled, archived with their manifest, ``points.csv`` and ``raw.csv``, and are
the same images that go into a paper. A second rendering in the browser would be
a second spelling of one figure.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse

from console.rapps.ethos.figures import get_figure, list_figures
from console.templating import render

router = APIRouter()


@router.get("/graphs")
async def graphs(request: Request):
    settings = request.app.state.settings
    figures = list_figures(settings.graph_dir)
    return render(
        request,
        "graphs/page.html",
        {"figures": figures, "graph_dir": settings.graph_dir},
    )


@router.get("/graphs/view/{date}/{folder}")
async def graph_detail(request: Request, date: str, folder: str):
    settings = request.app.state.settings
    figure = get_figure(settings.graph_dir, f"{date}/{folder}")
    if figure is None:
        raise HTTPException(status_code=404, detail="no such figure")
    return render(request, "graphs/figure.html", {"figure": figure})


@router.get("/graphs/file/{date}/{folder}/{kind}")
async def graph_file(request: Request, date: str, folder: str, kind: str):
    """Serve the archived PNG or PDF. The path is resolved and confined to the
    graph directory by ``get_figure``, so a ``..`` segment cannot reach the disk."""
    settings = request.app.state.settings
    figure = get_figure(settings.graph_dir, f"{date}/{folder}")
    if figure is None:
        raise HTTPException(status_code=404, detail="no such figure")
    path = figure.png if kind == "png" else figure.pdf
    if path is None:
        raise HTTPException(status_code=404, detail=f"this figure has no {kind}")
    return FileResponse(
        path,
        media_type="image/png" if kind == "png" else "application/pdf",
        filename=f"{figure.label}.{kind}",
    )
