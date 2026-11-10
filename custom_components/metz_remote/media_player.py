"""Metz Remote media_player implementation."""

from __future__ import annotations

import math

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MetzCoordinator
from .api import MetzError
from .const import (
    DOMAIN,
    KEY_CODES,
    POWER_OFF_WATTS,
    POWER_ON_WATTS,
    SOURCE_BUTTONS,
    TV_SOURCE,
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
            MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    async def async_added_to_hass(self) -> None:
        """Refresh the entity when its configured power sensor changes."""
        await super().async_added_to_hass()
        entity_id = self.runtime.power_sensor_entity_id
        if entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [entity_id], self._async_power_sensor_changed
                )
            )

    @callback
    def _async_power_sensor_changed(self, _event) -> None:
        self.async_write_ha_state()

    def _power_watts(self) -> float | None:
        """Return the configured power sensor's Watt reading, if usable."""
        entity_id = self.runtime.power_sensor_entity_id
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            watts = float(state.state)
        except (TypeError, ValueError):
            return None
        return watts if math.isfinite(watts) else None

    def _power_mode(self) -> str | None:
        """Classify power-sensor readings or fall back to SOAP PowerState."""
        if self.runtime.power_sensor_entity_id:
            watts = self._power_watts()
            if watts is None:
                return None
            if watts > POWER_ON_WATTS:
                return "on"
            if watts > POWER_OFF_WATTS:
                return "active"
            return "off"
        if not self.coordinator.last_update_success:
            return "off" if self.runtime.mac else None
        if self.coordinator.data.power_state == 0:
            return "on"
        if self.coordinator.data.power_state == 1:
            return "off"
        return None

    @property
    def supported_features(self):
        """Offer only the safe power action for the current power mode."""
        features = self._attr_supported_features
        if self._power_mode() == "on":
            return features | MediaPlayerEntityFeature.TURN_OFF
        return features | MediaPlayerEntityFeature.TURN_ON

    @property
    def available(self) -> bool:
        """Allow Wake-on-LAN even when the SOAP service is asleep."""
        return (
            self.coordinator.last_update_success
            or bool(self.runtime.mac)
            or bool(self.runtime.power_sensor_entity_id)
        )

    @property
    def state(self) -> MediaPlayerState | None:
        """Report power-sensor state, or SOAP power state when no sensor is set."""
        power_mode = self._power_mode()
        if power_mode == "on":
            return MediaPlayerState.ON
        if power_mode == "active":
            return MediaPlayerState.IDLE
        if power_mode == "off":
            return MediaPlayerState.OFF
        return None

    @property
    def source(self) -> str | None:
        if not self.coordinator.last_update_success:
            return None
        return self.coordinator.data.source_name

    @property
    def source_list(self) -> list[str] | None:
        # Keep current source reporting independent of whether selecting is set up.
        if self.runtime.f1_source_selection_button_id is None:
            return [TV_SOURCE]
        return [TV_SOURCE, *SOURCE_BUTTONS]

    @property
    def extra_state_attributes(self) -> dict[str, float | int | list[str] | str | None] | None:
        if not self.coordinator.last_update_success:
            return None
        status = self.coordinator.data
        return {
            "power_state_raw": status.power_state,
            "operation_mode_raw": status.operation_mode,
            "active_device_raw": status.active_device,
            "detected_sources": list(status.devices.values()),
            "power_watts": self._power_watts(),
            "power_mode": self._power_mode(),
        }

    async def _key(self, code: int) -> None:
        try:
            await self.runtime.api.async_key(code)
        except MetzError as err:
            raise HomeAssistantError(f"Metz command failed: {err}") from err

    async def async_select_source(self, source: str) -> None:
        """Select TV directly or an F1-menu source through its numeric key."""
        f1_id: int | None = None
        if source != TV_SOURCE:
            f1_id = self.runtime.f1_source_selection_button_id
            if f1_id is None:
                raise HomeAssistantError(
                    "Configure an F1 source-selection button ID in integration options"
                )
            if source not in SOURCE_BUTTONS:
                raise HomeAssistantError(f"Unsupported Metz source: {source!r}")
        try:
            if source == TV_SOURCE:
                await self.runtime.api.async_select_tv_source()
            else:
                assert f1_id is not None
                await self.runtime.api.async_select_f1_source(source, f1_id)
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
        """Turn off from a confirmed high-power state, or toggle without a sensor."""
        if self.runtime.power_sensor_entity_id and self._power_mode() != "on":
            raise HomeAssistantError("TV power sensor does not report the TV as on")
        await self._key(KEY_CODES["power"])

    async def async_turn_on(self) -> None:
        """Toggle without a sensor; otherwise wake from a non-on power state."""
        if not self.runtime.power_sensor_entity_id:
            await self._key(KEY_CODES["power"])
            return
        if not self.runtime.mac:
            raise HomeAssistantError(
                "Wake-on-LAN needs a MAC address. Set it in integration options."
            )
        if self._power_mode() == "on":
            return
        try:
            await async_send_magic_packet(
                self.hass, self.runtime.mac, self.runtime.broadcast_address
            )
        except (OSError, ValueError) as err:
            raise HomeAssistantError(f"Could not send Metz Wake-on-LAN: {err}") from err
        # WOL only sends a packet, not proof the TV turned on. The coordinator
        # polls the TV every 15s and determines the actual state from SOAP.

    async def async_toggle(self) -> None:
        """Toggle the Metz power key without a sensor, else choose safely."""
        if not self.runtime.power_sensor_entity_id:
            await self._key(KEY_CODES["power"])
        elif self._power_mode() == "on":
            await self.async_turn_off()
        else:
            await self.async_turn_on()
