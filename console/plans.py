"""Saved test plans, as files under ``CONSOLE_PLANS_DIR``.

The console's only storage is plans, its env file and its logs (NF-04). A plan is
a small JSON document written outside the repository, so a saved plan survives a
``git clean`` and never lands in a commit.

A name is not a path: it is slugged and the result is checked to be a direct
child of the plans directory, so a name can never write outside it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
MAX_NAME = 64


class PlanError(Exception):
    """A plan could not be saved or read, with a reason worth showing."""


def slug(name: str) -> str:
    cleaned = SAFE.sub("-", name.strip()).strip("-._")
    if not cleaned:
        raise PlanError("a plan needs a name made of letters, digits, - or _")
    return cleaned[:MAX_NAME]


@dataclass(frozen=True)
class SavedPlan:
    name: str
    path: Path
    saved_at: str
    plan: dict[str, Any]

    @property
    def summary(self) -> str:
        p = self.plan
        bits = [
            str(p.get("config_id") or p.get("topology") or "no topology"),
            str(p.get("direction") or ""),
            str(p.get("rates") or ""),
            str(p.get("duration") or ""),
        ]
        return " · ".join(b for b in bits if b)


class PlanStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _file(self, name: str) -> Path:
        candidate = (self.directory / f"{slug(name)}.json").resolve()
        root = self.directory.resolve()
        if candidate.parent != root:
            raise PlanError("that plan name is not allowed")
        return candidate

    def save(self, name: str, plan: dict[str, Any]) -> SavedPlan:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._file(name)
        body = {
            "name": slug(name),
            "saved_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "plan": plan,
        }
        path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
        return SavedPlan(
            name=body["name"], path=path, saved_at=body["saved_at"], plan=plan
        )

    def get(self, name: str) -> SavedPlan:
        path = self._file(name)
        if not path.is_file():
            raise PlanError(f"no saved plan called {slug(name)}")
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PlanError(f"cannot read {path.name}: {exc}") from exc
        return SavedPlan(
            name=body.get("name", path.stem),
            path=path,
            saved_at=body.get("saved_at", ""),
            plan=body.get("plan", {}),
        )

    def list(self) -> list[SavedPlan]:
        if not self.directory.is_dir():
            return []
        found: list[SavedPlan] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                found.append(self.get(path.stem))
            except PlanError:
                continue
        return sorted(found, key=lambda p: p.saved_at, reverse=True)

    def delete(self, name: str) -> None:
        path = self._file(name)
        if path.is_file():
            path.unlink()
