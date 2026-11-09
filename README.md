# Metz Remote — experimental Home Assistant custom integration

Version **0.2.6**. Prototype for the local Metz **RemoteControlReceiver:1** SOAP service, verified on a real Metz TV at TCP 49200. This is **not** a published HACS repository or a fully validated integration. No Android application, account or cloud required.

## Fix in v0.2.2 — `SOAP SendKeyCode failed: Server disconnected`

Key commands now use a dedicated, fresh asynchronous TCP connection and exactly
match the known working `metzctl` HTTP/1.1 wire protocol, including its SOAP
request formatting. The integration checks the HTTP **status line** and does not
wait for the complete response body, since the older Metz server may terminate
it abruptly. Status queries continue to use `aiohttp` with `Connection: close`.

**Do not retry failed key requests automatically:** if the server disconnects
before returning an HTTP status, the command may already have reached the TV.
The resulting error now says that key execution is unknown. HDMI 1 sequence
and source readback remain unchanged.

Updating from any prior version: replace `custom_components/metz_remote/`
and restart Home Assistant. The existing config entry is retained.

## Fix in v0.2.1 — "Server disconnected" at setup

The original client reused HTTP/1.1 connections from Home Assistant's shared
`aiohttp` session. Older Metz UPnP servers can close sockets between requests.
All requests now send `Connection: close`, matching the Android application's
fresh-TCP-per-command behavior. Read-only SOAP queries retry **once** on a
transport-level disconnection; `SendKeyCode` deliberately **does not retry**
to avoid applying a command twice. This is a protocol-level mitigation based
on the capture; it still requires verification on an actual HA installation.



## v0.2.4 — offline / standby-safe setup

Previously, the TV had to answer `GET /description.xml` and both status requests
**on every Home Assistant start**. This caused `ConfigEntryNotReady` for TVs that
stop listening on TCP 49200 in standby, even after an earlier successful setup.

For an **already configured and verified** TV (stored UPnP UDN), the integration
now registers its entities using the saved identity when a network error makes
`description.xml` temporarily unreachable. It uses the known fixed RCRService
control URL while offline, and the normal coordinator continues polling the TV
every 15 seconds. A failed initial poll no longer blocks loading the entities.
The `media_player` remains `unavailable` when the TV cannot be reached unless
a Wake-on-LAN MAC address was configured (then it appears `off` so turn-on can
be attempted; a network failure can also produce `off`). The `remote` remains
unavailable until polling succeeds.

**This does not repair a closed TCP port.** The TV's service must come back
online before ordinary remote commands or source selection can work. Confirm
port 49200 from the Home Assistant runtime while the TV is awake.

A newly configured TV still needs to respond on port 49200 once during its
first configuration, to verify its UPnP identity. The fallback is used only
for transport failures, not malformed XML or an unexpected device type.

## Branding fix in v0.2.5 (Home Assistant >= 2026.3)

Home Assistant supports **local brand images** for custom integrations placed in
`custom_components/metz_remote/brand/`. Previous packages incorrectly placed the
images at the integration root, where they do not register as integration branding.

The correct local files are:

- `brand/icon.png` (256 x 256) and `brand/icon@2x.png` (512 x 512)
- `brand/logo.png` (red logo for light UI) and `brand/logo@2x.png`
- `brand/dark_logo.png` (white logo for dark UI) and `brand/dark_logo@2x.png`

No `manifest.json` branding flag or Home Assistant brands-repository contribution
is required for Home Assistant 2026.3 or later. The repository-root logo files
are retained only for documentation; the new `brand/` folder is what Home Assistant
uses. The logo is derived from the supplied Metz asset.

**Update procedure:** Replace `custom_components/metz_remote/` fully with this
release and **restart Home Assistant**. Browser caches can delay showing the new
logo. You do not need to delete or re-add the existing integration.

Version 0.2.5 was a branding-only update; v0.2.6 adds configurable power
control while preserving all branding assets and the verified HDMI 1 macro.

## Power control and status (v0.2.6)

- **State:** Every 15 seconds, `GetDeviceList` returns `PowerState`. `0` was
  observed with the TV on; `1` is an unverified standby interpretation. `GetOperationMode`
  is also queried. Ping is **not** used to decide whether the TV is on: the
  network interface can remain active in standby.
- **On:** Sends a **Wake-on-LAN** UDP magic packet to the configured MAC on
  port 9. No TV power-toggle key is sent for ON. SOAP updates within 15 s once
  the TV starts responding. WOL must be enabled in the TV's own network settings.
- **Off:** Refreshes SOAP power state, then sends exactly one Metz
  `SendKeyCode(11)` only if TV positively reports `PowerState=0` (on). The key
  is a **toggle**, not a guaranteed off-only key, so ambiguous/unreachable
  state raises an error instead of risking accidental power-on.
- **Configurable WOL:** Use **Settings → Devices & services → Metz Remote →
  Configure** to add or edit the MAC address and broadcast target for an already
  configured TV. Options automatically reload the integration. The default
  `255.255.255.255` works on many host-networked systems; if Home Assistant
  is in a separate Docker subnet, try the LAN broadcast (e.g. `192.168.1.255`
  **only if the TV LAN really uses a /24 subnet**), provided the router allows it.

A TV that stops serving SOAP in standby is presented as `off` only if a WOL
MAC is configured. This is an *inference*: network outages can also look like
standby. Without a MAC, an unreachable TV is `unavailable`. The status
usually changes up to 15 seconds after a command.

Example:

```yaml
action: media_player.turn_on
target:
  entity_id: media_player.metz_tv  # Replace with your real entity ID
```

```yaml
action: media_player.turn_off
target:
  entity_id: media_player.metz_tv
```

## Updating from v0.2.0 (manual)

Replace the existing `/config/custom_components/metz_remote/` directory with the
`custom_components/metz_remote/` folder from this ZIP, then restart Home Assistant.
Do not add the integration again: the existing configuration entry and entity IDs
are retained. The TV must be reachable by Home Assistant over TCP 49200.

## Installation (manual)

1. Copy the directory `custom_components/metz_remote` into your Home Assistant configuration directory, e.g. `/config/custom_components/metz_remote/`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → Metz Remote**.
4. Enter the TV address (e.g. `192.168.1.131`) and optionally its MAC address for Wake-on-LAN. Enable **Metz Remote zulassen** on the TV.
5. The integration creates a `media_player` and a `remote` entity.

For HACS installation later, publish **this repository layout** to GitHub and add the repository as a HACS custom integration repository; a local ZIP by itself cannot be registered as a HACS repository.

## HDMI 1 source switching (verified on an actual Metz TV)

Use the native Home Assistant media player action:

```yaml
action: media_player.select_source
target:
  entity_id: media_player.metz_tv  # Use the actual entity ID
data:
  source: HDMI 1
```

The implementation sends `Source(49) → Down(24) → Down(24) → OK(39) → OK(39)`
using `1.0 s` after Source, `0.65 s` between remaining keys, and `1.0 s`
for the menu to settle. It **skips** the macro if the current input is already HDMI 1
and **verifies** that `GetActiveDevice` reports `16` afterward.

Only HDMI 1 is offered as a selectable source, since this is the only verified
switching macro. The currently active source and all detected physical inputs
remain readable; the other inputs are included in `detected_sources` as
informational attributes. Unverified inputs are deliberately not selectable.

## Working or documented commands

The `remote.send_command` action accepts `volume_up`, `volume_down`, `mute` (toggle), `channel_up`, `channel_down`, `ok`, `power` (toggle), `up`, `down`, `left`, `right`, `source`, and unsigned **decimal key-code strings** (such as `"27"`). Basic commands were taken from the [metzctl source](https://github.com/kaoh/metzctl/blob/master/metzctl/remote.py). Key `27` (`volume_up`) has been confirmed working on a real Metz TV. The source and direction keys were identified from PCAPdroid captures, and the complete HDMI 1 selection macro has been confirmed working on that TV. Remaining metzctl keys are not all tested here.

Example automation action:

```yaml
- action: remote.send_command
  target:
    entity_id: remote.metz_tv_remote  # replace with actual entity ID
  data:
    command:
      - volume_up
      - ok
    delay_secs: 0.4
```

The `media_player` provides volume steps, next/previous **channel** via next/previous track, power-off via toggle (if known ON), and optional power-on via Wake-on-LAN when a MAC address is configured.

## Known limitations

- Initial prototype, not tested running inside Home Assistant yet. The SOAP client and HDMI 1 macro have been tested against a local mock; this integration package has not been installed in a live Home Assistant instance.
- Only `PowerState=0` is established while a TV is on. The interpretation `1=off` is **tentative**. The service may become unreachable in standby: without a configured MAC address the entity becomes `unavailable`, with a configured MAC address the player displays `off` to keep Wake-on-LAN accessible (also possible during a network outage).
- No numeric volume, mute-state readback, channel program information or EPG from this SOAP service.
- Source switching supports **HDMI 1 only**, using the confirmed menu macro. Other inputs are read-only until their sequences are verified. This menu macro may be firmware-/menu-layout-dependent.
- `mute` and `power` are **toggles**, not idempotent on/off or mute/unmute functions. Thus media_player mute control is deliberately omitted.
- `ButtonHold` semantics are unverified; `hold_secs` values other than zero are rejected.
- The remote's `device` argument only accepts `tv`, not other UPnP device IDs. `DestinationDevice` is fixed at 0 as in metzctl.
- Wake-on-LAN depends on device/firmware, TV settings, and network broadcast routing. Not yet verified.
- No MECA-I / EPG functions yet.
- SSDP discovery is implemented but untested; manual IP works independently of multicast.
- Host changes may need integration reconfiguration/re-add if SSDP does not discover the new IP.

## Source references

- TV-provided `/description.xml`, `/services/rcr/RCRService.xml` service definition.
- [kaoh/metzctl](https://github.com/kaoh/metzctl), existing Metz key code mapping.
- [Home Assistant developer documentation](https://developers.home-assistant.io/docs/creating_integration_manifest/).

## Safety

Use only on your LAN. SOAP is unencrypted and the TV's RCRService appears unauthenticated, so do **not** forward port 49200 to the Internet. The configuration flow verifies the remote-control service but has no login.
