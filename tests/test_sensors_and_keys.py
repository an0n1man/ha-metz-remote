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
        package_name + ".const": stub(package_name + ".const", DOMAIN="metz_remote"),
        "homeassistant": stub("homeassistant"),
        "homeassistant.components": stub("homeassistant.components"),
        "homeassistant.components.sensor": stub("homeassistant.components.sensor", SensorEntity=object),
        "homeassistant.config_entries": stub("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.core": stub("homeassistant.core", HomeAssistant=object),
        "homeassistant.helpers": stub("homeassistant.helpers"),
        "homeassistant.helpers.device_registry": stub("homeassistant.helpers.device_registry", DeviceInfo=dict),
        "homeassistant.helpers.entity_registry": stub("homeassistant.helpers.entity_registry", async_get=lambda hass: hass.registry),
        "homeassistant.helpers.entity_platform": stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=object),
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


def _make_entities(mod, *, powered=0, success=True, source=16):
    status = types.SimpleNamespace(
        active_device=source,
        power_state=powered,
        devices={0: "Metz-TV", 16: "HDMI 1", 17: "HDMI 2"},
        source_name={0: "Metz-TV", 16: "HDMI 1", 17: "HDMI 2"}.get(source),
    )
    coord = types.SimpleNamespace(last_update_success=success, data=status)
    runtime = types.SimpleNamespace(
        coordinator=coord,
        description=types.SimpleNamespace(udn="uuid:123", name="My Metz"),
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



def test_translated_entity_names_are_present():
    for name, lang in (("strings.json", "Active source"), ("translations/en.json", "Active source"), ("translations/de.json", "Aktive Quelle")):
        data = json.loads((ROOT/name).read_text())
        assert data["entity"]["sensor"]["active_source"]["name"] == lang
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
    assert len(entities) == 1
    assert isinstance(entities[0], mod.MetzSourceSensor)


def test_sensor_preserves_tv_reported_custom_input_name():
    mod = _import_real_sensor_module()
    source = _make_entities(mod)
    source.coordinator.data.source_name = "Blu-ray-Player"
    assert source.native_value == "Blu-ray-Player"
    assert source.extra_state_attributes["source"] == "Blu-ray-Player"
    assert source.extra_state_attributes["active_device_id"] == 16
