# Metz Remote — Home Assistant custom integration

Version **0.3.5**: F1 source selection uses the fixed Metz source-button mapping. No per-source configuration is required.

Experimental Home Assistant custom integration for **Metz Remote**, package
version **0.3.5**, domain `metz_remote`.

The communication is local: the TV advertises `RCRService:1` SOAP on TCP 49200.
It was discovered and the basics were tested with an actual Metz TV; this
version's F1 source-button mapping has been confirmed by the user.

## v0.3.5 - Fixed F1 source-button mapping

The F1 source list uses these fixed visible button IDs:

| Button | Source      | Expected ActiveDevice |
| -----: | ----------- | --------------------: |
|      1 | HDMI 1      |           `0x10` (16) |
|      2 | HDMI 2      |           `0x11` (17) |
|      3 | HDMI 3      |           `0x12` (18) |
|      4 | HDMI 4      |           `0x13` (19) |
|      5 | EURO        |           `0x14` (20) |
|      6 | Cinch AV    |           `0x15` (21) |
|      7 | Cinch Audio |           `0x16` (22) |

The integration sends the matching button for every source, waits three
seconds, then reads `GetActiveDevice` and `GetDeviceList`. The TV-reported
active device name must match the selected source.


## v0.3.4 — Active source uses the TV-reported name

The `sensor` active-source state and the `media_player.source` property
now consistently use the friendly name associated with the active device ID
in `GetDeviceList` (the name reported by the TV itself). This includes custom
input names when the TV actually returns them. Whitespace padding is removed;
unknown IDs or empty TV names report `unknown` instead of a fabricated
`Device <id>` label. Source IDs remain available as sensor attributes.

**Protocol distinction:** The Android APK's
`StringHelper.getDeviceName()` actually returns the Android phone manufacturer
and model; the TV's RCRService has no `GetDeviceName` SOAP operation. For source
labels, `GetDeviceList` is therefore the appropriate TV-provided lookup.

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
- **Only when configured:** the player exposes `SELECT_SOURCE` with all seven
  fixed targets: HDMI 1 through Cinch Audio (`0x10` through `0x16`).

### F1 source-selection sequence

The integration transmits exactly three button commands:

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
