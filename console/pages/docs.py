"""The repository's own documents, served as pages.

The four design documents and the guides live in ``docs/`` and are the contract
this console is built against. Serving them means the answer to "what was this
supposed to do?" is one click from the thing itself, rather than on a laptop.

Markdown is rendered by a small converter here rather than by a dependency: the
documents are headings, paragraphs, lists, tables and fenced code, and adding a
Markdown library to render four files this console ships with is not worth the
maintenance.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from console.templating import render

router = APIRouter()

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"


@dataclass(frozen=True)
class Doc:
    slug: str
    title: str
    path: Path


def _title_of(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return path.stem


def available() -> list[Doc]:
    if not DOCS_DIR.is_dir():
        return []
    return [
        Doc(slug=path.stem, title=_title_of(path), path=path)
        for path in sorted(DOCS_DIR.glob("*.md"))
    ]


_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![*\w])\*([^*]+)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
)


def _inline(text: str) -> str:
    out = html.escape(text)
    for pattern, replacement in _INLINE:
        out = pattern.sub(replacement, out)
    return out


def to_html(markdown: str) -> str:
    """Headings, paragraphs, lists, tables, fenced code and rules. Enough for
    these documents, and it escapes everything it does not understand."""
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while index < len(lines):
        line = lines[index]

        if line.startswith("```"):
            close_list()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            out.append("<pre class='cmd'>" + html.escape("\n".join(block)) + "</pre>")
            continue

        if line.startswith("|") and index + 1 < len(lines) and set(
            lines[index + 1].replace("|", "").replace(" ", "")
        ) <= {"-", ":"}:
            close_list()
            headers = [c.strip() for c in line.strip("|").split("|")]
            index += 2
            out.append("<div class='table-wrap'><table class='data'><thead><tr>")
            out.extend(f"<th>{_inline(h)}</th>" for h in headers)
            out.append("</tr></thead><tbody>")
            while index < len(lines) and lines[index].startswith("|"):
                cells = [c.strip() for c in lines[index].strip("|").split("|")]
                out.append("<tr>")
                out.extend(f"<td>{_inline(c)}</td>" for c in cells)
                out.append("</tr>")
                index += 1
            out.append("</tbody></table></div>")
            continue

        stripped = line.strip()
        if not stripped:
            close_list()
        elif stripped.startswith("#"):
            close_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            out.append(f"<h{min(level, 6)}>{_inline(stripped[level:].strip())}</h{min(level, 6)}>")
        elif stripped in ("---", "***", "___"):
            close_list()
            out.append("<hr>")
        elif re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(re.sub(r'^([-*+]|\\d+\\.)\\s+', '', stripped))}</li>")
        elif stripped.startswith(">"):
            close_list()
            out.append(f"<blockquote class='muted'>{_inline(stripped.lstrip('> '))}</blockquote>")
        else:
            close_list()
            out.append(f"<p>{_inline(stripped)}</p>")
        index += 1

    close_list()
    return "\n".join(out)


@router.get("/docs")
async def docs_index(request: Request):
    return render(request, "docs/index.html", {"docs": available()})


@router.get("/docs/{slug}")
async def doc_page(request: Request, slug: str):
    for doc in available():
        if doc.slug == slug:
            return render(
                request,
                "docs/page.html",
                {
                    "doc": doc,
                    "body": to_html(doc.path.read_text(encoding="utf-8")),
                    "docs": available(),
                },
            )
    raise HTTPException(status_code=404, detail="no such document")
