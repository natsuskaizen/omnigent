"""Pick where a remote-server session's runner launches when none is online."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from omnigent.cli_diagnostics import printable
from omnigent.cli_invocation import cli_invocation

if TYPE_CHECKING:
    from omnigent_client import SessionsNamespace

logger = logging.getLogger(__name__)


class LaunchHostError(RuntimeError):
    """No runner is online and no connected host can launch one here; ``str()`` says why."""


class RemoteLaunchHostError(LaunchHostError):
    """
    Only hosts on other machines can launch the runner, and none can use this cwd.

    :param host_names: Display names of those hosts, e.g. ``["devbox.local"]``.
    """

    def __init__(self, host_names: list[str]) -> None:
        names = ", ".join(printable(name) for name in host_names)
        super().__init__(
            f"No runner is online, and the connected hosts ({names}) are other machines "
            "that can't use this directory as their workspace. Run this command on one of "
            f"them, or connect this machine with `{cli_invocation()} host --server <url>`."
        )
        self.host_names = host_names


class LocalHostCannotLaunchError(LaunchHostError):
    """
    This machine is a connected host but reports it can't run the agent's harness.

    :param harness: The agent's harness, e.g. ``"claude-sdk"``.
    :param reason: The host's readiness report, e.g. ``"binary-missing"``.
    """

    def __init__(self, harness: str | None, reason: str | None) -> None:
        from omnigent.onboarding.harness_install import harness_setup_hint

        super().__init__(
            f"No runner is online, and this machine's host can't run "
            f"{printable(harness or 'this agent')} ({printable(reason or 'unavailable')}): "
            f"{harness_setup_hint(harness)}, then restart `{cli_invocation()} host`."
        )
        self.harness = harness
        self.reason = reason


async def resolve_remote_launch_host(
    sessions: SessionsNamespace, *, harness: str | None
) -> str | None:
    """
    Choose a connected host for the server to launch a runner on.

    Only this machine qualifies: the session's workspace is this process's
    cwd, which another machine's host can't open.

    :param sessions: The client's sessions namespace.
    :param harness: Harness the agent runs on, e.g. ``"claude-sdk"``.
    :returns: This machine's host id, or ``None`` when no connected host
        could run the agent.
    :raises LocalHostCannotLaunchError: If this machine is a connected host
        that can't run *harness*.
    :raises RemoteLaunchHostError: If only other machines' hosts could.
    """
    from omnigent_client import OmnigentError

    from omnigent.harness_aliases import canonicalize_harness
    from omnigent.host import identity

    try:
        hosts = await sessions.list_launch_hosts(
            harness=harness,
            canonicalize=lambda name: canonicalize_harness(name) or name,
        )
    except OmnigentError:
        # Can't see the hosts: report the missing runner as before.
        logger.debug("could not list launch hosts", exc_info=True)
        return None
    local = identity.load_host_identity_if_present()
    mine = next((h for h in hosts if local is not None and h.host_id == local.host_id), None)
    if mine is not None:
        if mine.launchable:
            return mine.host_id
        raise LocalHostCannotLaunchError(harness, mine.unavailable_reason)
    others = [h.name for h in hosts if h.launchable]
    if others:
        raise RemoteLaunchHostError(others)
    return None
