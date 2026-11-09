"""Constants for Metz Remote integration."""

DOMAIN = "metz_remote"
CONF_MAC = "mac"
CONF_BROADCAST = "broadcast_address"
DEFAULT_BROADCAST = "255.255.255.255"
DEFAULT_PORT = 49200
SERVICE_TYPE = "urn:metz.de:service:RCRService:1"
DEVICE_TYPE = "urn:metz.de:device:RemoteControlReceiver:1"
DEFAULT_SCAN_INTERVAL = 15

# Confirmed by PCAPdroid captures and on-device HDMI 1 macro test.
HDMI_1_DEVICE_ID = 0x10
HDMI_1_SOURCE = "HDMI 1"
HDMI_1_KEY_SEQUENCE = (49, 24, 24, 39, 39)  # Source, Down, Down, OK, OK.

# Verified by the metzctl project; volume_up (27) was tested on a Metz TV.
KEY_CODES: dict[str, int] = {
    "power": 11,
    "volume_up": 27,
    "volume_down": 28,
    "mute": 35,  # Toggle only; mute state is not exposed by RCRService.
    "ok": 39,
    "up": 23,
    "down": 24,
    "left": 25,
    "right": 26,
    "source": 49,
    "channel_up": 46,
    "channel_down": 47,
    "ch_up": 46,
    "ch_down": 47,
}
