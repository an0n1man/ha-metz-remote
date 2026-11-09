# Metz Remote APK: SendKeyCode mappings

Static reconstruction from `de.metz.android.mecaremote.apk` (17,633,145 bytes).

## Discovery

- The remote HTML uses `data-action` strings and the JavaScript bridge `Android.sendAction`.
- `RemoteControlFragment.handleRemoteAction` calls `ButtonLayout.getRCKeyForKey(action)` and `RemoteControlService.sendKey(context, code)`.
- `ButtonLayout.<clinit>` populates `rcViewMap` with 44 names mapped to numeric IDs.
- The old `keyToIcon` and `descriptionMap` add code 11 (`OffOn`), distinct from `Off`=51 on the HTML remote.
- Native `RcView.swipe()` additionally uses literal IDs 70 and 71.
- -1 in keyToIcon is a UI placeholder (`moreButtons`), not a sendKey command, and is excluded.

## Complete mapping

| ID | Hex | Action | Source |
|---:|---|---|---|
| 1 | 0x01 | `0` | HTML remote (rcViewMap) |
| 2 | 0x02 | `1` | HTML remote (rcViewMap) |
| 3 | 0x03 | `2` | HTML remote (rcViewMap) |
| 4 | 0x04 | `3` | HTML remote (rcViewMap) |
| 5 | 0x05 | `4` | HTML remote (rcViewMap) |
| 6 | 0x06 | `5` | HTML remote (rcViewMap) |
| 7 | 0x07 | `6` | HTML remote (rcViewMap) |
| 8 | 0x08 | `7` | HTML remote (rcViewMap) |
| 9 | 0x09 | `8` | HTML remote (rcViewMap) |
| 10 | 0x0A | `9` | HTML remote (rcViewMap) |
| 11 | 0x0B | `OffOn` | Legacy Android button layout (descriptionMap + keyToIcon) |
| 12 | 0x0C | `F1` | HTML remote (rcViewMap) |
| 13 | 0x0D | `F2` | HTML remote (rcViewMap) |
| 14 | 0x0E | `F3` | HTML remote (rcViewMap) |
| 18 | 0x12 | `Blue` | HTML remote (rcViewMap) |
| 19 | 0x13 | `Yellow` | HTML remote (rcViewMap) |
| 20 | 0x14 | `Portal` | HTML remote (rcViewMap) |
| 21 | 0x15 | `Green` | HTML remote (rcViewMap) |
| 22 | 0x16 | `Red` | HTML remote (rcViewMap) |
| 23 | 0x17 | `cursor_up` | HTML remote (rcViewMap) |
| 24 | 0x18 | `cursor_down` | HTML remote (rcViewMap) |
| 25 | 0x19 | `cursor_left` | HTML remote (rcViewMap) |
| 26 | 0x1A | `cursor_right` | HTML remote (rcViewMap) |
| 27 | 0x1B | `VolumeUp` | HTML remote (rcViewMap) |
| 28 | 0x1C | `VolumeDown` | HTML remote (rcViewMap) |
| 29 | 0x1D | `Help` | HTML remote (rcViewMap) |
| 30 | 0x1E | `Pip` | HTML remote (rcViewMap) |
| 33 | 0x21 | `Back` | HTML remote (rcViewMap) |
| 35 | 0x23 | `Mute` | HTML remote (rcViewMap) |
| 36 | 0x24 | `Text` | HTML remote (rcViewMap) |
| 37 | 0x25 | `Epg` | HTML remote (rcViewMap) |
| 38 | 0x26 | `Menu` | HTML remote (rcViewMap) |
| 39 | 0x27 | `OKNEW` | HTML remote (rcViewMap) |
| 40 | 0x28 | `Exit` | HTML remote (rcViewMap) |
| 41 | 0x29 | `Rewind` | HTML remote (rcViewMap) |
| 42 | 0x2A | `Forward` | HTML remote (rcViewMap) |
| 43 | 0x2B | `Play` | HTML remote (rcViewMap) |
| 44 | 0x2C | `Stop` | HTML remote (rcViewMap) |
| 45 | 0x2D | `Record_red` | HTML remote (rcViewMap) |
| 46 | 0x2E | `ChannelPlus` | HTML remote (rcViewMap) |
| 47 | 0x2F | `ChannelMinus` | HTML remote (rcViewMap) |
| 48 | 0x30 | `Home` | HTML remote (rcViewMap) |
| 49 | 0x31 | `Av` | HTML remote (rcViewMap) |
| 51 | 0x33 | `Off` | HTML remote (rcViewMap) |
| 66 | 0x42 | `Pause` | HTML remote (rcViewMap) |
| 70 | 0x46 | `swipe_70` | Legacy native remote swipe handler |
| 71 | 0x47 | `swipe_71` | Legacy native remote swipe handler |

## Important validation points

- `Off` = 51 is from the new HTML mapping; `OffOn` = 11 is from a legacy Android resource mapping. Sending them may produce different behavior on different TVs; test on your TV.
- Numeric digit 0 is 1, digits 1–9 are codes 2–10.
- Key 66 is `Pause`; do not substitute an assumed consecutive key code.
- `Av`/Source = 49, Up=23, Down=24, Left=25, Right=26, OK=39.
- Keys 70 and 71 are emitted in legacy `RcView.swipe()` but are not normal HTML buttons. Their precise user-facing names cannot be conclusively recovered from the method alone.
- This inventory covers distinct literal codes found in the APK remote mapping and sendKey call sites; it is not a specification of every code supported by the TV firmware.

## Verification methodology

The APK was read as a ZIP. Both Dalvik DEX files were inspected. Constant values were reconstructed from the static initializer of `de.metz.android.mecaremote.views.widgets.ButtonLayout` by interpreting DEX instructions that populate the maps. `R$string` and `R$drawable` resource identifiers were resolved from the DEX constant arrays, and all compiled call sites to `RemoteControlService.sendKey` and `MecaRemoteControl.sendKey` were inspected for other literal code values. The app was not executed.

