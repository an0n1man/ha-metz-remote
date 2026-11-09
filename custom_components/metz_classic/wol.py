"""Wake-on-LAN for a Metz Remote; no HA WOL integration required."""

from __future__ import annotations

import socket

from homeassistant.core import HomeAssistant

from .const import DEFAULT_BROADCAST


def _send_magic_packet(mac: str, broadcast_address: str = DEFAULT_BROADCAST) -> None:
    """Send standard magic packet to a configurable broadcast target.

    In a Docker installation the limited broadcast address may stay within
    the container network. A directed broadcast (e.g. 192.168.1.255 for a
    /24 LAN) can be configured instead, subject to router/firewall settings.
    """
    mac_bytes = bytes.fromhex(mac)
    if len(mac_bytes) != 6:
        raise ValueError("Wake-on-LAN MAC must contain exactly 6 bytes")
    payload = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(3)
        sock.sendto(payload, (broadcast_address, 9))


async def async_send_magic_packet(
    hass: HomeAssistant, mac: str, broadcast_address: str = DEFAULT_BROADCAST
) -> None:
    """Send WOL without blocking the Home Assistant event loop."""
    await hass.async_add_executor_job(_send_magic_packet, mac, broadcast_address)
