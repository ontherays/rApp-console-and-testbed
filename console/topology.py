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
from dataclasses import dataclass, replace
from typing import Any

from console.rapps.ethos.series import series_for


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


#: The interfaces the row draws on its connectors. Each is the name the
#: O-RAN architecture gives that link, so the picture says which standard
#: carries what rather than leaving every line meaning the same thing.
UU = "Uu"
FRONTHAUL = "7.2x FH"
FAPI = "FAPI \u00b7 nvIPC"
F1 = "F1"
NG = "N2/N3"


@dataclass(frozen=True)
class Node:
    icon: str
    label: str
    sub: str = ""
    tone: str = "slate"
    #: The interface between this node and the one on its left, drawn on the
    #: connector. Empty on the first node, which has nothing to its left.
    link_in: str = ""


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
        """What a screen reader is told: containment and interfaces and all."""

        def say(node: Node) -> str:
            name = f"{node.label} {node.sub}".strip()
            return f"{name} over {node.link_in}" if node.link_in else name

        outside = ", ".join(say(n) for n in self.before)
        inside = ", ".join(say(n) for n in self.hosted)
        tail = ", ".join(say(n) for n in self.after)
        if self.server:
            middle = f"O-Cloud {self.server}, running {inside}"
        else:
            middle = inside
        return ", ".join(part for part in (outside, middle, tail) if part)


#: The L1 backend that runs on the DGX Spark. A plan naming it draws the
#: Aerial path instead of the software-PHY one.
AERIAL_L1 = "Aerial-cuBB"
SPARK_SERVER = "DGX-Spark"


def is_aerial(selection: dict[str, Any]) -> bool:
    """Does this selection run on the Aerial L1?"""
    return str(selection.get("l1_backend", "")) == AERIAL_L1


def server_of(config_id: str) -> str:
    """The server a run's config_id names. The sixth field of six.

    Derived, not asked for: the config_id already carries the server, so a run
    needs no new API field to be drawn on the right path.
    """
    parts = str(config_id or "").split("_")
    if len(parts) < 6:
        return ""
    return {"dgxspark": SPARK_SERVER, "joule": "joule"}.get(parts[-1].lower(), "")


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
        hosted = [Node("gnb", "gNB", f"{stack}, CU and DU in one", "orange", FRONTHAUL)]
    else:
        cu, du = stack, stack
        if split == "OCUDU-CU+OAI-DU":
            cu, du = "OCUDU", "OAI"
        elif split == "OAI-CU+OCUDU-DU":
            cu, du = "OAI", "OCUDU"
        hosted = [Node("du", "O-DU", du, "orange", FRONTHAUL),
                  Node("cu", "O-CU", cu, "purple", F1)]

    if is_aerial(selection):
        # The Aerial L1 sits between the gNB and the radio: the gNB speaks FAPI
        # over nvIPC to it, and it drives the fronthaul off the ConnectX-7
        # through OcNOS. Drawn first in `hosted` because the row reads
        # outwards from the RU.
        # The L1 takes the fronthaul, and the stack behind it reaches the L1
        # over FAPI rather than over the radio link it no longer touches.
        hosted = [
            Node("l1", "Aerial L1", "NVIDIA cuPHY", "teal", FRONTHAUL),
            replace(hosted[0], link_in=FAPI),
            *hosted[1:],
        ]
        ru_node = Node("ru", "O-RU", f"{ru}, via CX7 and OcNOS", "teal", UU)
    else:
        ru_node = Node("ru", "O-RU", ru, "teal", UU)

    return Chain(
        before=[Node("ue", "UE", ue, "blue"), ru_node],
        hosted=hosted,
        after=[Node("core", "5GC", core, "purple", NG)],
        server=server,
    )


TONE_COLOURS = {
    "blue": "#2F6FED", "orange": "#D9822B", "teal": "#0F9B8E",
    "purple": "#7C5CFC", "slate": "#55606F",
}

#: Ink. The captions and the interface names are supporting text, so they are
#: the muted grey rather than the faint one: `--faint` reads 2.6:1 on the
#: card and this has to be legible, not decorative.
INK_MUTED = "#6B7280"
INK_LABEL = "#55606F"
LINE = "#C9CDD4"

#: Type. Three sizes only, the console's own 14/12/11, and 1.35 line-height
#: wherever a block of text has more than one line.
NODE_PX = 12
CAPTION_PX = 11
LINK_PX = 11
CLOUD_PX = 11
LINE_HEIGHT = 1.35
CAPTION_LINE = round(CAPTION_PX * LINE_HEIGHT)

#: Space. Multiples of four, the scale the stylesheet uses.
GAP_BASE = 20
HUG = 16
PAD_TOP = 8
HEAD_H = 16
CAPTION_TOP = 16
LINK_PAD = 6

#: How wide the row is laid out to be. The SVG is server-rendered, so it
#: cannot measure the card it will land in; this is the width the card gives
#: it at the narrowest viewport that must not scroll (1024px, where the facts
#: column has stacked below and the diagram has about 925px). Drawn at its own
#: size and centred in anything wider, so the type is never scaled down.
TARGET_W = 920

#: What a node and a connector may grow to, and shrink to. A node is wide
#: enough for its label at the minimum and stops before it becomes a panel; a
#: connector is never narrower than the interface name written on it. Four
#: nodes therefore spread into wide boxes and long links, and six compact
#: themselves, out of the same width.
NODE_MIN_W = 96
NODE_MAX_W = 150
LINK_MAX_W = 140

#: How wide one character is, near enough to lay text out against a box whose
#: width is known. system-ui averages about 0.53em, and a little more at the
#: semibold weight the node and O-Cloud labels use.
CHAR_EM = 0.53
CHAR_EM_BOLD = 0.56

#: A caption is never taller than this, so one node cannot push the row down.
CAPTION_LINES = 2

#: A caption may lean a little way into the gap on either side, which buys a
#: word without letting two captions meet: the gap is never below GAP_BASE.
CAPTION_BLEED = 12


def _text_px(text: str, size: float, em: float = CHAR_EM) -> float:
    return len(str(text)) * size * em


def _to4(value: float) -> int:
    """Round up to the spacing scale, so every gap is a multiple of four."""
    return int(-(-value // 4) * 4)


def allocate(bounds: list[tuple[float, float]], available: float) -> list[float]:
    """Share *available* between items that each have a (min, max) width.

    The row is one row of boxes and the connectors between them, and every
    one of them has a width it must not go under and one it must not go over.
    Three cases, and the middle one is the usual:

    * everything fits at its maximum with room to spare: give each its
      maximum and let the caller centre what is left over. Nothing is ever
      stretched past its maximum, because a 300px box is not a better box.
    * there is not even room for the minimums: give each its minimum and
      overflow. The card scrolls, which is what a narrow window gets.
    * otherwise: give each its minimum, then share the slack in proportion to
      how much room each has left to grow. An item with no headroom takes
      none of it, so a connector pinned to a long interface name does not
      swallow the width its neighbours need.
    """
    lows = [low for low, _high in bounds]
    headroom = [max(0.0, high - low) for low, high in bounds]
    total_min, total_slack = sum(lows), sum(headroom)
    if available >= total_min + total_slack:
        return [high for _low, high in bounds]
    if available <= total_min or total_slack <= 0:
        return list(lows)
    share = (available - total_min) / total_slack
    return [low + room * share for low, room in zip(lows, headroom)]


def wrap_caption(text: str, width: float, size: int = CAPTION_PX) -> list[str]:
    """Break *text* into at most two lines that each fit inside *width*.

    What does not fit ends in an ellipsis; the caller keeps the whole text as
    the element's tooltip. Returns at least one line for any non-empty text,
    so a node always says something.
    """
    per_line = max(4, int(width / (size * CHAR_EM)))
    words = str(text or "").split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= per_line:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == CAPTION_LINES:
            break
    if current and len(lines) < CAPTION_LINES:
        lines.append(current)

    # Anything left over, including a single word too long for one line.
    used = len(" ".join(lines).split())
    if used < len(words) or (lines and len(lines[-1]) > per_line):
        last = lines[-1] if lines else words[0]
        lines[-1 if lines else 0:] = [last[: max(1, per_line - 1)].rstrip() + "\u2026"]
    return lines[:CAPTION_LINES]


def diagram(
    selection: dict[str, Any],
    *,
    split: str = "",
    size: str = "full",
) -> str:
    """The chain as inline SVG, with the gNB inside the O-Cloud that runs it.

    ``mini`` is the version that fits on a preset card: boxes and links, no
    text around them. ``full`` names every element, captions it, and names the
    interface on every connector.

    **The row shares one width between however many nodes it has.** Each box
    and each connector is allocated between a minimum and a maximum, so a
    four-node chain spreads into wide boxes with long links and a six-node
    chain compacts itself, and both come out the same width instead of one
    of them ending halfway across the card. Nothing is stretched past its
    maximum: a chain short enough to reach every maximum is drawn at its own
    size and centred by the stylesheet.
    """
    chain = nodes_for(selection, split=split)
    mini = size == "mini"

    box_h = 46 if mini else 70
    hug = 8 if mini else HUG
    pad_top = 4 if mini else PAD_TOP
    head_h = 10 if mini else HEAD_H
    row = chain.all_nodes()
    first_hosted = len(chain.before)
    after_hosted = first_hosted + len(chain.hosted)

    def link_min(node: Node) -> float:
        """A connector is at least as wide as the name written on it."""
        if mini or not node.link_in:
            return GAP_BASE
        return max(GAP_BASE, _text_px(node.link_in, LINK_PX) + 2 * LINK_PAD)

    # --- share the width ----------------------------------------------------
    # One list, boxes and connectors interleaved exactly as they are drawn,
    # so the allocation sees the whole row at once rather than sizing each
    # gap against its neighbours.
    if mini:
        box_w = 54.0
        widths = [12.0 if index % 2 else box_w
                  for index in range(2 * len(row) - 1)]
    else:
        bounds: list[tuple[float, float]] = []
        for index, node in enumerate(row):
            if index:
                bounds.append((link_min(node), max(link_min(node), LINK_MAX_W)))
            bounds.append((NODE_MIN_W, NODE_MAX_W))
        widths = allocate(bounds, TARGET_W)

    box_ws = widths[0::2]
    link_ws = widths[1::2]

    # --- lay the row out ----------------------------------------------------
    # The O-Cloud's own padding is part of the connector that crosses its
    # outline, so the frame hugs its nodes by the same `hug` on both sides
    # without the row having to leave a wider gap there.
    xs: list[float] = []
    host_x = host_right = 0.0
    x = 0.0
    for index in range(len(row)):
        if index:
            gap = link_ws[index - 1]
            x = xs[-1] + box_ws[index - 1] + gap
            if index == first_hosted:
                host_x = x - hug
            elif index == after_hosted:
                host_right = xs[-1] + box_ws[index - 1] + hug
        xs.append(x)
    if not host_right:
        host_right = xs[after_hosted - 1] + box_ws[after_hosted - 1] + hug
    host_w = host_right - host_x

    caption_block = 0 if mini else CAPTION_TOP + (CAPTION_LINES - 1) * CAPTION_LINE + 4
    host_h = head_h + box_h + caption_block + (hug if mini else 8)
    width = max(xs[-1] + box_ws[-1], host_right)
    height = pad_top + host_h
    row_y = pad_top + head_h                     # every box sits on this line
    mid_y = row_y + box_h / 2                    # and every connector on this

    # The full diagram is drawn at its own size: scaling it to fit would take
    # the type down with it. A preset's mini diagram has no text, so it scales.
    sizing = 'width="100%"' if mini else f'width="{width:.0f}" height="{height:.0f}"'
    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" {sizing} '
        f'class="topo {"mini" if mini else ""}" role="img" '
        f'aria-label="{_esc(chain.describe())}" '
        'preserveAspectRatio="xMidYMid meet">'
    ]

    def caption_text(centre: float, top: float, text: str, box_w: float) -> str:
        """The caption, inside its own node's width and at most two lines.

        SVG text does not wrap, so the lines are measured here against the box
        this node was allocated and emitted as tspans. What does not fit ends
        in an ellipsis, and the whole caption is the element's tooltip.
        """
        lines = wrap_caption(text, box_w + CAPTION_BLEED, CAPTION_PX)
        spans = "".join(
            f'<tspan x="{centre:.1f}" dy="{0 if index == 0 else CAPTION_LINE}">'
            f"{_esc(line)}</tspan>"
            for index, line in enumerate(lines)
        )
        return (
            f'<text class="topo-caption" x="{centre:.1f}" y="{top:.0f}" text-anchor="middle" '
            f'font-size="{CAPTION_PX}" fill="{INK_MUTED}" '
            f'font-family="system-ui, sans-serif">'
            f"<title>{_esc(text)}</title>{spans}</text>"
        )

    def box(x: float, node: Node, box_w: float) -> str:
        colour = TONE_COLOURS.get(node.tone, TONE_COLOURS["slate"])
        icon = 24 if mini else 30
        out = (
            f'<g transform="translate({x:.1f},{row_y})" color="{colour}">'
            f'<rect x="0.75" y="0.75" width="{box_w - 1.5:.1f}" height="{box_h - 1.5}" rx="9" '
            f'fill="#fff" stroke="currentColor" stroke-opacity=".35" stroke-width="1.5"/>'
            f'<svg x="{(box_w - icon) / 2:.1f}" y="{6 if mini else 10}" '
            f'width="{icon}" height="{icon}"><use href="#icon-{node.icon}"/></svg>'
            f'<text x="{box_w / 2:.1f}" y="{box_h - (6 if mini else 12)}" text-anchor="middle" '
            f'font-size="{8.5 if mini else NODE_PX}" font-weight="600" fill="currentColor" '
            f'font-family="system-ui, sans-serif">{_esc(node.label)}</text>'
            "</g>"
        )
        if not mini and node.sub:
            out += caption_text(x + box_w / 2, row_y + box_h + CAPTION_TOP,
                                node.sub, box_w)
        return out

    def link(x_from: float, x_to: float, name: str) -> str:
        """The connector and the name of the interface it carries.

        The name is set on a panel of the card's own background so it reads
        where the line crosses the O-Cloud outline.
        """
        out = (
            f'<path d="M{x_from + 3:.1f} {mid_y} H{x_to - 3:.1f}" '
            f'stroke="{LINE}" stroke-width="1.5" stroke-linecap="round"/>'
        )
        if mini or not name:
            return out
        centre = (x_from + x_to) / 2
        label_w = _text_px(name, LINK_PX) + 2 * LINK_PAD
        return out + (
            f'<rect x="{centre - label_w / 2:.1f}" y="{mid_y - LINK_PX - 7}" '
            f'width="{label_w:.1f}" height="{LINK_PX + 5}" rx="3" fill="#FAFBFC"/>'
            f'<text class="topo-link" x="{centre:.1f}" y="{mid_y - 8}" text-anchor="middle" '
            f'font-size="{LINK_PX}" fill="{INK_MUTED}" '
            f'font-family="system-ui, sans-serif">{_esc(name)}</text>'
        )

    # --- the O-Cloud, behind everything it holds -----------------------------
    # Dashed and tinted: it is the place the releases land, not a network
    # element the gNB talks to. Its name sits ON the outline, the way a
    # fieldset names what it encloses, so the frame is read as a container
    # and not as one more box in the row.
    frame_fill = "#F7F8FA"
    parts.append(
        f'<rect x="{host_x + 0.75:.1f}" y="{pad_top + 0.75}" width="{host_w - 1.5:.1f}" '
        f'height="{host_h - 1.5}" rx="12" fill="{frame_fill}" stroke="{INK_LABEL}" '
        'stroke-opacity=".38" stroke-width="1.5" stroke-dasharray="5 3"/>'
    )
    label = "O-Cloud" + (f" \u00b7 {chain.server}" if chain.server else "")
    icon_px = 11 if mini else 13
    cloud_px = 8 if mini else CLOUD_PX
    text_x = host_x + 12 + icon_px + 5
    plate_w = icon_px + 5 + _text_px(label, cloud_px, CHAR_EM_BOLD) + 16
    parts.append(
        f'<rect x="{host_x + 8:.1f}" y="{pad_top - cloud_px / 2 - 3}" width="{plate_w:.1f}" '
        f'height="{cloud_px + 6}" rx="3" fill="{frame_fill}"/>'
        f'<svg x="{host_x + 12:.1f}" y="{pad_top - icon_px / 2}" '
        f'width="{icon_px}" height="{icon_px}" color="{INK_LABEL}">'
        '<use href="#icon-server"/></svg>'
        f'<text class="topo-cloud-name" x="{text_x:.1f}" y="{pad_top + cloud_px / 2 - 1}" '
        f'font-size="{cloud_px}" font-weight="600" fill="{INK_LABEL}" '
        f'font-family="system-ui, sans-serif">{_esc(label)}</text>'
    )

    # --- the row -------------------------------------------------------------
    for index, node in enumerate(row):
        if index:
            parts.append(link(xs[index - 1] + box_ws[index - 1], xs[index],
                              node.link_in))
        parts.append(box(xs[index], node, box_ws[index]))

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
    #: Only the fields this preset means to set. `selection` carries the
    #: page's defaults too, which are frozen at render time and must not be
    #: applied over a choice made since.
    sets: dict[str, str]
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
#: What each preset sets on the form. A preset that names an L1 backend and a
#: server overrides the joule defaults; the rest inherit them.
PRESET_SELECTIONS: dict[str, dict[str, str]] = {
    "ocudu-mono": {"gnb_stack": "OCUDU", "gnb_split": "monolithic"},
    "oai-mono": {"gnb_stack": "OAI", "gnb_split": "monolithic"},
    "ocudu-cudu": {"gnb_stack": "OCUDU", "gnb_split": "CU+DU"},
    "oai-cudu": {"gnb_stack": "OAI", "gnb_split": "CU+DU"},
    "ocudu-cu-oai-du": {"gnb_stack": "OCUDU", "gnb_split": "OCUDU-CU+OAI-DU"},
    "oai-cu-ocudu-du": {"gnb_stack": "OAI", "gnb_split": "OAI-CU+OCUDU-DU"},
    "oai-mono-aerial": {"gnb_stack": "OAI", "gnb_split": "monolithic",
                        "l1_backend": AERIAL_L1, "server": SPARK_SERVER},
    "oai-f1-aerial": {"gnb_stack": "OAI", "gnb_split": "CU+DU",
                      "l1_backend": AERIAL_L1, "server": SPARK_SERVER},
    "ocudu-mono-aerial": {"gnb_stack": "OCUDU", "gnb_split": "monolithic",
                          "l1_backend": AERIAL_L1, "server": SPARK_SERVER},
    "ocudu-f1-aerial": {"gnb_stack": "OCUDU", "gnb_split": "CU+DU",
                        "l1_backend": AERIAL_L1, "server": SPARK_SERVER},
}

PRESET_ORDER = tuple(PRESET_SELECTIONS)

LABELS: dict[str, str] = {
    "ocudu-mono": "OCUDU monolithic",
    "oai-mono": "OAI monolithic",
    "ocudu-cudu": "OCUDU CU + OCUDU DU",
    "oai-cudu": "OAI CU + OAI DU",
    "ocudu-cu-oai-du": "OCUDU CU + OAI DU",
    "oai-cu-ocudu-du": "OAI CU + OCUDU DU",
    "oai-mono-aerial": "OAI mono \u00b7 DGX Spark",
    "oai-f1-aerial": "OAI F1 \u00b7 DGX Spark",
    "ocudu-mono-aerial": "OCUDU mono \u00b7 DGX Spark",
    "ocudu-f1-aerial": "OCUDU F1 \u00b7 DGX Spark",
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
    "oai-mono-aerial": "oai-mono",
    "oai-f1-aerial": "oai-cudu",
    "ocudu-mono-aerial": "ocudu-mono",
    "ocudu-f1-aerial": "ocudu-cudu",
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
                sets=dict(PRESET_SELECTIONS[name]),
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
