"""The diagram's text: captions that wrap, and interfaces on the connectors.

SVG text neither wraps nor pushes anything aside, so a caption one word too
long is drawn straight over its neighbour. The renderer measures each caption
against its own box and breaks it itself. The browser tests check the result
on the laid-out page; these check the arithmetic that gets it there.
"""

from __future__ import annotations

import re

import pytest

from console.topology import (
    CAPTION_LINES,
    CAPTION_PX,
    CHAR_EM,
    LINK_PAD,
    LINK_PX,
    LINK_MAX_W,
    NODE_MAX_W,
    NODE_MIN_W,
    TARGET_W,
    allocate,
    F1,
    FAPI,
    FRONTHAUL,
    NG,
    UU,
    diagram,
    nodes_for,
    wrap_caption,
)

SELECTION = {"gnb_stack": "OCUDU", "ue": "Samsung", "ru": "Pegatron",
             "core": "Open5GS", "server": "joule", "l1_backend": "software-PHY"}
SPARK = {**SELECTION, "l1_backend": "Aerial-cuBB", "server": "DGX-Spark"}


class TestCaptions:
    def test_a_caption_that_fits_is_left_alone(self):
        assert wrap_caption("Samsung", 86) == ["Samsung"]

    def test_a_long_caption_breaks_between_words(self):
        lines = wrap_caption("Pegatron, via CX7 and OcNOS", 86)
        assert len(lines) == 2
        assert " ".join(lines) == "Pegatron, via CX7 and OcNOS"

    def test_a_caption_is_never_more_than_two_lines(self):
        lines = wrap_caption("one two three four five six seven eight nine", 86)
        assert len(lines) == CAPTION_LINES
        assert lines[-1].endswith("…")

    def test_a_single_word_too_long_for_a_line_is_cut_with_an_ellipsis(self):
        lines = wrap_caption("anextremelylongsinglewordwithnobreaks", 86)
        assert len(lines) == 1
        assert lines[0].endswith("…")
        assert len(lines[0]) < len("anextremelylongsinglewordwithnobreaks")

    def test_nothing_is_drawn_for_an_empty_caption(self):
        assert wrap_caption("", 86) == []
        assert wrap_caption("   ", 86) == []

    def test_the_whole_caption_stays_as_the_tooltip(self):
        """What was cut is still readable, so shortening never loses it."""
        svg = diagram({**SPARK, "ru": "Pegatron"}, split="CU+DU")
        assert "<title>Pegatron, via CX7 and OcNOS</title>" in svg

    def test_each_caption_is_one_text_element_with_its_lines_as_tspans(self):
        svg = diagram(SELECTION, split="monolithic")
        captions = re.findall(r'<text class="topo-caption".*?</text>', svg)
        assert captions
        for caption in captions:
            assert caption.count("<tspan") <= CAPTION_LINES
            assert f'font-size="{CAPTION_PX}"' in caption


class TestInterfaces:
    def test_every_connector_but_the_first_names_its_interface(self):
        chain = nodes_for(SPARK, split="CU+DU")
        row = chain.all_nodes()
        assert row[0].link_in == ""
        assert [node.link_in for node in row[1:]] == [UU, FRONTHAUL, FAPI, F1, NG]

    def test_a_monolithic_stack_reaches_the_radio_over_the_fronthaul(self):
        chain = nodes_for(SELECTION, split="monolithic")
        assert [node.link_in for node in chain.all_nodes()] == ["", UU, FRONTHAUL, NG]

    def test_the_names_are_drawn(self):
        svg = diagram(SPARK, split="CU+DU")
        drawn = re.findall(r'class="topo-link"[^>]*>([^<]+)<', svg)
        assert drawn == [UU, FRONTHAUL, FAPI, F1, NG]

    def test_a_screen_reader_is_told_the_interfaces_too(self):
        said = nodes_for(SPARK, split="CU+DU").describe()
        for name in (UU, FRONTHAUL, FAPI, F1, NG):
            assert f"over {name}" in said

    def test_a_preset_card_draws_no_text_at_all(self):
        """The mini diagram is 54px of box. Captions and interface names would
        be unreadable, and the card's own name says what it is."""
        svg = diagram(SPARK, split="CU+DU", size="mini")
        assert "topo-caption" not in svg
        assert "topo-link" not in svg


class TestGeometry:
    @pytest.mark.parametrize("split", ["monolithic", "CU+DU"])
    @pytest.mark.parametrize("selection", [SELECTION, SPARK],
                             ids=["joule", "spark"])
    def test_every_chain_is_laid_out_to_the_same_width(self, selection, split):
        """However many nodes it has, the row fills one width.

        That is what stops a four-node chain ending halfway across the card
        while a six-node one fills it: they share the width out differently
        rather than being drawn at different sizes.
        """
        svg = diagram(selection, split=split)
        width = float(re.search(r'viewBox="0 0 ([\d.]+)', svg).group(1))
        assert width == pytest.approx(TARGET_W, abs=1), width

    @pytest.mark.parametrize("split", ["monolithic", "CU+DU"])
    @pytest.mark.parametrize("selection", [SELECTION, SPARK],
                             ids=["joule", "spark"])
    def test_a_gap_is_wide_enough_for_the_name_that_sits_in_it(
        self, selection, split
    ):
        """No connector is drawn narrower than the interface written on it,
        whatever the allocation gave the rest of the row."""
        svg = diagram(selection, split=split)
        chain = nodes_for(selection, split=split)
        drawn = [float(w) for w in
                 re.findall(r'<rect x="[\d.-]+" y="[\d.]+" width="([\d.]+)" height="16"', svg)]
        wanted = [len(node.link_in) * LINK_PX * CHAR_EM + 2 * LINK_PAD
                  for node in chain.all_nodes()[1:] if node.link_in]
        assert len(drawn) == len(wanted), (drawn, wanted)
        for got, need in zip(drawn, wanted):
            assert got >= need - 0.5, (got, need)

    @pytest.mark.parametrize("split", ["monolithic", "CU+DU"])
    @pytest.mark.parametrize("selection", [SELECTION, SPARK],
                             ids=["joule", "spark"])
    def test_every_box_sits_between_the_minimum_and_the_maximum(
        self, selection, split
    ):
        """Few nodes get wide boxes, many get compact ones, and neither runs
        past the bounds: a 300px box is not a better box."""
        svg = diagram(selection, split=split)
        boxes = [float(w) + 1.5 for w in
                 re.findall(r'<rect x="0.75" y="0.75" width="([\d.]+)"', svg)]
        assert boxes
        for box in boxes:
            assert NODE_MIN_W - 0.5 <= box <= NODE_MAX_W + 0.5, box

    def test_a_short_chain_reaches_its_maximum_and_is_not_stretched(self):
        """Nothing is ever widened past its maximum to fill a gap. A chain
        short enough to reach every maximum is drawn narrower than the target
        and centred by the stylesheet."""
        widths = allocate([(NODE_MIN_W, NODE_MAX_W)] * 3 + [(24, LINK_MAX_W)] * 2,
                          TARGET_W)
        assert widths == [NODE_MAX_W] * 3 + [LINK_MAX_W] * 2
        assert sum(widths) < TARGET_W

    def test_the_full_diagram_is_drawn_at_its_own_size(self):
        """Scaling it to fit would take the type down with it."""
        svg = diagram(SPARK, split="CU+DU")
        width = re.search(r'viewBox="0 0 ([\d.]+)', svg).group(1)
        assert f'width="{width}"' in svg
        assert 'width="100%"' not in svg

    def test_a_preset_diagram_scales_to_its_card(self):
        assert 'width="100%"' in diagram(SPARK, split="CU+DU", size="mini")
