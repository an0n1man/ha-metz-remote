"""Expose Metz key codes via Home Assistant remote.send_command."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MetzCoordinator
from .api import MetzError
from .const import DOMAIN, KEY_CODES


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the remote-control entity."""
    async_add_entities([MetzRemoteEntity(entry)])


class MetzRemoteEntity(CoordinatorEntity[MetzCoordinator], RemoteEntity):
    """Send named commands or raw key codes (no unknown key mappings)."""

    _attr_has_entity_name = True
    _attr_name = "Remote"

    def __init__(self, entry: ConfigEntry) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.description.udn}_remote"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.description.udn)},
            manufacturer="Metz",
            model="Metz Remote",
            name=runtime.description.name,
        )

    @property
    def is_on(self) -> bool:
        """Remote commands can be sent while the SOAP service is reachable."""
        return self.coordinator.last_update_success

    async def async_send_command(
        self, command: Iterable[str], **kwargs: Any
    ) -> None:
        """Send a list of commands or unsigned decimal remote codes."""
        repeats = int(kwargs.get("num_repeats", 1))
        delay = float(kwargs.get("delay_secs", 0.4))
        hold = float(kwargs.get("hold_secs", 0))
        if not 1 <= repeats <= 20 or not 0 <= delay <= 10:
            raise HomeAssistantError("Repeats must be 1..20 and delay 0..10s")
        if hold:
            raise HomeAssistantError("ButtonHold duration has not been established")
        if kwargs.get("device") not in (None, "", "tv"):
            raise HomeAssistantError("Only the primary TV device is supported")
        commands = [command] if isinstance(command, str) else list(command)
        codes: list[int] = []
        for name in commands:
            name = str(name).strip().lower()
            if name in KEY_CODES:
                codes.append(KEY_CODES[name])
            elif name.isascii() and name.isdecimal() and int(name) <= 0xFFFFFFFF:
                codes.append(int(name))
            else:
                raise HomeAssistantError(f"Unknown Metz key code/name: {name}")
        try:
            for i in range(repeats):
                for j, code in enumerate(codes):
                    await self.runtime.api.async_key(code)
                    if delay and (i < repeats - 1 or j < len(codes) - 1):
                        await asyncio.sleep(delay)
        except MetzError as err:
            raise HomeAssistantError(f"Metz command failed: {err}") from err
