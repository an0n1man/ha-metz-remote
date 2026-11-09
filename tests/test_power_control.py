"""Power behavior tests without installing Home Assistant."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "metz_remote"


def _stub(name: str, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


def _load_player():
    """Load the real media_player.py with minimal HA type stubs."""
    class HomeAssistantError(Exception):
        pass

    class MediaPlayerState:
        ON = "on"
        OFF = "off"

    class MediaPlayerEntityFeature:
        TURN_OFF = 1
        TURN_ON = 2
        VOLUME_STEP = 4
        NEXT_TRACK = 8
        PREVIOUS_TRACK = 16
        SELECT_SOURCE = 32

    class MediaPlayerDeviceClass:
        TV = "tv"

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

    CoordinatorEntity.__class_getitem__ = classmethod(lambda cls, _type: cls)

    class DummyApiError(Exception):
        pass

    pkgname = "metz_power_fixture"
    pkg = _stub(pkgname, MetzCoordinator=object)
    pkg.__path__ = [str(ROOT)]
    stubs = {
        pkgname: pkg,
        pkgname + ".api": _stub(pkgname + ".api", MetzError=DummyApiError),
        pkgname + ".const": _stub(
            pkgname + ".const", DOMAIN="metz_remote", SOURCE_BUTTONS={
                "HDMI 1": (16, 1), "HDMI 2": (17, 2),
                "HDMI 3": (18, 3), "HDMI 4": (19, 4),
                "EURO": (20, 5), "Cinch AV": (21, 6),
                "Cinch Audio": (22, 7),
            },
            KEY_CODES={"power": 11},
        ),
        pkgname + ".wol": _stub(pkgname + ".wol", async_send_magic_packet=None),
        "homeassistant": _stub("homeassistant"),
        "homeassistant.components": _stub("homeassistant.components"),
        "homeassistant.components.media_player": _stub(
            "homeassistant.components.media_player",
            MediaPlayerDeviceClass=MediaPlayerDeviceClass,
            MediaPlayerEntity=object,
            MediaPlayerEntityFeature=MediaPlayerEntityFeature,
            MediaPlayerState=MediaPlayerState,
        ),
        "homeassistant.config_entries": _stub("homeassistant.config_entries", ConfigEntry=object),
        "homeassistant.core": _stub("homeassistant.core", HomeAssistant=object),
        "homeassistant.exceptions": _stub("homeassistant.exceptions", HomeAssistantError=HomeAssistantError),
        "homeassistant.helpers": _stub("homeassistant.helpers"),
        "homeassistant.helpers.device_registry": _stub("homeassistant.helpers.device_registry", DeviceInfo=dict),
        "homeassistant.helpers.entity_platform": _stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=object),
        "homeassistant.helpers.update_coordinator": _stub("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity),
    }
    spec = importlib.util.spec_from_file_location(
        pkgname + ".media_player", ROOT / "media_player.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        sys.modules[pkgname + ".media_player"] = module
        try:
            spec.loader.exec_module(module)
        finally:
            del sys.modules[pkgname + ".media_player"]
    return module, MediaPlayerState, HomeAssistantError


class FakeCoordinator:
    def __init__(self, *, power=0, success=True):
        self.last_update_success = success
        self.data = types.SimpleNamespace(power_state=power)
        self.refresh_count = 0

    async def async_refresh(self):
        self.refresh_count += 1


class FakeAPI:
    def __init__(self):
        self.sent = []

    async def async_key(self, code):
        self.sent.append(code)


def _make_player(module, *, mac="AABBCCDDEEFF", broadcast="192.168.1.255", power=0, success=True):
    coordinator = FakeCoordinator(power=power, success=success)
    api = FakeAPI()
    runtime = types.SimpleNamespace(
        coordinator=coordinator, api=api,
        description=types.SimpleNamespace(udn="uuid:123", name="Test TV"),
        mac=mac, broadcast_address=broadcast,
        f1_source_selection_button_id=None,
    )
    entry = types.SimpleNamespace(runtime_data=runtime)
    player = module.MetzMediaPlayer(entry)
    player.hass = object()
    return player, coordinator, api


def test_turn_off_uses_key_11_only_when_soap_reports_on():
    mod, _, _ = _load_player()
    player, coord, api = _make_player(mod, power=0)
    asyncio.run(player.async_turn_off())
    assert api.sent == [11]
    assert coord.refresh_count == 1


def test_turn_off_never_toggles_if_off_unknown_or_unreachable():
    mod, _, HomeAssistantError = _load_player()
    for power, available in ((1, True), (5, True), (0, False)):
        player, coord, api = _make_player(mod, power=power, success=available)
        if power == 1 and available:
            asyncio.run(player.async_turn_off())
        else:
            with pytest.raises(HomeAssistantError, match="refusing to send"):
                asyncio.run(player.async_turn_off())
        assert api.sent == []
        assert coord.refresh_count == 1


def test_turn_on_sends_wol_to_configured_broadcast_without_power_key():
    mod, _, _ = _load_player()
    player, _, api = _make_player(mod, success=False)
    called = []

    async def send(hass, mac, broadcast):
        called.append((mac, broadcast))

    mod.async_send_magic_packet = send
    asyncio.run(player.async_turn_on())
    assert called == [("AABBCCDDEEFF", "192.168.1.255")]
    assert api.sent == []


def test_turn_on_requires_configured_mac():
    mod, _, HomeAssistantError = _load_player()
    player, _, _ = _make_player(mod, mac="", power=1)
    with pytest.raises(HomeAssistantError, match="MAC address"):
        asyncio.run(player.async_turn_on())


def test_turn_on_does_nothing_if_already_on():
    mod, _, _ = _load_player()
    player, _, api = _make_player(mod, power=0)
    called = []

    async def send(*_args):
        called.append(True)

    mod.async_send_magic_packet = send
    asyncio.run(player.async_turn_on())
    assert not called and api.sent == []


def test_wol_packet_format_and_broadcast_target():
    """Verify exact 102-byte payload without sending real network packets."""
    class DummySock:
        def __init__(self):
            self.sent = None
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def setsockopt(self, *_):
            pass
        def settimeout(self, _):
            pass
        def sendto(self, payload, dst):
            self.sent = (payload, dst)

    package = _stub("metz_wol_fixture")
    package.__path__ = [str(ROOT)]
    stubs = {
        "metz_wol_fixture": package,
        "metz_wol_fixture.const": _stub("metz_wol_fixture.const", DEFAULT_BROADCAST="255.255.255.255"),
        "homeassistant": _stub("homeassistant"),
        "homeassistant.core": _stub("homeassistant.core", HomeAssistant=object),
    }
    spec = importlib.util.spec_from_file_location("metz_wol_fixture.wol", ROOT / "wol.py")
    module = importlib.util.module_from_spec(spec)
    sock = DummySock()
    with patch.dict(sys.modules, stubs):
        with patch("socket.socket", return_value=sock):
            spec.loader.exec_module(module)
            module._send_magic_packet("AABBCCDDEEFF", "192.168.1.255")
    payload, target = sock.sent
    assert len(payload) == 102
    assert payload == b"\xff" * 6 + bytes.fromhex("AABBCCDDEEFF") * 16
    assert target == ("192.168.1.255", 9)


def test_source_selection_is_hidden_unless_f1_id_is_configured():
    mod, _, HomeAssistantError = _load_player()
    player, coord, _ = _make_player(mod)
    coord.data.source_name = "HDMI 2"
    # Even without a configurable F1 key, SOAP source status remains readable.
    assert player.source == "HDMI 2"
    assert player.source_list is None
    assert not player._attr_supported_features & 32  # SELECT_SOURCE
    with pytest.raises(HomeAssistantError, match="Configure an F1"):
        asyncio.run(player.async_select_source("HDMI 1"))
    player.runtime.f1_source_selection_button_id = 5
    # Entity attributes are set when the config-entry is loaded, so recreate.
    fresh, _, _ = _make_player(mod)
    fresh.runtime.f1_source_selection_button_id = 5
    fresh2 = mod.MetzMediaPlayer(types.SimpleNamespace(runtime_data=fresh.runtime))
    assert fresh2._attr_supported_features & 32
    assert fresh2.source_list == [
        "HDMI 1", "HDMI 2", "HDMI 3", "HDMI 4",
        "EURO", "Cinch AV", "Cinch Audio",
    ]


def test_source_selection_calls_three_key_macro_and_refreshes_status():
    mod, _, _ = _load_player()
    player, coord, api = _make_player(mod)
    player.runtime.f1_source_selection_button_id = 5
    coord.refreshes = []

    async def refresh():
        coord.refreshes.append(True)

    async def select(source, key):
        api.sent.append((source, key))

    coord.async_request_refresh = refresh
    api.async_select_f1_source = select
    asyncio.run(player.async_select_source("Cinch AV"))
    assert api.sent == [("Cinch AV", 5)]
    assert coord.refreshes == [True]
