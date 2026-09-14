# mobile-mcp

**Complete A-to-Z Guide: Cross-Platform Android & iOS Device Automation for AI Agents**

`mobile-mcp` is a unified Model Context Protocol (MCP) server that empowers AI agents to inspect, control, and automate both **Android** and **iOS** devices. Built with Python, [uv](https://github.com/astral-sh/uv), and the official `mcp` SDK, it operates using **100% official first-party tooling** without requiring unstable third-party daemons (no Appium, WebDriverAgent, or `pymobiledevice3`).

- **Android Engine**: Backed by Android Studio's `adb` and the official [`android` CLI](https://developer.android.com/tools/agents/android-cli) for accessibility layout hierarchy, high-speed input events, APK management, emulators, and filesystem access.
- **iOS Engine**: Backed by Apple's `xcrun simctl` for iOS Simulators, `xcrun devicectl` (Xcode 15+ CoreDevice) for physical iOS devices, and macOS native Quartz CoreGraphics (`ctypes`) + AppleScript for pixel-accurate Simulator gestures and hardware keys.

Works out-of-the-box with any MCP-compliant client: **Claude Code**, **Claude Desktop**, **Cursor**, **VS Code (GitHub Copilot)**, **Windsurf (Cascade)**, **Cline**, **Roo Code**, **Codex CLI**, **Gemini CLI**, **opencode**, and custom agent frameworks over stdio.

---

## Table of Contents

1. [Architecture & How It Works](#architecture--how-it-works)
2. [Prerequisites & System Setup](#prerequisites--system-setup)
   - [Android Prerequisites](#android-prerequisites)
   - [iOS Prerequisites](#ios-prerequisites)
3. [Installation & Client Configuration](#installation--client-configuration)
   - [Claude Code](#claude-code)
   - [Claude Desktop](#claude-desktop)
   - [Cursor / VS Code](#cursor--vs-code)
4. [Unified Diagnostics & Device Discovery](#unified-diagnostics--device-discovery)
5. [Android Tool Reference (30 Tools)](#android-tool-reference)
6. [iOS Tool Reference (26 Tools)](#ios-tool-reference)
   - [Simulator Lifecycle](#simulator-lifecycle)
   - [Simulator UI & Gesture Automation](#simulator-ui--gesture-automation)
   - [App Lifecycle & Deep Links](#app-lifecycle--deep-links)
   - [Environment, Permissions & Simulation](#environment-permissions--simulation)
   - [Physical iOS Hardware Management (devicectl)](#physical-ios-hardware-management-devicectl)
7. [Cross-Platform Automation Recipes](#cross-platform-automation-recipes)
8. [Security Architecture & Configuration](#security-architecture--configuration)
9. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## Architecture & How It Works

### Unified Dual-Engine Design

`mobile-mcp` exposes 81 typed tools on a single server endpoint (`mobile-mcp`). Agents can interact with Android and iOS seamlessly in the same workflow.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              AI Agent / LLM                             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ JSON-RPC (MCP Protocol / stdio)
┌────────────────────────────────────▼────────────────────────────────────┐
│                       mobile-mcp Server (main.py)                       │
│    Unified health_check & list_all_devices • 81 Protocol-Compliant Tools│
└──────────────────┬──────────────────────────────────┬───────────────────┘
                   │                                  │
         === Android Engine ===              === iOS Engine ===
                   │                                  │
         ┌─────────┴─────────┐              ┌─────────┴─────────┐
         ▼                   ▼              ▼                   ▼
  ┌──────────────┐    ┌──────────────┐┌──────────────┐   ┌──────────────┐
  │  android CLI │    │   adb Engine ││ xcrun simctl │   │xcrun devicectl
  │  (Layout/OCR)│    │(Touch/Shell) ││ (Simulators) │   │ (Real Devices)
  └──────────────┘    └──────────────┘└──────┬───────┘   └──────────────┘
                                             ▼
                                     ┌───────────────┐
                                     │ Quartz/macOS  │
                                     │ (Touch/Keys)  │
                                     └───────────────┘
```

---

## Prerequisites & System Setup

### Android Prerequisites

1. **Android SDK Platform-Tools (`adb`)**:
   Installed via Android Studio at `~/Library/Android/sdk/platform-tools/adb` (macOS) or in your system `PATH`.
2. **Physical Device or Android Emulator**:
   - **Real Device**: Enable Developer Options -> USB Debugging. Tap "Allow" on the RSA authorization prompt.
   - **Emulator**: Created via Android Studio AVD Manager, or launched using `emulator_start`.
3. **Optional `android` CLI**:
   Recommended for structured accessibility trees (`get_layout`) and delta APK installs.

### iOS Prerequisites

1. **macOS with Xcode 15+ installed**:
   Ensure active developer directory is set to Xcode:
   ```bash
   sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
   ```
2. **First-Party Tools Included with Xcode**:
   - `xcrun simctl` (built-in Simulator management).
   - `xcrun devicectl` (built-in CoreDevice physical hardware management).
3. **macOS Accessibility Permission (for Simulator UI gestures)**:
   Simulator touch injection uses native Quartz CoreGraphics mouse events and AppleScript keystrokes. When prompted, grant your terminal/IDE Accessibility access in `System Settings > Privacy & Security > Accessibility`.

---

## Installation & Client Configuration

### Claude Code

Install directly via the marketplace catalog:

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install mobile-mcp@claude-marketplace
```

Or add locally:

```bash
claude mcp add mobile-mcp -s user -- uv run --project /path/to/claude-marketplace/plugins/mobile-mcp main.py
```

Or standalone without a clone, pinned to `v0.2.0` (recommended — reproducible;
drop `@v0.2.0` to track `main`):

```bash
claude mcp add mobile-mcp -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace@v0.2.0#subdirectory=plugins/mobile-mcp" mobile-mcp
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mobile-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/claude-marketplace/plugins/mobile-mcp",
        "main.py"
      ]
    }
  }
}
```

### Cursor / VS Code

In `.cursor/mcp.json` or `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "mobile-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/path/to/claude-marketplace/plugins/mobile-mcp",
        "main.py"
      ]
    }
  }
}
```

---

## Unified Diagnostics & Device Discovery

### `health_check`
Validates both Android (ADB, android CLI, SDK root) and iOS (Xcode, simctl, devicectl) toolchains in one invocation:
```json
// Tool: health_check
{}
```
*Returns:*
```
=== Android Environment ===
adb: Android Debug Bridge version 1.0.41 (/Users/username/Library/Android/sdk/platform-tools/adb)
android CLI: 1.0.16261425
sdk: /Users/username/Library/Android/sdk
devices: 1
  - emulator-5554 [device] model:sdk_gphone64_arm64

=== iOS Environment ===
Developer Dir: /Applications/Xcode.app/Contents/Developer
Xcode Version: Xcode 16.0, Build version 16A242d
simctl: Available
devicectl: Available
Booted Simulators: 1
  - iPhone 16 Pro (iOS-18-0): 07519AD6-CDA5-4416-AA66-DFDBB37740A5
Physical Devices: 0
```

### `list_all_devices`
Lists all connected Android phones, active emulators, booted iOS simulators, and attached physical iOS devices in one call.

---

## Android Tool Reference

| Tool | Purpose | Primary Parameters |
|---|---|---|
| `list_devices` | List connected Android phones & emulators | — |
| `device_info` | Model, manufacturer, Android OS version, SDK level | `serial` |
| `get_screen_size` | Physical screen resolution (e.g. 1080x2400) | `serial` |
| `get_layout` | **Cheap structured accessibility tree** (buttons, text, bounds) | `serial` |
| `take_screenshot` | High-res PNG capture (inline image for visual inspection) | `serial`, `save_to` |
| `tap` | Tap coordinate `(x, y)` | `x`, `y`, `serial` |
| `tap_element` | OCR/accessibility selector tap (e.g. `input tap #2`) | `selector`, `screenshot_path` |
| `double_tap` | Double tap coordinate | `x`, `y`, `serial` |
| `long_press` | Press and hold coordinate | `x`, `y`, `duration_ms`, `serial` |
| `swipe` | Gesture vector `(x1, y1) -> (x2, y2)` | `x1`, `y1`, `x2`, `y2`, `duration_ms` |
| `scroll` | Relative swipe vector | `dx`, `dy`, `duration_ms` |
| `input_text` | Enter text into focused field | `text`, `serial` |
| `clear_text` | Clear characters from field | `count`, `serial` |
| `press_key` | Hardware key (`KEYCODE_BACK`, `KEYCODE_HOME`, etc.) | `key`, `serial` |
| `open_app` | Launch app by package name | `package`, `serial` |
| `launch_app` | Launch specific activity | `package`, `activity`, `serial` |
| `stop_app` | Force stop package | `package`, `serial` |
| `list_installed_apps` | List third-party or system packages | `third_party_only`, `filter_text` |
| `install_apk` | Install single or split APK files | `apk_path`, `serial` |
| `uninstall_app` | Uninstall package | `package`, `serial` |
| `open_url` | Dispatch `android.intent.action.VIEW` deep link | `url`, `serial` |
| `wake_screen` | Wake screen and dismiss keyguard | `serial` |
| `open_notification_panel` | Expand notifications shade | `serial` |
| `open_quick_settings` | Expand quick toggles shade | `serial` |
| `press_back` / `press_home` / `press_recents` | Standard navigation keys | `serial` |
| `press_power` / `press_volume_up` / `press_volume_down` | Physical buttons | `serial` |
| `emulator_list` / `emulator_start` | Manage local Android Virtual Devices | `name`, `wipe_data`, `headless` |
| `file_push` / `file_pull` / `file_list` / `file_delete` | Safe device filesystem operations | `remote_path`, `local_path` |
| `run_shell` | Escape hatch shell (opt-in whitelist protected) | `command`, `args`, `serial` |

---

## iOS Tool Reference

### Simulator Lifecycle

| Tool | Purpose | Parameters |
|---|---|---|
| `ios_list_simulators` | List all available runtimes and simulators | `filter_runtime`, `filter_state` |
| `ios_boot_simulator` | Boot simulator by UDID or name (optionally launches Simulator.app) | `udid`, `show_gui` |
| `ios_shutdown_simulator` | Graceful shutdown of simulator | `udid` (optional if 1 booted) |
| `ios_erase_simulator` | Factory reset / wipe simulator | `udid` |

### Simulator UI & Gesture Automation

| Tool | Purpose | Parameters |
|---|---|---|
| `ios_get_layout` | **Cheap structured text tree**: extracts on-screen text, bounding boxes, and tap centers via Apple Vision framework (zero vision tokens) | `udid` |
| `ios_tap_element` | Tap on-screen element by index (e.g. `#1`, `1`) or text (e.g. `Settings`) | `selector`, `udid` |
| `ios_screenshot` | Pixel-perfect headless PNG capture (returns inline image for visual inspection) | `udid`, `save_to` |
| `ios_tap` | Tap screen coordinates `(x, y)` via Quartz CoreGraphics | `x`, `y`, `udid` |
| `ios_swipe` | Drag gesture `(x1, y1) -> (x2, y2)` with duration | `x1`, `y1`, `x2`, `y2`, `duration_ms` |
| `ios_input_text` | Paste text into focused field via pasteboard + `Cmd+V` | `text`, `udid` |
| `ios_press_button` | Hardware buttons (`home`, `lock`, `app_switcher`, `shake`, `volume_up`, `volume_down`, `rotate_left`, `rotate_right`) | `button`, `udid` |

### App Lifecycle & Deep Links

| Tool | Purpose | Parameters |
|---|---|---|
| `ios_launch_app` | Launch app by bundle ID (Simulator or physical device) | `bundle_id`, `args`, `udid`, `device_type` |
| `ios_terminate_app` | Terminate running app process | `bundle_id`, `udid`, `device_type` |
| `ios_install_app` | Install `.app` (Simulator) or `.ipa`/`.app` (device) | `app_path`, `udid`, `device_type` |
| `ios_uninstall_app` | Uninstall app by bundle ID | `bundle_id`, `udid`, `device_type` |
| `ios_list_apps` | List installed applications on Simulator | `udid` |
| `ios_get_app_container` | Resolve sandboxed path on disk (`app`, `data`, `groups`) | `bundle_id`, `container_type`, `udid` |
| `ios_open_url` | Open URL or deep link scheme (e.g. `myapp://profile/123`) | `url`, `udid` |

### Environment, Permissions & Simulation

| Tool | Purpose | Parameters |
|---|---|---|
| `ios_set_appearance` | Toggle system interface mode (`light` or `dark`) | `style`, `udid` |
| `ios_set_location` | Simulate GPS latitude and longitude | `latitude`, `longitude`, `udid` |
| `ios_set_permission` | Grant/revoke permissions (`camera`, `photos`, `location`, `microphone`, `contacts`, `faceid`, etc.) | `service`, `bundle_id`, `action`, `udid` |
| `ios_set_status_bar` | Override status bar for clean screenshots (time, battery, cellular, wifi) | `time_str`, `battery_level`, `wifi_bars`, `cellular_bars`, `reset` |
| `ios_send_push_notification`| Inject simulated APNs push notification payload | `bundle_id`, `payload` (JSON), `udid` |
| `ios_add_media` | Ingest images or videos into Simulator Photos library | `paths`, `udid` |
| `ios_clipboard_copy` | Copy string to Simulator pasteboard | `text`, `udid` |
| `ios_clipboard_paste` | Read string from Simulator pasteboard | `udid` |

### Physical iOS Hardware Management (`devicectl`)

| Tool | Purpose | Parameters |
|---|---|---|
| `ios_list_physical_devices` | List connected iPhones/iPads with OS, build, pairing status | — |
| `ios_device_info` | Detailed hardware properties and status for device | `device_uuid` |
| `ios_device_reboot` | Reboot physical iOS device | `device_uuid` |

---

## Cross-Platform Automation Recipes

### 1. Cross-Platform Deep Link Testing

Verify that a universal deep link routes correctly on both platforms:

```
Agent invocation:
1. open_url("https://example.com/checkout?item=42") -> Android default browser / handler
2. ios_open_url("https://example.com/checkout?item=42") -> iOS Safari / handler
3. take_screenshot() -> inspect Android screen
4. ios_screenshot() -> inspect iOS screen
```

### 2. Mocking GPS Location Across Both Platforms

Simulate user arrival in San Francisco:

- **Android**: `run_shell("am", ["broadcast", "-a", "geo.fix", "--ef", "lat", "37.7749", "--ef", "lon", "-122.4194"])`
- **iOS**: `ios_set_location(latitude=37.7749, longitude=-122.4194)`

### 3. Granting Camera Permissions for Automated QA

- **Android**: `run_shell("pm", ["grant", "com.example.app", "android.permission.CAMERA"])`
- **iOS**: `ios_set_permission(service="camera", bundle_id="com.example.app", action="grant")`

---

## Security Architecture & Configuration

1. **Subprocess Isolation**: All commands are executed as discrete argument vectors (`argv`) without shell expansion (`shell=False`), preventing injection attacks.
2. **Bundle & Package Sanitization**: Every package name and bundle ID is verified against strict alphanumeric and reverse-DNS schemas (`^[a-zA-Z0-9.\-_]+$`).
3. **Protected Roots for Filesystem Ops**: Destructive operations (`file_delete`, `file_push`) strictly forbid targeting system partitions (`/system`, `/vendor`, `/dev`).
4. **Opt-In Shell**: `run_shell` is disabled by default and requires setting `ANDROID_ADB_ALLOW_SHELL=1` in your environment.
5. **Destructive-operation confirmation**: `uninstall_app`, `clear_app_data`, `delete_file`/`file_delete`, `reboot`, `ios_erase_simulator`, `ios_uninstall_app`, and `ios_device_reboot` are server-side gated — they refuse with a `confirm_required` error unless called with `confirm=true` after user approval.

---

## Troubleshooting & FAQ

### `health_check` reports "Xcode developer directory not found"
Ensure Xcode is installed and select the developer directory:
```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

### `ios_screenshot` capture fails
Ensure a simulator is booted:
```bash
# List available simulators
ios_list_simulators()

# Boot your target simulator
ios_boot_simulator(udid="iPhone 16 Pro")
```

### `ios_tap` or `ios_swipe` does not register on the Simulator
1. Ensure the Simulator window is not minimized or hidden on another macOS desktop Space.
2. Ensure your terminal or IDE has Accessibility permissions in `System Settings > Privacy & Security > Accessibility`.

### Multiple Android devices connected
Specify `serial="<device_id>"` in your tool arguments. Run `list_devices` to view all attached serials.
