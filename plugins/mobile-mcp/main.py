"""MCP server: Unified mobile device control for Android and iOS.

Run:  uv run main.py
Register:  claude mcp add mobile-mcp -s user -- uv run --project <this dir> main.py

Prerequisites:
- Android: Android Studio + SDK (adb) and the `android` CLI.
- iOS: Xcode (xcrun simctl + xcrun devicectl) and macOS permissions for Simulator UI automation.

See README.md for complete documentation and setup guides.
"""

from __future__ import annotations

import base64
import json

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent

import android
import ios

mcp = MCPServer("mobile-mcp", version="0.4.0")


def _ok(text: str, **extra) -> CallToolResult:
    """Tool result: human-readable text + machine-readable structured fields."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=extra if extra else None,
    )


def _err(text: str, **extra) -> CallToolResult:
    """Tool error: human-readable error text + is_error flag + machine-readable details."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        is_error=True,
        structured_content=extra if extra else None,
    )


def _require_confirm(confirm: bool, op: str) -> CallToolResult | None:
    """Server-side guard for destructive ops. Returns an error result when
    confirm is not set, otherwise None (caller proceeds)."""
    if not confirm:
        return _err(
            f"{op} is destructive. Re-invoke with confirm=true after user approval.",
            operation=op,
            confirm_required=True,
        )
    return None


def _shot(text: str, png: bytes, path: str, **extra) -> CallToolResult:
    """Screenshot result: inline image (agent sees the screen) + text + fields."""
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(png).decode(),
                mime_type="image/png",
            ),
            TextContent(type="text", text=text),
        ],
        structured_content={"path": path, **extra},
    )


# ---- health / devices --------------------------------------------------------


@mcp.tool()
def health_check() -> CallToolResult:
    """Verify Android (adb, android CLI, SDK) and iOS (Xcode, simctl, devicectl)
    toolchains, and report connected devices and simulators. Run this first!"""
    lines = ["=== Android Environment ==="]
    android_health = {}
    try:
        h = android.health()
        android_health = h
        lines.extend(
            [
                f"adb: {h['adb_version']} ({h['adb']})",
                f"android CLI: {h['android_cli_version']}",
                f"sdk: {h['sdk_root']}",
                f"devices: {h['device_count']}",
            ]
        )
        for d in h["devices"]:
            model = d.get("model", "?")
            lines.append(f"  - {d['serial']} [{d['state']}] model:{model}")
        if not h["devices"]:
            lines.append("  (none — connect a USB phone or emulator_start)")
        if h["android_cli"] is None:
            lines.append(f"WARNING: {h['android_cli_version']}")
    except Exception as e:
        android_health = {"error": str(e)}
        lines.append(f"Android check failed: {e}")

    lines.append("\n=== iOS Environment ===")
    ios_health = {}
    try:
        ih = ios.health()
        ios_health = ih
        lines.extend(
            [
                f"Developer Dir: {ih.get('developer_dir') or 'Not found'}",
                f"Xcode Version: {ih.get('xcode_version') or 'Not found'}",
                f"simctl: {'Available' if ih.get('simctl_available') else 'Not available'}",
                f"devicectl: {'Available' if ih.get('devicectl_available') else 'Not available'}",
                f"Booted Simulators: {len(ih.get('booted_simulators', []))}",
            ]
        )
        for sim in ih.get("booted_simulators", []):
            lines.append(f"  - {sim['name']} ({sim['runtime']}): {sim['udid']}")
        if not ih.get("booted_simulators"):
            lines.append("  (none booted — boot with ios_boot_simulator)")

        pdevs = ih.get("physical_devices", [])
        lines.append(f"Physical Devices: {len(pdevs)}")
        for pd in pdevs:
            lines.append(
                f"  - {pd['name']} ({pd['modelName']}, {pd['osVersion']}): {pd['identifier']}"
            )
    except Exception as e:
        ios_health = {"error": str(e)}
        lines.append(f"iOS check failed: {e}")

    return _ok("\n".join(lines), android=android_health, ios=ios_health)


@mcp.tool()
def list_all_devices() -> CallToolResult:
    """List all connected Android devices/emulators, iOS simulators, and physical iOS devices."""
    lines = ["--- Android Devices ---"]
    android_devs = []
    try:
        android_devs = android.list_devices()
        for d in android_devs:
            lines.append(f"- {d['serial']} [{d['state']}] model:{d.get('model', '?')}")
        if not android_devs:
            lines.append("(no Android devices connected)")
    except Exception as e:
        lines.append(f"(error listing Android devices: {e})")

    lines.append("\n--- iOS Simulators ---")
    ios_sims = []
    try:
        ios_sims = ios.list_simulators()
        booted = [s for s in ios_sims if s["state"] == "Booted"]
        if booted:
            lines.append("Booted:")
            for s in booted:
                lines.append(f"- {s['name']} ({s['runtime']}): {s['udid']}")
        else:
            lines.append("(no iOS simulators currently booted)")
    except Exception as e:
        lines.append(f"(error listing iOS simulators: {e})")

    lines.append("\n--- iOS Physical Devices ---")
    ios_pdevs = []
    try:
        ios_pdevs = ios.list_physical_devices()
        for pd in ios_pdevs:
            lines.append(
                f"- {pd['name']} ({pd['modelName']}, {pd['osVersion']}): {pd['identifier']}"
            )
        if not ios_pdevs:
            lines.append("(no physical iOS devices connected)")
    except Exception as e:
        lines.append(f"(error listing physical iOS devices: {e})")

    return _ok(
        "\n".join(lines),
        android=android_devs,
        ios_simulators=ios_sims,
        ios_devices=ios_pdevs,
    )


@mcp.tool()
def list_devices() -> CallToolResult:
    """List connected devices/emulators (serial, state, model)."""
    try:
        devices = android.list_devices()
        text = (
            "\n".join(
                f"- {d['serial']} [{d['state']}] model:{d.get('model', '?')}" for d in devices
            )
            or "(no devices — connect USB phone or emulator_start)"
        )
        return _ok(text, devices=devices, count=len(devices))
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def device_info(serial: str | None = None) -> CallToolResult:
    """Device details: manufacturer, model, Android version, SDK level, display
    size. serial optional (auto-selected when exactly one device is online)."""
    try:
        info = android.device_info(serial)
        text = (
            f"{info['manufacturer']} {info['model']} — "
            f"Android {info['android']} (SDK {info['sdk']}), "
            f"display {info['display']} [{info['serial']}]"
        )
        return _ok(text, **info)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- observe: layout-first ----------------------------------------------------


@mcp.tool()
def get_layout(serial: str | None = None, flat: bool = False, full: bool = False) -> CallToolResult:
    """UI hierarchy as JSON (class, text, content-desc, resource-id, bounds,
    center, interactions). THE primary observation tool — always call this
    before screenshot. Tap coordinates come from node `center`s. First call
    installs a layout server on device (slow once). Fails on WebView/animation
    screens → then use screenshot(annotate=true)."""
    try:
        tree = android.get_layout(serial, flat=flat, full=full)
        count = len(tree) if isinstance(tree, list) else 1

        def _summarize_node(node: dict, indent: int = 0) -> list[str]:
            lines = []
            if not isinstance(node, dict):
                return lines
            parts = []
            if node.get("text"):
                parts.append(f"text={node['text']!r}")
            if node.get("content-desc"):
                parts.append(f"desc={node['content-desc']!r}")
            if node.get("resource-id"):
                parts.append(f"id={node['resource-id']}")
            if node.get("center"):
                c = node["center"]
                parts.append(f"center=({c.get('x', '?')},{c.get('y', '?')})")
            if node.get("interactions"):
                parts.append(f"actions={','.join(node['interactions'])}")
            cls_name = node.get("class", "").rsplit(".", 1)[-1]
            if parts:
                prefix = "  " * indent + f"- [{cls_name}] "
                lines.append(prefix + " ".join(parts))
            for child in node.get("children", []) or []:
                lines.extend(_summarize_node(child, indent + 1))
            return lines

        summary_lines = []
        if isinstance(tree, list):
            for n in tree:
                summary_lines.extend(_summarize_node(n, 0))
        elif isinstance(tree, dict):
            summary_lines.extend(_summarize_node(tree, 0))

        if summary_lines:
            text_header = (
                f"Layout: {count} top-level node(s), {len(summary_lines)} interactive element(s).\n"
                "Interactive elements (use center coordinates for tap/swipe):\n"
                + "\n".join(summary_lines[:80])
            )
            if len(summary_lines) > 80:
                text_header += (
                    f"\n... [{len(summary_lines) - 80} more element(s) truncated in text overview, "
                    "full tree in structuredContent]"
                )
        else:
            text_header = f"Layout: {count} top-level node(s). Full tree in structured content."

        return _ok(
            text_header,
            tree=tree,
            count=count,
        )
    except android.AndroidError as e:
        return _err(f"ERROR: {e} — fall back to screenshot(annotate=true).")


@mcp.tool()
def screenshot(
    serial: str | None = None, annotate: bool = False, save_to: str | None = None
) -> CallToolResult:
    """Capture the screen, returned INLINE as an image. FALLBACK-ONLY: call
    only when get_layout fails/ambiguous or the question is genuinely visual.
    annotate=true draws numbered boxes for tap_element. Rate-limited (default 2s).
    save_to keeps the PNG on disk (default: temp file managed server-side;
    latest capture is reused by tap_element). Full-res PNGs are large (~7MB);
    don't loop on this."""
    try:
        shot = android.take_screenshot(serial, annotate=annotate, save_to=save_to)
        w, h = shot["width"], shot["height"]
        size = f"{w}x{h}" if w else "unknown size"
        return _shot(
            f"Screenshot ({size}, annotate={annotate}). Visually inspect it "
            "before acting. Prefer get_layout for re-observation.",
            shot["data"],
            shot["path"],
            width=w,
            height=h,
            annotate=annotate,
        )
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def tap_element(
    screenshot_path: str | None = None,
    template: str = "input tap #1",
    serial: str | None = None,
    execute: bool = False,
) -> CallToolResult:
    """Resolve #N labels from an ANNOTATED screenshot into coordinates, e.g.
    template="input tap #3". screenshot_path is optional and defaults to the
    latest annotated screenshot. Pass execute=true to immediately tap the
    resolved coordinates."""
    try:
        resolved, coords = android.tap_element(screenshot_path, template)
        msg = f"Resolved: {resolved}"
        if execute and coords:
            x, y = coords
            android.tap(x, y, serial)
            msg += f" -> Executed tap({x}, {y}). Re-observe with get_layout."
        extra: dict = {"resolved": resolved}
        if coords:
            extra["x"] = coords[0]
            extra["y"] = coords[1]
        return _ok(msg, **extra)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- input ---------------------------------------------------------------------


@mcp.tool()
def tap(x: int, y: int, serial: str | None = None) -> CallToolResult:
    """Tap screen coordinates. Prefer node `center`s from get_layout over
    guessed coordinates."""
    try:
        android.tap(x, y, serial)
        return _ok(f"Tapped ({x}, {y}). Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def swipe(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    serial: str | None = None,
) -> CallToolResult:
    """Swipe from (x1,y1) to (x2,y2). Slow swipes scroll better (larger
    duration_ms). Scroll slowly when hunting for off-screen elements."""
    try:
        android.swipe(x1, y1, x2, y2, duration_ms, serial)
        return _ok(
            f"Swiped ({x1},{y1})→({x2},{y2}) in {duration_ms}ms. Re-observe with get_layout."
        )
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def key_event(code: str, serial: str | None = None) -> CallToolResult:
    """Send a keyevent: BACK, HOME, ENTER, APP_SWITCH, SLEEP, WAKEUP, or numeric keycode (4, 66)..."""
    try:
        android.key_event(code, serial)
        return _ok(f"Sent key {code}. Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def input_text(text: str, serial: str | None = None) -> CallToolResult:
    """Type into the FOCUSED field — tap the field's layout center first and
    confirm focus. ASCII only; shell metacharacters are refused."""
    try:
        android.input_text(text, serial)
        return _ok(f"Typed {len(text)} char(s). Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- apps -----------------------------------------------------------------------


@mcp.tool()
def list_packages(
    serial: str | None = None,
    third_party_only: bool = False,
    filter: str | None = None,
) -> CallToolResult:
    """Installed packages. third_party_only=true for user apps; filter= for a
    case-insensitive substring (e.g. filter="chrome")."""
    try:
        pkgs = android.list_packages(serial, third_party_only, filter)
        text = f"{len(pkgs)} package(s)" + (
            "\n" + "\n".join(f"- {p}" for p in pkgs) if pkgs else ""
        )
        return _ok(text, packages=pkgs, count=len(pkgs))
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def launch_app(
    package: str, activity: str | None = None, serial: str | None = None
) -> CallToolResult:
    """Launch an installed app by package (launcher intent). Pass activity=
    (".MainActivity" or fully-qualified) when the launcher intent can't find
    one. Observe → get_layout, then act → re-observe."""
    try:
        out = android.launch_app(package, activity, serial)
        return _ok(
            f"Launched {package}. Observe with get_layout next.",
            output=out,
        )
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def force_stop(package: str, serial: str | None = None) -> CallToolResult:
    """Force-stop an app."""
    try:
        android.force_stop(package, serial)
        return _ok(f"Stopped {package}.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def clear_app_data(
    package: str, serial: str | None = None, confirm: bool = False
) -> CallToolResult:
    """Wipe an app's data. DESTRUCTIVE — requires confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "clear_app_data")) is not None:
        return denied
    try:
        out = android.clear_app_data(package, serial)
        return _ok(f"Cleared data for {package}: {out}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def uninstall_app(package: str, serial: str | None = None, confirm: bool = False) -> CallToolResult:
    """Remove an app. DESTRUCTIVE — requires confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "uninstall_app")) is not None:
        return denied
    try:
        out = android.uninstall_app(package, serial)
        return _ok(f"Uninstalled {package}: {out}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def install_apk(
    host_path: str, serial: str | None = None, install_options: str | None = None
) -> CallToolResult:
    """Delta-install APK(s) via `android install` (faster than adb install).
    host_path must be under ANDROID_ADB_ALLOWED_INSTALL_DIRS (default /tmp/;
    symlinks rejected). Comma-separated for split APKs."""
    try:
        out = android.install_apk(host_path, serial, install_options)
        return _ok(f"Installed {host_path}: {out}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- files -----------------------------------------------------------------------


@mcp.tool()
def pull_file(
    device_path: str, host_dest: str | None = None, serial: str | None = None
) -> CallToolResult:
    """Pull a file from device to host. device_path absolute; host_dest is a
    file path or an existing directory (parents created, default: cwd)."""
    try:
        out = android.pull_file(device_path, host_dest, serial)
        return _ok(f"Pulled {device_path} → {host_dest or '(cwd)'}: {out}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def push_file(host_src: str, device_dest: str, serial: str | None = None) -> CallToolResult:
    """Push a host file to device. Both sides checked (host must exist,
    device path absolute)."""
    try:
        out = android.push_file(host_src, device_dest, serial)
        return _ok(f"Pushed {host_src} → {device_dest}: {out}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def list_files(device_path: str, serial: str | None = None) -> CallToolResult:
    """List a device directory (`ls -la`). Absolute path."""
    try:
        out = android.list_files(device_path, serial)
        return _ok(out, output=out)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def delete_file(
    device_path: str, serial: str | None = None, confirm: bool = False
) -> CallToolResult:
    """Delete a file on device. Refuses protected roots (/, /system, /data,
    …). DESTRUCTIVE — requires confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "delete_file")) is not None:
        return denied
    try:
        android.delete_file(device_path, serial)
        return _ok(f"Deleted {device_path}.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- emulator ---------------------------------------------------------------------


@mcp.tool()
def emulator_list(long: bool = False) -> CallToolResult:
    """Available virtual devices (AVDs). Use when no USB phone is attached."""
    try:
        out = android.emulator_list(long)
        return _ok(out, output=out)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def emulator_start(avd: str, cold: bool = False) -> CallToolResult:
    """Start an AVD. BLOCKS until the emulator is ready (up to ~5 min) —
    be patient. cold=true skips snapshot loading."""
    try:
        out = android.emulator_start(avd, cold)
        return _ok(f"Emulator {avd} ready: {out}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def emulator_stop(device: str | None = None) -> CallToolResult:
    """Stop a running emulator (name/serial; omit when only one runs)."""
    try:
        out = android.emulator_stop(device)
        return _ok(f"Stopped: {out or device or 'emulator'}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- system ------------------------------------------------------------------------


@mcp.tool()
def logcat(serial: str | None = None, lines: int = 200, clear: bool = False) -> CallToolResult:
    """Recent device logs (default last 200 lines).
    clear=true wipes the buffer instead."""
    try:
        out = android.logcat(serial, lines, clear)
        return _ok(out, output=out)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def get_prop(name: str | None = None, serial: str | None = None) -> CallToolResult:
    """Device properties. name= for one (e.g. "ro.build.version.release"),
    omit for all."""
    try:
        out = android.get_prop(name, serial)
        return _ok(out, output=out)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def reboot(
    mode: str | None = None, serial: str | None = None, confirm: bool = False
) -> CallToolResult:
    """Reboot the device. mode: bootloader | recovery | omit (normal).
    DESTRUCTIVE — requires confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "reboot")) is not None:
        return denied
    try:
        return _ok(android.reboot(mode, serial))
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def current_app(serial: str | None = None) -> CallToolResult:
    """Detect the currently focused foreground app (package, activity, and component)."""
    try:
        info = android.current_app(serial)
        if info["package"]:
            text = f"Current app: {info['component']}"
        else:
            text = "No foreground app detected (screen off, launcher, or transition)."
        return _ok(text, **info)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def open_url(url: str, serial: str | None = None) -> CallToolResult:
    """Open a URL or deep link via VIEW intent in the default browser/handler."""
    try:
        out = android.open_url(url, serial)
        return _ok(f"Opened {url}: {out or 'intent dispatched'}")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def wake_screen(serial: str | None = None) -> CallToolResult:
    """Wake device screen and dismiss keyguard if locked."""
    try:
        out = android.wake_screen(serial)
        return _ok(out)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def run_shell(
    command: str, args: list[str] | None = None, serial: str | None = None
) -> CallToolResult:
    """Escape hatch: one device-shell command with centrally-quoted args.
    DISABLED unless ANDROID_ADB_ALLOW_SHELL=1, and `command` must be in
    ANDROID_ADB_ALLOWED_COMMANDS. Prefer the named tools above."""
    try:
        out = android.run_shell(command, args, serial)
        return _ok(out, output=out)
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- Android Navigation Helpers (own logic, not aliases) ------------------------


@mcp.tool()
def double_tap(x: int, y: int, serial: str | None = None) -> CallToolResult:
    """Double tap coordinate (x, y) rapidly."""
    try:
        android.tap(x, y, serial)
        android.tap(x, y, serial)
        return _ok(f"Double tapped ({x}, {y}). Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def long_press(
    x: int, y: int, duration_ms: int = 1000, serial: str | None = None
) -> CallToolResult:
    """Long press coordinate (x, y) with specified duration (default 1000ms)."""
    try:
        android.swipe(x, y, x, y, duration_ms, serial)
        return _ok(f"Long-pressed ({x}, {y}) for {duration_ms}ms. Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def scroll(
    dx: int = 0, dy: int = -500, duration_ms: int = 300, serial: str | None = None
) -> CallToolResult:
    """Relative swipe/scroll gesture (default scrolls down by 500px)."""
    try:
        android.swipe(500, 1500, 500 + dx, 1500 + dy, duration_ms, serial)
        return _ok(f"Scrolled dx={dx}, dy={dy}. Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def clear_text(count: int = 25, serial: str | None = None) -> CallToolResult:
    """Clear characters from currently focused field by sending delete key events."""
    try:
        for _ in range(min(count, 100)):
            android.key_event("67", serial)
        return _ok(f"Cleared up to {count} characters. Re-observe with get_layout.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def open_notification_panel(serial: str | None = None) -> CallToolResult:
    """Expand the Android notification shade."""
    try:
        out = android.run_device_shell(["cmd", "statusbar", "expand-notifications"], serial)
        return _ok(out or "Notification panel expanded.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def open_quick_settings(serial: str | None = None) -> CallToolResult:
    """Expand the Android quick settings shade."""
    try:
        out = android.run_device_shell(["cmd", "statusbar", "expand-settings"], serial)
        return _ok(out or "Quick settings expanded.")
    except android.AndroidError as e:
        return _err(f"ERROR: {e}")


# ---- iOS Tools (Simulators & Physical Devices) ------------------------------


@mcp.tool()
def ios_list_simulators(
    filter_runtime: str | None = None,
    filter_state: str | None = None,
) -> CallToolResult:
    """List iOS Simulators. filter_runtime (e.g. 'iOS-18', 'watchOS') or filter_state ('Booted', 'Shutdown')."""
    try:
        sims = ios.list_simulators(filter_runtime=filter_runtime, filter_state=filter_state)
        lines = [f"- {s['name']} ({s['runtime']}): {s['udid']} [{s['state']}]" for s in sims]
        text = "\n".join(lines) or "(no matching simulators found)"
        return _ok(text, simulators=sims, count=len(sims))
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_boot_simulator(udid: str, show_gui: bool = True) -> CallToolResult:
    """Boot an iOS Simulator by UDID or name, optionally launching Simulator.app."""
    try:
        msg = ios.boot_simulator(udid, show_gui=show_gui)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_shutdown_simulator(udid: str | None = None) -> CallToolResult:
    """Shut down an iOS Simulator. udid optional if only 1 simulator is booted."""
    try:
        msg = ios.shutdown_simulator(udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_erase_simulator(udid: str | None = None, confirm: bool = False) -> CallToolResult:
    """Wipe an iOS Simulator to factory defaults (shuts down first if running). DESTRUCTIVE — requires confirm=true."""
    if (denied := _require_confirm(confirm, "ios_erase_simulator")) is not None:
        return denied
    try:
        msg = ios.erase_simulator(udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_get_layout(udid: str | None = None) -> CallToolResult:
    """Extract on-screen text elements, bounding boxes, and tap centers from the iOS Simulator using Apple's Vision framework (cheap structured JSON, zero vision tokens)."""
    try:
        elements = ios.get_layout_simulator(udid=udid)
        lines = [
            f'[{el["index"]}] "{el["text"]}" at ({int(el["point_center"]["x"])}, {int(el["point_center"]["y"])})'
            for el in elements
        ]
        text = "\n".join(lines) or "(no text elements detected on screen)"
        return _ok(text, elements=elements, count=len(elements))
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_tap_element(selector: str, udid: str | None = None) -> CallToolResult:
    """Tap an on-screen element found in ios_get_layout by index (e.g. '#1', '1') or text (e.g. 'Settings')."""
    try:
        msg, coords = ios.tap_element_simulator(selector, udid=udid)
        return _ok(msg, x=coords[0], y=coords[1])
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_screenshot(udid: str | None = None, save_to: str | None = None) -> CallToolResult:
    """Capture pixel-perfect screenshot of an iOS Simulator. Returns inline image for visual inspection."""
    try:
        png_bytes, path = ios.take_screenshot_simulator(udid=udid, save_to=save_to)
        return _shot(f"Screenshot captured ({len(png_bytes)} bytes) at {path}", png_bytes, path)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_tap(x: int, y: int, udid: str | None = None) -> CallToolResult:
    """Tap coordinates on the active Simulator window via native Quartz CoreGraphics."""
    try:
        msg = ios.tap_simulator(x, y, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_swipe(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    udid: str | None = None,
) -> CallToolResult:
    """Perform swipe gesture on active Simulator from (x1, y1) to (x2, y2)."""
    try:
        msg = ios.swipe_simulator(x1, y1, x2, y2, duration_ms, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_input_text(text: str, udid: str | None = None) -> CallToolResult:
    """Paste text into the focused Simulator text field via pasteboard and Cmd+V."""
    try:
        msg = ios.input_text_simulator(text, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_press_button(button: str, udid: str | None = None) -> CallToolResult:
    """Press hardware button on Simulator: home, lock, app_switcher, shake, rotate_left, rotate_right, volume_up, volume_down."""
    try:
        msg = ios.press_button_simulator(button, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_open_url(url: str, udid: str | None = None) -> CallToolResult:
    """Open URL or deep link scheme in iOS Simulator."""
    try:
        msg = ios.open_url_simulator(url, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_launch_app(
    bundle_id: str,
    args: list[str] | None = None,
    udid: str | None = None,
    device_type: str = "simulator",
) -> CallToolResult:
    """Launch application on iOS Simulator or physical device ('simulator' or 'device')."""
    try:
        if device_type.lower() == "device":
            if not udid:
                return _err("udid/device_uuid is required when launching on physical device.")
            msg = ios.launch_app_device(udid, bundle_id, args)
        else:
            msg = ios.launch_app_simulator(bundle_id, args, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_terminate_app(
    bundle_id: str,
    udid: str | None = None,
    device_type: str = "simulator",
) -> CallToolResult:
    """Terminate application on iOS Simulator or physical device ('simulator' or 'device')."""
    try:
        if device_type.lower() == "device":
            if not udid:
                return _err("udid/device_uuid is required when terminating on physical device.")
            msg = ios.terminate_app_device(udid, bundle_id)
        else:
            msg = ios.terminate_app_simulator(bundle_id, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_install_app(
    app_path: str,
    udid: str | None = None,
    device_type: str = "simulator",
) -> CallToolResult:
    """Install .app bundle (Simulator) or .ipa/.app (device)."""
    try:
        if device_type.lower() == "device":
            if not udid:
                return _err("udid/device_uuid is required when installing on physical device.")
            msg = ios.install_app_device(udid, app_path)
        else:
            msg = ios.install_app_simulator(app_path, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_uninstall_app(
    bundle_id: str,
    udid: str | None = None,
    device_type: str = "simulator",
    confirm: bool = False,
) -> CallToolResult:
    """Uninstall application by bundle ID from simulator or physical device. DESTRUCTIVE — requires confirm=true."""
    if (denied := _require_confirm(confirm, "ios_uninstall_app")) is not None:
        return denied
    try:
        if device_type.lower() == "device":
            if not udid:
                return _err("udid/device_uuid is required when uninstalling from physical device.")
            msg = ios.uninstall_app_device(udid, bundle_id)
        else:
            msg = ios.uninstall_app_simulator(bundle_id, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_list_apps(udid: str | None = None) -> CallToolResult:
    """List installed applications on iOS Simulator."""
    try:
        apps = ios.list_apps_simulator(udid)
        lines = [
            f"- {a.get('bundle_id', '?')} ({a.get('CFBundleDisplayName', a.get('CFBundleName', ''))})"
            for a in apps
        ]
        text = "\n".join(lines) or "(no third-party apps found)"
        return _ok(text, apps=apps, count=len(apps))
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_get_app_container(
    bundle_id: str,
    container_type: str = "data",
    udid: str | None = None,
) -> CallToolResult:
    """Get sandbox container path ('app', 'data', 'groups') for an app on Simulator."""
    try:
        path = ios.get_app_container(bundle_id, container_type, udid)
        return _ok(path, path=path)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_set_appearance(style: str, udid: str | None = None) -> CallToolResult:
    """Set Simulator interface appearance ('light' or 'dark')."""
    try:
        msg = ios.set_appearance(style, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_set_location(latitude: float, longitude: float, udid: str | None = None) -> CallToolResult:
    """Set simulated GPS coordinates on iOS Simulator."""
    try:
        msg = ios.set_location(latitude, longitude, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_set_permission(
    service: str,
    bundle_id: str,
    action: str = "grant",
    udid: str | None = None,
) -> CallToolResult:
    """Set privacy permission on Simulator.
    service: all, camera, photos, photos-add, location, location-always, microphone, contacts, reminders, calendar.
    action: grant, revoke, reset, no-prompt.
    """
    try:
        msg = ios.set_permission(service, bundle_id, action, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_set_status_bar(
    time_str: str | None = None,
    battery_level: int | None = None,
    wifi_bars: int | None = None,
    cellular_bars: int | None = None,
    reset: bool = False,
    udid: str | None = None,
) -> CallToolResult:
    """Override or reset status bar on iOS Simulator (clean screenshots)."""
    try:
        msg = ios.set_status_bar(
            time_str=time_str,
            battery_level=battery_level,
            wifi_bars=wifi_bars,
            cellular_bars=cellular_bars,
            reset=reset,
            udid=udid,
        )
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_send_push_notification(
    bundle_id: str,
    payload: str,
    udid: str | None = None,
) -> CallToolResult:
    """Send simulated APNs push notification payload (JSON string) to Simulator."""
    try:
        msg = ios.send_push_notification(bundle_id, payload, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_add_media(paths: list[str], udid: str | None = None) -> CallToolResult:
    """Import photos or videos into Simulator Photos library."""
    try:
        msg = ios.add_media_simulator(paths, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_clipboard_copy(text: str, udid: str | None = None) -> CallToolResult:
    """Copy text to iOS Simulator pasteboard."""
    try:
        msg = ios.pbcopy_simulator(text, udid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_clipboard_paste(udid: str | None = None) -> CallToolResult:
    """Read text from iOS Simulator pasteboard."""
    try:
        text = ios.pbpaste_simulator(udid)
        return _ok(text, paste=text)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_list_physical_devices() -> CallToolResult:
    """List connected physical iOS devices via xcrun devicectl."""
    try:
        devs = ios.list_physical_devices()
        lines = [
            f"- {d['name']} ({d['modelName']}, {d['osVersion']}): {d['identifier']} [paired:{d['isPaired']}]"
            for d in devs
        ]
        text = "\n".join(lines) or "(no physical iOS devices connected)"
        return _ok(text, devices=devs, count=len(devs))
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_device_info(device_uuid: str) -> CallToolResult:
    """Get detailed hardware and status properties for a physical iOS device."""
    try:
        info = ios.device_info_physical(device_uuid)
        # Nested (not splatted): devicectl keys are unmanaged and could
        # collide with _ok's own parameters.
        return _ok(f"Device info for {device_uuid}:\n{json.dumps(info, indent=2)}", info=info)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


@mcp.tool()
def ios_device_reboot(device_uuid: str, confirm: bool = False) -> CallToolResult:
    """Reboot a physical iOS device via devicectl. DESTRUCTIVE — requires confirm=true."""
    if (denied := _require_confirm(confirm, "ios_device_reboot")) is not None:
        return denied
    try:
        msg = ios.reboot_device(device_uuid)
        return _ok(msg)
    except ios.IosError as e:
        return _err(f"ERROR: {e}")


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
