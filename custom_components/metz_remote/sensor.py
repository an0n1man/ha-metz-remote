"""Read-only Metz Remote active input sensor."""

from __future__ import annotations

import math

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MetzCoordinator
from .const import DOMAIN, POWER_OFF_WATTS, POWER_ON_WATTS


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the source sensor; remove v0.3.0's unsupported volume entity."""
    runtime = entry.runtime_data
    registry = er.async_get(hass)
    old_volume_entity = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{runtime.description.udn}_volume"
    )
    if old_volume_entity is not None:
        registry.async_remove(old_volume_entity)
    async_add_entities([MetzSourceSensor(entry), MetzInternalTVStateSensor(entry)])


class MetzBaseSensor(CoordinatorEntity[MetzCoordinator], SensorEntity):
    """Common device identity for status sensors."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinator)
        self.runtime = runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.description.udn)},
            manufacturer="Metz",
            model="Metz Remote",
            name="TV",
        )


class MetzSourceSensor(MetzBaseSensor):
    """Active input from the canonical RCRService ActiveDevice table."""

    _attr_translation_key = "active_source"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{self.runtime.description.udn}_active_source"

    @property
    def available(self) -> bool:
        """Keep the sensor available to expose unknown during TV startup."""
        return (
            self.coordinator.last_update_success
            or self.coordinator.active_source_unknown
        )

    @property
    def native_value(self) -> str | None:
        """Report current source when TV is on and the service is reachable."""
        if self.coordinator.active_source_unknown:
            return None
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        status = self.coordinator.data
        if status.power_state != 0:
            return None
        return self.coordinator.source_name

    @property
    def extra_state_attributes(self) -> dict[str, int | str | None] | None:
        """Expose both friendly name and numeric source for automation."""
        if self.coordinator.active_source_unknown:
            return {
                "active_device_id": None,
                "active_device_hex": None,
                "source": None,
            }
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        status = self.coordinator.data
        return {
            "active_device_id": status.active_device,
            "active_device_hex": f"0x{status.active_device:02X}",
            "source": self.coordinator.source_name,
        }


class MetzInternalTVStateSensor(MetzBaseSensor):
    """Internal TV power state with the idle power band preserved."""

    _attr_translation_key = "internal_tv_state"
    _attr_icon = "mdi:television"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{self.runtime.description.udn}_internal_tv_state"

    async def async_added_to_hass(self) -> None:
        """Refresh state immediately when the configured power sensor changes."""
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

    @property
    def available(self) -> bool:
        """A configured power sensor remains useful while SOAP is unavailable."""
        return self.coordinator.last_update_success or bool(
            self.runtime.power_sensor_entity_id
        )

    def _power_watts(self) -> float | None:
        """Read a finite Watt value from the configured sensor entity."""
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

    @property
    def native_value(self) -> str | None:
        """Return on, idle, or off from power watts or SOAP fallback."""
        if self.runtime.power_sensor_entity_id:
            watts = self._power_watts()
            if watts is None:
                return None
            if watts > POWER_ON_WATTS:
                return "on"
            if watts > POWER_OFF_WATTS:
                return "idle"
            return "off"
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        if self.coordinator.data.power_state == 0:
            return "on"
        if self.coordinator.data.power_state == 1:
            return "off"
        return None

