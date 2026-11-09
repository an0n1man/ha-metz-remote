"""Unit-test startup without installing the full Home Assistant runtime.

Only the Home Assistant framework hooks are stubbed. The integration's real
async_setup_entry logic and the real Metz API error types are exercised.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "metz_remote"


def mod(name: str, **names):
    module = types.ModuleType(name)
    module.__dict__.update(names)
    return module


def setup_module_with_fake_ha():
    class ConfigEntryNotReady(Exception):
        pass

    class UpdateFailed(Exception):
        pass

    class FakeCoordinator:
        def __init__(self, hass, logger, *, name, update_interval):
            self.last_update_success = None

        async def async_refresh(self):
            try:
                self.data = await self._async_update_data()
            except UpdateFailed:
                self.last_update_success = False
            else:
                self.last_update_success = True

    class Platform:
        MEDIA_PLAYER = "media_player"
        REMOTE = "remote"
        SENSOR = "sensor"

    ha = mod("homeassistant")
    ha.__path__ = []
    helpers = mod("homeassistant.helpers")
    helpers.__path__ = []
    stubs = {
        "homeassistant": ha,
        "homeassistant.config_entries": mod("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.const": mod("homeassistant.const", CONF_HOST="host", Platform=Platform),
        "homeassistant.core": mod("homeassistant.core", HomeAssistant=object),
        "homeassistant.exceptions": mod("homeassistant.exceptions", ConfigEntryNotReady=ConfigEntryNotReady),
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.aiohttp_client": mod(
            "homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: object()
        ),
        "homeassistant.helpers.update_coordinator": mod(
            "homeassistant.helpers.update_coordinator",
            DataUpdateCoordinator=FakeCoordinator,
            UpdateFailed=UpdateFailed,
        ),
    }
    FakeCoordinator.__class_getitem__ = classmethod(lambda cls, typ: cls)
    name = "metz_offline_fixture"
    spec = importlib.util.spec_from_file_location(
        name,
        COMPONENT_DIR / "__init__.py",
        submodule_search_locations=[str(COMPONENT_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            for entry in list(sys.modules):
                if entry.startswith(name + "."):
                    del sys.modules[entry]
            del sys.modules[name]
    return module, ConfigEntryNotReady


def test_offline_setup_uses_saved_udn_and_loads_entities():
    setup, _ = setup_module_with_fake_ha()

    class FakeApi:
        def __init__(self, session, host):
            self.control_url = f"http://{host}:49200/services/rcr/control/RCRService"

        async def async_description(self):
            raise setup.MetzConnectionError("TV is sleeping")

        async def async_status(self):
            raise setup.MetzError("TV is sleeping")

    setup.MetzClient = FakeApi
    forwarded = []

    class Entry:
        unique_id = "uuid:3265DECF-33F5-714A-4D58-1CA770651CF6"
        title = "Metz-TV (192.168.1.131)"
        data = {"host": "192.168.1.131", "mac": ""}
        options = {}

    class Hass:
        config_entries = types.SimpleNamespace(
            async_forward_entry_setups=lambda entry, platforms: _forward(platforms)
        )

    async def _forward(platforms):
        forwarded.extend(platforms)

    entry = Entry()
    assert asyncio.run(setup.async_setup_entry(Hass(), entry)) is True
    assert entry.runtime_data.description.udn == entry.unique_id
    assert entry.runtime_data.coordinator.last_update_success is False
    assert forwarded == ["media_player", "remote", "sensor"]


def test_offline_setup_does_not_invent_unverified_udn():
    setup, NotReady = setup_module_with_fake_ha()

    class FakeApi:
        def __init__(self, session, host):
            self.control_url = f"http://{host}:49200/services/rcr/control/RCRService"

        async def async_description(self):
            raise setup.MetzConnectionError("TV is sleeping")

    setup.MetzClient = FakeApi

    class Entry:
        unique_id = None
        title = "TV"
        data = {"host": "192.168.1.131"}

    class Hass:
        pass

    with pytest.raises(NotReady, match="unreachable"):
        asyncio.run(setup.async_setup_entry(Hass(), Entry()))


def test_options_override_initial_wol_configuration():
    """An existing config entry can gain WOL later through OptionsFlow."""
    setup, _ = setup_module_with_fake_ha()

    class FakeApi:
        def __init__(self, session, host):
            self.control_url = f"http://{host}:49200/services/rcr/control/RCRService"

        async def async_description(self):
            raise setup.MetzConnectionError("standby")

        async def async_status(self):
            raise setup.MetzError("standby")

    setup.MetzClient = FakeApi

    async def _forward(*_):
        pass

    class Entry:
        unique_id = "uuid:known"
        title = "Metz TV"
        data = {"host": "192.168.1.131", "mac": ""}
        options = {"mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255"}

    class Hass:
        config_entries = types.SimpleNamespace(async_forward_entry_setups=_forward)

    entry = Entry()
    assert asyncio.run(setup.async_setup_entry(Hass(), entry))
    assert entry.runtime_data.mac == "AABBCCDDEEFF"
    assert entry.runtime_data.broadcast_address == "192.168.1.255"
