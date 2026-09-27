"""The campaign command a plan corresponds to.

Starting a campaign over HTTP is backend change B2; today it runs from
`python -m campaign`. Rather than disable RUN and leave the operator to
reconstruct the flags, the Test Plan renders the exact command for the plan on
screen, with a copy button.

Every flag was checked against `.venv/bin/python -m campaign --help` in the
ETHOS repository, and the result was run with `--dry-run`. What that turned up:

* the positional argument is the deploy-profile name, which is also what the CLI
  lists as a topology, so it comes from `profiles.py` and is never assembled;
* `--duration` is written in seconds. The CLI's help says a minute or hour
  suffix is refused, and its parser in fact accepts one, so the two disagree;
  seconds are correct whichever way that is settled, and the form still takes
  "5m" because it is easier to type;
* `--core` accepts open5gs or free5gc, and `--ue` accepts samsung, mtk or
  tm500. Anything else is left off with a note rather than passed through to be
  rejected;
* there is no `--repeats`. Repeats mean running the command again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# What --core and --ue accept, from the CLI's own choices.
CORES: dict[str, str] = {"Open5GS": "open5gs", "free5GC": "free5gc"}
UES: dict[str, str] = {"Samsung": "samsung", "MTK": "mtk", "TM500": "tm500"}


@dataclass(frozen=True)
class CampaignCommand:
    command: str
    caveats: tuple[str, ...] = ()


def campaign_command(
    *,
    ethos_repo: Path,
    topology: str | None,
    rates: str,
    direction: str,
    duration_s: float,
    repeats: int = 1,
    radio_samples: bool = False,
    core: str | None = None,
    ue: str | None = None,
) -> CampaignCommand:
    if not topology:
        return CampaignCommand(
            command="",
            caveats=(
                "No deploy profile matches this selection, so there is no "
                "campaign command for it.",
            ),
        )

    caveats: list[str] = []
    parts = [
        f"cd {ethos_repo}",
        "&&",
        ".venv/bin/python -m campaign",
        topology,
        f"--rates {rates}",
        f"--direction {direction}",
        f"--duration {duration_s:g}s",
    ]

    if core:
        flag = CORES.get(core)
        if flag:
            parts.append(f"--core {flag}")
        else:
            caveats.append(
                f"The CLI has no --core value for {core}, so the command leaves "
                f"the flag off and its default (open5gs) applies."
            )
    if ue:
        flag = UES.get(ue)
        if flag:
            parts.append(f"--ue {flag}")
        else:
            caveats.append(
                f"The CLI's --ue accepts only samsung, mtk or tm500, so {ue} is "
                f"left off and its default (samsung) applies."
            )
    if radio_samples:
        parts.append("--radio-samples")

    if repeats > 1:
        caveats.append(
            f"There is no --repeats flag, so {repeats} repeats per rate means "
            f"running this command {repeats} times. Repeats inside one campaign "
            f"arrive with backend change B8."
        )

    return CampaignCommand(command=" ".join(parts), caveats=tuple(caveats))
