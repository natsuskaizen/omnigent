"""REPL fresh sessions on a remote server with no online runner.

A ``run --server <url>`` REPL has no local runner. When the server has no
online runner either but this machine is a connected host, the session is
created on it so the server launches a runner there, and the REPL must not
rebind it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from omnigent_client import LaunchHost
from omnigent_client._sessions import Session

import omnigent.host.identity as identity
from omnigent.repl._repl import _SessionsChatReplAdapter


def _local_host(monkeypatch: pytest.MonkeyPatch, host_id: str | None) -> None:
    local = SimpleNamespace(host_id=host_id, name="me.local") if host_id else None
    monkeypatch.setattr(identity, "load_host_identity_if_present", lambda *_a, **_kw: local)


def _sessions_stub(
    *, hosts: list[LaunchHost], created: dict[str, Any], bound: list[str]
) -> SimpleNamespace:
    """Sessions namespace with no online runner and the given connected hosts."""

    async def _resolve_agent(_name: str) -> SimpleNamespace:
        return SimpleNamespace(id="id_scribe", harness="claude-sdk")

    async def _no_runner(**_kwargs: object) -> None:
        return None

    async def _list_launch_hosts(**kwargs: object) -> list[LaunchHost]:
        created["lookup"] = kwargs
        return hosts

    async def _create(agent_id: str, **kwargs: object) -> Session:
        created.update(kwargs, agent_id=agent_id)
        runner = "runner_launched" if kwargs.get("host_id") else None
        return Session.from_dict(
            {
                "id": "conv_new",
                "agent_id": agent_id,
                "agent_name": "scribe",
                "status": "idle",
                "created_at": 1700000000,
                "items": [],
                "runner_id": runner,
                "host_id": kwargs.get("host_id"),
            }
        )

    async def _bind_runner(session_id: str, *, runner_id: str) -> Session:
        bound.append(runner_id)
        raise AssertionError("a host-launched session is bound by the server")

    return SimpleNamespace(
        resolve_agent=_resolve_agent,
        resolve_online_runner=_no_runner,
        list_launch_hosts=_list_launch_hosts,
        create_from_agent_id=_create,
        bind_runner=_bind_runner,
    )


def _adapter(sessions: SimpleNamespace) -> _SessionsChatReplAdapter:
    return _SessionsChatReplAdapter(SimpleNamespace(sessions=sessions), "scribe")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_remote_repl_creates_session_on_this_host_and_skips_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _local_host(monkeypatch, "host_local")
    created: dict[str, Any] = {}
    bound: list[str] = []
    adapter = _adapter(
        _sessions_stub(hosts=[LaunchHost("host_local", "me.local")], created=created, bound=bound)
    )

    await adapter._create_session_from_registered_agent(pending_debug=False)
    await adapter._bind_runner_if_needed()

    assert created["host_id"] == "host_local"
    assert created["lookup"]["harness"] == "claude-sdk"
    # The runner comes from the create snapshot; no client-side PATCH.
    assert adapter._runner_id == "runner_launched"
    assert bound == []


@pytest.mark.asyncio
async def test_remote_repl_with_only_other_hosts_names_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _local_host(monkeypatch, None)
    created: dict[str, Any] = {}
    adapter = _adapter(
        _sessions_stub(hosts=[LaunchHost("host_dev", "devbox.local")], created=created, bound=[])
    )

    with pytest.raises(RuntimeError, match=r"devbox\.local"):
        await adapter._create_session_from_registered_agent(pending_debug=False)

    assert "agent_id" not in created


@pytest.mark.asyncio
async def test_remote_repl_without_runner_or_host_still_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _local_host(monkeypatch, None)
    created: dict[str, Any] = {}
    adapter = _adapter(_sessions_stub(hosts=[], created=created, bound=[]))

    await adapter._create_session_from_registered_agent(pending_debug=False)

    assert created.get("host_id") is None
    with pytest.raises(RuntimeError, match="no online runner"):
        await adapter._bind_runner_if_needed()


@pytest.mark.asyncio
async def test_remote_repl_with_this_host_unable_to_run_the_harness_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _local_host(monkeypatch, "host_local")
    created: dict[str, Any] = {}
    host = LaunchHost(
        "host_local", "me.local", launchable=False, unavailable_reason="binary-missing"
    )
    adapter = _adapter(_sessions_stub(hosts=[host], created=created, bound=[]))

    with pytest.raises(RuntimeError, match="binary-missing"):
        await adapter._create_session_from_registered_agent(pending_debug=False)

    assert "agent_id" not in created


@pytest.mark.asyncio
async def test_remote_repl_unknown_agent_error_is_escaped() -> None:
    """A missing agent name keeps its LookupError, with control characters escaped."""

    async def _resolve_agent(name: str) -> object:
        raise LookupError(f"No agent named {name!r} is registered on this server.")

    adapter = _SessionsChatReplAdapter(
        SimpleNamespace(sessions=SimpleNamespace(resolve_agent=_resolve_agent)),  # type: ignore[arg-type]
        "evil\x1b[2J",
    )

    # The REPL renders exceptions at its UI boundary; keep the LookupError contract.
    with pytest.raises(LookupError) as excinfo:
        await adapter._create_session_from_registered_agent(pending_debug=False)

    assert "\x1b" not in str(excinfo.value) and "\\x1b" in str(excinfo.value)
