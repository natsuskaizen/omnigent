"""Choosing the host a remote-server session's runner launches on."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from omnigent_client import LaunchHost

import omnigent.host.identity as identity
from omnigent.remote_launch import (
    RemoteLaunchHostError,
    remote_launch_host_message,
    resolve_remote_launch_host,
)


def _sessions(hosts: list[LaunchHost], seen: dict[str, object]) -> SimpleNamespace:
    async def _list_launch_hosts(**kwargs: object) -> list[LaunchHost]:
        seen.update(kwargs)
        return hosts

    return SimpleNamespace(list_launch_hosts=_list_launch_hosts)


def _local_host(monkeypatch: pytest.MonkeyPatch, host_id: str | None) -> None:
    local = SimpleNamespace(host_id=host_id, name="me.local") if host_id else None
    monkeypatch.setattr(identity, "load_host_identity_if_present", lambda *_a, **_kw: local)


def _resolve(hosts: list[LaunchHost], seen: dict[str, object] | None = None) -> str | None:
    return asyncio.run(
        resolve_remote_launch_host(
            _sessions(hosts, seen if seen is not None else {}),  # type: ignore[arg-type]
            harness="claude-sdk",
        )
    )


def test_uses_this_machine_when_it_is_a_connected_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_host(monkeypatch, "host_local")
    seen: dict[str, object] = {}

    hosts = [LaunchHost("host_other", "devbox.local"), LaunchHost("host_local", "me.local")]

    assert _resolve(hosts, seen) == "host_local"
    assert seen["harness"] == "claude-sdk"


def test_no_connected_host_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _local_host(monkeypatch, "host_local")

    assert _resolve([]) is None


@pytest.mark.parametrize("local_id", [None, "host_local"])
def test_only_other_machines_connected_names_them(
    monkeypatch: pytest.MonkeyPatch, local_id: str | None
) -> None:
    """Another machine can't use this directory as its workspace, so don't launch there."""
    _local_host(monkeypatch, local_id)

    with pytest.raises(RemoteLaunchHostError) as excinfo:
        _resolve([LaunchHost("host_a", "devbox.local"), LaunchHost("host_b", "ci.local")])

    assert excinfo.value.host_names == ["devbox.local", "ci.local"]
    message = remote_launch_host_message(excinfo.value)
    assert "devbox.local" in message and "ci.local" in message
    assert "host --server" in message
