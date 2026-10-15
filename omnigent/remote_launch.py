"""Pick where a remote-server session's runner launches when none is online."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnigent.cli_invocation import cli_invocation

if TYPE_CHECKING:
    from omnigent_client import SessionsNamespace


class RemoteLaunchHostError(RuntimeError):
    """
    Only hosts on other machines are connected, so none can use this cwd.

    :param host_names: Display names of those hosts, e.g. ``["devbox.local"]``.
    """

    def __init__(self, host_names: list[str]) -> None:
        super().__init__(f"Connected hosts are on other machines: {', '.join(host_names)}")
        self.host_names = host_names


async def resolve_remote_launch_host(
    sessions: SessionsNamespace, *, harness: str | None
) -> str | None:
    """
    Choose a connected host for the server to launch a runner on.

    Only this machine qualifies: the session's workspace is this process's
    cwd, which another machine's host can't open.

    :param sessions: The client's sessions namespace.
    :param harness: Harness the agent runs on, e.g. ``"claude-sdk"``.
    :returns: This machine's host id, or ``None`` when no host is connected.
    :raises RemoteLaunchHostError: If hosts are connected but none is this
        machine.
    """
    from omnigent.harness_aliases import canonicalize_harness
    from omnigent.host import identity

    hosts = await sessions.list_launch_hosts(
        harness=harness,
        canonicalize=lambda name: canonicalize_harness(name) or name,
    )
    if not hosts:
        return None
    local = identity.load_host_identity_if_present()
    if local is not None and any(host.host_id == local.host_id for host in hosts):
        return local.host_id
    raise RemoteLaunchHostError([host.name for host in hosts])


def remote_launch_host_message(exc: RemoteLaunchHostError) -> str:
    """
    Explain why a host on another machine wasn't used, and what to do.

    :param exc: The error naming the connected hosts.
    :returns: A one-line, actionable error message.
    """
    return (
        f"No runner is online, and the connected hosts ({', '.join(exc.host_names)}) are "
        "other machines that can't use this directory as their workspace. Run this "
        f"command on one of them, or connect this machine with `{cli_invocation()} host "
        "--server <url>`."
    )
