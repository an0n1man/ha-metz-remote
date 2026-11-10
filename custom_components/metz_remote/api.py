"""Async Metz Remote UPnP/SOAP protocol client.

Only the device's advertised service and confirmed action names are used.
This module intentionally has no dependency on Home Assistant, making it testable.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import aiohttp

from .const import (
    ACTIVE_SOURCE_NAMES,
    DEFAULT_PORT,
    DEVICE_TYPE,
    KEY_CODES,
    SERVICE_TYPE,
    SOURCE_BUTTONS,
)

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
DEVICE_NS = "urn:schemas-upnp-org:device-1-0"
DEFAULT_CONTROL_PATH = "/services/rcr/control/RCRService"
# The TV's old UPnP HTTP stack may close a socket immediately after a response.
# The Android remote also uses a fresh TCP connection for each command.
NO_KEEPALIVE_HEADERS = {"Connection": "close"}
READ_ONLY_ACTIONS = frozenset({
    "GetOperationMode", "GetDeviceList", "GetPowerState", "GetActiveDevice",
})


def _parse_device_list(value: str) -> dict[int, str]:
    """Parse TV-supplied input IDs and names from GetDeviceList."""
    raw_list = value.split(";")
    device_names: dict[int, str] = {}
    for index in range(0, len(raw_list) - 1, 2):
        try:
            device_id = int(raw_list[index].strip(), 0)
        except ValueError:
            continue
        device_name = raw_list[index + 1].strip()
        if device_name:
            device_names[device_id] = device_name
    return device_names


class MetzError(Exception):
    """Metz communication or invalid device response."""


class MetzConnectionError(MetzError):
    """The TV did not answer a network request (possibly sleeping)."""


@dataclass(frozen=True)
class MetzDescription:
    """Description supplied by the television."""

    udn: str
    name: str
    control_url: str


@dataclass(frozen=True)
class MetzStatus:
    """Values provided by RCRService; no undocumented interpretation here."""

    operation_mode: int
    power_state: int
    active_device: int
    devices: dict[int, str]

    def get_device_name(self, device_id: int) -> str | None:
        """Return the canonical name for an RCRService ActiveDevice ID."""
        return ACTIVE_SOURCE_NAMES.get(device_id)

    @property
    def source_name(self) -> str | None:
        """Name of the active input from the canonical ActiveDevice table."""
        return self.get_device_name(self.active_device)


class MetzClient:
    """Small non-blocking client for the Metz Remote remote protocol."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        control_url: str | None = None,
    ) -> None:
        self.session = session
        self.host = host
        self.base_url = f"http://{host}:{DEFAULT_PORT}"
        self.control_url = control_url or self.base_url + DEFAULT_CONTROL_PATH
        # Prevent other remote commands from interrupting a source-selection macro.
        self._command_lock = asyncio.Lock()

    async def async_description(self) -> MetzDescription:
        """Fetch and validate the manufacturer's UPnP description."""
        url = self.base_url + "/description.xml"
        try:
            async with self.session.get(
                url,
                headers=NO_KEEPALIVE_HEADERS,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                response.raise_for_status()
                data = await response.read()
            root = ET.fromstring(data)
        except aiohttp.ClientResponseError as err:
            raise MetzError(f"HTTP error reading device description: {err}") from err
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as err:
            raise MetzConnectionError(f"Cannot read device description: {err}") from err
        except aiohttp.ClientError as err:
            raise MetzError(f"Error reading device description: {err}") from err
        except ET.ParseError as err:
            raise MetzError(f"Invalid UPnP device description: {err}") from err

        device = root.find(f".//{{{DEVICE_NS}}}device")
        if device is None or device.findtext(f"{{{DEVICE_NS}}}deviceType") != DEVICE_TYPE:
            raise MetzError("Device is not a Metz RemoteControlReceiver")
        udn = device.findtext(f"{{{DEVICE_NS}}}UDN")
        if not udn:
            raise MetzError("UPnP description has no device identifier (UDN)")
        name = device.findtext(f"{{{DEVICE_NS}}}friendlyName")
        for service in device.findall(f".//{{{DEVICE_NS}}}service"):
            if service.findtext(f"{{{DEVICE_NS}}}serviceType") != SERVICE_TYPE:
                continue
            path = service.findtext(f"{{{DEVICE_NS}}}controlURL")
            if not path:
                raise MetzError("RCRService has no control URL")
            control_url = urljoin(self.base_url + "/", path)
            # Never follow arbitrary URLs from a misconfigured/untrusted TV.
            if not control_url.startswith(self.base_url + "/"):
                raise MetzError("RCRService control URL points to another host")
            self.control_url = control_url
            return MetzDescription(udn=udn, name=name, control_url=control_url)
        raise MetzError("UPnP device does not advertise RCRService")

    async def async_action(
        self, action: str, arguments: dict[str, int] | None = None
    ) -> dict[str, str]:
        """Invoke a SOAP action and parse the response.

        For this TV we disable HTTP keep-alive for *every* request. A read-only
        action may be retried once after an interrupted connection; SendKeyCode
        must never be replayed since a TV may have applied the key already.
        """
        permitted = READ_ONLY_ACTIONS | {"SendKeyCode"}
        if action not in permitted:
            raise MetzError(f"Unsupported SOAP action {action}")
        if action == "SendKeyCode":
            # A full aiohttp response parse can fail on the Metz UPnP server.
            # Use the metzctl-compatible raw request and read only the status.
            args = arguments or {}
            code = args.get("KeyCode")
            if (not isinstance(code, int) or isinstance(code, bool)
                    or not 0 <= code <= 0xFFFFFFFF
                    or args.get("DestinationDevice") != 0
                    or args.get("ButtonHold") != 0):
                raise MetzError("Invalid SendKeyCode arguments")
            await self._async_raw_key(code)
            return {}
        fields = "".join(
            f"<{name}>{escape(str(value))}</{name}>"
            for name, value in (arguments or {}).items()
        )
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{SERVICE_TYPE}">'
            f'{fields}</u:{action}></s:Body></s:Envelope>'
        ).encode("utf-8")
        headers = {
            **NO_KEEPALIVE_HEADERS,
            "SOAPAction": f'"{SERVICE_TYPE}#{action}"',
            "Content-Type": 'text/xml; charset="utf-8"',
        }
        attempts = 2 if action in READ_ONLY_ACTIONS else 1
        for attempt in range(attempts):
            try:
                async with self.session.post(
                    self.control_url,
                    data=xml,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    data = await response.read()
                    if response.status != 200:
                        raise MetzError(
                            f"SOAP {action} returned HTTP {response.status}: "
                            f"{data[:300].decode(errors='replace')}"
                        )
                root = ET.fromstring(data)
                break
            except aiohttp.ClientConnectionError as err:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.2)
                    continue
                raise MetzConnectionError(f"SOAP {action} failed: {err}") from err
            except (aiohttp.ClientError, TimeoutError, ET.ParseError) as err:
                raise MetzError(f"SOAP {action} failed: {err}") from err
        body = root.find(f"{{{SOAP_NS}}}Body")
        if body is None:
            raise MetzError(f"SOAP {action} response has no Body")
        if body.find(f"{{{SOAP_NS}}}Fault") is not None:
            raise MetzError(f"SOAP {action} returned a Fault")
        result = next(iter(body), None)
        if result is None or result.tag.split("}")[-1] != f"{action}Response":
            raise MetzError(f"SOAP {action} response does not contain {action}Response")
        return {child.tag.split("}")[-1]: child.text or "" for child in result}

    async def _async_raw_key(self, code: int) -> None:
        """Send exactly one key using the known working metzctl wire format.

        Read only HTTP status line (not full SOAP body). This avoids an old TV
        disconnect during body parsing. Never retry: the key may have arrived.
        """
        url = urlsplit(self.control_url)
        host = url.hostname
        port = url.port or DEFAULT_PORT
        if url.scheme != "http" or not host or not url.path:
            raise MetzError("Invalid Metz control endpoint")
        path = url.path + (f"?{url.query}" if url.query else "")
        # Deliberately match the working metzctl payload, including whitespace.
        payload = f"""<?xml version="1.0" encoding="utf-8"?>
  <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
    <s:Body>
      <u:SendKeyCode xmlns:u="urn:metz.de:service:RCRService:1">
        <KeyCode>{code}</KeyCode>
        <DestinationDevice>0</DestinationDevice>
        <ButtonHold>0</ButtonHold>
      </u:SendKeyCode>
    </s:Body>
  </s:Envelope>""".encode("utf-8")
        headers = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f'SOAPAction: "{SERVICE_TYPE}#SendKeyCode"\r\n'
            'Content-Type: text/xml; charset="utf-8"\r\n'
            f"Content-Length: {len(payload)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")

        writer = None
        try:
            async def _send_once() -> bytes:
                nonlocal writer
                reader, writer = await asyncio.open_connection(host, port)
                writer.write(headers + payload)
                await writer.drain()
                return await reader.readline()

            status_line = await asyncio.wait_for(_send_once(), timeout=5)
            if not status_line:
                raise MetzError(
                    f"SOAP SendKeyCode({code}): disconnected before HTTP status; "
                    "key execution is unknown"
                )
            parts = status_line.decode("latin-1", errors="replace").split()
            if len(parts) < 2 or not parts[0].startswith("HTTP/"):
                raise MetzError(
                    f"SOAP SendKeyCode({code}): invalid HTTP status "
                    f"{status_line[:120]!r}"
                )
            if parts[1] != "200":
                raise MetzError(
                    f"SOAP SendKeyCode({code}): HTTP {parts[1]} "
                    "(key execution is unknown)"
                )
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
            raise MetzError(
                f"SOAP SendKeyCode({code}) transport failure: {err}; "
                "key execution is unknown"
            ) from err
        finally:
            if writer is not None:
                writer.close()
                # Ignore a late reset after the HTTP status was received.
                with suppress(OSError, TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), timeout=0.5)

    async def async_status(self) -> MetzStatus:
        """Read all status information the service exposes (no modifications)."""
        devices = await self.async_action("GetDeviceList")
        mode = await self.async_action("GetOperationMode")
        device_names = _parse_device_list(devices.get("DeviceList", ""))
        try:
            return MetzStatus(
                operation_mode=int(mode["OperationMode"]),
                active_device=int(devices["ActiveDevice"]),
                power_state=int(devices["PowerState"]),
                devices=device_names,
            )
        except (KeyError, ValueError) as err:
            raise MetzError(f"Invalid status response: {err}") from err

    async def _async_send_key_unlocked(self, code: int) -> None:
        """Send one key. The caller must hold the command lock."""
        await self.async_action("SendKeyCode", {
            "KeyCode": code, "DestinationDevice": 0, "ButtonHold": 0,
        })

    async def async_key(self, code: int) -> None:
        """Send an RCRService remote key, serialized with macro execution."""
        if not isinstance(code, int) or not 0 <= code <= 0xFFFFFFFF:
            raise MetzError("Key code must be an unsigned 32-bit integer")
        async with self._command_lock:
            await self._async_send_key_unlocked(code)

    async def _async_get_active_device_when_ready_unlocked(
        self,
        *,
        startup_wait_timeout: float,
        startup_retry_delay: float,
    ) -> int:
        """Wait for startup SOAP readiness and return ActiveDevice once available."""
        deadline = asyncio.get_running_loop().time() + startup_wait_timeout
        while True:
            try:
                response = await self.async_action("GetActiveDevice")
                return int(response["ActiveDevice"])
            except MetzConnectionError as err:
                if asyncio.get_running_loop().time() >= deadline:
                    raise MetzConnectionError(
                        "TV did not become ready for source selection before timeout"
                    ) from err
                await asyncio.sleep(startup_retry_delay)
            except (KeyError, ValueError) as err:
                raise MetzError("Cannot determine current TV source") from err

    async def _async_confirm_source_unlocked(
        self, source: str, expected_device: int
    ) -> None:
        """Confirm an active source after the caller's key sequence."""
        after = await self.async_action("GetActiveDevice")
        try:
            reported_active_device = int(after["ActiveDevice"])
        except (KeyError, ValueError) as err:
            raise MetzError("Cannot verify TV source after switching") from err
        devices = await self.async_action("GetDeviceList")
        try:
            listed_active_device = int(devices["ActiveDevice"])
        except (KeyError, ValueError) as err:
            raise MetzError("Cannot verify TV source after switching") from err
        if reported_active_device != expected_device:
            await self._async_send_key_unlocked(KEY_CODES["exit"])
            raise MetzError(
                f"{source} not confirmed: expected ActiveDevice="
                f"{expected_device}, GetActiveDevice={reported_active_device}, "
                f"GetDeviceList ActiveDevice={listed_active_device}"
            )

    async def async_select_tv_source(
        self,
        *,
        source_key_delay: float = 1.0,
        settle_delay: float = 3.0,
        startup_wait_timeout: float = 60.0,
        startup_retry_delay: float = 2.0,
    ) -> bool:
        """Select TV with Source -> OK once startup SOAP is ready."""
        expected_device = 0
        async with self._command_lock:
            active_device = await self._async_get_active_device_when_ready_unlocked(
                startup_wait_timeout=startup_wait_timeout,
                startup_retry_delay=startup_retry_delay,
            )
            if active_device == expected_device:
                return False
            await self._async_send_key_unlocked(KEY_CODES["source"])
            await asyncio.sleep(source_key_delay)
            await self._async_send_key_unlocked(KEY_CODES["ok"])
            await asyncio.sleep(settle_delay)
            await self._async_confirm_source_unlocked("TV", expected_device)
            return True

    async def async_select_f1_source(
        self,
        source: str,
        button_id: int,
        *,
        first_key_delay: float = 0.85,
        second_key_delay: float = 0.65,
        settle_delay: float = 3.0,
        startup_wait_timeout: float = 60.0,
        startup_retry_delay: float = 2.0,
    ) -> bool:
        """Select via F1 -> configured SOAP KeyCode -> numeric source key.

        After a three-second settle period, GetActiveDevice and GetDeviceList
        are read. The canonical ActiveDevice table, rather than DeviceList
        labels, is used for comparison. A partially delivered command is
        never retried automatically.
        """
        if source not in SOURCE_BUTTONS:
            raise MetzError(f"Unsupported source: {source!r}")
        if type(button_id) is not int or not 1 <= button_id <= 10:
            raise MetzError("F1 source-list button ID must be between 1 and 10")
        expected_device, button_number = SOURCE_BUTTONS[source]
        async with self._command_lock:
            active_device = await self._async_get_active_device_when_ready_unlocked(
                startup_wait_timeout=startup_wait_timeout,
                startup_retry_delay=startup_retry_delay,
            )
            if active_device == expected_device:
                return False
            # Metz APK: F1=12; digit_1=2, ..., digit_7=8.
            await self._async_send_key_unlocked(KEY_CODES["f1"])
            await asyncio.sleep(first_key_delay)
            await self._async_send_key_unlocked(button_id)
            await asyncio.sleep(second_key_delay)
            await self._async_send_key_unlocked(KEY_CODES[f"digit_{button_number}"])
            await asyncio.sleep(settle_delay)
            await self._async_confirm_source_unlocked(source, expected_device)
            return True
