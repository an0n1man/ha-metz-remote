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
from .const import CONF_BROADCAST, CONF_MAC, DEFAULT_BROADCAST, DOMAIN


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


class MetzClassicConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up by manual IP or SSDP announcement."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MetzClassicOptionsFlow:
        """Allow configuring WOL for an already installed TV."""
        return MetzClassicOptionsFlow()

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_description: MetzDescription | None = None

    async def _probe(self, host: str) -> MetzDescription:
        api = MetzClient(async_get_clientsession(self.hass), host)
        description = await api.async_description()
        await api.async_action("GetPowerState")
        return description

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Show a form and validate the TV before creating an entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host = _clean_host(user_input[CONF_HOST])
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    mac = _clean_mac(user_input.get(CONF_MAC, ""))
                except ValueError:
                    errors[CONF_MAC] = "invalid_mac"
                else:
                    try:
                        broadcast = _clean_broadcast(
                            user_input.get(CONF_BROADCAST, DEFAULT_BROADCAST)
                        )
                    except ValueError:
                        errors[CONF_BROADCAST] = "invalid_broadcast"
                    else:
                        try:
                            description = await self._probe(host)
                        except MetzError:
                            errors["base"] = "cannot_connect"
                        else:
                            await self.async_set_unique_id(description.udn)
                            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                            return self.async_create_entry(
                                title=description.name,
                                data={CONF_HOST: host, CONF_MAC: mac,
                                      CONF_BROADCAST: broadcast},
                            )
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=self._discovered_host or ""): str,
            vol.Optional(CONF_MAC, default=""): str,
            vol.Optional(CONF_BROADCAST, default=DEFAULT_BROADCAST): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

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
        """Ask for confirmation of an SSDP-discovered TV."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_description.name,
                data={CONF_HOST: self._discovered_host, CONF_MAC: "",
                      CONF_BROADCAST: DEFAULT_BROADCAST},
            )
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


class MetzClassicOptionsFlow(config_entries.OptionsFlowWithReload):
    """Update the WOL configuration and automatically reload the integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Set/clear MAC and configure where to send the magic packet."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                mac = _clean_mac(user_input.get(CONF_MAC, ""))
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"
            else:
                try:
                    broadcast = _clean_broadcast(
                        user_input.get(CONF_BROADCAST, DEFAULT_BROADCAST)
                    )
                except ValueError:
                    errors[CONF_BROADCAST] = "invalid_broadcast"
                else:
                    return self.async_create_entry(data={
                        CONF_MAC: mac, CONF_BROADCAST: broadcast,
                    })

        entry = self.config_entry
        mac_default = entry.options.get(CONF_MAC, entry.data.get(CONF_MAC, ""))
        broadcast_default = entry.options.get(
            CONF_BROADCAST, entry.data.get(CONF_BROADCAST, DEFAULT_BROADCAST)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_MAC, default=mac_default): str,
                vol.Required(CONF_BROADCAST, default=broadcast_default): str,
            }),
            errors=errors,
        )
