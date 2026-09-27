"""The campaign command a plan corresponds to.

Starting a campaign over HTTP is backend change B2; today it runs from
``python -m campaign``. Rather than disable RUN and leave the operator to
reconstruct the flags, the Test Plan page renders the exact command for the plan
on screen, with a copy button.

The topology argument is the deploy-profile name, which is what the CLI's
positional argument takes — resolved from the selection by ``profiles.py``, not
assembled from strings here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    duration: str,
    repeats: int = 1,
    radio_samples: bool = False,
    core: str | None = None,
    ue: str | None = None,
) -> CampaignCommand:
    if not topology:
        return CampaignCommand(
            command="",
            caveats=("No deploy profile matches this selection, so there is no "
                     "campaign command for it.",),
        )

    parts = [
        f"cd {ethos_repo}",
        "&&",
        ".venv/bin/python -m campaign",
        topology,
        f"--rates {rates}",
        f"--direction {direction}",
        f"--duration {duration}",
    ]
    if core:
        parts.append(f"--core {core}")
    if ue:
        parts.append(f"--ue {ue}")
    if radio_samples:
        parts.append("--radio-samples")

    caveats: list[str] = []
    if repeats > 1:
        caveats.append(
            f"The CLI has no --repeats flag, so {repeats} repeats per rate means "
            f"running this command {repeats} times. Repeats inside one campaign "
            f"arrive with backend change B8."
        )
    return CampaignCommand(command=" ".join(parts), caveats=tuple(caveats))
