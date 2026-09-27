"""Load ``console.env`` as a default layer under the real environment.

The rule, and the reason for it: **the real environment always wins.** A shell
``export``, a systemd ``Environment=`` line and a Kubernetes Secret all reach
the process through ``os.environ``, and every one of them predates this file.
If the file could overwrite them, installing it would silently change how an
existing deployment behaves. So the file fills in names that are *not* already
set, and nothing else. Loading twice is therefore a no-op.

A missing file is normal, not an error: in a container, in the test suite, and
on a host configured entirely through systemd there is no file to read.

``python-dotenv`` is used to *parse*. The merge is ours, because the precedence
rule above is the whole point.

Nothing here logs a value. Half of what the file holds is the password hash and
the session secret, so the load record carries names and counts only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

# Read from the real environment only — it names the file, so a file cannot
# choose which file is read.
ENV_FILE_VAR = "CONSOLE_ENV_FILE"

DEFAULT_ENV_FILE = "console.env"
EXAMPLE_ENV_FILE = "console.env.example"


@dataclass(frozen=True)
class EnvFileLoad:
    """What one load did. Names only, never values."""

    path: Path
    exists: bool
    applied: tuple[str, ...] = ()
    kept_from_environment: tuple[str, ...] = ()

    def describe(self) -> str:
        if not self.exists:
            return f"no env file at {self.path} (using the environment as-is)"
        return (
            f"{self.path}: applied {len(self.applied)}, "
            f"kept {len(self.kept_from_environment)} already in the environment"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "applied": list(self.applied),
            "kept_from_environment": list(self.kept_from_environment),
        }


def env_file_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Explicit argument, then ``$CONSOLE_ENV_FILE``, then ``./console.env``."""
    if path is not None:
        return Path(path)
    named = os.environ.get(ENV_FILE_VAR)
    if named:
        return Path(named)
    return Path(DEFAULT_ENV_FILE)


def load_env_file(
    path: str | os.PathLike[str] | None = None,
    target: dict[str, str] | None = None,
) -> EnvFileLoad:
    """Apply the file's names that the environment does not already define."""
    resolved = env_file_path(path)
    environ = os.environ if target is None else target

    if not resolved.is_file():
        return EnvFileLoad(path=resolved, exists=False)

    applied: list[str] = []
    kept: list[str] = []
    for name, value in dotenv_values(resolved).items():
        if value is None:
            # A bare ``NAME`` with no ``=``. It declares nothing; skip it.
            continue
        if name in environ:
            kept.append(name)
            continue
        environ[name] = value
        applied.append(name)

    return EnvFileLoad(
        path=resolved,
        exists=True,
        applied=tuple(sorted(applied)),
        kept_from_environment=tuple(sorted(kept)),
    )
