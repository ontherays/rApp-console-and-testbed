"""Vendor marks for the components a topology is built from.

**These are not the vendors' logos.** OpenAirInterface, Open5GS, free5GC and
NVIDIA logos are trademarks: redistributing them inside this repository is a
licensing question rather than a design one, they would each have to be vendored
to satisfy the console's `default-src 'self'` policy, and a set of five logos
drawn by five different hands does not survive being shrunk into a 20 px chip
next to a line icon.

So each vendor gets a wordmark instead: its short name, set in the console's own
type, on its series colour where it has one. The colours are ETHOS's figure
colours, so a vendor mark, a chip and a plotted line agree.

If you want the real logos, drop the SVG files you are licensed to use into
`console/static/vendor-logos/` and point `MARKS[...].logo` at them; the macro
prefers a file when one is there.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mark:
    key: str
    short: str      # what goes in the mark
    label: str      # what a human reads
    colour: str
    note: str = ""
    logo: str | None = None   # a licensed SVG under static/vendor-logos/


MARKS: dict[str, Mark] = {
    "ocudu": Mark("ocudu", "OCUDU", "OCUDU gNB stack", "#56B4E9",
                  "The lab's own CU/DU stack"),
    "oai": Mark("oai", "OAI", "OpenAirInterface", "#E69F00",
                "OpenAirInterface 5G gNB"),
    "open5gs": Mark("open5gs", "O5GS", "Open5GS", "#0F9B8E",
                    "Open5GS 5G core"),
    "free5gc": Mark("free5gc", "F5GC", "free5GC", "#7C5CFC",
                    "free5GC 5G core"),
    "nvidia": Mark("nvidia", "NV", "NVIDIA Aerial", "#76B900",
                   "Aerial cuBB on the DGX-Spark"),
    "pegatron": Mark("pegatron", "PEG", "Pegatron O-RU", "#55606F", "7.2x O-RU"),
    "foxconn": Mark("foxconn", "FOX", "Foxconn O-RU", "#55606F", "7.2x O-RU"),
    "tm500": Mark("tm500", "TM", "VIAVI TM500", "#55606F", "UE and RU emulator"),
    "samsung": Mark("samsung", "SM", "Samsung handset", "#2F6FED", "Android UE"),
    "mtk": Mark("mtk", "MTK", "MediaTek handset", "#2F6FED", "Android UE"),
    "joule": Mark("joule", "JLE", "joule", "#55606F", "O-Cloud worker"),
    "dgxspark": Mark("dgxspark", "DGX", "DGX-Spark", "#76B900", "GB10 ARM host"),
}

# Which mark a catalogue option resolves to. Data, so adding a vendor is an edit
# here and not a branch anywhere.
BY_OPTION: dict[tuple[str, str], str] = {
    ("gnb_stack", "OCUDU"): "ocudu",
    ("gnb_stack", "OAI"): "oai",
    ("core", "Open5GS"): "open5gs",
    ("core", "free5GC"): "free5gc",
    ("l1_backend", "Aerial-cuBB"): "nvidia",
    ("ru", "Pegatron"): "pegatron",
    ("ru", "Foxconn"): "foxconn",
    ("ru", "TM500"): "tm500",
    ("ue", "Samsung"): "samsung",
    ("ue", "MTK"): "mtk",
    ("ue", "TM500"): "tm500",
    ("ue", "Pegatron-Dongle"): "pegatron",
    ("server", "joule"): "joule",
    ("server", "DGX-Spark"): "dgxspark",
}


def mark_for(category: str, option_id: str) -> Mark | None:
    key = BY_OPTION.get((category, option_id))
    return MARKS.get(key) if key else None
