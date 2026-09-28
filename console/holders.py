"""How a lock holder is worded, in one place.

A holder appears in the status strip, on the Overview, in the readiness panel, in
a refused action's toast and on the Jobs page. It has to read the same in all of
them, so this is the only code that turns ETHOS's holder string into a sentence.

ETHOS names the holder and the console never guesses at one. The string carries
its own kind:

    cli:<pid>        a campaign someone is running from a shell
    job:<job_id>     a job, started here or by another client
    action:<name>    a standalone act, such as an attach

A CLI holder is the one worth spelling out, because it is the case a console user
cannot see from the console: somebody is at a terminal. So it reads
"CLI campaign <what> since <time>" rather than "cli:3340113", which means nothing
to anyone who did not start it.
"""

from __future__ import annotations

from typing import Any

from console.templating import clocktime

#: What to say when nothing holds the testbed. Not "unknown": a lock that was
#: read and found free is a fact.
FREE = "free"


def kind_of(holder: str | None) -> str:
    """`cli`, `job`, `action` or `other`."""
    text = str(holder or "")
    for prefix in ("cli", "job", "action"):
        if text.startswith(f"{prefix}:"):
            return prefix
    return "other" if text else ""


def describe(source: Any, *, tz: str = "Asia/Taipei") -> str:
    """One sentence for whoever holds the testbed.

    *source* is anything carrying `holder`, `what` and `since`: the `/lock` body,
    the summary's lock part, or a 409's detail.
    """
    holder = _get(source, "holder")
    if not holder:
        return FREE

    what = str(_get(source, "what") or "").strip()
    since = _get(source, "since")
    when = f" since {clocktime(since, tz)}" if since else ""
    kind = kind_of(holder)

    if kind == "cli":
        # ETHOS words a CLI holder's `what` as "campaign ocudu-mono, rates 100,
        # DL", so prefixing "CLI campaign" verbatim read "CLI campaign campaign
        # ocudu-mono". The word is dropped from one side, not both: "CLI" alone
        # would not say what is running.
        subject = what[len("campaign "):] if what.startswith("campaign ") else what
        return f"CLI campaign {subject}{when}" if subject else f"CLI campaign{when}"
    if kind == "job":
        job_id = str(holder).split(":", 1)[1]
        return f"job {job_id}, {what}{when}" if what else f"job {job_id}{when}"
    if kind == "action":
        name = str(holder).split(":", 1)[1]
        return f"{what or name}{when}"
    return f"{holder}{when}"


def short(source: Any) -> str:
    """The strip's own value, which has one line to say it in."""
    holder = _get(source, "holder")
    if not holder:
        return FREE
    kind = kind_of(holder)
    if kind == "cli":
        return "CLI campaign"
    if kind == "job":
        return "job"
    if kind == "action":
        return str(holder).split(":", 1)[1].replace("_", " ")
    return str(holder)


def held_by_cli(source: Any) -> bool:
    return kind_of(_get(source, "holder")) == "cli"


def _get(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)
