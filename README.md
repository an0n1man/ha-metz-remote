# Metz Remote — Home Assistant custom integration

Experimental Home Assistant custom integration for **Metz Remote**, package
version **0.3.1**, domain `metz_remote`.

The communication is local: the TV advertises `RCRService:1` SOAP on TCP 49200.
It was discovered and the basics were tested with an actual Metz TV; this
version's **new** F1 source-list workflow has not yet been validated on that TV.

## New in 0.3.1

- Removed the nonfunctional **Volume sensor**, including a targeted cleanup
  of the legacy `_volume` entity registry entry during sensor setup.
- Preserved the **Active source sensor**, based on `GetDeviceList` and
  `GetActiveDevice` every 15 seconds. The player also reports `source` even
  when source-selection commands are disabled.
- Added optional **F1 source-selection button ID** at initial setup, SSDP
  confirmation and the integration's **Configure** (options) screen, alongside
  MAC address and Wake-on-LAN broadcast address. Options updates reload the
  integration automatically.
- **Only when configured:** the player exposes the `SELECT_SOURCE` feature
  and this list of seven targets:

| Source | Source menu digit | SOAP digit KeyCode | Expected ActiveDevice |
|---|---:|---:|---:|
| HDMI 1 | 1 | 2 | `0x10` (16) |
| HDMI 2 | 2 | 3 | `0x11` (17) |
| HDMI 3 | 3 | 4 | `0x12` (18) |
| HDMI 4 | 4 | 5 | `0x13` (19) |
| EURO | 5 | 6 | `0x14` (20) |
| Cinch AV | 6 | 7 | `0x15` (21) |
| Cinch Audio | 7 | 8 | `0x16` (22) |

### F1 source-selection sequence

The integration transmits exactly three button commands:

1. `F1` — SOAP `SendKeyCode(12)`
2. **Configured F1 source-selection button ID** — raw SOAP key code that
   opens the TV's source list after F1
3. Numeric source button — e.g., HDMI 2 means `digit_2` = `SendKeyCode(3)`

The configurable ID is a raw **SOAP key code**, not the printed number on the
remote. Allowed codes **1–10** correspond to digits **0–9**, respectively.
Example: the digit **4** is SOAP key ID **5**. Leave the setting empty to
hide all source selections.

The TV's active source is read before sending any commands. If already
selected, the macro is skipped. Otherwise the integration holds its command
lock for the full sequence, uses short delays, and verifies the final
`GetActiveDevice` response. Failed/ambiguous key transmissions are never
retried automatically, to avoid duplicate actions.

The older HDMI 1 five-key menu macro is removed: no source switching is
advertised until the F1 button ID is configured.

## Install / upgrade

Copy `custom_components/metz_remote/` into HA's `/config/custom_components/`
and restart Home Assistant. If you are upgrading from **0.3.0** (same domain),
you do **not** need to remove or re-add the integration. Open **Settings →
Devices & services → Metz Remote → Configure** to enter the F1 button ID.

If you previously installed the much older `metz_classic` domain instead,
remove that integration separately, and configure `metz_remote` as a new one.

## Power and remote

- Turn on: optional Wake-on-LAN using the configured MAC/broadcast.
- Turn off: guarded SOAP power **toggle** (`11`) only when a fresh SOAP state
  poll confirms the TV is on. APK key `51` has not been verified as off-only.
- State: SOAP `PowerState` and `GetDeviceList`, normally polled every 15 s;
  ICMP ping is *not* used as an on/off indicator.
- Remote: `remote.send_command` exposes the APK-mapped keys (`f1`, `menu`,
  `epg`, `digit_0` ... `digit_9`, arrows, playback, etc.), including raw decimal
  key IDs. Each request uses a fresh TCP connection modeled on `metzctl`.

Example source change after configuration:

```yaml
action: media_player.select_source
target:
  entity_id: media_player.metz_tv
data:
  source: HDMI 2
```

The entity ID is illustrative; use the actual ID created by Home Assistant.

## Scope and known limitations

- No real volume-level readback. The old unknown-only volume entity is gone;
  Volume +/- buttons still work.
- The newly configured F1 shortcut sequence is based on the TV menu layout
  described by the user; test on the real TV before relying on automations.
- The selected input is always confirmed by SOAP, not assumed from keypresses.
- The TV's UPnP RCRService is unencrypted; do not expose TCP 49200 to WAN.
- Local branding files are in `custom_components/metz_remote/brand/`.
- The package is suitable for manual installation; to install through HACS,
  publish this folder layout in a GitHub repository and register it in HACS.

### References

- Metz-provided `/description.xml` and `RCRService.xml`
- APK-derived mappings under `docs/`
- [metzctl](https://github.com/kaoh/metzctl)
- [Home Assistant options flow](https://contributors.home-assistant.io/core/integrations/options-flow/)
