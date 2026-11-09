"""Constants and APK-derived remote-control key mappings for Metz Remote."""

DOMAIN = "metz_remote"
CONF_MAC = "mac"
CONF_BROADCAST = "broadcast_address"
DEFAULT_BROADCAST = "255.255.255.255"
DEFAULT_PORT = 49200
SERVICE_TYPE = "urn:metz.de:service:RCRService:1"
DEVICE_TYPE = "urn:metz.de:device:RemoteControlReceiver:1"
DEFAULT_SCAN_INTERVAL = 15

# Stored setting: SOAP key ID to press after F1 to open the TV's source list.
# UI displays printed digit 0..9; config_flow stores digit + 1 (SOAP ID 1..10).
# This preserves existing 0.3.1 config entries without a migration.
CONF_F1_SOURCE_SELECTION_BUTTON_ID = "f1_source_selection_button_id"

# TV-reported input IDs and the numbered buttons in the F1 source list.
# Explicitly excludes the internal tuner (0x00), as requested.
SOURCE_BUTTONS: dict[str, tuple[int, int]] = {
    "HDMI 1": (0x10, 1),
    "HDMI 2": (0x11, 2),
    "HDMI 3": (0x12, 3),
    "HDMI 4": (0x13, 4),
    "EURO": (0x14, 5),
    "Cinch AV": (0x15, 6),
    "Cinch Audio": (0x16, 7),
}

# From Metz Remote APK de.metz.android.mecaremote: the Android
# ButtonLayout.rcViewMap and legacy RcView class. Unknown swipe codes 70/71
# are deliberately NOT assigned a function; they can still be sent as raw IDs.
# WARNING: "off" (51) comes from APK, but its behavior on this model is NOT
# verified. The legacy "power" (11) remains the guarded turn-off key in HA.
KEY_CODES: dict[str, int] = {
    "digit_0": 1,
    "digit_1": 2,
    "digit_2": 3,
    "digit_3": 4,
    "digit_4": 5,
    "digit_5": 6,
    "digit_6": 7,
    "digit_7": 8,
    "digit_8": 9,
    "digit_9": 10,
    "power": 11,
    "power_toggle": 11,
    "f1": 12,
    "f2": 13,
    "f3": 14,
    "blue": 18,
    "yellow": 19,
    "portal": 20,
    "white": 20,
    "green": 21,
    "red": 22,
    "up": 23,
    "down": 24,
    "left": 25,
    "right": 26,
    "volume_up": 27,
    "volume_down": 28,
    "help": 29,
    "pip": 30,
    "back": 33,
    "mute": 35,
    "teletext": 36,
    "text": 36,
    "epg": 37,
    "menu": 38,
    "ok": 39,
    "exit": 40,
    "rewind": 41,
    "fast_forward": 42,
    "play": 43,
    "stop": 44,
    "record": 45,
    "channel_up": 46,
    "channel_down": 47,
    "ch_up": 46,
    "ch_down": 47,
    "home": 48,
    "source": 49,
    "av": 49,
    "off": 51,  # APK HTML action 'Off'; untested on user's TV.
    "pause": 66,
}
