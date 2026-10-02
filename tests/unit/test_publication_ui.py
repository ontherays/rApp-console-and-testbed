"""The Publication page: four actions, and never a false success.

The console presents; ETHOS decides. So these assert what the console SENDS and
what it SHOWS, never whether anything was published: that is ETHOS's answer, and
the fake gives it.

The property worth the most here is the last one. A publish can be committed and
not verified, or verified and not pushed, and each of those is a failure an
operator has to see. A page that rendered "Published" and stopped would be
telling somebody their results are safe when they are on one disk.
"""

from __future__ import annotations

import pytest


# --- the console owns no git -------------------------------------------------


def test_the_console_runs_no_git_and_no_subprocess():
    """The architectural rule, asserted rather than assumed.

    Every publication action is an HTTP call to ETHOS, which holds the
    repository and the credentials. A console that shelled out to git would be
    a second thing that can publish, with none of the gates.
    """
    from pathlib import Path

    import re

    root = Path(__file__).resolve().parent.parent.parent / "console"
    # Usage, not the word: this file's own modules explain in prose that they
    # run no subprocess, and a search for the string would flag the sentence.
    usage = re.compile(r"\bimport\s+subprocess\b|\bsubprocess\s*\.|"
                       r"\bPopen\s*\(|\bos\.system\s*\(|"
                       r"create_subprocess_(exec|shell)")
    offenders = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if usage.search(path.read_text(encoding="utf-8"))
    )
    assert offenders == []


def test_the_page_only_ever_calls_the_publication_endpoints(client, ethos_url):
    client.get("/publication")
    paths = {path for _method, path in ethos_url.calls}
    assert "/publish/status" in paths
    assert not any(p.startswith("/publish") and "git" in p for p in paths)


# --- status ------------------------------------------------------------------


def test_the_status_panel_shows_the_counts(client, ethos_url):
    body = client.get("/publication").text
    assert "952" in body and "937" in body        # artifacts, durable
    assert "Pending" in body and "Incomplete" in body
    assert "10 days" in body


def test_the_status_panel_shows_retention_as_local_and_an_upper_bound(client, ethos_url):
    body = client.get("/publication").text
    assert "Eligible locally" in body and "135" in body
    assert "upper bound" in body
    assert "python -m publication prune --confirm" in body


def test_there_is_no_delete_or_prune_button(client, ethos_url):
    """Retention is shown and never acted on. No force, no per-artifact delete."""
    body = client.get("/publication").text
    for forbidden in ("Delete", "Force", "/publication/prune", "hx-delete"):
        assert forbidden not in body, forbidden


def test_the_remote_is_not_asked_for_on_a_plain_page_load(client, ethos_url):
    """Opening the page must not depend on GitHub being up."""
    client.get("/publication")
    assert ("GET", "/publish/status") in ethos_url.calls
    body = client.get("/publication").text
    assert "Not asked" in body and "Check GitHub" in body


def test_the_remote_is_shown_when_the_operator_asks(client, ethos_url):
    body = client.get("/publication/status?remote=true").text
    assert "origin/main is at eaa4a737" in body


def test_an_unknown_remote_is_shown_as_unknown_not_as_failure(client, ethos_url):
    ethos_url.publication["remote_when_asked"] = {
        "checked": True, "established": False, "head": None,
        "reason": "could not read from remote repository",
    }
    body = client.get("/publication/status?remote=true").text
    assert "Remote synchronization unknown" in body
    assert "could not read from remote repository" in body


def test_a_busy_publication_is_named_on_the_page(client, ethos_url):
    ethos_url.hold_publication(holder="cli:publish:4242", what="publishing results")
    body = client.get("/publication").text
    assert "Publication busy" in body
    assert "cli:publish:4242" in body and "4242" in body
    assert "publishing results" in body


# --- publish -----------------------------------------------------------------


def test_publish_previews_before_it_publishes(client, ethos_url):
    body = client.post("/publication/publish/preview").text
    assert "Publish?" in body
    assert "1790.abc.def" in body, "the token the confirmation carries"
    assert ("POST", "/publish") not in ethos_url.calls, "nothing was published"


def test_confirming_sends_the_token_and_not_push(client, ethos_url):
    client.post("/publication/publish", data={"preview_token": "1790.abc.def"})
    sent = ethos_url.publish_calls[-1]
    assert sent == {"confirm": True, "preview_token": "1790.abc.def", "push": False}


def test_a_successful_publish_says_what_it_did(client, ethos_url):
    body = client.post("/publication/publish",
                       data={"preview_token": "1790.abc.def"}).text
    assert "Published" in body and "09816212" in body
    assert "Verified" in body
    assert "not asked to push" in body


# --- publish + push ----------------------------------------------------------


def test_publish_and_push_is_one_request_the_backend_sequences(client, ethos_url):
    """The console must not order commit, verify and push itself."""
    client.post("/publication/publish",
                data={"preview_token": "1790.abc.def", "push": "true"})

    assert ethos_url.publish_calls[-1]["push"] is True
    assert ethos_url.push_calls == [], "no separate push call is made"


def test_publish_and_push_reports_the_push(client, ethos_url):
    body = client.post("/publication/publish",
                       data={"preview_token": "1790.abc.def", "push": "true"}).text
    assert "Pushed" in body and "origin/main now at" in body


def test_the_preview_carries_the_push_choice_through(client, ethos_url):
    body = client.post("/publication/publish/preview", data={"push": "true"}).text
    assert "Publish and push?" in body
    assert 'name="push" value="true"' in body


# --- no false success --------------------------------------------------------


def test_an_unverified_publication_is_shown_as_a_failure(client, ethos_url):
    """Phase 3: committed, not verified, not pushed. The page must say so."""
    ethos_url.publish_result = {
        "published": True, "verified": False, "pushed": False,
        "commit": "abc1234" + "0" * 33, "files_written": 1,
        "push_detail": "not pushed: this publication did not land in full",
        "verification": {"ok": False, "reason": "1 file is not in the commit"},
    }
    body = client.post("/publication/publish",
                       data={"preview_token": "1790.abc.def", "push": "true"}).text

    assert "Not verified" in body
    assert "did not land in full" in body
    assert "1 file is not in the commit" in body


def test_a_push_failure_after_a_good_publish_is_shown_and_retryable(client, ethos_url):
    ethos_url.publish_result = {
        "published": True, "verified": True, "pushed": False,
        "commit": "abc1234" + "0" * 33, "files_written": 15,
        "push_detail": "push failed: Permission denied (publickey)",
        "verification": {"ok": True},
    }
    body = client.post("/publication/publish",
                       data={"preview_token": "1790.abc.def", "push": "true"}).text

    assert "Not pushed" in body
    assert "Permission denied" in body
    assert "commit is kept" in body
    assert "Push to GitHub to retry" in body


def test_nothing_to_publish_is_not_reported_as_published(client, ethos_url):
    ethos_url.publish_result = {
        "published": False,
        "detail": "nothing to publish, everything selected is already durable",
    }
    body = client.post("/publication/publish",
                       data={"preview_token": "1790.abc.def"}).text
    assert "already durable" in body
    assert "Verified" not in body


# --- verify ------------------------------------------------------------------


def test_verify_is_a_read(client, ethos_url):
    client.get("/publication/verify")
    methods = [m for m, p in ethos_url.calls if p == "/publish/verify"]
    assert methods == ["GET"]
    assert ethos_url.publish_calls == [] and ethos_url.push_calls == []


def test_verify_shows_the_result(client, ethos_url):
    body = client.get("/publication/verify").text
    assert "Verification" in body
    assert "Read-only" in body
    assert "Every published artifact matches" in body


def test_verify_names_what_is_not_durable(client, ethos_url):
    ethos_url.publication["verification"] = {
        "configured": True, "head": "eaa4a737", "artifacts": 3,
        "durable": 2, "not_durable": 1, "verified": False, "missing_files": 1,
        "artifacts_detail": [
            {"artifact_id": "run-a", "status": "mismatch", "durable": False,
             "reason": "1 file is not in the repository"},
        ],
    }
    body = client.get("/publication/verify").text
    assert "run-a" in body and "mismatch" in body
    assert "1 file is not in the repository" in body


# --- push on its own ---------------------------------------------------------


def test_push_previews_first(client, ethos_url):
    body = client.post("/publication/push/preview").text
    assert "Push to GitHub?" in body
    assert "eaa4a737" in body
    assert "commits nothing" in body
    assert ethos_url.push_calls[-1] == {}, "the preview confirmed nothing"


def test_push_sends_the_token(client, ethos_url):
    client.post("/publication/push", data={"preview_token": "1790.head.sig"})
    assert ethos_url.push_calls[-1] == {"confirm": True,
                                        "preview_token": "1790.head.sig"}


def test_push_works_with_nothing_pending(client, ethos_url):
    """Phase 2's retry. The state it exists for has nothing pending."""
    ethos_url.publication["to_publish"] = 0
    ethos_url.publication["new"] = 0
    ethos_url.publication["changed"] = 0

    body = client.post("/publication/push",
                       data={"preview_token": "1790.head.sig"}).text
    assert "origin/main now at" in body


def test_a_push_refusal_is_shown_as_one(client, ethos_url):
    ethos_url.push_result = {
        "configured": True, "pushed": False, "head": "eaa4a737", "surveyed": 952,
        "detail": "not pushed: 1 artifact is missing from the repository.",
        "missing_files": [{"artifact_id": "run-a", "missing": ["runs/run-a/x.yml"]}],
    }
    body = client.post("/publication/push",
                       data={"preview_token": "1790.head.sig"}).text
    assert "Not pushed" in body
    assert "missing from the repository" in body


def test_nothing_published_yet_is_not_offered_as_a_push(client, ethos_url):
    ethos_url.push_result = {
        "configured": True, "pushed": False,
        "detail": "nothing has been published yet, so there is nothing to push",
    }
    response = client.post("/publication/push/preview")
    assert "nothing to push" in response.headers["X-Console-Toast"]
    assert response.headers["X-Console-Toast-Variant"] == "warning"


# --- refusals and failures ---------------------------------------------------


@pytest.mark.parametrize("path, data", [
    ("/publication/publish", {"preview_token": "t"}),
    ("/publication/push/preview", {}),
    ("/publication/push", {"preview_token": "t"}),
])
def test_a_busy_publication_refuses_every_act_with_the_holder(
    client, ethos_url, path, data
):
    ethos_url.hold_publication(holder="cli:prune:777", what="a retention run")
    response = client.post(path, data=data)

    assert response.status_code == 409
    toast = response.headers["X-Console-Toast"]
    assert "publication busy" in toast
    assert "cli:prune:777" in toast and "777" in toast
    assert response.headers["X-Console-Toast-Variant"] == "warning"


def test_a_publish_preview_is_a_read_and_is_not_refused_while_busy(client, ethos_url):
    """ETHOS does not take the lock to describe what publishing would do.

    Asking is not acting, and an operator looking at a long publish must be
    able to see what is pending without being turned away.
    """
    ethos_url.hold_publication()
    assert client.post("/publication/publish/preview").status_code == 200
    assert client.get("/publication").status_code == 200
    assert client.get("/publication/verify").status_code == 200


def test_a_backend_failure_is_a_failure_not_a_blank_page(client, ethos_url):
    ethos_url.refuse(500, {"detail": "the archive could not be read"})
    response = client.post("/publication/publish/preview")

    assert response.status_code == 500
    assert "could not be read" in response.headers["X-Console-Toast"]
    assert response.headers["X-Console-Toast-Variant"] == "danger"


def test_ethos_being_down_is_shown_on_the_page(client, ethos_url):
    ethos_url.go_down()
    body = client.get("/publication").text
    assert "unreachable" in body.lower()


def test_a_timeout_is_shown_rather_than_an_empty_panel(client, ethos_url):
    ethos_url.go_down()
    response = client.post("/publication/publish/preview")
    assert response.status_code >= 400
    assert response.headers["X-Console-Toast"]


def test_a_stale_preview_is_refused_and_said_so(client, ethos_url):
    ethos_url.answer("POST", "/publish", 412,
                     {"detail": {"error": "state_changed",
                                 "message": "the content moved after the preview"}})
    response = client.post("/publication/publish", data={"preview_token": "old"})

    assert response.status_code == 412
    assert "content moved" in response.headers["X-Console-Toast"]


def test_publishing_without_a_token_never_reaches_ethos(client, ethos_url):
    """There is no console route that can publish unconfirmed.

    The token is a required form field, so a request without one is refused
    before any call is made -- the preview gate cannot be skipped by posting
    straight at the confirm route.
    """
    response = client.post("/publication/publish", data={})
    assert response.status_code == 422
    assert ethos_url.publish_calls == [], "nothing was asked of ETHOS"


def test_a_confirmation_ethos_rejects_is_relayed_not_swallowed(client, ethos_url):
    ethos_url.answer("POST", "/publish", 428,
                     {"detail": {"error": "confirmation_required",
                                 "message": "preview first"}})
    response = client.post("/publication/publish", data={"preview_token": "stale"})

    assert response.status_code == 428
    assert "preview first" in response.headers["X-Console-Toast"]


# --- the page is called GitHub, the implementation is not --------------------


def test_the_page_is_titled_github(client, ethos_url):
    """The operator-facing name. What ETHOS calls it is a different question."""
    body = client.get("/publication").text
    assert "<title>GitHub · Testbed Console</title>" in body
    assert '<h1 class="page-title">GitHub</h1>' in body


def test_the_sidebar_calls_it_github():
    from console.nav import GROUPS

    labels = {item.label: item.href for group in GROUPS for item in group.items}
    assert labels.get("GitHub") == "/publication"
    assert "Publication" not in labels


def test_the_route_and_the_endpoints_keep_their_names(client, ethos_url):
    """Renaming the label must not rename the implementation.

    The console route, ETHOS's endpoints and the page module are all still
    `publication`; only what an operator reads changed.
    """
    assert client.get("/publication").status_code == 200
    client.get("/publication")
    assert ("GET", "/publish/status") in ethos_url.calls

    import console.pages.publication as page

    assert page.router is not None


def test_the_operational_wording_still_matches_what_ethos_says(client, ethos_url):
    """`Publication busy` is ETHOS's own phrase, and the toast uses it too.

    Renaming only the banner would leave the page and the toast disagreeing
    about the same refusal, so the operational messages keep the backend's
    word even though the page is called GitHub.
    """
    ethos_url.hold_publication(holder="cli:publish:4242", what="publishing results")
    assert "Publication busy" in client.get("/publication").text


# --- the layout ---------------------------------------------------------------


def test_the_four_counts_are_stat_cards_not_a_bare_list(client, ethos_url):
    """The page used `<dl class="kv">` for these and the CSS had no `.kv` rule,
    so they rendered as a browser-default list: the pale, loose column this
    replaces."""
    body = client.get("/publication").text
    assert body.count('class="statgrid"') >= 1
    for label in ("Artifacts", "Durable", "Pending", "Incomplete"):
        assert f'<span class="k">{label}</span>' in body


def test_every_class_the_page_uses_is_defined_in_the_stylesheet(client, ethos_url):
    """The bug behind the pale look, caught mechanically.

    `.kv` and `.preview-list` were used from the day the page landed and were
    never defined, so they did nothing at all. A class that names no rule is a
    silent styling failure, which is the hardest kind to notice.
    """
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2]
           / "console" / "static" / "css" / "console.css").read_text()
    body = client.get("/publication").text

    used: set[str] = set()
    for group in re.findall(r'class="([^"{}]*)"', body):
        used.update(name for name in group.split() if name)

    # Shoelace parts and state hooks are styled by the vendored theme.
    ignore = {"ic", "page-title", "title-ico"}
    missing = sorted(
        name for name in used - ignore
        if not re.search(r"\." + re.escape(name) + r"[\s,{:.\[]", css)
    )
    assert missing == [], f"classes with no rule behind them: {missing}"


def test_actions_lead_the_page_and_the_whole_workflow_is_the_primary(client, ethos_url):
    """`Publish + Push` is what the scheduled timer runs, so it is the one the
    page pushes forward."""
    body = client.get("/publication").text
    assert body.index("Publish + Push") < body.index("Artifacts")
    assert 'class="btn lg grad"' in body


def test_zero_states_read_as_facts_rather_than_as_missing_data(client, ethos_url):
    ethos_url.publication["to_publish"] = 0
    ethos_url.publication["new"] = 0
    ethos_url.publication["changed"] = 0
    ethos_url.publication["incomplete"] = []

    body = client.get("/publication").text
    assert "Nothing awaiting publication" in body
    assert "None, every artifact is whole" in body


def test_an_unchecked_remote_looks_deliberate(client, ethos_url):
    body = client.get("/publication").text
    assert "Not asked" in body
    assert "Reading this page does not depend on GitHub." in body
    assert "Check GitHub" in body


def test_a_checked_remote_shows_the_branch_and_head(client, ethos_url):
    body = client.get("/publication/status?remote=true").text
    assert "In sync" in body
    assert "origin/main" in body and "eaa4a737" in body
