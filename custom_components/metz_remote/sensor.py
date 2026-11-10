"""Read-only Metz Remote active input sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MetzCoordinator
from .const import DOMAIN


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
    async_add_entities([MetzSourceSensor(entry)])


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
    def native_value(self) -> str | None:
        """Report current source when TV is on and the service is reachable."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        status = self.coordinator.data
        if status.power_state != 0:
            return None
        return status.source_name

    @property
    def extra_state_attributes(self) -> dict[str, int | str | None] | None:
        """Expose both friendly name and numeric source for automation."""
        if not self.coordinator.last_update_success or self.coordinator.data is None:
            return None
        status = self.coordinator.data
        return {
            "active_device_id": status.active_device,
            "active_device_hex": f"0x{status.active_device:02X}",
            "source": status.source_name,
        }

