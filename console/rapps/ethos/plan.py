"""The test plan the console builds, and the checks it can make itself.

The plan document is the one backend change B2 will accept, so the form is built
against that shape from the start, a plan saved today is the body ``POST /jobs``
will take unchanged.

**The console adds no readiness check of its own.** ``POST /readiness`` (B5) is
what makes the CLI and the console judge readiness identically, and duplicating
its logic here would create a second opinion. What this module does instead is
narrower and honest: it parses the traffic plan with the same grammar the CLI
uses, so a plan that cannot be expressed as a campaign is caught before it is
saved, and every check is labelled as a console pre-check rather than as ETHOS's
answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MIN_RATE = 1.0
MAX_RATE = 10000.0
MIN_DURATION_S = 5.0
MAX_REPEATS = 20

DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.IGNORECASE)
UNITS = {"": 1.0, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


class PlanInvalid(Exception):
    pass


def parse_rates(text: str) -> list[float]:
    """``500``, ``100,200,300`` or ``100-1000:100``, the CLI's own grammar."""
    raw = (text or "").strip()
    if not raw:
        raise PlanInvalid("an offered load is required")

    if "-" in raw and "," not in raw:
        body, _, step_text = raw.partition(":")
        start_text, _, end_text = body.partition("-")
        try:
            start = float(start_text)
            end = float(end_text)
            step = float(step_text) if step_text else 100.0
        except ValueError as exc:
            raise PlanInvalid(
                f"{raw!r} is not a range; write it as start-end:step, e.g. 100-1000:100"
            ) from exc
        if step <= 0:
            raise PlanInvalid("a range step must be greater than 0")
        if end < start:
            raise PlanInvalid("a range must end at or above its start")
        rates: list[float] = []
        value = start
        while value <= end + 1e-9:
            rates.append(round(value, 6))
            value += step
    else:
        rates = []
        for piece in raw.replace(" ", "").split(","):
            if not piece:
                continue
            try:
                rates.append(float(piece))
            except ValueError as exc:
                raise PlanInvalid(f"{piece!r} is not a rate in Mbit/s") from exc

    if not rates:
        raise PlanInvalid("no rate was parsed from that offered load")
    for rate in rates:
        if not (MIN_RATE <= rate <= MAX_RATE):
            raise PlanInvalid(
                f"{rate:g} Mbit/s is outside the accepted range "
                f"{MIN_RATE:g}–{MAX_RATE:g}"
            )
    return rates


def parse_duration(text: str) -> float:
    """``30s``, ``5m``, or a bare number of seconds."""
    match = DURATION.match(text or "")
    if not match:
        raise PlanInvalid(
            f"{text!r} is not a duration; write 30s, 5m, or a number of seconds"
        )
    seconds = float(match.group(1)) * UNITS[match.group(2).lower()]
    if seconds < MIN_DURATION_S:
        raise PlanInvalid(f"a run must last at least {MIN_DURATION_S:g} s")
    return seconds


@dataclass
class Check:
    """One line of the readiness panel."""

    id: str
    label: str
    status: str = "unknown"      # pass | fail | unknown
    reason: str = ""


@dataclass
class TrafficPlan:
    rates_text: str = "100"
    direction: str = "DL"
    duration_text: str = "30s"
    repeats: int = 1
    iperf_server: str = "app_binary"
    radio_samples: bool = False
    label: str = ""

    rates: list[float] = field(default_factory=list)
    duration_s: float = 0.0
    errors: dict[str, str] = field(default_factory=dict)

    def parse(self) -> "TrafficPlan":
        try:
            self.rates = parse_rates(self.rates_text)
        except PlanInvalid as exc:
            self.errors["rates"] = str(exc)
        try:
            self.duration_s = parse_duration(self.duration_text)
        except PlanInvalid as exc:
            self.errors["duration"] = str(exc)
        if not 1 <= self.repeats <= MAX_REPEATS:
            self.errors["repeats"] = f"repeats must be between 1 and {MAX_REPEATS}"
        if self.direction not in ("DL", "UL"):
            self.errors["direction"] = "direction must be DL or UL"
        return self

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def points(self) -> int:
        return len(self.rates) * max(1, self.repeats)

    def estimated_seconds(self, *, gap_s: float = 30.0, overhead_s: float = 180.0) -> float:
        """Rates × repeats × (duration + the gap the CLI leaves between points),
        plus deploy and teardown. The overhead is a fixed estimate until job
        history exists to measure it (TP-16)."""
        return self.points * (self.duration_s + gap_s) + overhead_s

    def as_document(self, config_id: str | None, selection: dict[str, Any]) -> dict[str, Any]:
        """The plan in the shape ``POST /jobs`` will take (B2)."""
        return {
            "selection": selection,
            "config_id": config_id,
            "direction": self.direction,
            "rates": self.rates_text,
            "duration": self.duration_text,
            "repeats": self.repeats,
            "iperf_server": self.iperf_server,
            "radio_samples": self.radio_samples,
            "label": self.label,
            "cm_steps": [],
            "cm_sweep": None,
        }
