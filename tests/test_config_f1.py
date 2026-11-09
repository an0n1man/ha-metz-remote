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
        name: str = "Metz TV"

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
    assert mod._clean_f1_source_button_id("5") == 5
    for invalid in (0, 11, -1, True, "abc", "5.1"):
        with pytest.raises(ValueError):
            mod._clean_f1_source_button_id(invalid)


def test_new_setup_exposes_optional_f1_id_and_persists_valid_one():
    mod = load_flow()
    flow = mod.MetzRemoteConfigFlow()

    async def probe(host):
        return mod.MetzDescription()

    flow._probe = probe
    initial_form = asyncio.run(flow.async_step_user())
    assert KEY in [k.key for k in initial_form["data_schema"]]
    created = asyncio.run(flow.async_step_user({
        "host": "192.168.1.131", "mac": "", "broadcast_address": "192.168.1.255",
        KEY: 5,
    }))
    assert created["data"][KEY] == 5
    assert created["data"]["host"] == "192.168.1.131"
    blank = asyncio.run(flow.async_step_user({
        "host": "192.168.1.131", "mac": "", "broadcast_address": "192.168.1.255",
    }))
    assert KEY not in blank["data"]


def test_options_can_set_and_clear_f1_id_without_removing_existing_entry():
    mod = load_flow()
    flow = mod.MetzRemoteOptionsFlow()
    flow.config_entry = types.SimpleNamespace(
        data={"mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255", KEY: 5},
        options={},
    )
    form = asyncio.run(flow.async_step_init())
    assert KEY in [k.key for k in form["data_schema"]]
    changed = asyncio.run(flow.async_step_init({
        "mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255", KEY: 7,
    }))
    assert changed["data"][KEY] == 7
    cleared = asyncio.run(flow.async_step_init({
        "mac": "AABBCCDDEEFF", "broadcast_address": "192.168.1.255",
    }))
    # Explicit None overrides old entry.data to disable SELECT_SOURCE.
    assert KEY in cleared["data"]
    assert cleared["data"][KEY] is None
