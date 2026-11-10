# Metz Remote — Home Assistant custom integration

Version **0.3.10**: adds direct TV source selection with `Source -> OK` and ActiveDevice `0` verification.

Experimental Home Assistant custom integration for **Metz Remote**, package
version **0.3.10**, domain `metz_remote`.

The communication is local: the TV advertises `RCRService:1` SOAP on TCP 49200.
It was discovered and the basics were tested with an actual Metz TV; this
version's F1 source-button and active-device mappings have been confirmed by the user.

## v0.3.10 - TV source selection

The F1 source list uses these fixed visible button IDs:

| Button | Source      | Expected ActiveDevice |
| -----: | ----------- | --------------------: |
| Source -> OK | TV | `0x00` (0) |
|      1 | HDMI 1      |           `0x10` (16) |
|      2 | HDMI 2      |           `0x11` (17) |
|      3 | HDMI 3      |           `0x12` (18) |
|      4 | HDMI 4      |           `0x13` (19) |
|      5 | EURO        |                    22 |
|      6 | Cinch AV    |                    23 |
|      7 | Cinch Audio |                    54 |

`TV` is always available for source selection and uses `Source (49) -> OK
(39)`. The other seven sources require the configured F1 shortcut and use the
matching numeric button. Every macro waits three seconds, then reads
`GetActiveDevice` and `GetDeviceList`. It compares the reported active ID to
the fixed table above; `DeviceList` labels are not used for source comparison
or active-source reporting. On a mismatch, the integration sends **Exit** to
leave the source menu and reports the failure.


## v0.3.4 — Active source status

The `sensor` active-source state and the `media_player.source` property use
the canonical RCRService `ActiveDevice` table. `GetDeviceList` remains useful
for diagnostics and detected-source attributes, but its labels do not identify
the active source. Unknown IDs report `unknown`; raw IDs remain available as
sensor attributes.

**Protocol distinction:** The Android APK's
`StringHelper.getDeviceName()` actually returns the Android phone manufacturer
and model; the TV's RCRService has no `GetDeviceName` SOAP operation. For source
labels, `GetDeviceList` is therefore not used as the active-source lookup.

Source selection, saved configuration, entity IDs, branding and command mappings
are unchanged.

## Changes in 0.3.3

- Renamed the integration to **Metz Remote** in the manifest, setup labels, translations, and HACS metadata.
- Kept the integration domain `metz_remote` and the Home Assistant device name `TV`.
- No protocol, remote control or source-selection behavior changed.

## Previous fixes (0.3.2)

- The F1 source-selection configuration field accepts the **visible digit 0–9**
  (rather than the raw SOAP ID 1–10), converts it to the actual SOAP KeyCode
  when saving, and shows the corresponding digit for existing configurations.
- The Home Assistant **device name is now `TV`**; the model and integration
  name remain Metz Remote. New config-entry titles are also `TV`.
  Existing custom entry titles and manually renamed devices are not overwritten.
- The working commands and TV status reporting remain unchanged.

## Previous features (0.3.1)

- Removed the nonfunctional **Volume sensor**, including a targeted cleanup
  of the legacy `_volume` entity registry entry during sensor setup.
- Preserved the **Active source sensor**, based on `GetDeviceList` and
  `GetActiveDevice` every 15 seconds. The player also reports `source` even
  when source-selection commands are disabled.
- Added optional **F1 source-selection button (0–9)** at initial setup, SSDP
  confirmation and the integration's **Configure** (options) screen, alongside
  MAC address and Wake-on-LAN broadcast address. Options updates reload the
  integration automatically.
- The player always exposes `SELECT_SOURCE` for **TV**. When the F1 shortcut
  is configured, it additionally offers HDMI 1 through Cinch Audio.

### F1 source-selection sequence

TV transmits exactly two button commands:

1. `Source` — SOAP `SendKeyCode(49)`
2. `OK` — SOAP `SendKeyCode(39)`

The remaining sources transmit exactly three button commands:

1. `F1` — SOAP `SendKeyCode(12)`
2. **Configured F1 source-selection digit (0–9)** — the integration sends the
   corresponding SOAP key code (`digit + 1`) to open the source list after F1
3. Fixed numeric source button for the selected target

The configuration field accepts the **visible digit 0–9**, not its SOAP key code. Existing
v0.3.1 configurations remain compatible: the persisted setting is still the
SOAP key ID **1–10**, but the options dialog displays its digit (ID minus 1).
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
and restart Home Assistant. If you are upgrading from **0.3.0 or 0.3.1** (same domain),
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
