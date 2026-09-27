"""Which options can actually be deployed — until ``GET /catalogue`` exists.

``GET /compatibility`` says what is *compatible*. It does not say what can be
*deployed*, and the two differ: TM500, Foxconn and Aerial validate happily and
then fail at deploy against a ``TODO(Ravi)`` profile. Offering them as if they
were ready is the one failure mode the Test Plan page must not have.

So the console reads ETHOS's ``deployment/deploy_profiles.yaml`` — a plain data
file on this host, read and never written, holding no credential — and joins it
with the catalogue itself. That is exactly what backend change B4 will do
server-side; when it lands, this file goes and the endpoint answers instead.

If the file is not configured or not readable, deployability is ``None``, which
renders "unknown" rather than a guess. An unreadable file must not turn into
"everything works".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

WIRED = "wired"


@dataclass(frozen=True)
class Profile:
    name: str
    status: str
    releases: tuple[str, ...]
    match: dict[str, str]
    description: str = ""

    @property
    def deployable(self) -> bool:
        """``wired`` means the chart path, release name, values and namespace
        were confirmed from the real lab commands. ``todo`` is a placeholder the
        resolver refuses rather than fabricate a chart path — a wrong
        ``helm upgrade --install`` is a testbed change, not a bad reply."""
        return self.status == WIRED and bool(self.releases)

    def matches(self, selection: dict[str, Any]) -> bool:
        """Every key in the profile's own ``match`` block must equal the
        selection. Comparison is case-insensitive because the catalogue spells
        an id ``OCUDU`` and a slug ``ocudu``."""
        if not self.match:
            return False
        for key, wanted in self.match.items():
            got = selection.get(key)
            if got is None:
                return False
            if str(got).strip().lower() != str(wanted).strip().lower():
                return False
        return True


@dataclass(frozen=True)
class Profiles:
    """The deploy profiles as read. ``source`` is shown on the page so the
    stand-in is never mistaken for ETHOS's own answer."""

    profiles: tuple[Profile, ...]
    source: str | None
    error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.profiles) and self.error is None

    def get(self, name: str) -> Profile | None:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        return None

    def resolve(self, selection: dict[str, Any]) -> Profile | None:
        """The profile a selection resolves to, most specific first — so a
        TM500 UE picks ``ocudu-mono-tm500`` over ``ocudu-mono``."""
        candidates = [p for p in self.profiles if p.matches(selection)]
        if not candidates:
            return None
        return sorted(candidates, key=lambda p: len(p.match), reverse=True)[0]

    def deployable(self, selection: dict[str, Any]) -> tuple[bool | None, str]:
        """(deployable, reason). ``None`` means unknown, which is rendered as
        "unknown" — an unreadable profile file must never read as "works"."""
        if not self.available:
            return None, self.error or "deploy profiles were not read"
        profile = self.resolve(selection)
        if profile is None:
            return False, "No deploy profile matches this combination."
        if profile.deployable:
            return True, f"profile {profile.name}, {len(profile.releases)} release(s)"
        return False, (
            f"Deploy profile {profile.name} is a placeholder "
            f"(status: {profile.status or 'unset'}); its chart paths are not filled in."
        )


def load_profiles(path: Path | None) -> Profiles:
    if path is None:
        return Profiles((), None, "no deploy-profile file configured")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        return Profiles((), str(path), f"cannot read {path}: {exc}")
    except yaml.YAMLError as exc:
        return Profiles((), str(path), f"cannot parse {path}: {exc}")

    entries = raw.get("profiles") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return Profiles((), str(path), f"{path} has no profiles list")

    found: list[Profile] = []
    for body in entries:
        if not isinstance(body, dict) or not body.get("name"):
            continue
        names: list[str] = []
        for release in body.get("releases") or []:
            if isinstance(release, dict):
                value = release.get("release_name") or release.get("name")
                if value:
                    names.append(str(value))
            elif release:
                names.append(str(release))
        match = body.get("match") or {}
        found.append(
            Profile(
                name=str(body["name"]),
                status=str(body.get("status", "")).strip().lower(),
                releases=tuple(names),
                match={str(k): str(v) for k, v in match.items()}
                if isinstance(match, dict)
                else {},
                description=str(body.get("description", "")),
            )
        )
    return Profiles(tuple(found), str(path))


# Reasons an option cannot be deployed today. Every one of these was checked
# against the deploy profiles and the chart values on this host; none is a guess.
# They disappear as B4 supplies ETHOS's own reason per option.
OPTION_REASONS: dict[tuple[str, str], str] = {
    ("ru", "Foxconn"): "No chart configuration for this RU yet.",
    ("ru", "TM500"): "No chart configuration for this RU yet.",
    ("ue", "TM500"): "Driven from its own chassis; no ETHOS UE driver.",
    ("ue", "Pegatron-Dongle"): (
        "The driver needs the vendor attach and detach commands, which have no "
        "default — a guessed command would record an attach that never happened."
    ),
    ("l1_backend", "Aerial-cuBB"): (
        "Requires the DGX-Spark GB10 host; no deploy profile yet."
    ),
    ("server", "DGX-Spark"): (
        "ARM host: Intel RAPL does not apply, so energy capture is phase 2."
    ),
    ("core", "free5GC"): "Not verified on this testbed yet.",
}
