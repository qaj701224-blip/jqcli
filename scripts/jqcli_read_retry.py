"""Opt-in, process-local timeout retries for audited read-only CLI commands."""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Use the checkout containing this script, regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import click
import httpx

from jqcli.api.client import ApiClient
from jqcli.cli import main as cli
from jqcli.errors import NetworkError


READ_ONLY_COMMANDS = frozenset({
    ("strategy", "ls"),
    ("strategy", "show"),
    ("backtest", "ls"),
    ("backtest", "show"),
    ("backtest", "stats"),
    ("backtest", "result"),
    ("backtest", "logs"),
})
NETWORK_TIMEOUTS = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)
MAX_RETRIES = 3


def is_read_only_command() -> bool:
    context = click.get_current_context(silent=True)
    names = []
    while context is not None and context.parent is not None:
        names.append(context.command.name)
        context = context.parent
    return tuple(reversed(names)) in READ_ONLY_COMMANDS


@contextmanager
def read_only_retries():
    """Share three extra attempts across one invocation; never replay the CLI."""
    original_send = ApiClient._send
    retries_used = 0

    def send(client, method, path, **kwargs):
        nonlocal retries_used
        eligible = method.upper() in {"GET", "HEAD"} and is_read_only_command()
        while True:
            try:
                return original_send(client, method, path, **kwargs)
            except NetworkError as error:
                if (not eligible or retries_used >= MAX_RETRIES
                        or not isinstance(error.__cause__, NETWORK_TIMEOUTS)):
                    raise
                retries_used += 1
                # Never include URLs, request arguments, credentials or responses.
                click.echo(
                    f"[read-retry] 网络超时，{retries_used} 秒后重试 "
                    f"{retries_used}/{MAX_RETRIES}（仅当前只读请求）",
                    err=True,
                )
                time.sleep(retries_used)

    ApiClient._send = send
    try:
        yield
    finally:
        ApiClient._send = original_send


def main():
    with read_only_retries():
        cli(prog_name="jqcli-read-retry")


if __name__ == "__main__":
    main()
