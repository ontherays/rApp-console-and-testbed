"""The topology as a picture, and the presets the picker offers.

A config_id says what a topology is, once you have learned to read it. A row of
boxes left to right says it at a glance: UE, RU, O-DU, O-CU, 5GC, and the server
underneath. Monolithic stacks draw CU and DU as one gNB box, because that is
what they are.

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


def nodes_for(selection: dict[str, Any], *, split: str = "") -> list[Node]:
    """The chain, left to right, for one selection."""
    split = split or str(selection.get("gnb_split", "monolithic"))
    stack = str(selection.get("gnb_stack", ""))
    ue = str(selection.get("ue", ""))
    ru = str(selection.get("ru", ""))
    core = str(selection.get("core", ""))
    server = str(selection.get("server", ""))

    chain = [
        Node("ue", "UE", ue, "blue"),
        Node("ru", "O-RU", ru, "teal"),
    ]

    if split == "monolithic":
        chain.append(Node("gnb", "gNB", f"{stack}, CU and DU in one", "orange"))
    else:
        cu, du = stack, stack
        if split == "OCUDU-CU+OAI-DU":
            cu, du = "OCUDU", "OAI"
        elif split == "OAI-CU+OCUDU-DU":
            cu, du = "OAI", "OCUDU"
        chain.append(Node("du", "O-DU", du, "orange"))
        chain.append(Node("cu", "O-CU", cu, "purple"))

    chain.append(Node("core", "5GC", core, "purple"))
    if server:
        chain.append(Node("server", "O-Cloud", server, "slate"))
    return chain


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
    """The chain as inline SVG.

    ``mini`` is the version that fits on a preset card: boxes and links, no
    captions. ``full`` labels every element.
    """
    chain = nodes_for(selection, split=split)
    mini = size == "mini"

    box_w, box_h = (54, 46) if mini else (94, 70)
    gap = 14 if mini else 30
    pad_top = 4 if mini else 6
    caption = 0 if mini else 26
    width = len(chain) * box_w + (len(chain) - 1) * gap
    height = pad_top + box_h + caption

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'class="topo {"mini" if mini else ""}" role="img" '
        f'aria-label="{_esc(", ".join(n.label + " " + n.sub for n in chain))}" '
        'preserveAspectRatio="xMidYMid meet">'
    ]

    for index, node in enumerate(chain):
        x = index * (box_w + gap)
        colour = TONE_COLOURS.get(node.tone, "#55606F")
        parts.append(
            f'<g transform="translate({x},{pad_top})" color="{colour}">'
            f'<rect x="0.75" y="0.75" width="{box_w - 1.5}" height="{box_h - 1.5}" rx="9" '
            f'fill="#fff" stroke="currentColor" stroke-opacity=".35" stroke-width="1.5"/>'
            f'<svg x="{(box_w - (24 if mini else 30)) / 2}" y="{6 if mini else 11}" '
            f'width="{24 if mini else 30}" height="{24 if mini else 30}">'
            f'<use href="#icon-{node.icon}"/></svg>'
            f'<text x="{box_w / 2}" y="{box_h - (6 if mini else 13)}" text-anchor="middle" '
            f'font-size="{8.5 if mini else 11}" font-weight="600" fill="currentColor" '
            f'font-family="system-ui, sans-serif">{_esc(node.label)}</text>'
            "</g>"
        )
        if not mini and node.sub:
            parts.append(
                f'<text x="{x + box_w / 2}" y="{pad_top + box_h + 16}" text-anchor="middle" '
                f'font-size="10" fill="#9AA1AC" font-family="system-ui, sans-serif">'
                f"{_esc(node.sub)}</text>"
            )
        if index < len(chain) - 1:
            line_y = pad_top + box_h / 2
            parts.append(
                f'<path d="M{x + box_w + 3} {line_y} H{x + box_w + gap - 3}" '
                'stroke="#C9CDD4" stroke-width="1.5" stroke-linecap="round"/>'
            )

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
