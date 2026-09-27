"""No em dash anywhere the console writes.

The house rule: a comma, a colon, a full stop or brackets, never the long dash.
It applies to what a person reads on a page and to what is written in docs/, and
the check covers the source of both because a dash in a Python string reaches
the screen just as surely as one in a template.

The one deliberate exception is a fixture copied byte for byte from ETHOS: it is
neither UI text nor documentation, and editing it would make it useless as a
record of what that file says.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
EM_DASH = "—"

# A copy of ETHOS's own deploy_profiles.yaml, kept verbatim.
EXEMPT = {ROOT / "tests" / "recorded" / "deploy_profiles.yaml"}


def sources() -> list[Path]:
    found: list[Path] = []
    for pattern in (
        "console/**/*.py", "console/**/*.html", "console/**/*.css", "console/**/*.js",
        "docs/*.md", "docs/design/*.md", "tests/**/*.py",
        "README.md", "CLAUDE.md", "console.env.example",
    ):
        found += [
            path for path in ROOT.glob(pattern)
            if path.is_file()
            and path not in EXEMPT
            and "vendor" not in path.parts
            and path.name != "test_no_em_dash.py"
        ]
    return sorted(set(found))


@pytest.mark.parametrize("path", sources(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_em_dash_in_source(path: Path):
    text = path.read_text(encoding="utf-8")
    if EM_DASH not in text:
        return
    lines = [
        f"  {number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), 1)
        if EM_DASH in line
    ]
    pytest.fail(
        f"{path.relative_to(ROOT)} uses an em dash. Use a comma, a colon, a full "
        f"stop or brackets instead.\n" + "\n".join(lines)
    )


def test_the_check_covers_the_templates_and_the_python_that_feeds_them():
    covered = {str(path.relative_to(ROOT)) for path in sources()}
    for expected in (
        "console/templates/base.html",
        "console/templates/plan/page.html",
        "console/capabilities.py",
        "console/pages/plan.py",
        "docs/running-guide.md",
    ):
        assert expected in covered, f"{expected} is not being checked"


def test_the_not_measured_marker_is_not_a_dash():
    """GL-09 spells this as an em dash. It is words instead, so the rule holds
    without a value that was not measured looking like a minus sign."""
    from console.rapps.ethos.metrics import NOT_MEASURED

    assert EM_DASH not in NOT_MEASURED
    assert NOT_MEASURED.strip() not in ("", "-", ",", ".")
    assert NOT_MEASURED == "n/a"
