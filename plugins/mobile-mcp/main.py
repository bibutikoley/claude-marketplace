"""MCP server: Android phone control for developers.

Run:  uv run main.py
Register:  claude mcp add mobile-mcp -s user -- uv run --project <this dir> main.py

Prerequisites: Android Studio + SDK (adb), and the `android` CLI.
Connect a phone with USB debugging (tap Allow on the RSA prompt), or start
an emulator. See README.md.

Observation policy: get_layout FIRST (cheap structured JSON). screenshot is
fallback-only — layout failure (WebView/animation) or genuinely visual
questions. Never both on one turn.
"""

from __future__ import annotations

import base64

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent

import adb

mcp = MCPServer("mobile-mcp", version="0.1.0")


def _ok(text: str, **extra) -> CallToolResult:
    """Tool result: human-readable text + machine-readable structured fields."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structuredContent=extra
    )


def _shot(text: str, png: bytes, path: str, **extra) -> CallToolResult:
    """Screenshot result: inline image (agent sees the screen) + text + fields."""
    return CallToolResult(
        content=[
            ImageContent(
                type="image",
                data=base64.b64encode(png).decode(),
                mimeType="image/png",
            ),
            TextContent(type="text", text=text),
        ],
        structuredContent={"path": path, **extra},
    )


# ---- health / devices --------------------------------------------------------


@mcp.tool()
def health_check() -> dict:
    """Verify adb + `android` CLI resolve, SDK is found, and report connected
    devices. Run this first; it tells you exactly what prerequisite is missing."""
    try:
        h = adb.health()
        lines = [
            f"adb: {h['adb_version']} ({h['adb']})",
            f"android CLI: {h['android_cli_version']}",
            f"sdk: {h['sdk_root']}",
            f"devices: {h['device_count']}",
        ]
        for d in h["devices"]:
            model = d.get("model", "?")
            lines.append(f"  - {d['serial']} [{d['state']}] model:{model}")
        if not h["devices"]:
            lines.append("  (none — connect a USB phone or emulator_start)")
        if h["android_cli"] is None:
            lines.append(f"WARNING: {h['android_cli_version']}")
        return _ok("\n".join(lines), **h)
    except adb.AdbError as e:
        return _ok(f"FAIL: {e}", error=str(e))


@mcp.tool()
def list_devices() -> dict:
    """List connected devices/emulators (serial, state, model)."""
    try:
        devices = adb.list_devices()
        text = "\n".join(
            f"- {d['serial']} [{d['state']}] model:{d.get('model', '?')}"
            for d in devices
        ) or "(no devices — connect USB phone or emulator_start)"
        return _ok(text, devices=devices, count=len(devices))
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def device_info(serial: str | None = None) -> dict:
    """Device details: manufacturer, model, Android version, SDK level, display
    size. serial optional (auto-selected when exactly one device is online)."""
    try:
        info = adb.device_info(serial)
        text = (
            f"{info['manufacturer']} {info['model']} — "
            f"Android {info['android']} (SDK {info['sdk']}), "
            f"display {info['display']} [{info['serial']}]"
        )
        return _ok(text, **info)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


# ---- observe: layout-first ----------------------------------------------------


@mcp.tool()
def get_layout(
    serial: str | None = None, flat: bool = False, full: bool = False
) -> dict:
    """UI hierarchy as JSON (class, text, content-desc, resource-id, bounds,
    center, interactions). THE primary observation tool — always call this
    before screenshot. Tap coordinates come from node `center`s. First call
    installs a layout server on device (slow once). Fails on WebView/animation
    screens → then use screenshot(annotate=true)."""
    try:
        tree = adb.get_layout(serial, flat=flat, full=full)
        count = len(tree) if isinstance(tree, list) else 1
        return _ok(
            f"Layout: {count} top-level node(s). Use node centers for tap/swipe. "
            "Full tree in structured content.",
            tree=tree,
            count=count,
        )
    except adb.AdbError as e:
        return _ok(f"ERROR: {e} — fall back to screenshot(annotate=true).")


@mcp.tool()
def screenshot(
    serial: str | None = None, annotate: bool = False, save_to: str | None = None
) -> dict:
    """Capture the screen, returned INLINE as an image. FALLBACK-ONLY: call
    only when get_layout fails/ambiguous or the question is genuinely visual.
    annotate=true draws numbered boxes for tap_element. Rate-limited (1/10s).
    save_to keeps the PNG on disk (default: temp file, cleaned up server-side
    after reading — path still reported when kept). Full-res PNGs are large
    (~7MB); don't loop on this."""
    shot: dict | None = None
    try:
        shot = adb.take_screenshot(serial, annotate=annotate, save_to=save_to)
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
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")
    finally:
        if shot and shot["tmp"] and not save_to:
            adb.cleanup_screenshot(shot["path"], True)


@mcp.tool()
def tap_element(screenshot_path: str, template: str) -> dict:
    """Resolve #N labels from an ANNOTATED screenshot into coordinates, e.g.
    screenshot_path from screenshot(annotate=true), template="input tap #3".
    Returns the resolved command string — then execute it via tap() (preferred)
    or run_shell. Fallback targeting path; primary targeting is layout centers."""
    try:
        resolved = adb.tap_element(screenshot_path, template)
        return _ok(f"Resolved: {resolved}", resolved=resolved)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


# ---- input ---------------------------------------------------------------------


@mcp.tool()
def tap(x: int, y: int, serial: str | None = None) -> dict:
    """Tap screen coordinates. Prefer node `center`s from get_layout over
    guessed coordinates."""
    try:
        adb.tap(x, y, serial)
        return _ok(f"Tapped ({x}, {y}). Re-observe with get_layout.")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def swipe(
    x1: int, y1: int, x2: int, y2: int,
    duration_ms: int = 300, serial: str | None = None,
) -> dict:
    """Swipe from (x1,y1) to (x2,y2). Slow swipes scroll better (larger
    duration_ms). Scroll slowly when hunting for off-screen elements."""
    try:
        adb.swipe(x1, y1, x2, y2, duration_ms, serial)
        return _ok(
            f"Swiped ({x1},{y1})→({x2},{y2}) in {duration_ms}ms. "
            "Re-observe with get_layout."
        )
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def key_event(code: str, serial: str | None = None) -> dict:
    """Send a keyevent: BACK, HOME, ENTER, APP_SWITCH, SLEEP, WAKEUP, … (with
    or without the KEYCODE_ prefix)."""
    try:
        adb.key_event(code, serial)
        return _ok(f"Sent key {code}. Re-observe with get_layout.")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def input_text(text: str, serial: str | None = None) -> dict:
    """Type into the FOCUSED field — tap the field's layout center first and
    confirm focus. ASCII only; shell metacharacters are refused."""
    try:
        adb.input_text(text, serial)
        return _ok(f"Typed {len(text)} char(s). Re-observe with get_layout.")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


# ---- apps -----------------------------------------------------------------------


@mcp.tool()
def list_packages(
    serial: str | None = None,
    third_party_only: bool = False,
    filter: str | None = None,
) -> dict:
    """Installed packages. third_party_only=true for user apps; filter= for a
    case-insensitive substring (e.g. filter="chrome")."""
    try:
        pkgs = adb.list_packages(serial, third_party_only, filter)
        text = f"{len(pkgs)} package(s)" + (
            "\n" + "\n".join(f"- {p}" for p in pkgs) if pkgs else ""
        )
        return _ok(text, packages=pkgs, count=len(pkgs))
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def launch_app(
    package: str, activity: str | None = None, serial: str | None = None
) -> dict:
    """Launch an installed app by package (launcher intent). Pass activity=
    (".MainActivity" or fully-qualified) when the launcher intent can't find
    one. Observe → get_layout, then act → re-observe."""
    try:
        out = adb.launch_app(package, activity, serial)
        return _ok(
            f"Launched {package}. Observe with get_layout next.",
            output=out,
        )
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def force_stop(package: str, serial: str | None = None) -> dict:
    """Force-stop an app."""
    try:
        adb.force_stop(package, serial)
        return _ok(f"Stopped {package}.")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def clear_app_data(package: str, serial: str | None = None) -> dict:
    """Wipe an app's data. DESTRUCTIVE — confirm with the user first."""
    try:
        out = adb.clear_app_data(package, serial)
        return _ok(f"Cleared data for {package}: {out}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def uninstall_app(package: str, serial: str | None = None) -> dict:
    """Remove an app. DESTRUCTIVE — confirm with the user first."""
    try:
        out = adb.uninstall_app(package, serial)
        return _ok(f"Uninstalled {package}: {out}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def install_apk(
    host_path: str, serial: str | None = None, install_options: str | None = None
) -> dict:
    """Delta-install APK(s) via `android install` (faster than adb install).
    host_path must be under ANDROID_ADB_ALLOWED_INSTALL_DIRS (default /tmp/;
    symlinks rejected). Comma-separated for split APKs."""
    try:
        out = adb.install_apk(host_path, serial, install_options)
        return _ok(f"Installed {host_path}: {out}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


# ---- files -----------------------------------------------------------------------


@mcp.tool()
def pull_file(device_path: str, host_dest: str, serial: str | None = None) -> dict:
    """Pull a file from device to host. device_path absolute; host_dest is a
    file path or an existing directory (parents created)."""
    try:
        out = adb.pull_file(device_path, host_dest, serial)
        return _ok(f"Pulled {device_path} → {host_dest}: {out}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def push_file(host_src: str, device_dest: str, serial: str | None = None) -> dict:
    """Push a host file to device. Both sides checked (host must exist,
    device path absolute)."""
    try:
        out = adb.push_file(host_src, device_dest, serial)
        return _ok(f"Pushed {host_src} → {device_dest}: {out}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def list_files(device_path: str, serial: str | None = None) -> dict:
    """List a device directory (`ls -la`). Absolute path."""
    try:
        out = adb.list_files(device_path, serial)
        return _ok(out, output=out)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def delete_file(device_path: str, serial: str | None = None) -> dict:
    """Delete a file on device. Refuses protected roots (/, /system, /data,
    …). DESTRUCTIVE — confirm with the user first."""
    try:
        adb.delete_file(device_path, serial)
        return _ok(f"Deleted {device_path}.")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


# ---- emulator ---------------------------------------------------------------------


@mcp.tool()
def emulator_list(long: bool = False) -> dict:
    """Available virtual devices (AVDs). Use when no USB phone is attached."""
    try:
        out = adb.emulator_list(long)
        return _ok(out, output=out)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def emulator_start(avd: str, cold: bool = False) -> dict:
    """Start an AVD. BLOCKS until the emulator is ready (up to ~5 min) —
    be patient. cold=true skips snapshot loading."""
    try:
        out = adb.emulator_start(avd, cold)
        return _ok(f"Emulator {avd} ready: {out}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def emulator_stop(device: str | None = None) -> dict:
    """Stop a running emulator (name/serial; omit when only one runs)."""
    try:
        out = adb.emulator_stop(device)
        return _ok(f"Stopped: {out or device or 'emulator'}")
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


# ---- system ------------------------------------------------------------------------


@mcp.tool()
def logcat(
    serial: str | None = None, lines: int = 200, clear: bool = False
) -> dict:
    """Recent device logs (default last 200 lines, truncated at 100KB).
    clear=true wipes the buffer instead."""
    try:
        out = adb.logcat(serial, lines, clear)
        return _ok(out, output=out)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def get_prop(name: str | None = None, serial: str | None = None) -> dict:
    """Device properties. name= for one (e.g. "ro.build.version.release"),
    omit for all."""
    try:
        out = adb.get_prop(name, serial)
        return _ok(out, output=out)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def reboot(mode: str | None = None, serial: str | None = None) -> dict:
    """Reboot the device. mode: bootloader | recovery | omit (normal).
    DESTRUCTIVE — confirm with the user first."""
    try:
        return _ok(adb.reboot(mode, serial))
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def run_shell(
    command: str, args: list[str] | None = None, serial: str | None = None
) -> dict:
    """Escape hatch: one device-shell command with centrally-quoted args.
    DISABLED unless ANDROID_ADB_ALLOW_SHELL=1, and `command` must be in
    ANDROID_ADB_ALLOWED_COMMANDS. Prefer the named tools above."""
    try:
        out = adb.run_shell(command, args, serial)
        return _ok(out, output=out)
    except adb.AdbError as e:
        return _ok(f"ERROR: {e}")


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
