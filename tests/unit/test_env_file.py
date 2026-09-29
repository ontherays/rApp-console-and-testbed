"""The env file, and the promise that the example lists everything."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from console.env_file import EnvFileLoad, env_file_path, load_env_file
from console.variables import declared_env_vars, known_env_vars

EXAMPLE = Path(__file__).resolve().parent.parent.parent / "console.env.example"


@pytest.fixture(autouse=True)
def keep_environ():
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)


def test_a_missing_file_is_normal(tmp_path):
    load = load_env_file(tmp_path / "absent.env")
    assert load.exists is False
    assert load.applied == ()


def test_the_file_fills_in_names_that_are_not_set(tmp_path):
    path = tmp_path / "console.env"
    path.write_text('CONSOLE_PORT=9443\nCONSOLE_TZ="Asia/Taipei"\n')
    target: dict[str, str] = {}
    load = load_env_file(path, target)
    assert target == {"CONSOLE_PORT": "9443", "CONSOLE_TZ": "Asia/Taipei"}
    assert load.applied == ("CONSOLE_PORT", "CONSOLE_TZ")


def test_the_real_environment_wins(tmp_path):
    """The rule that makes installing the file safe for an existing deployment."""
    path = tmp_path / "console.env"
    path.write_text("CONSOLE_PORT=9443\n")
    target = {"CONSOLE_PORT": "8443"}
    load = load_env_file(path, target)
    assert target["CONSOLE_PORT"] == "8443"
    assert load.kept_from_environment == ("CONSOLE_PORT",)
    assert load.applied == ()


def test_loading_twice_changes_nothing(tmp_path):
    path = tmp_path / "console.env"
    path.write_text("CONSOLE_PORT=9443\n")
    target: dict[str, str] = {}
    load_env_file(path, target)
    second = load_env_file(path, target)
    assert second.applied == ()
    assert second.kept_from_environment == ("CONSOLE_PORT",)


def test_a_bare_name_declares_nothing(tmp_path):
    path = tmp_path / "console.env"
    path.write_text("CONSOLE_PORT\nCONSOLE_TZ=Asia/Taipei\n")
    target: dict[str, str] = {}
    load_env_file(path, target)
    assert "CONSOLE_PORT" not in target


def test_the_env_file_variable_is_read_from_the_environment_only(tmp_path):
    path = tmp_path / "named.env"
    path.write_text("CONSOLE_PORT=9443\n")
    os.environ["CONSOLE_ENV_FILE"] = str(path)
    assert env_file_path() == path


def test_the_load_record_carries_names_never_values(tmp_path):
    path = tmp_path / "console.env"
    path.write_text('CONSOLE_PASSWORD_HASH="$argon2id$secret"\n')
    load = load_env_file(path, {})
    assert "secret" not in load.describe()
    assert "secret" not in str(load.to_dict())
    assert load.applied == ("CONSOLE_PASSWORD_HASH",)


def test_the_example_lists_every_variable_the_code_reads():
    """Both directions. A variable added to the code without the example, or an
    example entry nothing reads, are both drift."""
    in_code = set(known_env_vars())
    in_example = set(declared_env_vars(EXAMPLE))
    assert in_code - in_example == set(), "read by the code, missing from console.env.example"
    assert in_example - in_code == set(), "in console.env.example, read by nothing"


@pytest.mark.parametrize(
    "name",
    [
        "CONSOLE_BIND",
        "CONSOLE_PORT",
        "CONSOLE_TLS_CERT",
        "CONSOLE_PASSWORD_HASH",
        "CONSOLE_SESSION_SECRET",
        "CONSOLE_ETHOS_URL",
        "CONSOLE_PLANS_DIR",
        "CONSOLE_DEPLOY_PROFILES",
        "CONSOLE_TZ",
    ],
)
def test_known_variables_cover_every_subsystem(name):
    assert name in known_env_vars()


def test_the_example_leaks_no_credential():
    text = EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        for name in ("CONSOLE_PASSWORD_HASH=", "CONSOLE_SESSION_SECRET="):
            if line.startswith(name):
                value = line.split("=", 1)[1].split("#")[0].strip()
                assert value == '""', f"{name} must ship empty, not {value!r}"
    assert "$argon2id$" not in text


def test_no_example_placeholder_is_a_comment():
    """``KEY=  # note`` parses the NOTE as the value. Blanks must be ``KEY=""``."""
    for number, line in enumerate(EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("CONSOLE_") or "=" not in line:
            continue
        value = line.split("=", 1)[1].split("#")[0].strip()
        assert value != "", f"line {number} leaves a bare value: {line!r}"


def test_the_example_is_loadable(tmp_path):
    target: dict[str, str] = {}
    load = load_env_file(EXAMPLE, target)
    assert load.exists
    assert target["CONSOLE_PORT"] == "8443"
    assert target["CONSOLE_PASSWORD_HASH"] == ""


def test_no_example_line_puts_a_comment_after_a_value():
    """systemd's ``EnvironmentFile=`` does not strip a trailing ``# comment``, and
    this file is loaded that way by the service unit. ``CONSOLE_LOG_LEVEL=info
    # the level`` becomes the literal value "info  # the level" and uvicorn
    refuses to start. Comments belong on their own line."""
    for number, line in enumerate(EXAMPLE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("CONSOLE_") or "=" not in line:
            continue
        value = line.split("=", 1)[1]
        assert "#" not in value, (
            f"line {number} puts a comment after a value, which systemd keeps "
            f"as part of it: {line!r}"
        )


def test_the_example_can_be_read_the_way_systemd_reads_it(tmp_path):
    """Parse it the way systemd does, split on the first ``=``, keep the rest
    verbatim, and check the values that must be machine-readable."""
    values: dict[str, str] = {}
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("CONSOLE_") or "=" not in line:
            continue
        name, _, raw = line.partition("=")
        values[name] = raw.strip().strip('"')

    assert values["CONSOLE_PORT"].isdigit()
    assert values["CONSOLE_LOG_LEVEL"] in (
        "critical", "error", "warning", "info", "debug", "trace"
    )
    assert values["CONSOLE_BIND"].replace(".", "").isdigit()
    assert values["CONSOLE_ETHOS_URL"].startswith("http")
    for name in ("CONSOLE_ETHOS_TIMEOUT_S", "CONSOLE_RUNS_CACHE_S",
                 "CONSOLE_STATUS_CACHE_S", "CONSOLE_ETHOS_SLOW_TIMEOUT_S"):
        assert float(values[name]) > 0
