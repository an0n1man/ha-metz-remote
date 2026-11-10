"""Metz Remote media_player implementation."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MetzCoordinator
from .api import MetzError
from .const import (
    ANALOGUE_F1_SOURCE_ACTIVE_DEVICE_IDS,
    DOMAIN,
    KEY_CODES,
    SOURCE_BUTTONS,
)
from .wol import async_send_magic_packet


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add one media player for this TV."""
    async_add_entities([MetzMediaPlayer(entry)])


class MetzMediaPlayer(CoordinatorEntity[MetzCoordinator], MediaPlayerEntity):
    """Power, key controls and optional F1-driven source selection."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.TV

    def __init__(self, entry: ConfigEntry) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.description.udn}_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.description.udn)},
            manufacturer="Metz",
            model="Metz Remote",
            name="TV",
        )
        self._attr_supported_features = (
            MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
        )
        if runtime.f1_source_selection_button_id is not None:
            self._attr_supported_features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if runtime.mac:
            self._attr_supported_features |= MediaPlayerEntityFeature.TURN_ON

    @property
    def available(self) -> bool:
        """Allow Wake-on-LAN even when the SOAP service is asleep."""
        return self.coordinator.last_update_success or bool(self.runtime.mac)

    @property
    def state(self) -> MediaPlayerState | None:
        """PowerState=0 was observed while ON; other values are not fully mapped."""
        if not self.coordinator.last_update_success:
            return MediaPlayerState.OFF if self.runtime.mac else None
        if self.coordinator.data.power_state == 0:
            return MediaPlayerState.ON
        if self.coordinator.data.power_state == 1:
            return MediaPlayerState.OFF
        return None

    @property
    def source(self) -> str | None:
        if not self.coordinator.last_update_success:
            return None
        return self.coordinator.source_name

    @property
    def source_list(self) -> list[str] | None:
        # Keep current source reporting independent of whether selecting is set up.
        if self.runtime.f1_source_selection_button_id is None:
            return None
        return list(SOURCE_BUTTONS)

    @property
    def extra_state_attributes(self) -> dict[str, int | list[str]] | None:
        if not self.coordinator.last_update_success:
            return None
        status = self.coordinator.data
        return {
            "power_state_raw": status.power_state,
            "operation_mode_raw": status.operation_mode,
            "active_device_raw": status.active_device,
            "detected_sources": list(status.devices.values()),
        }

    async def _key(self, code: int) -> None:
        try:
            await self.runtime.api.async_key(code)
        except MetzError as err:
            raise HomeAssistantError(f"Metz command failed: {err}") from err

    async def async_select_source(self, source: str) -> None:
        """F1 → configured source-list key → numeric source shortcut."""
        f1_id = self.runtime.f1_source_selection_button_id
        if f1_id is None:
            raise HomeAssistantError(
                "Configure an F1 source-selection button ID in integration options"
            )
        if source not in SOURCE_BUTTONS:
            raise HomeAssistantError(f"Unsupported Metz source: {source!r}")
        try:
            await self.runtime.api.async_select_f1_source(source, f1_id)
            self.coordinator.set_source_override(
                source if source in ANALOGUE_F1_SOURCE_ACTIVE_DEVICE_IDS else None
            )
        except MetzError as err:
            raise HomeAssistantError(f"Metz source selection failed: {err}") from err
        finally:
            # Always read the actual source from the TV, never assume the key worked.
            await self.coordinator.async_request_refresh()

    async def async_volume_up(self) -> None:
        await self._key(KEY_CODES["volume_up"])

    async def async_volume_down(self) -> None:
        await self._key(KEY_CODES["volume_down"])

    async def async_media_next_track(self) -> None:
        """Map Next to next TV channel (not playback seek)."""
        await self._key(KEY_CODES["channel_up"])

    async def async_media_previous_track(self) -> None:
        await self._key(KEY_CODES["channel_down"])

    async def async_turn_off(self) -> None:
        """Send POWER TOGGLE (11), but only after confirming TV is ON.

        The Metz API exposes a toggle, not separate on/off commands. Refresh
        the SOAP state immediately before sending to avoid acting on a stale
        coordinator value (which can be up to 15 seconds old).
        """
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            # We cannot reliably distinguish standby from a network failure.
            # Sending the power toggle could turn on an already sleeping TV.
            raise HomeAssistantError(
                "Cannot verify TV is on; refusing to send Metz power toggle"
            )
        if self.coordinator.data.power_state == 1:
            return  # Already off, based on TV's reported PowerState.
        if self.coordinator.data.power_state != 0:
            raise HomeAssistantError(
                "Unknown Metz PowerState; refusing to send power toggle"
            )
        await self._key(KEY_CODES["power"])
        # Next scheduled SOAP poll (every 15s) updates the reported state.

    async def async_turn_on(self) -> None:
        """Wake with a magic packet; never use Metz's power-toggle for ON."""
        if not self.runtime.mac:
            raise HomeAssistantError(
                "Wake-on-LAN needs a MAC address. Set it in integration options."
            )
        if self.state == MediaPlayerState.ON:
            return
        try:
            await async_send_magic_packet(
                self.hass, self.runtime.mac, self.runtime.broadcast_address
            )
        except (OSError, ValueError) as err:
            raise HomeAssistantError(f"Could not send Metz Wake-on-LAN: {err}") from err
        # WOL only sends a packet, not proof the TV turned on. The coordinator
        # polls the TV every 15s and determines the actual state from SOAP.
