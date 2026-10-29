from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import click
import httpx
import pytest
from click.testing import CliRunner

from jqcli.api.client import ApiClient
from jqcli.cli import main as cli
from jqcli.errors import ApiError, NetworkError


@pytest.fixture
def wrapper(monkeypatch):
    path = Path(__file__).parents[1] / "scripts" / "jqcli_read_retry.py"
    assert path.exists(), "The opt-in read-only retry wrapper is missing"
    spec = importlib.util.spec_from_file_location("read_retry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


def context(group, command):
    root = click.Context(cli)
    parent = click.Context(cli.commands[group], parent=root)
    return click.Context(cli.commands[group].commands[command], parent=parent)


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout])
def test_only_three_extra_attempts(wrapper, error, capsys):
    calls = []

    def fail(request):
        calls.append(request)
        raise error("timeout", request=request)

    original = ApiClient._send
    with wrapper.read_only_retries(), context("strategy", "ls"):
        with ApiClient("https://example.test", transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(NetworkError):
                client.get("/read")
    assert len(calls) == 4
    assert ApiClient._send is original
    assert capsys.readouterr().err.count("[read-retry]") == 3


@pytest.mark.parametrize("group,command,method", [
    ("backtest", "run", "GET"), ("backtest", "run", "POST"),
    ("strategy", "edit", "GET"), ("strategy", "edit", "POST"),
    ("strategy", "new", "POST"), ("strategy", "rm", "POST"),
    ("backtest", "rm", "POST"), ("community", "clone-strategy", "GET"),
    ("auth", "login", "GET"), ("strategy", "ls", "POST"),
])
def test_writes_and_write_command_preflight_never_retry(wrapper, group, command, method):
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ConnectTimeout("timeout", request=request)

    with wrapper.read_only_retries(), context(group, command):
        with ApiClient("https://example.test", transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(NetworkError):
                client.request(method, "/test")
    assert len(calls) == 1


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadError, httpx.PoolTimeout])
def test_non_network_timeout_errors_not_retried(wrapper, error):
    calls = []

    def fail(request):
        calls.append(request)
        raise error("failure", request=request)

    with wrapper.read_only_retries(), context("strategy", "ls"):
        with ApiClient("https://example.test", transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(NetworkError):
                client.get("/read")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_not_retried(wrapper, status):
    from jqcli.errors import JqcliError
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(status)

    with wrapper.read_only_retries(), context("backtest", "show"):
        with ApiClient("https://example.test", transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(JqcliError):
                client.get("/read")
    assert len(calls) == 1


def test_budget_shared_across_requests_and_not_reset_by_success(wrapper):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if len(calls) in (3, 5):
            return httpx.Response(200, json={"ok": True})
        raise httpx.ConnectTimeout("timeout", request=request)

    with wrapper.read_only_retries(), context("strategy", "ls"):
        with ApiClient("https://example.test", transport=httpx.MockTransport(handle)) as client:
            assert client.get("/one") == {"ok": True}
            assert client.get("/two") == {"ok": True}
            with pytest.raises(NetworkError):
                client.get("/three")
    assert calls == ["/one"] * 3 + ["/two"] * 2 + ["/three"]


def test_cli_json_and_arguments_preserved(wrapper, monkeypatch, tmp_path):
    import jqcli.commands.strategy as strategy
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(strategy, "make_client", lambda app: ApiClient(
        app.api_base, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(strategy, "list_strategies", lambda client, **kw: client.get("/read"))
    config = tmp_path / "config.json"
    config.write_text("{}")
    with wrapper.read_only_retries():
        result = CliRunner().invoke(cli, ["--config", str(config), "--format", "json",
                                         "strategy", "ls", "--limit", "3"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"items": []}
    assert len(calls) == 2
    assert "[read-retry]" in result.stderr


def test_no_click_context_never_retries(wrapper):
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ConnectTimeout("timeout", request=request)

    with wrapper.read_only_retries():
        with ApiClient("https://example.test", transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(NetworkError):
                client.get("/read")
    assert len(calls) == 1
