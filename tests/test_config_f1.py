"""Configuration-flow regressions without an installed Home Assistant runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "metz_remote"
KEY = "f1_source_selection_button_id"
POWER_KEY = "power_sensor_entity_id"


def load_flow():
    def stub(name, **symbols):
        module = types.ModuleType(name)
        vars(module).update(symbols)
        return module

    class Marker:
        def __init__(self, key, default=None):
            self.key = key
            self.default = default

    class FakeVol:
        Required = Marker
        Optional = Marker
        Schema = staticmethod(lambda value: value)
        All = staticmethod(lambda *args: args)
        Coerce = staticmethod(lambda type_: type_)
        Range = staticmethod(lambda **kwargs: kwargs)

    class EntitySelectorConfig(dict):
        pass

    class EntitySelector:
        def __init__(self, config):
            self.config = config

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            # Consume domain=<slug> as the real HA superclass does.
            super().__init_subclass__()

        async def async_set_unique_id(self, unique_id):
            self.unique_id = unique_id

        def _abort_if_unique_id_configured(self, **kwargs):
            pass

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

    class OptionsFlowWithReload(ConfigFlow):
        automatic_reload = True

    class MetzError(Exception):
        pass

    @dataclass
    class MetzDescription:
        udn: str = "uuid:test"
        name: str = "TV"

    root = stub("metz_flow_fixture")
    root.__path__ = [str(COMPONENT_DIR)]
    stubs = {
        "metz_flow_fixture": root,
        "probatio": stub("probatio", **vars(FakeVol)),
        "metz_flow_fixture.api": stub("metz_flow_fixture.api", MetzClient=object, MetzDescription=MetzDescription, MetzError=MetzError),
        "homeassistant": stub("homeassistant", config_entries=stub("homeassistant.config_entries", ConfigFlow=ConfigFlow, OptionsFlowWithReload=OptionsFlowWithReload, ConfigEntry=object)),
        "homeassistant.config_entries": stub("homeassistant.config_entries", ConfigFlow=ConfigFlow, OptionsFlowWithReload=OptionsFlowWithReload, ConfigEntry=object),
        "homeassistant.const": stub("homeassistant.const", CONF_HOST="host"),
        "homeassistant.core": stub("homeassistant.core", callback=lambda f: f),
        "homeassistant.helpers": stub("homeassistant.helpers"),
        "homeassistant.helpers.selector": stub(
            "homeassistant.helpers.selector",
            EntitySelector=EntitySelector,
            EntitySelectorConfig=EntitySelectorConfig,
        ),
        "homeassistant.helpers.aiohttp_client": stub("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None),
        "homeassistant.helpers.service_info": stub("homeassistant.helpers.service_info"),
        "homeassistant.helpers.service_info.ssdp": stub("homeassistant.helpers.service_info.ssdp", SsdpServiceInfo=object),
    }
    spec = importlib.util.spec_from_file_location("metz_flow_fixture.config_flow", COMPONENT_DIR / "config_flow.py")
    mod = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(mod)
    return mod


def test_f1_config_validation():
    mod = load_flow()
    assert mod._clean_f1_source_button_id(None) is None
    assert mod._clean_f1_source_button_id("") is None
    assert mod._clean_f1_source_button_id("0") == 1
    assert mod._clean_f1_source_button_id("4") == 5
    assert mod._clean_f1_source_button_id("9") == 10
    for invalid in (10, 11, -1, True, "abc", "5.1"):
        with pytest.raises(ValueError):
            mod._clean_f1_source_button_id(invalid)


def test_power_sensor_entity_validation():
    mod = load_flow()
    assert mod._clean_power_sensor_entity_id(None) is None
    assert mod._clean_power_sensor_entity_id("") is None
    assert mod._clean_power_sensor_entity_id(" Sensor.TV_Power ") == "sensor.tv_power"
    for invalid in (True, "switch.tv", "sensor.bad-id", "sensor."):
        with pytest.raises(ValueError):
            mod._clean_power_sensor_entity_id(invalid)


def test_new_setup_exposes_optional_f1_id_and_persists_valid_one():
    mod = load_flow()
    flow = mod.MetzRemoteConfigFlow()

    async def probe(host):
        return mod.MetzDescription()

    flow._probe = probe
    initial_form = asyncio.run(flow.async_step_user())
    assert KEY in [k.key for k in initial_form["data_schema"]]
    assert POWER_KEY in [k.key for k in initial_form["data_schema"]]
    power_marker = next(k for k in initial_form["data_schema"] if k.key == POWER_KEY)
    assert initial_form["data_schema"][power_marker].config == {
        "filter": {"domain": "sensor", "device_class": "power"}
    }
    created = asyncio.run(flow.async_step_user({
        "host": "192.168.1.131", "mac": "", "broadcast_address": "192.168.1.255",
        KEY: 0, POWER_KEY: "sensor.tv_power",
    }))
    assert created["data"][KEY] == 1
    assert created["data"][POWER_KEY] == "sensor.tv_power"
    assert created["data"]["host"] == "192.168.1.131"
    assert created["title"] == "TV"
    blank = asyncio.run(flow.async_step_user({
        "host": "192.168.1.131", "mac": "", "broadcast_address": "192.168.1.255",
    }))
    assert KEY not in blank["data"]


def test_options_can_set_and_clear_f1_id_without_removing_existing_entry():
    mod = load_flow()
    flow = mod.MetzRemoteOptionsFlow()
    flow.config_entry = types.SimpleNamespace(
        data={
            "mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255",
            KEY: 5, POWER_KEY: "sensor.old_power",
        },
        options={},
    )
    form = asyncio.run(flow.async_step_init())
    f1_marker = next(k for k in form["data_schema"] if k.key == KEY)
    # Previous v0.3.1 saved SOAP code 5 for physical digit 4.
    assert f1_marker.default == 4
    assert form["data_schema"][f1_marker][1] == {"min": 0, "max": 9}
    power_marker = next(k for k in form["data_schema"] if k.key == POWER_KEY)
    assert power_marker.default == "sensor.old_power"
    changed = asyncio.run(flow.async_step_init({
        "mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255", KEY: 9,
        POWER_KEY: "sensor.tv_power",
    }))
    assert changed["data"][KEY] == 10
    assert changed["data"][POWER_KEY] == "sensor.tv_power"
    cleared = asyncio.run(flow.async_step_init({
        "mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255",
    }))
    # Explicit None overrides old entry.data to disable SELECT_SOURCE.
    assert KEY in cleared["data"]
    assert cleared["data"][KEY] is None
    assert cleared["data"][POWER_KEY] is None


def test_all_f1_forms_offer_digits_zero_through_nine():
    mod = load_flow()
    initial = mod.MetzRemoteConfigFlow()
    user_form = asyncio.run(initial.async_step_user())
    confirm_form = asyncio.run(initial.async_step_confirm())
    options = mod.MetzRemoteOptionsFlow()
    options.config_entry = types.SimpleNamespace(data={}, options={})
    options_form = asyncio.run(options.async_step_init())
    for form in (user_form, confirm_form, options_form):
        marker = next(k for k in form["data_schema"] if k.key == KEY)
        assert form["data_schema"][marker][1] == {"min": 0, "max": 9}
        assert POWER_KEY in [field.key for field in form["data_schema"]]


def test_existing_f1_config_remains_compatible_on_options_save():
    mod = load_flow()
    flow = mod.MetzRemoteOptionsFlow()
    flow.config_entry = types.SimpleNamespace(
        data={KEY: 10, "mac": "", "broadcast_address": "255.255.255.255"},
        options={},
    )
    form = asyncio.run(flow.async_step_init())
    field = next(k for k in form["data_schema"] if k.key == KEY)
    assert field.default == 9  # Existing SOAP KeyCode 10 => physical 9
    saved = asyncio.run(flow.async_step_init({
        KEY: 9, "mac": "", "broadcast_address": "255.255.255.255",
    }))
    assert saved["data"][KEY] == 10
