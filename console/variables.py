"""The list of ``CONSOLE_*`` variables, derived from the code that reads them.

A hand-kept list drifts the moment someone adds a variable and forgets the
documentation. So the list is not kept: it is collected by importing the config
modules and reading their ``ENV_*`` constants. A test compares it against
``console.env.example`` in both directions, which is what makes the example file
trustworthy.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

# Hand-curated, deliberately not a package scan: a scan would happily collect a
# name out of a docstring or a test fixture.
CONFIG_MODULES: tuple[str, ...] = (
    "console.settings",   # the server, login, ETHOS, storage, presentation
    "console.env_file",   # CONSOLE_ENV_FILE itself
)

PREFIX = "CONSOLE_"

# A commented-out declaration in the example still counts as declared, so an
# optional variable can be documented without being set.
_DECLARATION = re.compile(r"^\s*#?\s*(CONSOLE_[A-Z0-9_]+)\s*=")


def known_env_vars() -> tuple[str, ...]:
    """Every ``CONSOLE_*`` name the code reads, sorted."""
    found: set[str] = set()
    for name in CONFIG_MODULES:
        module = importlib.import_module(name)
        for value in vars(module).values():
            if (
                isinstance(value, str)
                and value.startswith(PREFIX)
                and value.isidentifier()
            ):
                found.add(value)
    return tuple(sorted(found))


def declared_env_vars(path: str | Path) -> tuple[str, ...]:
    """Every ``CONSOLE_*`` name declared in an env file, set or commented out."""
    found: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = _DECLARATION.match(line)
        if match:
            found.add(match.group(1))
    return tuple(sorted(found))
