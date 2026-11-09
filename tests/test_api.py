"""Integration's SOAP client tests; run with pytest (no HA installation needed)."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from xml.etree import ElementTree as ET

import aiohttp
from aiohttp import web
import pytest

# Import the standalone API module without importing Home Assistant's integration.
COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "metz_remote"
pkg = types.ModuleType("metz_remote")
pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules.setdefault("metz_remote", pkg)
from metz_remote.api import MetzClient, MetzError, MetzConnectionError  # noqa: E402

NS = "urn:metz.de:service:RCRService:1"
SOAP = "http://schemas.xmlsoap.org/soap/envelope/"


def xml_response(action: str, values: dict[str, str]) -> str:
    args = "".join(f"<{k}>{v}</{k}>" for k, v in values.items())
    return (f'<s:Envelope xmlns:s="{SOAP}"><s:Body>'
            f'<u:{action}Response xmlns:u="{NS}">{args}</u:{action}Response>'
            f'</s:Body></s:Envelope>')


def test_read_status_and_send_key() -> None:
    async def check():
        actions = []
        async def handler(req):
            payload = ET.fromstring(await req.read())
            method = next(iter(payload.find(f"{{{SOAP}}}Body")))
            action = method.tag.split("}")[-1]
            args = {c.tag: c.text for c in method}
            actions.append((action, args, req.headers.get("SOAPAction")))
            if action == "GetDeviceList":
                data = {"DeviceList": "0x00;Metz-TV;0x10;HDMI 1;0x11;HDMI 2;",
                        "ActiveDevice": "16", "PowerState": "0"}
            elif action == "GetOperationMode":
                data = {"OperationMode": "1"}
            else:
                data = {}
            return web.Response(text=xml_response(action, data), content_type="text/xml")

        app = web.Application()
        app.router.add_post("/services/rcr/control/RCRService", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.control_url = f"http://127.0.0.1:{port}/services/rcr/control/RCRService"
                status = await api.async_status()
                assert status.operation_mode == 1
                assert status.power_state == 0
                assert status.active_device == 16
                assert status.source_name == "HDMI 1"
                await api.async_key(27)
                assert actions[-1] == (
                    "SendKeyCode",
                    {"KeyCode": "27", "DestinationDevice": "0", "ButtonHold": "0"},
                    f'"{NS}#SendKeyCode"',
                )
                with pytest.raises(MetzError):
                    await api.async_key(-1)
                with pytest.raises(MetzError):
                    await api.async_key(2**32)
        finally:
            await runner.cleanup()
    asyncio.run(check())


def test_device_description() -> None:
    async def check():
        async def handler(req):
            return web.Response(text='''<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
<deviceType>urn:metz.de:device:RemoteControlReceiver:1</deviceType>
<friendlyName>Metz-TV</friendlyName><UDN>uuid:test-123</UDN>
<serviceList><service>
<serviceType>urn:metz.de:service:RCRService:1</serviceType>
<controlURL>/services/rcr/control/RCRService</controlURL>
</service></serviceList></device></root>''', content_type="text/xml")
        app = web.Application()
        app.router.add_get("/description.xml", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.base_url = f"http://127.0.0.1:{port}"
                desc = await api.async_description()
                assert desc.udn == "uuid:test-123"
                assert desc.name == "Metz-TV"
                assert desc.control_url.endswith("/services/rcr/control/RCRService")
        finally:
            await runner.cleanup()
    asyncio.run(check())


def test_f1_source_macro_all_seven_inputs() -> None:
    """For each source, send F1 → configured key → corresponding digit and verify."""
    from metz_remote.const import SOURCE_BUTTONS

    async def check():
        for source, (target, number) in SOURCE_BUTTONS.items():
            active = 0
            sent = []
            calls = []

            async def handler(req):
                nonlocal active
                payload = ET.fromstring(await req.read())
                method = next(iter(payload.find(f"{{{SOAP}}}Body")))
                action = method.tag.split("}")[-1]
                calls.append(action)
                args = {child.tag: child.text for child in method}
                if action == "SendKeyCode":
                    sent.append(args)
                    if len(sent) == 3:
                        active = target
                    values = {}
                elif action == "GetActiveDevice":
                    values = {"ActiveDevice": str(active)}
                else:
                    return web.Response(status=500)
                return web.Response(text=xml_response(action, values), content_type="text/xml")

            app = web.Application()
            app.router.add_post("/services/rcr/control/RCRService", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            try:
                async with aiohttp.ClientSession() as session:
                    api = MetzClient(session, "127.0.0.1")
                    api.control_url = f"http://127.0.0.1:{port}/services/rcr/control/RCRService"
                    assert await api.async_select_f1_source(
                        source, 5, first_key_delay=0,
                        second_key_delay=0, settle_delay=0,
                    ) is True
                    assert [int(cmd["KeyCode"]) for cmd in sent] == [12, 5, number + 1]
                    assert all(cmd["DestinationDevice"] == "0" for cmd in sent)
                    assert all(cmd["ButtonHold"] == "0" for cmd in sent)
                    assert calls == ["GetActiveDevice", "SendKeyCode", "SendKeyCode", "SendKeyCode", "GetActiveDevice"]
                    assert await api.async_select_f1_source(
                        source, 5, first_key_delay=0,
                        second_key_delay=0, settle_delay=0,
                    ) is False
                    assert len(sent) == 3
            finally:
                await runner.cleanup()

    asyncio.run(check())


def test_f1_source_macro_rejects_unknown_and_mismatching_readback() -> None:
    async def check():
        async def handler(req):
            payload = ET.fromstring(await req.read())
            method = next(iter(payload.find(f"{{{SOAP}}}Body")))
            action = method.tag.split("}")[-1]
            values = {"ActiveDevice": "17"} if action == "GetActiveDevice" else {}
            return web.Response(text=xml_response(action, values), content_type="text/xml")

        app = web.Application()
        app.router.add_post("/services/rcr/control/RCRService", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.control_url = f"http://127.0.0.1:{port}/services/rcr/control/RCRService"
                with pytest.raises(MetzError, match="HDMI 1 not confirmed"):
                    await api.async_select_f1_source("HDMI 1", 5, first_key_delay=0,
                                                     second_key_delay=0, settle_delay=0)
                for invalid in (None, 0, 11, True, -1):
                    with pytest.raises(MetzError, match="button ID"):
                        await api.async_select_f1_source("HDMI 1", invalid)
                with pytest.raises(MetzError, match="Unsupported source"):
                    await api.async_select_f1_source("TV", 5)
        finally:
            await runner.cleanup()

    asyncio.run(check())

def test_verified_direction_and_source_codes() -> None:
    from metz_remote.const import KEY_CODES, SOURCE_BUTTONS
    assert [KEY_CODES[k] for k in ("up", "left", "right", "down")] == [23, 25, 26, 24]
    assert KEY_CODES["source"] == 49
    assert SOURCE_BUTTONS["HDMI 1"] == (16, 1)
    assert SOURCE_BUTTONS["Cinch Audio"] == (22, 7)


def test_separate_tcp_connection_for_each_soap_request() -> None:
    """Metz's UPnP daemon must not receive keep-alive requests."""
    async def check():
        remote_ports = []
        connection_headers = []

        async def handler(req):
            remote_ports.append(req.transport.get_extra_info("peername")[1])
            connection_headers.append(req.headers.get("Connection"))
            payload = ET.fromstring(await req.read())
            action = next(iter(payload.find(f"{{{SOAP}}}Body"))).tag.split("}")[-1]
            return web.Response(
                text=xml_response(action, {"OperationMode": "1"}),
                content_type="text/xml",
            )

        app = web.Application()
        app.router.add_post("/services/rcr/control/RCRService", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.control_url = f"http://127.0.0.1:{port}/services/rcr/control/RCRService"
                for _ in range(3):
                    assert await api.async_action("GetOperationMode") == {"OperationMode": "1"}
            assert connection_headers == ["close"] * 3
            assert len(set(remote_ports)) == 3, "Each command requires a new TCP connection"
        finally:
            await runner.cleanup()

    asyncio.run(check())


def test_read_only_retry_but_never_replay_keypress() -> None:
    """Connection failures are retried only for safe read-only requests."""
    async def check():
        attempts = {"GetOperationMode": 0, "SendKeyCode": 0}

        async def handler(req):
            payload = ET.fromstring(await req.read())
            action = next(iter(payload.find(f"{{{SOAP}}}Body"))).tag.split("}")[-1]
            attempts[action] += 1
            if action == "SendKeyCode" or attempts[action] == 1:
                # Mimic a UPnP server dropping the connection without a response.
                req.transport.close()
                raise ConnectionResetError("Simulated legacy UPnP disconnection")
            return web.Response(
                text=xml_response(action, {"OperationMode": "1"}),
                content_type="text/xml",
            )

        app = web.Application()
        app.router.add_post("/services/rcr/control/RCRService", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.control_url = f"http://127.0.0.1:{port}/services/rcr/control/RCRService"
                assert await api.async_action("GetOperationMode") == {"OperationMode": "1"}
                with pytest.raises(MetzError, match=r"SOAP SendKeyCode\(27\): disconnected before HTTP status"):
                    await api.async_key(27)
            assert attempts == {"GetOperationMode": 2, "SendKeyCode": 1}
        finally:
            await runner.cleanup()

    asyncio.run(check())


def test_raw_sendkeycode_wire_format_and_status_only() -> None:
    """A status line alone counts as success; don't wait for a SOAP body."""
    async def check():
        requests = []

        async def handle(reader, writer):
            try:
                header = await reader.readuntil(b"\r\n\r\n")
                content_len = int(next(
                    line.split(b":", 1)[1].strip()
                    for line in header.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                ))
                body = await reader.readexactly(content_len)
                requests.append(header + body)
                # Legacy server terminates after status before any HTTP headers/body.
                writer.write(b"HTTP/1.1 200 OK\r\n")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.control_url = f"http://127.0.0.1:{port}/services/rcr/control/RCRService"
                for code in (49, 24, 39):
                    await api.async_key(code)
            assert len(requests) == 3
            for raw, code in zip(requests, (49, 24, 39)):
                head, payload = raw.split(b"\r\n\r\n", 1)
                assert head.startswith(b"POST /services/rcr/control/RCRService HTTP/1.1\r\n")
                assert b"Connection: close" in head
                assert b"User-Agent:" not in head
                assert b'Content-Type: text/xml; charset="utf-8"' in head
                assert f"<KeyCode>{code}</KeyCode>".encode() in payload
                assert b"<DestinationDevice>0</DestinationDevice>" in payload
                assert b"<ButtonHold>0</ButtonHold>" in payload
                assert b"\n    <s:Body>\n" in payload
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(check())


def test_unreachable_description_is_offline_error() -> None:
    """A refused connection, such as when a TV goes to standby, is explicit."""
    async def check():
        import socket
        # Find a local port that is not listening.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            unused_port = sock.getsockname()[1]
        async with aiohttp.ClientSession() as session:
            api = MetzClient(session, "127.0.0.1")
            api.base_url = f"http://127.0.0.1:{unused_port}"
            with pytest.raises(MetzConnectionError, match="Cannot read device description"):
                await api.async_description()
    asyncio.run(check())


def test_bad_description_is_not_offline_error() -> None:
    """An invalid service description must not be treated as TV standby."""
    async def check():
        async def handler(req):
            return web.Response(text="not valid XML", content_type="text/plain")
        app = web.Application()
        app.router.add_get("/description.xml", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as session:
                api = MetzClient(session, "127.0.0.1")
                api.base_url = f"http://127.0.0.1:{port}"
                with pytest.raises(MetzError, match="Invalid UPnP device description") as exc:
                    await api.async_description()
                assert not isinstance(exc.value, MetzConnectionError)
        finally:
            await runner.cleanup()
    asyncio.run(check())


def test_device_name_lookup_uses_tv_labels_not_hardcoded_ids():
    from metz_remote.api import MetzStatus

    status = MetzStatus(
        operation_mode=1, power_state=0, active_device=16,
        devices={0: " TV-Tuner ", 16: " Blu-ray-Player ", 17: "Wohnzimmer-Konsole"},
    )
    assert status.get_device_name(16) == "Blu-ray-Player"
    assert status.source_name == "Blu-ray-Player"
    assert status.get_device_name(17) == "Wohnzimmer-Konsole"
    assert status.get_device_name(0) == "TV-Tuner"
    assert status.get_device_name(19) is None
    assert MetzStatus(1, 0, 19, status.devices).source_name is None
    assert MetzStatus(1, 0, 16, {16: "   "}).source_name is None
