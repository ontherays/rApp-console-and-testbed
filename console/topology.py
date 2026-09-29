"""The topology as a picture, and the presets the picker offers.

A config_id says what a topology is, once you have learned to read it. A row of
boxes left to right says it at a glance: UE, RU, the gNB, 5GC. Monolithic stacks
draw CU and DU as one gNB box, because that is what they are.

**The gNB is drawn INSIDE the O-Cloud.** joule is not a sixth element in the
chain that the gNB talks to, it is the worker the gNB runs on: the Helm release
lands there, its process is what the node check looks for, and pkg1 is the socket
whose energy the run measures. Drawing it as a peer at the end of the row said
the gNB connects to the O-Cloud, which is the one thing it does not do.

Nothing here decides anything. The selection is still validated by ETHOS and the
config_id still comes from `POST /testdef/generate`; this only draws what was
chosen, and lists the profiles that ETHOS says it can deploy.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any

from console.rapps.ethos.series import series_for


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


@dataclass(frozen=True)
class Node:
    icon: str
    label: str
    sub: str = ""
    tone: str = "slate"


@dataclass(frozen=True)
class Chain:
    """One topology, drawn as a row with the gNB held inside the O-Cloud."""

    before: list[Node]           # UE, O-RU
    hosted: list[Node]           # the gNB: one box, or O-DU and O-CU
    after: list[Node]            # 5GC
    server: str = ""             # the O-Cloud that holds `hosted`, if named

    def all_nodes(self) -> list[Node]:
        return [*self.before, *self.hosted, *self.after]

    def describe(self) -> str:
        """What a screen reader is told, containment and all."""
        outside = ", ".join(f"{n.label} {n.sub}".strip() for n in self.before)
        inside = ", ".join(f"{n.label} {n.sub}".strip() for n in self.hosted)
        tail = ", ".join(f"{n.label} {n.sub}".strip() for n in self.after)
        if self.server:
            middle = f"O-Cloud {self.server}, running {inside}"
        else:
            middle = inside
        return ", ".join(part for part in (outside, middle, tail) if part)


def nodes_for(selection: dict[str, Any], *, split: str = "") -> Chain:
    """The chain for one selection, split into what the O-Cloud holds and what
    it does not."""
    split = split or str(selection.get("gnb_split", "monolithic"))
    stack = str(selection.get("gnb_stack", ""))
    ue = str(selection.get("ue", ""))
    ru = str(selection.get("ru", ""))
    core = str(selection.get("core", ""))
    server = str(selection.get("server", ""))

    if split == "monolithic":
        hosted = [Node("gnb", "gNB", f"{stack}, CU and DU in one", "orange")]
    else:
        cu, du = stack, stack
        if split == "OCUDU-CU+OAI-DU":
            cu, du = "OCUDU", "OAI"
        elif split == "OAI-CU+OCUDU-DU":
            cu, du = "OAI", "OCUDU"
        hosted = [Node("du", "O-DU", du, "orange"), Node("cu", "O-CU", cu, "purple")]

    return Chain(
        before=[Node("ue", "UE", ue, "blue"), Node("ru", "O-RU", ru, "teal")],
        hosted=hosted,
        after=[Node("core", "5GC", core, "purple")],
        server=server,
    )


TONE_COLOURS = {
    "blue": "#2F6FED", "orange": "#D9822B", "teal": "#0F9B8E",
    "purple": "#7C5CFC", "slate": "#55606F",
}


def diagram(
    selection: dict[str, Any],
    *,
    split: str = "",
    size: str = "full",
) -> str:
    """The chain as inline SVG, with the gNB inside the O-Cloud that runs it.

    ``mini`` is the version that fits on a preset card: boxes and links, no
    captions. ``full`` labels every element.
    """
    chain = nodes_for(selection, split=split)
    mini = size == "mini"

    box_w, box_h = (54, 46) if mini else (94, 70)
    gap = 12 if mini else 26
    pad_top = 4 if mini else 6
    caption = 0 if mini else 18
    # The O-Cloud's own frame: a header for its name, and room around the boxes
    # it holds. Its title sits ABOVE them, so containment reads as containment
    # rather than as one more box in the row.
    head_h = 15 if mini else 22
    hug = 8 if mini else 12

    hosted_w = len(chain.hosted) * box_w + (len(chain.hosted) - 1) * gap
    # A caption can be wider than the box it sits under ("OCUDU, CU and DU in
    # one" against a 94-wide gNB box), and a caption spilling past the dashed
    # edge would undo the containment the frame is there to show. So the frame
    # is widened to hold its own text, at ~5.3px per character for the 10px
    # label font, and the boxes are centred in whatever width that gives.
    caption_w = 0.0
    if not mini:
        for node in chain.hosted:
            caption_w = max(caption_w, len(node.sub) * 5.3)
    host_w = max(hosted_w + 2 * hug, caption_w + 2 * hug)
    host_h = head_h + box_h + caption + hug

    columns = len(chain.before) + len(chain.after)
    width = columns * (box_w + gap) + host_w
    height = pad_top + host_h

    row_y = pad_top + head_h                     # every box sits on this line
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'class="topo {"mini" if mini else ""}" role="img" '
        f'aria-label="{_esc(chain.describe())}" '
        'preserveAspectRatio="xMidYMid meet">'
    ]

    def box(x: float, node: Node) -> str:
        colour = TONE_COLOURS.get(node.tone, "#55606F")
        icon = 24 if mini else 30
        out = (
            f'<g transform="translate({x},{row_y})" color="{colour}">'
            f'<rect x="0.75" y="0.75" width="{box_w - 1.5}" height="{box_h - 1.5}" rx="9" '
            f'fill="#fff" stroke="currentColor" stroke-opacity=".35" stroke-width="1.5"/>'
            f'<svg x="{(box_w - icon) / 2}" y="{6 if mini else 11}" '
            f'width="{icon}" height="{icon}"><use href="#icon-{node.icon}"/></svg>'
            f'<text x="{box_w / 2}" y="{box_h - (6 if mini else 13)}" text-anchor="middle" '
            f'font-size="{8.5 if mini else 11}" font-weight="600" fill="currentColor" '
            f'font-family="system-ui, sans-serif">{_esc(node.label)}</text>'
            "</g>"
        )
        if not mini and node.sub:
            out += (
                f'<text x="{x + box_w / 2}" y="{row_y + box_h + 13}" text-anchor="middle" '
                'font-size="10" fill="#9AA1AC" font-family="system-ui, sans-serif">'
                f"{_esc(node.sub)}</text>"
            )
        return out

    def link(x_from: float, x_to: float) -> str:
        return (
            f'<path d="M{x_from + 3} {row_y + box_h / 2} H{x_to - 3}" '
            'stroke="#C9CDD4" stroke-width="1.5" stroke-linecap="round"/>'
        )

    x = 0.0
    for node in chain.before:
        parts.append(box(x, node))
        parts.append(link(x + box_w, x + box_w + gap))
        x += box_w + gap

    # The O-Cloud. Dashed, tinted and behind its contents: it is the place the
    # releases land, not a network element the gNB talks to.
    host_x = x
    parts.append(
        f'<g color="{TONE_COLOURS["slate"]}">'
        f'<rect x="{host_x + 0.75}" y="{pad_top + 0.75}" width="{host_w - 1.5}" '
        f'height="{host_h - 1.5}" rx="12" fill="#F7F8FA" stroke="currentColor" '
        'stroke-opacity=".38" stroke-width="1.5" stroke-dasharray="5 3"/>'
        "</g>"
    )
    label = "O-Cloud" + (f" · {chain.server}" if chain.server else "")
    parts.append(
        f'<svg x="{host_x + hug}" y="{pad_top + (3 if mini else 5)}" '
        f'width="{11 if mini else 13}" height="{11 if mini else 13}" '
        f'color="{TONE_COLOURS["slate"]}"><use href="#icon-server"/></svg>'
        f'<text x="{host_x + hug + (14 if mini else 17)}" '
        f'y="{pad_top + (12 if mini else 15)}" font-size="{8 if mini else 10.5}" '
        'font-weight="600" fill="#55606F" font-family="system-ui, sans-serif">'
        f"{_esc(label)}</text>"
    )

    x = host_x + (host_w - hosted_w) / 2
    for index, node in enumerate(chain.hosted):
        parts.append(box(x, node))
        if index < len(chain.hosted) - 1:
            parts.append(link(x + box_w, x + box_w + gap))
        x += box_w + gap
    x = host_x + host_w

    for node in chain.after:
        parts.append(link(x, x + gap))
        parts.append(box(x + gap, node))
        x += gap + box_w

    parts.append("</svg>")
    return "".join(parts)


# --- the presets -------------------------------------------------------------


@dataclass
class Preset:
    """One wired deploy profile, as the picker offers it.

    ``diagram`` is filled in by the page, because drawing needs the sprite that
    only a template knows about.
    """

    profile: str
    label: str
    selection: dict[str, str]
    split: str
    status: str                  # supported, for every profile that is wired
    colour: str
    releases: tuple[str, ...] = ()
    last_run: str | None = None
    last_result: str | None = None
    run_count: int = 0
    diagram: str = ""

    @property
    def experimental(self) -> bool:
        """Whether the card carries a caveat chip.

        A preset is one of ETHOS's own wired deploy profiles, and a profile is
        wired when its charts and values exist and have been run. This used to
        read "experimental" off the profile NAME, which was the console making
        a judgement of its own from a string: both cross-vendor splits have
        since been swept end to end, and the chip was telling the operator they
        were unproven while the cards underneath showed their runs.

        The caveat that remains is ETHOS's, on the topology summary, where
        `POST /validate` returns `experimental` with the rule and the reason
        that raised it. One source for that judgement, and it is not this one.
        """
        return self.status == "experimental"


# The selection each wired profile stands for. The profile names come from
# deploy_profiles.yaml, and the CLI takes the same names as its topology
# argument, so this table is the one place the two agree.
PRESET_SELECTIONS: dict[str, dict[str, str]] = {
    "ocudu-mono": {"gnb_stack": "OCUDU", "gnb_split": "monolithic"},
    "oai-mono": {"gnb_stack": "OAI", "gnb_split": "monolithic"},
    "ocudu-cudu": {"gnb_stack": "OCUDU", "gnb_split": "CU+DU"},
    "oai-cudu": {"gnb_stack": "OAI", "gnb_split": "CU+DU"},
    "ocudu-cu-oai-du": {"gnb_stack": "OCUDU", "gnb_split": "OCUDU-CU+OAI-DU"},
    "oai-cu-ocudu-du": {"gnb_stack": "OAI", "gnb_split": "OAI-CU+OCUDU-DU"},
}

PRESET_ORDER = tuple(PRESET_SELECTIONS)

LABELS: dict[str, str] = {
    "ocudu-mono": "OCUDU monolithic",
    "oai-mono": "OAI monolithic",
    "ocudu-cudu": "OCUDU CU + OCUDU DU",
    "oai-cudu": "OAI CU + OAI DU",
    "ocudu-cu-oai-du": "OCUDU CU + OAI DU",
    "oai-cu-ocudu-du": "OAI CU + OCUDU DU",
}

# Which config_id head each profile produces, so a preset can be matched to the
# runs that used it. Derived from ETHOS's own naming, never assembled.
HEADS: dict[str, str] = {
    "ocudu-mono": "ocudu-mono",
    "oai-mono": "oai-mono",
    "ocudu-cudu": "ocudu-cudu",
    "oai-cudu": "oai-cudu",
    "ocudu-cu-oai-du": "ocuducu-oaidu",
    "oai-cu-ocudu-du": "oaicu-ocududu",
}

ALIASES: dict[str, str] = {
    "ocudu-mixocuoai": "ocuducu-oaidu",
    "oai-mixoaiocu": "oaicu-ocududu",
}


def build_presets(profiles, defaults: dict[str, str], runs: list) -> list[Preset]:
    """The wired profiles, each with the date and result of its last run."""
    latest: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for run in runs:
        head = (run.config_id or "").split("_", 1)[0]
        head = ALIASES.get(head, head)
        if not head:
            continue
        counts[head] = counts.get(head, 0) + 1
        seen = latest.get(head)
        if seen is None or (run.t_created or "") > (seen.t_created or ""):
            latest[head] = run

    out: list[Preset] = []
    for name in PRESET_ORDER:
        profile = profiles.get(name) if profiles.available else None
        if profile is not None and not profile.deployable:
            continue
        selection = dict(defaults)
        selection.update(PRESET_SELECTIONS[name])
        head = HEADS[name]
        run = latest.get(head)

        result = None
        if run is not None:
            if run.achieved_over_tx_mbps is not None:
                result = f"{run.achieved_over_tx_mbps:.0f} Mbit/s at {run.offered_mbps:.0f} offered"
            elif run.status == "defined":
                result = "defined, no traffic"
            else:
                result = run.status or "no result recorded"

        out.append(
            Preset(
                profile=name,
                label=LABELS[name],
                selection=selection,
                split=PRESET_SELECTIONS[name]["gnb_split"],
                status="supported",
                colour=series_for(f"{head}_x").colour,
                releases=profile.releases if profile else (),
                last_run=run.t_created if run else None,
                last_result=result,
                run_count=counts.get(head, 0),
            )
        )
    return out
