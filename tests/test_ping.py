"""Reachability fallback tests without Home Assistant."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import patch

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "metz_remote"
pkg = types.ModuleType("metz_remote")
pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules.setdefault("metz_remote", pkg)
from metz_remote.ping import async_ping  # noqa: E402


def test_async_ping_uses_one_linux_ping_and_returns_status() -> None:
    commands = []

    class Process:
        async def wait(self):
            return 0

    async def create_process(*command, **kwargs):
        commands.append((command, kwargs))
        return Process()

    with (
        patch("metz_remote.ping.sys.platform", "linux"),
        patch("metz_remote.ping.asyncio.create_subprocess_exec", create_process),
    ):
        assert asyncio.run(async_ping("192.168.1.131")) is True

    assert commands[0][0] == ("ping", "-c", "1", "-W", "1", "192.168.1.131")


def test_async_ping_fails_closed_when_ping_is_unavailable() -> None:
    async def create_process(*_args, **_kwargs):
        raise OSError("ping unavailable")

    with patch("metz_remote.ping.asyncio.create_subprocess_exec", create_process):
        assert asyncio.run(async_ping("192.168.1.131")) is False