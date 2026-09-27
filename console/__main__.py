"""``python -m console``, serve, set the password, or check the configuration."""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from console.auth import hash_password
from console.env_file import load_env_file
from console.settings import (
    ENV_PASSWORD_HASH,
    ENV_SESSION_SECRET,
    load_settings,
)


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings()
    problems = settings.problems()
    if problems and not args.insecure:
        print("The console will not serve until these are fixed:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nSee docs/running-guide.md §2. To serve over plain HTTP anyway "
            "(a tunnel only, never the LAN), pass --insecure.",
            file=sys.stderr,
        )
        return 2

    tls = {}
    if settings.tls_ready and not args.insecure:
        tls = {
            "ssl_certfile": str(settings.tls_cert),
            "ssl_keyfile": str(settings.tls_key),
        }
    scheme = "https" if tls else "http"
    print(f"Testbed Console on {scheme}://{settings.bind}:{settings.port}")
    print(f"ETHOS at {settings.ethos_url}")
    if not tls:
        print("WARNING: serving without TLS. Reach it over an ssh -L tunnel only.")

    uvicorn.run(
        "console.app:create_app",
        factory=True,
        host=settings.bind,
        port=settings.port,
        log_level=settings.log_level,
        **tls,
    )
    return 0


def _set_password(args: argparse.Namespace) -> int:
    """Prompt twice, print the hash. The password is never stored or echoed."""
    first = getpass.getpass("New console password: ")
    if len(first) < 8:
        print("Use at least 8 characters.", file=sys.stderr)
        return 2
    second = getpass.getpass("Again: ")
    if first != second:
        print("Those did not match.", file=sys.stderr)
        return 2

    print("\nPut this line in console.env:\n")
    print(f"{ENV_PASSWORD_HASH}={hash_password(first)}")
    settings = load_settings()
    if not settings.session_secret:
        print(
            f"\nAnd a session secret, which is not set yet:\n\n"
            f"{ENV_SESSION_SECRET}={secrets.token_hex(32)}"
        )
    print("\nRestart the service to pick them up.")
    return 0


def _check(args: argparse.Namespace) -> int:
    load = load_env_file()
    settings = load_settings()
    print(load.describe())
    print(f"bind            {settings.bind}:{settings.port}")
    print(f"ethos           {settings.ethos_url}")
    print(f"tls             {'ready' if settings.tls_ready else 'NOT ready'}")
    print(f"login           {'configured' if settings.login_ready else 'NOT configured'}")
    print(f"plans           {settings.plans_dir}")
    print(f"deploy profiles {settings.deploy_profiles or 'not configured (B4 stand-in off)'}")
    print(f"graph dir       {settings.graph_dir or 'not configured (gallery empty)'}")
    print(f"time zone       {settings.tz}")
    problems = settings.problems()
    if problems:
        print("\nproblems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nno problems found")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m console")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the console")
    serve.add_argument(
        "--insecure",
        action="store_true",
        help="serve plain HTTP (for an ssh -L tunnel; never expose it on the LAN)",
    )
    serve.set_defaults(run=_serve)

    password = sub.add_parser("set-password", help="print a new password hash")
    password.set_defaults(run=_set_password)

    check = sub.add_parser("check", help="show the resolved configuration")
    check.set_defaults(run=_check)

    args = parser.parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":
    raise SystemExit(main())
