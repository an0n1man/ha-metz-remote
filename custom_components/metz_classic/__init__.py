"""Metz Remote control over the local network."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    MetzClient, MetzConnectionError, MetzDescription, MetzError, MetzStatus,
)
from .const import CONF_MAC, CONF_BROADCAST, DEFAULT_BROADCAST, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS = (Platform.MEDIA_PLAYER, Platform.REMOTE)


@dataclass
class MetzRuntime:
    """Shared state for entities belonging to one television."""

    api: MetzClient
    description: MetzDescription
    coordinator: MetzCoordinator
    mac: str | None
    broadcast_address: str


class MetzCoordinator(DataUpdateCoordinator[MetzStatus]):
    """Poll state; never perform network IO inside entity properties."""

    def __init__(self, hass: HomeAssistant, api: MetzClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Metz Remote",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api

    async def _async_update_data(self) -> MetzStatus:
        try:
            return await self.api.async_status()
        except MetzError as err:
            raise UpdateFailed(f"Cannot reach Metz TV: {err}") from err


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Metz control and its entities."""
    api = MetzClient(async_get_clientsession(hass), entry.data[CONF_HOST])
    try:
        description = await api.async_description()
    except MetzConnectionError as err:
        # A TV in standby may stop listening on TCP 49200. An existing config
        # entry already has the UDN from the initial successful setup, so it
        # is safe to register its entities without contacting the sleeping TV.
        # Never invent identity for an entry that was not previously verified.
        if not entry.unique_id:
            raise ConfigEntryNotReady(f"Metz TV unreachable: {err}") from err
        _LOGGER.info(
            "Metz TV at %s is offline during setup; loading saved device %s",
            entry.data[CONF_HOST], entry.unique_id,
        )
        description = MetzDescription(
            udn=entry.unique_id,
            name=entry.title or "Metz TV",
            control_url=api.control_url,
        )
    except MetzError as err:
        # Wrong device, invalid XML, or an incompatible service should still
        # be diagnosed rather than silently treated as normal TV standby.
        raise ConfigEntryNotReady(f"Metz TV description invalid: {err}") from err

    coordinator = MetzCoordinator(hass, api)
    # A startup poll may fail while the TV is asleep. async_refresh records
    # the failed update but (unlike first_refresh) does not block entity setup.
    # Subsequent polls restore availability automatically when the TV wakes.
    await coordinator.async_refresh()
    entry.runtime_data = MetzRuntime(
        api=api,
        description=description,
        coordinator=coordinator,
        mac=(entry.options.get(CONF_MAC, entry.data.get(CONF_MAC, "")) or None),
        broadcast_address=entry.options.get(
            CONF_BROADCAST, entry.data.get(CONF_BROADCAST, DEFAULT_BROADCAST)
        ),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integrations' entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
