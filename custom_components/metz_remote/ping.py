"""Asynchronous ICMP reachability checks for Metz Remote."""

from __future__ import annotations

import asyncio
import sys


async def async_ping(host: str, timeout: float = 1.0) -> bool:
    """Return whether one operating-system ping receives a response."""
    if sys.platform == "win32":
        command = ("ping", "-n", "1", "-w", str(round(timeout * 1000)), host)
    else:
        command = ("ping", "-c", "1", "-W", str(round(timeout)), host)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return False
    try:
        return await asyncio.wait_for(process.wait(), timeout=timeout + 1) == 0
    except TimeoutError:
        process.kill()
        await process.wait()
        return False