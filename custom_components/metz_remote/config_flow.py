"""User and SSDP discovery configuration for Metz Remotes."""

from __future__ import annotations

from ipaddress import ip_address
import re
from urllib.parse import urlparse
from typing import Any

try:
    import probatio as vol  # Home Assistant's newer configuration schema library
except ImportError:
    import voluptuous as vol  # compatibility with older HA releases

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

from .api import MetzClient, MetzDescription, MetzError
from .const import (
    CONF_BROADCAST, CONF_MAC, CONF_F1_SOURCE_SELECTION_BUTTON_ID,
    CONF_POWER_SENSOR_ENTITY_ID,
    DEFAULT_BROADCAST, DOMAIN,
)


def _clean_mac(value: str) -> str:
    """Validate and normalize an optional wake-on-LAN MAC address."""
    mac = re.sub(r"[:-]", "", value).strip().upper()
    if mac and not re.fullmatch(r"[0-9A-F]{12}", mac):
        raise ValueError("Invalid MAC address")
    return mac


def _clean_broadcast(value: str) -> str:
    """Validate the configured IPv4 WOL destination."""
    try:
        address = ip_address(value.strip())
    except ValueError as err:
        raise ValueError("Invalid broadcast address") from err
    if address.version != 4 or address.is_multicast or address.is_loopback:
        raise ValueError("Invalid IPv4 broadcast address")
    return str(address)


def _clean_host(value: str) -> str:
    """Accept IPv4 addresses and simple DNS names, not URL paths."""
    host = value.strip()
    if not host or len(host) > 253 or any(c in host for c in ":/\\ @"):
        raise ValueError("Invalid host")
    try:
        ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", host):
            raise ValueError("Invalid host") from None
    return host


def _clean_f1_source_button_id(value: Any) -> int | None:
    """Validate optional raw Metz SOAP KeyCode for the F1 submenu shortcut.

    The user enters the visible digit (0..9), not the SOAP KeyCode.
    Persist the corresponding SOAP ID (digit + 1) for compatibility with
    existing config entries, which stored the raw KeyCode (1..10).
    Empty input disables source selection completely.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Invalid F1 button ID")
    try:
        keycode = int(value)
    except (TypeError, ValueError) as err:
        raise ValueError("Invalid F1 button ID") from err
    if str(value).strip() != str(keycode) or not 0 <= keycode <= 9:
        raise ValueError("F1 button must be a digit (0-9)")
    return keycode + 1


def _clean_power_sensor_entity_id(value: Any) -> str | None:
    """Validate an optional Watt power-sensor entity ID."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid power sensor entity ID")
    entity_id = value.strip().lower()
    if not re.fullmatch(r"sensor\.[a-z0-9_]+", entity_id):
        raise ValueError("Invalid power sensor entity ID")
    return entity_id


class MetzRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up by manual IP or SSDP announcement."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MetzRemoteOptionsFlow:
        """Allow configuring WOL for an already installed TV."""
        return MetzRemoteOptionsFlow()

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_description: MetzDescription | None = None

    async def _probe(self, host: str) -> MetzDescription:
        api = MetzClient(async_get_clientsession(self.hass), host)
        description = await api.async_description()
        await api.async_action("GetPowerState")
        return description

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Set up host, Wake-on-LAN and optional F1 source-list shortcut."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host = _clean_host(user_input[CONF_HOST])
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            try:
                mac = _clean_mac(user_input.get(CONF_MAC, ""))
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            try:
                broadcast = _clean_broadcast(
                    user_input.get(CONF_BROADCAST, DEFAULT_BROADCAST)
                )
            except ValueError:
                errors[CONF_BROADCAST] = "invalid_broadcast"
            try:
                f1_id = _clean_f1_source_button_id(
                    user_input.get(CONF_F1_SOURCE_SELECTION_BUTTON_ID)
                )
            except ValueError:
                errors[CONF_F1_SOURCE_SELECTION_BUTTON_ID] = "invalid_f1_button_id"
            try:
                power_sensor = _clean_power_sensor_entity_id(
                    user_input.get(CONF_POWER_SENSOR_ENTITY_ID)
                )
            except ValueError:
                errors[CONF_POWER_SENSOR_ENTITY_ID] = "invalid_power_sensor"
            if not errors:
                try:
                    description = await self._probe(host)
                except MetzError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(description.udn)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    data = {CONF_HOST: host, CONF_MAC: mac,
                            CONF_BROADCAST: broadcast}
                    if f1_id is not None:
                        data[CONF_F1_SOURCE_SELECTION_BUTTON_ID] = f1_id
                    if power_sensor is not None:
                        data[CONF_POWER_SENSOR_ENTITY_ID] = power_sensor
                    return self.async_create_entry(title="TV", data=data)
        schema_fields = {
            vol.Required(CONF_HOST, default=self._discovered_host or ""): str,
            vol.Optional(CONF_MAC, default=""): str,
            vol.Optional(CONF_BROADCAST, default=DEFAULT_BROADCAST): str,
            vol.Optional(CONF_F1_SOURCE_SELECTION_BUTTON_ID): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=9)
            ),
            vol.Optional(CONF_POWER_SENSOR_ENTITY_ID): str,
        }
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(schema_fields), errors=errors
        )

    async def async_step_ssdp(self, discovery_info: SsdpServiceInfo):
        """Handle discovery from Home Assistant's SSDP integration."""
        host = urlparse(discovery_info.ssdp_location).hostname
        if not host:
            return self.async_abort(reason="cannot_connect")
        try:
            description = await self._probe(host)
        except MetzError:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(description.udn)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        self._discovered_host = host
        self._discovered_description = description
        self.context["title_placeholders"] = {"name": description.name}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None):
        """Ask for optional F1 shortcut and WOL settings for discovered TVs."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                f1_id = _clean_f1_source_button_id(
                    user_input.get(CONF_F1_SOURCE_SELECTION_BUTTON_ID)
                )
            except ValueError:
                errors[CONF_F1_SOURCE_SELECTION_BUTTON_ID] = "invalid_f1_button_id"
            try:
                mac = _clean_mac(user_input.get(CONF_MAC, ""))
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            try:
                broadcast = _clean_broadcast(
                    user_input.get(CONF_BROADCAST, DEFAULT_BROADCAST)
                )
            except ValueError:
                errors[CONF_BROADCAST] = "invalid_broadcast"
            try:
                power_sensor = _clean_power_sensor_entity_id(
                    user_input.get(CONF_POWER_SENSOR_ENTITY_ID)
                )
            except ValueError:
                errors[CONF_POWER_SENSOR_ENTITY_ID] = "invalid_power_sensor"
            if not errors:
                data = {CONF_HOST: self._discovered_host, CONF_MAC: mac,
                        CONF_BROADCAST: broadcast}
                if f1_id is not None:
                    data[CONF_F1_SOURCE_SELECTION_BUTTON_ID] = f1_id
                if power_sensor is not None:
                    data[CONF_POWER_SENSOR_ENTITY_ID] = power_sensor
                return self.async_create_entry(
                    title="TV", data=data,
                )
        return self.async_show_form(
            step_id="confirm", errors=errors,
            data_schema=vol.Schema({
                vol.Optional(CONF_MAC, default=""): str,
                vol.Optional(CONF_BROADCAST, default=DEFAULT_BROADCAST): str,
                vol.Optional(CONF_F1_SOURCE_SELECTION_BUTTON_ID): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=9)
                ),
                vol.Optional(CONF_POWER_SENSOR_ENTITY_ID): str,
            }),
        )


class MetzRemoteOptionsFlow(config_entries.OptionsFlowWithReload):
    """Update WOL and F1 source-selection settings; reload when changed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Configure optional F1 shortcut without recreating the integration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                mac = _clean_mac(user_input.get(CONF_MAC, ""))
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            try:
                broadcast = _clean_broadcast(
                    user_input.get(CONF_BROADCAST, DEFAULT_BROADCAST)
                )
            except ValueError:
                errors[CONF_BROADCAST] = "invalid_broadcast"
            try:
                f1_id = _clean_f1_source_button_id(
                    user_input.get(CONF_F1_SOURCE_SELECTION_BUTTON_ID)
                )
            except ValueError:
                errors[CONF_F1_SOURCE_SELECTION_BUTTON_ID] = "invalid_f1_button_id"
            try:
                power_sensor = _clean_power_sensor_entity_id(
                    user_input.get(CONF_POWER_SENSOR_ENTITY_ID)
                )
            except ValueError:
                errors[CONF_POWER_SENSOR_ENTITY_ID] = "invalid_power_sensor"
            if not errors:
                # Keep explicit None when cleared, overriding a value initially
                # saved in entry.data on older installations.
                data = {
                    CONF_MAC: mac,
                    CONF_BROADCAST: broadcast,
                    CONF_F1_SOURCE_SELECTION_BUTTON_ID: f1_id,
                    CONF_POWER_SENSOR_ENTITY_ID: power_sensor,
                }
                return self.async_create_entry(data=data)

        entry = self.config_entry
        mac_default = entry.options.get(CONF_MAC, entry.data.get(CONF_MAC, ""))
        broadcast_default = entry.options.get(
            CONF_BROADCAST, entry.data.get(CONF_BROADCAST, DEFAULT_BROADCAST)
        )
        stored_f1_keycode = entry.options.get(
            CONF_F1_SOURCE_SELECTION_BUTTON_ID,
            entry.data.get(CONF_F1_SOURCE_SELECTION_BUTTON_ID),
        )
        # Existing entries store SOAP IDs 1..10; show visible digits 0..9.
        f1_default = (
            int(stored_f1_keycode) - 1
            if stored_f1_keycode is not None else None
        )
        power_sensor_default = entry.options.get(
            CONF_POWER_SENSOR_ENTITY_ID,
            entry.data.get(CONF_POWER_SENSOR_ENTITY_ID, ""),
        )
        schema = {
            vol.Optional(CONF_MAC, default=mac_default): str,
            vol.Required(CONF_BROADCAST, default=broadcast_default): str,
            vol.Optional(CONF_POWER_SENSOR_ENTITY_ID, default=power_sensor_default): str,
        }
        if f1_default is None:
            schema[vol.Optional(CONF_F1_SOURCE_SELECTION_BUTTON_ID)] = vol.All(
                vol.Coerce(int), vol.Range(min=0, max=9)
            )
        else:
            schema[vol.Optional(CONF_F1_SOURCE_SELECTION_BUTTON_ID,
                                default=f1_default)] = vol.All(
                vol.Coerce(int), vol.Range(min=0, max=9)
            )
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(schema), errors=errors,
        )
