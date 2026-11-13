# BConn — UX Specification

The GUI has one job: make the common case feel instant. Everything else is
secondary.

---

## 1. Design principles

1. **Tray is home.** The full window is for discovery and troubleshooting, not
   for daily use.
2. **One click, one verb.** A device row has exactly one primary action.
3. **State is visible at a glance.** Icon shape/color changes for off, ready,
   connected, scanning, and error.
4. **Errors are actionable.** Cause + fix + details, never a bare D-Bus string.
5. **No surprise connections.** Auto-reconnect only applies to devices the user
   explicitly chose. A manual disconnect is final.
6. **Quiet on success.** A notification is enough; do not steal focus.
7. **Works without a mouse.** Keyboard navigation and a full CLI.

---

## 2. Tray icon states

| State | Icon | Tooltip |
|---|---|---|
| Bluetooth off | grey glyph with slash | "Bluetooth is off" |
| Ready, no devices | blue outline | "Bluetooth ready" |
| Connected | solid blue + dot | "Buds — 82% · audio on" |
| Scanning | pulsing blue | "Scanning for devices…" |
| Attention | amber dot | "Bluetooth needs attention" |
| Error | red dot | "Last connection failed" |

Clicking the icon opens the menu. The **Scan for devices…** item opens the scan
window; there is no separate middle-click action. If the desktop has no
StatusNotifier host, BConn opens a normal window instead.

---

## 3. Tray menu

```text
┌────────────────────────────────────────────┐
│  Bluetooth                          On  ⏻ │
├────────────────────────────────────────────┤
│  ● WH-1000XM4            82%  🔊  ⏏       │
│  ● MX Keys                             ⏏  │
├────────────────────────────────────────────┤
│  Quick connect                          ▸  │
│    SoundCore Mini          last used 2d    │
│    Galaxy Buds             off             │
│    ThinkPad Mouse          off             │
├────────────────────────────────────────────┤
│  Scan for devices…                    ⌘S   │
│  Audio output                           ▸  │
│    Laptop speakers                         │
│    WH-1000XM4                    ✓         │
├────────────────────────────────────────────┤
│  System check…                             │
│  Preferences…                              │
│  Quit                                      │
└────────────────────────────────────────────┘
```

Behavior:

- Header toggles adapter power; the label reflects the real state.
- Connected rows show battery if available, an audio marker if it is the
  default sink, and a disconnect action.
- "Quick connect" lists favorites/known devices, most recently used first.
  Hovering shows "last used 2 days ago"; clicking connects immediately.
- While an operation runs, row actions are disabled and status refreshes when it
  finishes; successful routine actions do not steal focus.
- Errors add a compact banner at the top of the menu:
  `⚠ Could not connect … — details…`, which opens the full error dialog with
  the cause, hint, and copyable detail.

---

## 4. Scan window

```text
┌──────────────────────────────────────────────────────────────┐
│  Bluetooth                                      [Scanning ●] │
│                                                              │
│  [ All ] [ Audio ] [ Input ] [ Phone ]          🔍 Search     │
├──────────────────────────────────────────────────────────────┤
│  🎧  SoundCore Mini        ▂▄▆█   Paired      [ Connect ]    │
│  🎧  WH-1000XM4            ▂▄▆_   Connected   [Disconnect]   │
│  ⌨   MX Keys               ▂▄__   Trusted     [ Pair ]       │
│  📱  Pixel 8               ▂___   —           [ Pair ]       │
│  🎧  Buds Live             ▂▄▆_   Paired      [ Connect ]    │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  5 devices · hci0 · audio: A2DP · scan ends in 7s            │
└──────────────────────────────────────────────────────────────┘
```

### Row anatomy

```text
[device icon]  Name (alias if set)          [RSSI bars]
               MAC · type · last seen       [status chip] [action]
```

- **Name:** alias first, then BlueZ name, then MAC.
- **RSSI:** 4 bars; dimmed for stale results.
- **Status chip:** `Connected`, `Paired`, `Trusted`, `New`, `Blocked`.
- **Action:** one button; `Connect` → `Connecting…` (spinner) → `Disconnect`.
- **Secondary actions:** right-click a row (or activate its menu button):
  Details, Auto-connect toggle, Set alias, Forget.
- **Sorting:** connected first, then paired/favorites, then RSSI descending.
- **Filter tabs** apply immediately; the selection persists for the session and
  **All** is the default.
- **Search** matches name, alias, and MAC; Ctrl+F focuses it.

### Empty and edge states

- **No adapter:** full-panel message with "Check system" button.
- **Bluetooth off:** "Bluetooth is off" + Turn on button.
- **rfkill blocked:** "The radio is blocked" + copyable `rfkill unblock bluetooth`.
- **Scanning, no results:** "No devices found yet" + tips (put device in pairing
  mode, move closer) + timer.
- **Device bonded elsewhere:** row shows "Connection refused" with details link.

---

## 5. Pairing dialog

Only appears when the device requires it. Never blocks routine connections.

```text
┌──────────────────────────────────────────┐
│  Pair with WH-1000XM4                    │
│                                          │
│  Confirm this code on the device:        │
│                                          │
│              4 8 2 1 9 0                │
│                                          │
│  [ Reject ]                 [ Confirm ]  │
└──────────────────────────────────────────┘
```

- Passkey entry variant: 6-digit numeric field, auto-submit optional.
- PIN code variant: text field.
- A "Pairing…" state with a Cancel button and a 30-second progress hint.
- If the device rejects, show the device's reason if BlueZ provides one.

---

## 6. Error screen anatomy

Tray menu banner expands into:

```text
┌──────────────────────────────────────────────────────────┐
│  Could not connect to WH-1000XM4                         │
│                                                          │
│  The device refused authentication. It may still be      │
│  paired with your phone or another computer.             │
│                                                          │
│  [ Remove pairing on the other device ]  [ Retry ]       │
│                                                          │
│  ▸ Details                                               │
│    Stage: pair                                           │
│    BlueZ error: org.bluez.Error.AuthenticationFailed     │
│    Adapter: hci0 · Address: AA:BB:CC:DD:EE:FF            │
│    Attempt 2 of 3 · 14:32:07                             │
│    [ Copy details ]  [ Open log ]                        │
└──────────────────────────────────────────────────────────┘
```

Rules:

- Title = human cause, not the D-Bus error.
- Body = one or two sentences of likely cause.
- Primary action = the most likely fix; "Retry" secondary.
- Details are collapsed by default and copyable.

---

## 7. First run / system check

If anything is blocking, the tray icon turns amber and opening it shows:

```text
┌──────────────────────────────────────────────────┐
│  Bluetooth isn't ready                            │
│                                                   │
│  ✕ The Bluetooth service is not running.          │
│    Run this once, then click Re-check:            │
│    sudo systemctl enable --now bluetooth          │
│    [ Copy command ]                               │
│                                                   │
│  ! PipeWire is running, WirePlumber is running    │
│  ✓ Adapter hci0 found                             │
│                                                   │
│  [ Re-check ]   [ Open full system check ]        │
└──────────────────────────────────────────────────┘
```

The full system check is the same output as `bconn doctor`, grouped by layer
(System → Radio → Adapter → Audio → Desktop → App) with pass/warn/fail icons.

---

## 8. Preferences

Keep it short; defaults matter more than knobs.

```text
General
  [x] Enable auto-connect            (master switch)
  [x] Connect on startup
  [x] Show notifications
  [ ] Keep only one audio device connected

Devices
  WH-1000XM4     [x] Auto-connect   [x] Route audio   [Forget]
  MX Keys        [ ] Auto-connect                    [Forget]
  SoundCore      [ ] Auto-connect   [x] Route audio   [Forget]

Advanced
  Scan duration: [ 12 s ]
  Preferred adapter: [ hci0 ▾ ]
  [ Open log folder ]   [ Run system check ]
```

Auto-connect is **opt-in per device** and defaults off. The master switch
enables the feature; each device still needs its own checkbox. Do not expose
retry timings or D-Bus options in the UI.

---

## 9. Notifications

| Event | Text | Action |
|---|---|---|
| Connected | "Buds connected · 82%" | — |
| Disconnected (unexpected) | "Buds disconnected" | [Reconnect] |
| Connect failed | "Could not connect to Buds" | [Details] |
| Audio routed | "Audio → Buds" | — |
| Doctor failure | "Bluetooth needs attention" | [Fix] |

Use `Notify` with a low urgency for success and normal urgency for failures.
Never notify for auto-reconnect attempts that are still in progress.

---

## 10. CLI experience

The CLI is a first-class interface, not an afterthought.

```console
$ bconn list
ADAPTER  hci0  AA:BB:CC:11:22:33  powered  "Kali laptop"

DEVICE                              TYPE    STATE
WH-1000XM4  AA:BB:CC:DD:EE:FF       audio   connected · 82% · default sink
MX Keys     AA:BB:CC:DD:EE:01       input   paired · trusted
SoundCore   AA:BB:CC:DD:EE:02       audio   known · auto-connect off

$ bconn connect buds
Connecting to WH-1000XM4 (AA:BB:CC:DD:EE:FF)…
Paired ✓  Trusted ✓  Connected ✓  Audio → WH-1000XM4 ✓

$ bconn connect pixel
error: device is paired but authentication failed
hint: remove the pairing on the phone/other computer, then run:
      bconn pair pixel
```

Rules:

- Exit codes: 0 success, 1 operation failed, 2 usage error, 3 system not ready.
- `--json` for `list`, `scan`, and `doctor`.
- `--timeout N` for scan/connect.
- Name matching is case-insensitive substring; ambiguous names error with the
  list of candidates.
- Progress goes to stderr, results to stdout, so piping works.
- No interactive prompts unless stdin is a TTY; otherwise fail with guidance.

---

## 11. Interaction flows

### First pairing

```text
Tray → Scan… → device appears → click Pair
  → [pairing dialog if needed] → trust → connect
  → audio routed → notification → row shows Connected
```

### Daily use

```text
App menu → BConn → manager window (tray icon also appears)
Tray → click favorite → connected → notification (optional)
```

### Auto-reconnect

```text
boot/resume → adapter ready → connect opted-in devices serially
  → success: quiet notification, tray turns solid
  → failure: amber dot; details available, no modal, no loop
```

### Manual disconnect

```text
Tray → ⏏ → device disconnects → row becomes "off"
  → auto-connect disabled for that device until the user connects again
  → no notification unless the user asked for one
```

### Forget device

```text
Row "…" → Forget → confirm dialog ("This removes the pairing")
  → RemoveDevice → row disappears from known devices
```

### Service down

```text
Startup check fails → amber icon → menu shows "Bluetooth isn't ready"
  → copy command → user runs it → Re-check → normal state
```

---

## 12. Accessibility and keyboard

- Full keyboard navigation in the scan window; visible focus ring.
- Ctrl+F search, Enter primary action, Space toggle scan, Esc close.
- Status is never conveyed by color alone: icon shape + text chip.
- Minimum contrast 4.5:1; respect the GTK theme (no hardcoded dark colors).
- Screen-reader labels for icon-only buttons (`Connect WH-1000XM4`).
- No time-limited dialogs except pairing, where the timeout is shown.

---

## 13. Visual language

- Native GTK 3 widgets; inherit the XFCE theme and icon set.
- Device icons from the standard icon theme, with fallbacks:
  `audio-headphones`, `audio-speakers`, `input-keyboard`, `input-mouse`,
  `phone`, `computer`, `bluetooth`.
- Accent color only for state (blue = connected/ready, amber = attention,
  red = error). Everything else is neutral.
- Spacing: 8px grid; rows 48px tall; 12px window padding.
- Typography: system UI font; device name semibold, metadata small/dimmed.
- Motion: 150ms fades for state changes; no bouncing or pulsing except a subtle
  scanning indicator.

---

## 14. Microcopy rules

- Verbs match the action: "Connect", "Disconnect", "Pair", "Forget".
- Say what happened, then what to do: "The radio is blocked. Unblock it with…"
- Avoid "A2DP", "HFP", "GATT", "ObjectManager" in primary UI; keep them in
  details/logs.
- Never blame the user. "The device is paired to another computer" is better
  than "Authentication failed".
- Use the device's real name, not "device AA:BB:…", whenever known.
