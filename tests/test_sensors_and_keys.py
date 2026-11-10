"""The new 0.3.0 sensors and the actual APK-derived numeric mappings."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "metz_remote"


def test_apk_keycode_mapping_is_complete_and_digit_zero_is_one():
    from metz_remote.const import KEY_CODES
    assert KEY_CODES["digit_0"] == 1
    assert KEY_CODES["digit_1"] == 2
    assert KEY_CODES["digit_9"] == 10
    assert KEY_CODES["power"] == 11
    assert KEY_CODES["off"] == 51
    assert KEY_CODES["pause"] == 66
    assert KEY_CODES["source"] == 49
    with open(Path(__file__).resolve().parents[1] / "docs/metz_remote_apk_sendkey_ids.json", encoding="utf8") as f:
        rows = json.load(f)
    # Unknown swipe commands 70/71 are still available as raw numeric commands.
    observed = {row["keycode"] for row in rows["keycodes"]}
    known = set(KEY_CODES.values()) | {70, 71}
    assert observed == known


def _import_real_sensor_module():
    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    CoordinatorEntity.__class_getitem__ = classmethod(lambda cls, _t: cls)

    def stub(name, **fields):
        mod = types.ModuleType(name)
        mod.__dict__.update(fields)
        return mod

    package_name = "metz_sensor_fixture"
    package = stub(package_name, MetzCoordinator=object)
    package.__path__ = [str(ROOT)]
    stubs = {
        package_name: package,
        package_name + ".const": stub(
            package_name + ".const",
            DOMAIN="metz_remote",
            POWER_OFF_WATTS=10.0,
            POWER_ON_WATTS=70.0,
        ),
        "homeassistant": stub("homeassistant"),
        "homeassistant.components": stub("homeassistant.components"),
        "homeassistant.components.sensor": stub("homeassistant.components.sensor", SensorEntity=object),
        "homeassistant.config_entries": stub("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.core": stub(
            "homeassistant.core", HomeAssistant=object, callback=lambda func: func
        ),
        "homeassistant.helpers": stub("homeassistant.helpers"),
        "homeassistant.helpers.device_registry": stub("homeassistant.helpers.device_registry", DeviceInfo=dict),
        "homeassistant.helpers.entity_registry": stub("homeassistant.helpers.entity_registry", async_get=lambda hass: hass.registry),
        "homeassistant.helpers.entity_platform": stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=object),
        "homeassistant.helpers.event": stub(
            "homeassistant.helpers.event", async_track_state_change_event=lambda *_: lambda: None
        ),
        "homeassistant.helpers.update_coordinator": stub("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity),
    }
    spec = importlib.util.spec_from_file_location(
        package_name + ".sensor", ROOT / "sensor.py",
    )
    mod = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        sys.modules[package_name + ".sensor"] = mod
        try:
            spec.loader.exec_module(mod)
        finally:
            del sys.modules[package_name + ".sensor"]
    return mod


def _make_entities(mod, *, powered=0, success=True, source=16, power_sensor=None):
    source_names = {
        0: "TV",
        16: "HDMI 1",
        17: "HDMI 2",
        18: "HDMI 3",
        19: "HDMI 4",
        22: "EURO",
        23: "Cinch AV",
        54: "Cinch Audio",
    }
    status = types.SimpleNamespace(
        active_device=source,
        power_state=powered,
        devices={0: "TV", 16: "HDMI 1", 17: "HDMI 2"},
        source_name=source_names.get(source),
    )
    coord = types.SimpleNamespace(
        last_update_success=success,
        active_source_unknown=False,
        data=status,
        source_name=status.source_name,
    )
    runtime = types.SimpleNamespace(
        coordinator=coord,
        description=types.SimpleNamespace(udn="uuid:123", name="My Metz"),
        power_sensor_entity_id=power_sensor,
    )
    entry = types.SimpleNamespace(runtime_data=runtime)
    return mod.MetzSourceSensor(entry)


def test_active_source_readback_uses_coordinator_and_device_list():
    mod = _import_real_sensor_module()
    source = _make_entities(mod)
    assert source.native_value == "HDMI 1"
    assert source.extra_state_attributes["active_device_id"] == 16
    assert source.extra_state_attributes["active_device_hex"] == "0x10"
    assert source._attr_device_info["name"] == "TV"
    assert source._attr_unique_id == "uuid:123_active_source"
    assert source._attr_translation_key == "active_source"
    assert not hasattr(mod, "MetzVolumeSensor")


def test_unknown_active_device_and_standby_are_not_fake_sources():
    mod = _import_real_sensor_module()
    source = _make_entities(mod, source=255)
    assert source.native_value is None
    assert source.extra_state_attributes["source"] is None
    assert source.extra_state_attributes["active_device_hex"] == "0xFF"

    for powered, success in ((1, True), (0, False)):
        source = _make_entities(mod, powered=powered, success=success)
        assert source.native_value is None


def test_starting_tv_reports_active_source_as_unknown_not_unavailable():
    mod = _import_real_sensor_module()
    source = _make_entities(mod, success=False)
    source.coordinator.active_source_unknown = True
    source.coordinator.source_name = None
    assert source.available is True
    assert source.native_value is None
    assert source.extra_state_attributes == {
        "active_device_id": None,
        "active_device_hex": None,
        "source": None,
    }


def test_active_source_uses_canonical_analogue_id():
    mod = _import_real_sensor_module()
    source = _make_entities(mod, source=22)
    assert source.native_value == "EURO"
    assert source.extra_state_attributes == {
        "active_device_id": 22,
        "active_device_hex": "0x16",
        "source": "EURO",
    }


def test_internal_tv_state_sensor_uses_power_sensor_classification():
    mod = _import_real_sensor_module()
    source = _make_entities(mod, power_sensor="sensor.tv_power")
    internal_state = mod.MetzInternalTVStateSensor(
        types.SimpleNamespace(runtime_data=source.runtime)
    )
    for watts, expected in ((80, "on"), (20, "idle"), (5, "off")):
        internal_state.hass = types.SimpleNamespace(
            states=types.SimpleNamespace(
                get=lambda _entity_id, watts=watts: types.SimpleNamespace(state=str(watts))
            )
        )
        assert internal_state.native_value == expected
    assert internal_state._attr_unique_id == "uuid:123_internal_tv_state"
    assert internal_state._attr_translation_key == "internal_tv_state"


def test_internal_tv_state_sensor_falls_back_to_soap_power_state():
    mod = _import_real_sensor_module()
    for powered, expected in ((0, "on"), (1, "off"), (5, None)):
        source = _make_entities(mod, powered=powered)
        internal_state = mod.MetzInternalTVStateSensor(
            types.SimpleNamespace(runtime_data=source.runtime)
        )
        assert internal_state.native_value == expected



def test_translated_entity_names_are_present():
    for name, active_source, internal_state in (
        ("strings.json", "Active source", "Internal TV state"),
        ("translations/en.json", "Active source", "Internal TV state"),
        ("translations/de.json", "Aktive Quelle", "Interner TV-Status"),
    ):
        data = json.loads((ROOT/name).read_text())
        assert data["entity"]["sensor"]["active_source"]["name"] == active_source
        assert data["entity"]["sensor"]["internal_tv_state"]["name"] == internal_state
        assert "volume" not in data["entity"]["sensor"]


def test_volume_registry_entry_is_removed_on_upgrade():
    import asyncio
    mod = _import_real_sensor_module()
    removed = []

    class Registry:
        def async_get_entity_id(self, platform, domain, unique_id):
            assert (platform, domain, unique_id) == (
                "sensor", "metz_remote", "uuid:123_volume"
            )
            return "sensor.metz_tv_volume"

        def async_remove(self, entity_id):
            removed.append(entity_id)

    runtime = types.SimpleNamespace(
        coordinator=types.SimpleNamespace(last_update_success=False),
        description=types.SimpleNamespace(udn="uuid:123", name="TV"),
    )
    hass = types.SimpleNamespace(registry=Registry())
    entities = []
    asyncio.run(mod.async_setup_entry(hass, types.SimpleNamespace(runtime_data=runtime), entities.extend))
    assert removed == ["sensor.metz_tv_volume"]
    assert len(entities) == 2
    assert isinstance(entities[0], mod.MetzSourceSensor)
    assert isinstance(entities[1], mod.MetzInternalTVStateSensor)


def test_sensor_preserves_tv_reported_custom_input_name():
    mod = _import_real_sensor_module()
    source = _make_entities(mod)
    source.coordinator.data.source_name = "HDMI 1"
    assert source.native_value == "HDMI 1"
    assert source.extra_state_attributes["source"] == "HDMI 1"
    assert source.extra_state_attributes["active_device_id"] == 16
