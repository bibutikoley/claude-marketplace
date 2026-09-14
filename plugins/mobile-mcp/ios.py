"""iOS automation engine: Simulators via xcrun simctl + physical devices via xcrun devicectl.

First-party Apple tooling only — no Appium, WebDriverAgent, or pymobiledevice3 required.
Uses:
  - `xcrun simctl` for iOS Simulator lifecycle, apps, network, permissions, and screenshotting.
  - `xcrun devicectl` (CoreDevice, Xcode 15+) for physical iOS hardware management.
  - macOS native CoreGraphics (via ctypes) and AppleScript for UI gestures and window interactions.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

logger = logging.getLogger("mobile-mcp.ios")

_COMMAND_LOCK = threading.Lock()
_LAST_SCREENSHOT_PATH: str | None = None
_LAST_LAYOUT_ELEMENTS: list[dict[str, Any]] = []
_BUNDLE_ID_RE = re.compile(r"[A-Za-z0-9._-]+")
_URL_RE = re.compile(r"[A-Za-z0-9+.-]+://\S+")

# macOS CoreGraphics bindings
_cg_lib = None
_kCGEventLeftMouseDown = 1
_kCGEventLeftMouseUp = 2
_kCGEventLeftMouseDragged = 6
_kCGHIDEventTap = 0
_kCGMouseButtonLeft = 0


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


def _get_core_graphics():
    global _cg_lib
    if _cg_lib is not None:
        return _cg_lib
    lib_path = ctypes.util.find_library("CoreGraphics")
    if not lib_path:
        lib_path = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    try:
        _cg_lib = ctypes.cdll.LoadLibrary(lib_path)
        _cg_lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        _cg_lib.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            CGPoint,
            ctypes.c_uint32,
        ]
        _cg_lib.CGEventPost.restype = None
        _cg_lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        _cg_lib.CFRelease.restype = None
        _cg_lib.CFRelease.argtypes = [ctypes.c_void_p]
    except Exception as e:
        logger.warning(f"Failed to load CoreGraphics: {e}")
        _cg_lib = None
    return _cg_lib


class IosError(RuntimeError):
    """Raised when an iOS command fails or prerequisites are missing."""

    pass


def _require_bundle_id(bundle_id: str) -> None:
    """Reject bundle IDs that could alter a downstream command argument."""
    if not _BUNDLE_ID_RE.fullmatch(bundle_id or ""):
        raise IosError(f"Invalid bundle ID: {bundle_id}")


# ---- Host filesystem authorization (install allowlist) -------------------
# IOS_ALLOWED_INSTALL_DIRS restricts which host paths may be installed on
# simulators/devices. Deny-by-default: when unset or empty, every install
# is refused. Multiple roots separated by os.pathsep, `~` expanded, all
# entries resolved before comparison. Mirrors Android's
# ANDROID_ADB_ALLOWED_INSTALL_DIRS model, except the iOS default is empty
# (deny) rather than /tmp/.
#
# Symlink policy: symlinks are REJECTED outright (even when the target
# sits inside an allowed directory), matching Android's install_apk. The
# caller must pass the real path. Resolved paths are then authorized, so
# symlink escapes through allowed parents cannot smuggle outside paths in.


def allowed_install_dirs() -> list[Path]:
    """Allowed host install roots from IOS_ALLOWED_INSTALL_DIRS."""
    raw = os.environ.get("IOS_ALLOWED_INSTALL_DIRS", "")
    dirs: list[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        dirs.append(Path(part).expanduser().resolve())
    return dirs


def validate_install_path(path: str) -> Path:
    """Normalize and authorize a host app path for installation.

    Returns the resolved absolute path. Raises IosError when the
    allowlist is empty, the path is a symlink, or the resolved path is
    not inside an allowed directory.
    """
    if not path or not path.strip():
        raise IosError("No app path provided.")
    allowed = allowed_install_dirs()
    if not allowed:
        raise IosError(
            "App installation is disabled: set IOS_ALLOWED_INSTALL_DIRS to a "
            f"{os.pathsep!r}-separated list of allowed directories "
            '(e.g. "$HOME/Developer/apps").'
        )
    raw = path.strip()
    p = Path(raw).expanduser()
    if p.is_symlink():
        raise IosError(f"Refusing symlinked app path: {path}")
    resolved = p.resolve()
    if not any(resolved == d or (d.is_dir() and resolved.is_relative_to(d)) for d in allowed):
        names = os.pathsep.join(str(d) for d in allowed)
        raise IosError(
            f"App outside allowed install dirs ({names}): {path}. "
            "Set IOS_ALLOWED_INSTALL_DIRS to include it."
        )
    return resolved


# ---- Developer directory & tool discovery -----------------------------------


def resolve_developer_dir() -> Path:
    """Find active Xcode developer directory."""
    env_dir = os.environ.get("DEVELOPER_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p

    try:
        proc = subprocess.run(
            ["xcode-select", "-p"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            if out and Path(out).is_dir():
                return Path(out)
    except Exception:
        pass

    for candidate in [
        Path("/Applications/Xcode.app/Contents/Developer"),
        Path("/Applications/Xcode-beta.app/Contents/Developer"),
    ]:
        if candidate.is_dir():
            return candidate

    raise IosError(
        "Xcode developer directory not found. Please install Xcode and run:\n"
        "  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
    )


def resolve_tool(tool_name: str) -> str:
    """Resolve simctl, devicectl, or xcrun path."""
    if shutil.which(tool_name):
        return tool_name

    dev_dir = resolve_developer_dir()
    candidate = dev_dir / "usr" / "bin" / tool_name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)

    # Fallback to xcrun if installed
    if shutil.which("xcrun"):
        return "xcrun"

    raise IosError(f"Tool '{tool_name}' not found under {dev_dir} or in PATH.")


# ---- Command Runners --------------------------------------------------------


def _run_simctl(
    argv: list[str],
    timeout: float = 30.0,
    input_bytes: bytes | None = None,
) -> str:
    """Run `xcrun simctl <argv>` with concurrency lock and timeout."""
    dev_dir = str(resolve_developer_dir())
    env = dict(os.environ)
    env["DEVELOPER_DIR"] = dev_dir

    cmd = ["xcrun", "simctl"] + argv
    with _COMMAND_LOCK:
        try:
            proc = subprocess.run(
                cmd,
                input=input_bytes,
                capture_output=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise IosError(f"simctl command timed out after {timeout}s: {' '.join(argv)}")
        except FileNotFoundError:
            raise IosError("xcrun/simctl binary not found. Is Xcode installed?")

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        raise IosError(f"simctl {' '.join(argv)} failed (code {proc.returncode}): {err}")

    return proc.stdout.decode(errors="replace")


def _run_devicectl(
    argv: list[str],
    timeout: float = 30.0,
    json_output: bool = False,
) -> dict[str, Any] | str:
    """Run `xcrun devicectl <argv>`, handling JSON output if requested."""
    dev_dir = str(resolve_developer_dir())
    env = dict(os.environ)
    env["DEVELOPER_DIR"] = dev_dir

    tmp_json_path = None
    cmd = ["xcrun", "devicectl"] + list(argv)
    if json_output:
        tmp_fd, tmp_json_path = tempfile.mkstemp(suffix=".json", prefix="devicectl_")
        os.close(tmp_fd)
        cmd.extend(["--json-output", tmp_json_path])

    with _COMMAND_LOCK:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            if tmp_json_path and os.path.exists(tmp_json_path):
                os.unlink(tmp_json_path)
            raise IosError(f"devicectl timed out after {timeout}s: {' '.join(argv)}")
        except FileNotFoundError:
            if tmp_json_path and os.path.exists(tmp_json_path):
                os.unlink(tmp_json_path)
            raise IosError("xcrun/devicectl binary not found. Requires Xcode 15+.")

    try:
        if json_output and tmp_json_path and os.path.exists(tmp_json_path):
            with open(tmp_json_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                return {}
    except Exception as e:
        logger.warning(f"Failed to read devicectl JSON: {e}")
    finally:
        if tmp_json_path and os.path.exists(tmp_json_path):
            try:
                os.unlink(tmp_json_path)
            except OSError:
                pass

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode(errors="replace").strip()
        raise IosError(f"devicectl {' '.join(argv)} failed (code {proc.returncode}): {err}")

    return proc.stdout.decode(errors="replace")


def _run_applescript(script: str, timeout: float = 10.0) -> str:
    """Run an AppleScript via osascript with lock and timeout."""
    with _COMMAND_LOCK:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise IosError("AppleScript execution timed out")
        except FileNotFoundError:
            raise IosError("osascript not found")

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip()
        raise IosError(f"AppleScript failed: {err}")
    return proc.stdout.strip()


# ---- Simulator Management (simctl) ------------------------------------------


def list_simulators(
    filter_runtime: str | None = None,
    filter_state: str | None = None,
) -> list[dict[str, Any]]:
    """List iOS Simulators.

    Returns list of dicts with:
      name, udid, state ('Booted' | 'Shutdown'), isAvailable, runtime, deviceTypeIdentifier
    """
    raw_json = _run_simctl(["list", "devices", "-j"])
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise IosError(f"Failed to parse simctl list devices JSON: {e}")

    devices_by_runtime = data.get("devices", {})
    results = []

    for runtime_id, dev_list in devices_by_runtime.items():
        # runtime_id e.g. "com.apple.CoreSimulator.SimRuntime.iOS-18-0"
        clean_runtime = runtime_id.replace("com.apple.CoreSimulator.SimRuntime.", "")
        if filter_runtime and filter_runtime.lower() not in clean_runtime.lower():
            continue

        for dev in dev_list:
            state = dev.get("state", "Unknown")
            if filter_state and filter_state.lower() != state.lower():
                continue

            results.append(
                {
                    "name": dev.get("name", "Unknown"),
                    "udid": dev.get("udid", ""),
                    "state": state,
                    "isAvailable": dev.get("isAvailable", True),
                    "runtime": clean_runtime,
                    "deviceTypeIdentifier": dev.get("deviceTypeIdentifier", ""),
                }
            )

    return results


def resolve_simulator(udid_or_name: str | None = None) -> str:
    """Resolve a target simulator UDID.

    - If udid_or_name is provided: matches against exact UDID, partial UDID, or device name.
    - If None: returns the currently booted simulator if exactly one is booted.
    """
    all_sims = list_simulators()

    if udid_or_name:
        target = udid_or_name.strip()
        # 1. Exact UDID
        for sim in all_sims:
            if sim["udid"].lower() == target.lower():
                return sim["udid"]
        # 2. Exact Name (case-insensitive)
        name_matches = [sim for sim in all_sims if sim["name"].lower() == target.lower()]
        if len(name_matches) == 1:
            return name_matches[0]["udid"]
        elif len(name_matches) > 1:
            # Prefer booted one if any
            booted = [s for s in name_matches if s["state"] == "Booted"]
            if len(booted) == 1:
                return booted[0]["udid"]
            sim_list_str = "\n".join(
                f"- {s['name']} ({s['runtime']}): {s['udid']} [{s['state']}]" for s in name_matches
            )
            raise IosError(
                f"Multiple simulators matched '{target}'. Please specify UDID:\n{sim_list_str}"
            )
        # 3. Partial UDID / Substring name
        partial_matches = [
            sim
            for sim in all_sims
            if target.lower() in sim["name"].lower() or target.lower() in sim["udid"].lower()
        ]
        if len(partial_matches) == 1:
            return partial_matches[0]["udid"]
        elif len(partial_matches) > 1:
            sim_list_str = "\n".join(
                f"- {s['name']}: {s['udid']} [{s['state']}]" for s in partial_matches[:5]
            )
            raise IosError(f"Ambiguous simulator match for '{target}':\n{sim_list_str}")

        raise IosError(f"No simulator found matching '{target}'.")

    # If udid_or_name is None, check booted simulators
    booted = [sim for sim in all_sims if sim["state"] == "Booted"]
    if not booted:
        raise IosError(
            "No simulator is currently booted. Please specify a simulator name/UDID, "
            "or boot one with ios_boot_simulator."
        )
    if len(booted) == 1:
        return booted[0]["udid"]

    sim_list_str = "\n".join(f"- {s['name']} ({s['runtime']}): {s['udid']}" for s in booted)
    raise IosError(
        f"Multiple simulators are booted ({len(booted)}). Please specify UDID:\n{sim_list_str}"
    )


def boot_simulator(udid_or_name: str, show_gui: bool = True) -> str:
    """Boot an iOS Simulator by UDID or name, optionally opening Simulator.app."""
    udid = resolve_simulator(udid_or_name)
    all_sims = list_simulators()
    matching = [s for s in all_sims if s["udid"] == udid]
    name = matching[0]["name"] if matching else udid

    if matching and matching[0]["state"] == "Booted":
        status = f"Simulator '{name}' ({udid}) is already booted."
    else:
        _run_simctl(["boot", udid], timeout=60.0)
        status = f"Booted simulator '{name}' ({udid})."

    if show_gui:
        try:
            subprocess.run(
                ["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid],
                check=False,
                timeout=5,
            )
            status += " Simulator.app launched."
        except Exception as e:
            logger.warning(f"Could not activate Simulator.app: {e}")

    return status


def shutdown_simulator(udid_or_name: str | None = None) -> str:
    """Shut down an iOS Simulator."""
    udid = resolve_simulator(udid_or_name)
    _run_simctl(["shutdown", udid], timeout=30.0)
    return f"Simulator {udid} shut down successfully."


def erase_simulator(udid_or_name: str | None = None) -> str:
    """Erase (factory reset) an iOS Simulator. Must be shutdown first."""
    udid = resolve_simulator(udid_or_name)
    try:
        _run_simctl(["shutdown", udid], timeout=15.0)
    except Exception:
        pass
    _run_simctl(["erase", udid], timeout=60.0)
    return f"Simulator {udid} wiped to factory defaults."


def install_app_simulator(app_path: str, udid: str | None = None) -> str:
    """Install an .app bundle on simulator.

    The host path must live under IOS_ALLOWED_INSTALL_DIRS
    (deny-by-default; symlinks rejected). Safe argv execution, no shell.
    """
    target_udid = resolve_simulator(udid)
    p = validate_install_path(app_path)
    if not p.exists():
        raise IosError(f"App path does not exist: {app_path}")
    if p.suffix != ".app" or not p.is_dir():
        raise IosError(f"Expected an .app bundle directory, got {app_path}")

    _run_simctl(["install", target_udid, str(p)], timeout=60.0)
    return f"Installed {p.name} onto simulator {target_udid}."


def uninstall_app_simulator(bundle_id: str, udid: str | None = None) -> str:
    """Uninstall an app by bundle ID from simulator."""
    _require_bundle_id(bundle_id)
    target_udid = resolve_simulator(udid)
    _run_simctl(["uninstall", target_udid, bundle_id], timeout=30.0)
    return f"Uninstalled {bundle_id} from simulator {target_udid}."


def launch_app_simulator(
    bundle_id: str,
    args: list[str] | None = None,
    udid: str | None = None,
) -> str:
    """Launch an installed application on simulator."""
    _require_bundle_id(bundle_id)
    target_udid = resolve_simulator(udid)
    cmd = ["launch", target_udid, bundle_id]
    if args:
        cmd.extend(args)
    out = _run_simctl(cmd, timeout=30.0)
    return out.strip() or f"Launched {bundle_id} on {target_udid}."


def terminate_app_simulator(bundle_id: str, udid: str | None = None) -> str:
    """Terminate an application process on simulator."""
    _require_bundle_id(bundle_id)
    target_udid = resolve_simulator(udid)
    _run_simctl(["terminate", target_udid, bundle_id], timeout=15.0)
    return f"Terminated {bundle_id} on {target_udid}."


def list_apps_simulator(udid: str | None = None) -> list[dict[str, Any]]:
    """List installed applications on simulator."""
    target_udid = resolve_simulator(udid)
    raw = _run_simctl(["listapps", target_udid], timeout=20.0)
    apps = []

    # Format is XML plist or key-value blocks
    current_app: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('"') and line.endswith('" = {'):
            bid = line.split('"')[1]
            current_app = {"bundle_id": bid}
            apps.append(current_app)
        elif "=" in line and current_app:
            parts = line.split("=", 1)
            key = parts[0].strip().strip('";')
            val = parts[1].strip().strip('";')
            current_app[key] = val

    if not apps:
        # Fallback regex for standard output
        for m in re.finditer(r'"([a-zA-Z0-9.\-_]+)"\s*=\s*\{([^}]+)\}', raw):
            bid = m.group(1)
            block = m.group(2)
            item: dict[str, Any] = {"bundle_id": bid}
            for line in block.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    item[k.strip().strip('";')] = v.strip().strip('";')
            apps.append(item)

    return apps


def get_app_container(
    bundle_id: str,
    container_type: str = "data",
    udid: str | None = None,
) -> str:
    """Get the container path ('app', 'data', 'groups') for an installed app."""
    _require_bundle_id(bundle_id)
    if container_type not in ["app", "data", "groups"]:
        raise IosError(f"container_type must be 'app', 'data', or 'groups', got '{container_type}'")

    target_udid = resolve_simulator(udid)
    cmd = ["get_app_container", target_udid, bundle_id]
    if container_type != "data":
        cmd.append(container_type)
    out = _run_simctl(cmd, timeout=15.0).strip()
    return out


def open_url_simulator(url: str, udid: str | None = None) -> str:
    """Open URL or deep link in simulator."""
    target_udid = resolve_simulator(udid)
    if not _URL_RE.fullmatch(url):
        raise IosError(f"Invalid URL format: {url}")
    _run_simctl(["openurl", target_udid, url], timeout=15.0)
    return f"Dispatched {url} to simulator {target_udid}."


def add_media_simulator(paths: list[str], udid: str | None = None) -> str:
    """Add photos or videos to simulator's Photos library."""
    target_udid = resolve_simulator(udid)
    resolved_paths = []
    for p in paths:
        path_obj = Path(p).expanduser().resolve()
        if not path_obj.exists():
            raise IosError(f"Media file not found: {p}")
        resolved_paths.append(str(path_obj))

    _run_simctl(["addmedia", target_udid] + resolved_paths, timeout=30.0)
    return f"Added {len(resolved_paths)} media item(s) to simulator {target_udid}."


def send_push_notification(
    bundle_id: str,
    payload: dict[str, Any] | str,
    udid: str | None = None,
) -> str:
    """Send simulated APNs push notification to an app."""
    _require_bundle_id(bundle_id)
    target_udid = resolve_simulator(udid)

    if isinstance(payload, str):
        try:
            payload_dict = json.loads(payload)
        except json.JSONDecodeError as e:
            raise IosError(f"Invalid JSON payload: {e}")
    else:
        payload_dict = payload

    if "Simulator Target Bundle" not in payload_dict:
        payload_dict["Simulator Target Bundle"] = bundle_id

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="push_", delete=False) as f:
        json.dump(payload_dict, f, indent=2)
        tmp_path = f.name

    try:
        _run_simctl(["push", target_udid, bundle_id, tmp_path], timeout=15.0)
        return f"Pushed notification to {bundle_id} on simulator {target_udid}."
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def set_appearance(style: str, udid: str | None = None) -> str:
    """Set Simulator interface appearance: 'light' or 'dark'."""
    style_clean = style.lower().strip()
    if style_clean not in ["light", "dark"]:
        raise IosError(f"Appearance must be 'light' or 'dark', got '{style}'")
    target_udid = resolve_simulator(udid)
    _run_simctl(["ui", target_udid, "appearance", style_clean], timeout=15.0)
    return f"Appearance set to '{style_clean}' on {target_udid}."


def set_location(latitude: float, longitude: float, udid: str | None = None) -> str:
    """Set simulated GPS location coordinates."""
    if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
        raise IosError(f"Invalid coordinates: lat {latitude}, lon {longitude}")
    target_udid = resolve_simulator(udid)
    _run_simctl(["location", target_udid, "set", f"{latitude},{longitude}"], timeout=15.0)
    return f"Simulated location set to ({latitude}, {longitude}) on {target_udid}."


def set_permission(
    service: str,
    bundle_id: str,
    action: str = "grant",
    udid: str | None = None,
) -> str:
    """Manage permissions on simulator (camera, photos, location, etc.).

    Services: all, calendar, contacts-limited, contacts, location, location-always,
              photos-add, photos, media-library, microphone, motion, reminders, siri
    Actions: grant, revoke, reset, no-prompt
    """
    valid_services = [
        "all",
        "camera",
        "calendar",
        "contacts-limited",
        "contacts",
        "location",
        "location-always",
        "photos-add",
        "photos",
        "media-library",
        "microphone",
        "motion",
        "reminders",
        "siri",
        "bluetooth",
        "user-tracking",
        "faceid",
    ]
    valid_actions = ["grant", "revoke", "reset", "no-prompt"]

    if service not in valid_services:
        raise IosError(f"Invalid service '{service}'. Valid: {', '.join(valid_services)}")
    if action not in valid_actions:
        raise IosError(f"Invalid action '{action}'. Valid: {', '.join(valid_actions)}")
    _require_bundle_id(bundle_id)

    target_udid = resolve_simulator(udid)
    _run_simctl(
        ["privacy", target_udid, action, service, bundle_id],
        timeout=15.0,
    )
    return f"Permission '{service}' set to '{action}' for {bundle_id} on {target_udid}."


def set_status_bar(
    time_str: str | None = None,
    battery_level: int | None = None,
    wifi_bars: int | None = None,
    cellular_bars: int | None = None,
    reset: bool = False,
    udid: str | None = None,
) -> str:
    """Override or reset status bar display on simulator."""
    target_udid = resolve_simulator(udid)
    if reset:
        _run_simctl(["status_bar", target_udid, "clear"], timeout=15.0)
        return f"Status bar overrides cleared on {target_udid}."

    cmd = ["status_bar", target_udid, "override"]
    if time_str:
        cmd.extend(["--time", time_str])
    if battery_level is not None:
        cmd.extend(["--batteryLevel", str(battery_level)])
    if wifi_bars is not None:
        cmd.extend(["--wifiBars", str(wifi_bars)])
    if cellular_bars is not None:
        cmd.extend(["--cellularBars", str(cellular_bars)])

    if len(cmd) == 3:
        raise IosError("At least one status bar property or reset=True must be specified.")

    _run_simctl(cmd, timeout=15.0)
    return f"Status bar overridden on {target_udid}."


def pbcopy_simulator(text: str, udid: str | None = None) -> str:
    """Copy text to simulator pasteboard."""
    target_udid = resolve_simulator(udid)
    _run_simctl(
        ["pbcopy", target_udid],
        input_bytes=text.encode("utf-8"),
        timeout=15.0,
    )
    return f"Copied {len(text)} characters to simulator pasteboard."


def pbpaste_simulator(udid: str | None = None) -> str:
    """Read text from simulator pasteboard."""
    target_udid = resolve_simulator(udid)
    return _run_simctl(["pbpaste", target_udid], timeout=15.0)


def take_screenshot_simulator(
    udid: str | None = None,
    save_to: str | None = None,
) -> tuple[bytes, str]:
    """Capture headless PNG screenshot of simulator screen directly via simctl io."""
    global _LAST_SCREENSHOT_PATH
    target_udid = resolve_simulator(udid)

    if save_to:
        dest_path = Path(save_to).expanduser().resolve()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        dest_fd, tmp_file = tempfile.mkstemp(suffix=".png", prefix=f"sim_{target_udid[:8]}_")
        os.close(dest_fd)
        dest_path = Path(tmp_file)

    _run_simctl(
        ["io", target_udid, "screenshot", str(dest_path)],
        timeout=25.0,
    )

    if not dest_path.is_file() or dest_path.stat().st_size == 0:
        raise IosError(f"Screenshot capture produced an empty file at {dest_path}")

    png_bytes = dest_path.read_bytes()
    _LAST_SCREENSHOT_PATH = str(dest_path)
    return png_bytes, str(dest_path)


_SWIFT_OCR_CODE = """
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    print("[]")
    exit(0)
}

let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("[]")
    exit(0)
}

let pixelWidth = Double(cgImage.width)
let pixelHeight = Double(cgImage.height)

let scaleFactor: Double
if pixelWidth >= 1100 || pixelHeight >= 2400 {
    scaleFactor = 3.0
} else if pixelWidth >= 640 || pixelHeight >= 1136 {
    scaleFactor = 2.0
} else {
    scaleFactor = 1.0
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try? handler.perform([request])

guard let results = request.results else {
    print("[]")
    exit(0)
}

struct ElementBounds: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ElementPoint: Codable {
    let x: Double
    let y: Double
}

struct LayoutElement: Codable {
    let index: Int
    let text: String
    let confidence: Float
    let pixel_bounds: ElementBounds
    let pixel_center: ElementPoint
    let point_bounds: ElementBounds
    let point_center: ElementPoint
}

var elements: [LayoutElement] = []
var index = 1

for observation in results {
    guard let candidate = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    
    let px = box.origin.x * pixelWidth
    let py = (1.0 - box.origin.y - box.size.height) * pixelHeight
    let pw = box.size.width * pixelWidth
    let ph = box.size.height * pixelHeight
    let pcx = px + (pw / 2.0)
    let pcy = py + (ph / 2.0)
    
    let ptx = px / scaleFactor
    let pty = py / scaleFactor
    let ptw = pw / scaleFactor
    let pth = ph / scaleFactor
    let ptcx = pcx / scaleFactor
    let ptcy = pcy / scaleFactor
    
    let el = LayoutElement(
        index: index,
        text: candidate.string,
        confidence: candidate.confidence,
        pixel_bounds: ElementBounds(x: round(px), y: round(py), width: round(pw), height: round(ph)),
        pixel_center: ElementPoint(x: round(pcx), y: round(pcy)),
        point_bounds: ElementBounds(x: round(ptx), y: round(pty), width: round(ptw), height: round(pth)),
        point_center: ElementPoint(x: round(ptcx), y: round(ptcy))
    )
    elements.append(el)
    index += 1
}

let encoder = JSONEncoder()
encoder.outputFormatting = .prettyPrinted
if let data = try? encoder.encode(elements), let str = String(data: data, encoding: .utf8) {
    print(str)
} else {
    print("[]")
}
"""


def get_layout_simulator(udid: str | None = None) -> list[dict[str, Any]]:
    """Capture simulator screen and extract structured text elements and bounding boxes using Apple's Vision framework."""
    global _LAST_LAYOUT_ELEMENTS
    target_udid = resolve_simulator(udid)
    _, shot_path = take_screenshot_simulator(target_udid)

    swift_script = Path(__file__).resolve().parent / "vision_ocr.swift"

    with _COMMAND_LOCK:
        try:
            if swift_script.exists():
                proc = subprocess.run(
                    ["swift", str(swift_script), shot_path],
                    capture_output=True,
                    text=True,
                    timeout=20.0,
                    check=False,
                )
            else:
                proc = subprocess.run(
                    ["swift", "-", shot_path],
                    input=_SWIFT_OCR_CODE,
                    capture_output=True,
                    text=True,
                    timeout=20.0,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            raise IosError("Vision OCR timed out after 20s")
        except FileNotFoundError:
            raise IosError("swift binary not found in PATH")

    if proc.returncode != 0:
        err = proc.stderr.strip()
        raise IosError(f"Vision OCR failed (code {proc.returncode}): {err}")

    try:
        elements = json.loads(proc.stdout.strip() or "[]")
    except json.JSONDecodeError as e:
        raise IosError(f"Failed to parse Vision OCR JSON: {e}")

    _LAST_LAYOUT_ELEMENTS = elements
    return elements


def tap_element_simulator(
    selector: str,
    udid: str | None = None,
) -> tuple[str, tuple[int, int]]:
    """Tap an on-screen element by layout index (e.g. '#1', '1') or text substring (e.g. 'Settings')."""
    global _LAST_LAYOUT_ELEMENTS
    target_udid = resolve_simulator(udid)

    # Refresh layout if cache is empty
    if not _LAST_LAYOUT_ELEMENTS:
        get_layout_simulator(target_udid)

    sel = selector.strip()
    target_el = None

    # 1. Numeric index (e.g. "#1", "1")
    if sel.startswith("#") and sel[1:].isdigit():
        idx = int(sel[1:])
        for el in _LAST_LAYOUT_ELEMENTS:
            if el.get("index") == idx:
                target_el = el
                break
    elif sel.isdigit():
        idx = int(sel)
        for el in _LAST_LAYOUT_ELEMENTS:
            if el.get("index") == idx:
                target_el = el
                break

    # 2. Text match (exact, then case-insensitive substring)
    if not target_el:
        for el in _LAST_LAYOUT_ELEMENTS:
            if el.get("text", "").lower() == sel.lower():
                target_el = el
                break
    if not target_el:
        for el in _LAST_LAYOUT_ELEMENTS:
            if sel.lower() in el.get("text", "").lower():
                target_el = el
                break

    if not target_el:
        available = ", ".join(
            f'[{e.get("index")}] "{e.get("text")}"' for e in _LAST_LAYOUT_ELEMENTS[:8]
        )
        raise IosError(
            f"No element matching '{selector}' in current layout. "
            f"Available elements:\n{available}..."
        )

    pt_center = target_el.get("point_center", {})
    x = int(pt_center.get("x", 0))
    y = int(pt_center.get("y", 0))

    tap_msg = tap_simulator(x, y, target_udid)
    return (
        f'Tapped [{target_el.get("index")}] "{target_el.get("text")}" at ({x}, {y}): {tap_msg}',
        (x, y),
    )


# ---- Simulator GUI Automation (Quartz CoreGraphics / AppleScript) -----------


def _activate_simulator_and_get_bounds() -> tuple[float, float, float, float]:
    """Activate Simulator.app and return window position and size (x, y, w, h)."""
    script = """
    tell application "Simulator" to activate
    delay 0.1
    tell application "System Events"
        tell process "Simulator"
            set win to front window
            set winPos to position of win
            set winSize to size of win
            return (item 1 of winPos as text) & "," & (item 2 of winPos as text) & "," & (item 1 of winSize as text) & "," & (item 2 of winSize as text)
        end tell
    end tell
    """
    raw = _run_applescript(script, timeout=5.0)
    parts = [float(p.strip()) for p in raw.split(",")]
    if len(parts) != 4:
        raise IosError(f"Failed to get Simulator window bounds: {raw}")
    return parts[0], parts[1], parts[2], parts[3]


def tap_simulator(x: int, y: int, udid: str | None = None) -> str:
    """Tap coordinates on the active Simulator window using macOS Quartz CoreGraphics.

    Coordinates (x, y) can be either:
    1. Points relative to the Simulator screen / device points
    2. Absolute window points
    """
    cg = _get_core_graphics()
    if not cg:
        raise IosError("CoreGraphics library not available on this macOS system.")

    win_x, win_y, win_w, win_h = _activate_simulator_and_get_bounds()

    # Title bar height in macOS is typically ~28-32pt
    title_bar_height = 28.0

    target_screen_x = win_x + min(max(float(x), 0.0), win_w)
    target_screen_y = win_y + title_bar_height + min(max(float(y), 0.0), win_h - title_bar_height)

    pt = CGPoint(x=target_screen_x, y=target_screen_y)

    # Mouse down
    evt_down = cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseDown, pt, _kCGMouseButtonLeft)
    cg.CGEventPost(_kCGHIDEventTap, evt_down)
    cg.CFRelease(evt_down)

    time.sleep(0.05)

    # Mouse up
    evt_up = cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, pt, _kCGMouseButtonLeft)
    cg.CGEventPost(_kCGHIDEventTap, evt_up)
    cg.CFRelease(evt_up)

    return f"Tapped Simulator at ({int(x)}, {int(y)}) [macOS screen: {int(target_screen_x)}, {int(target_screen_y)}]."


def swipe_simulator(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    udid: str | None = None,
) -> str:
    """Swipe gesture on Simulator from (x1, y1) to (x2, y2)."""
    cg = _get_core_graphics()
    if not cg:
        raise IosError("CoreGraphics library not available on this macOS system.")

    win_x, win_y, win_w, win_h = _activate_simulator_and_get_bounds()
    title_bar_height = 28.0

    start_x = win_x + min(max(float(x1), 0.0), win_w)
    start_y = win_y + title_bar_height + min(max(float(y1), 0.0), win_h - title_bar_height)
    end_x = win_x + min(max(float(x2), 0.0), win_w)
    end_y = win_y + title_bar_height + min(max(float(y2), 0.0), win_h - title_bar_height)

    pt_start = CGPoint(x=start_x, y=start_y)
    evt_down = cg.CGEventCreateMouseEvent(
        None, _kCGEventLeftMouseDown, pt_start, _kCGMouseButtonLeft
    )
    cg.CGEventPost(_kCGHIDEventTap, evt_down)
    cg.CFRelease(evt_down)

    steps = max(int(duration_ms / 20), 5)
    sleep_interval = (duration_ms / 1000.0) / steps

    for i in range(1, steps + 1):
        curr_x = start_x + (end_x - start_x) * (i / steps)
        curr_y = start_y + (end_y - start_y) * (i / steps)
        pt_curr = CGPoint(x=curr_x, y=curr_y)
        evt_drag = cg.CGEventCreateMouseEvent(
            None, _kCGEventLeftMouseDragged, pt_curr, _kCGMouseButtonLeft
        )
        cg.CGEventPost(_kCGHIDEventTap, evt_drag)
        cg.CFRelease(evt_drag)
        time.sleep(sleep_interval)

    pt_end = CGPoint(x=end_x, y=end_y)
    evt_up = cg.CGEventCreateMouseEvent(None, _kCGEventLeftMouseUp, pt_end, _kCGMouseButtonLeft)
    cg.CGEventPost(_kCGHIDEventTap, evt_up)
    cg.CFRelease(evt_up)

    return f"Swiped Simulator from ({x1}, {y1}) to ({x2}, {y2}) over {duration_ms}ms."


def input_text_simulator(text: str, udid: str | None = None) -> str:
    """Type or paste text into the active Simulator text field.

    Fast and 100% reliable for Unicode and emoji via simulator pasteboard + Command-V.
    """
    target_udid = resolve_simulator(udid)
    pbcopy_simulator(text, target_udid)

    # Bring Simulator forward and trigger Cmd+V
    script = """
    tell application "Simulator" to activate
    delay 0.05
    tell application "System Events"
        keystroke "v" using {command down}
    end tell
    """
    _run_applescript(script, timeout=5.0)
    return f"Pasted {len(text)} characters into Simulator text field."


def press_button_simulator(button: str, udid: str | None = None) -> str:
    """Press hardware button on Simulator.

    Buttons:
      - 'home': Cmd+Shift+H
      - 'lock': Cmd+L
      - 'app_switcher': Cmd+Shift+H twice
      - 'shake': Ctrl+Cmd+Z
      - 'rotate_left': Cmd+Left Arrow
      - 'rotate_right': Cmd+Right Arrow
      - 'volume_up': Cmd+Up Arrow
      - 'volume_down': Cmd+Down Arrow
    """
    btn = button.lower().strip()
    script = (
        'tell application "Simulator" to activate\ndelay 0.05\ntell application "System Events"\n'
    )

    if btn == "home":
        script += 'keystroke "h" using {command down, shift down}\n'
    elif btn == "lock":
        script += 'keystroke "l" using {command down}\n'
    elif btn in ["app_switcher", "recents"]:
        script += 'keystroke "h" using {command down, shift down}\ndelay 0.1\nkeystroke "h" using {command down, shift down}\n'
    elif btn == "shake":
        script += 'keystroke "z" using {command down, control down}\n'
    elif btn == "rotate_left":
        script += "key code 123 using {command down}\n"
    elif btn == "rotate_right":
        script += "key code 124 using {command down}\n"
    elif btn == "volume_up":
        script += "key code 126 using {command down}\n"
    elif btn == "volume_down":
        script += "key code 125 using {command down}\n"
    else:
        raise IosError(
            f"Unknown button '{button}'. Valid: home, lock, app_switcher, shake, "
            "rotate_left, rotate_right, volume_up, volume_down"
        )

    script += "end tell"
    _run_applescript(script, timeout=5.0)
    return f"Pressed '{btn}' on Simulator."


# ---- Physical Device Management (devicectl) ---------------------------------


def list_physical_devices() -> list[dict[str, Any]]:
    """List connected physical iOS devices using xcrun devicectl."""
    try:
        data = _run_devicectl(["list", "devices"], timeout=20.0, json_output=True)
    except IosError as e:
        logger.warning(f"devicectl device listing failed: {e}")
        return []

    if not isinstance(data, dict):
        return []

    raw_devices = data.get("result", {}).get("devices", [])
    devices = []
    for d in raw_devices:
        ident = d.get("identifier", "")
        props = d.get("deviceProperties", {})
        hw = d.get("hardwareProperties", {})
        conn = d.get("connectionProperties", {})
        devices.append(
            {
                "identifier": ident,
                "name": props.get("name", "Unknown"),
                "osVersion": props.get("osVersionNumber", ""),
                "osBuild": props.get("osBuildUpdate", ""),
                "modelName": hw.get("marketingName", hw.get("productType", "iPhone/iPad")),
                "platform": hw.get("platform", "iOS"),
                "isPaired": conn.get("isPaired", True),
                "tunnelState": conn.get("tunnelState", ""),
            }
        )
    return devices


def device_info_physical(device_uuid: str) -> dict[str, Any]:
    """Get detailed hardware and state properties for a physical iOS device."""
    try:
        data = _run_devicectl(
            ["device", "info", "properties", "--device", device_uuid],
            timeout=20.0,
            json_output=True,
        )
        if isinstance(data, dict):
            return data.get("result", data)
    except Exception as e:
        raise IosError(f"Failed to fetch info for physical device {device_uuid}: {e}")
    return {}


def install_app_device(device_uuid: str, app_path: str) -> str:
    """Install an app (.ipa or .app) on physical device via devicectl.

    The host path must live under IOS_ALLOWED_INSTALL_DIRS
    (deny-by-default; symlinks rejected). Safe argv execution, no shell.
    """
    p = validate_install_path(app_path)
    if not p.exists():
        raise IosError(f"App path does not exist: {app_path}")
    if p.suffix not in (".ipa", ".app"):
        raise IosError(f"Expected a .ipa or .app bundle, got {app_path}")
    _run_devicectl(
        ["device", "install", "app", "--device", device_uuid, str(p)],
        timeout=120.0,
    )
    return f"Installed {p.name} on physical device {device_uuid}."


def uninstall_app_device(device_uuid: str, bundle_id: str) -> str:
    """Uninstall an app from physical device via devicectl."""
    _require_bundle_id(bundle_id)
    _run_devicectl(
        ["device", "uninstall", "app", "--device", device_uuid, bundle_id],
        timeout=60.0,
    )
    return f"Uninstalled {bundle_id} from physical device {device_uuid}."


def launch_app_device(
    device_uuid: str,
    bundle_id: str,
    args: list[str] | None = None,
) -> str:
    """Launch process on physical device via devicectl."""
    _require_bundle_id(bundle_id)
    cmd = ["device", "process", "launch", "--device", device_uuid, bundle_id]
    if args:
        cmd.extend(args)
    out = _run_devicectl(cmd, timeout=30.0)
    return str(out).strip() or f"Launched {bundle_id} on {device_uuid}."


def terminate_app_device(device_uuid: str, bundle_id: str) -> str:
    """Terminate app process on physical device via devicectl."""
    _require_bundle_id(bundle_id)
    out = _run_devicectl(
        ["device", "process", "terminate", "--device", device_uuid, bundle_id],
        timeout=20.0,
    )
    return str(out).strip() or f"Terminated {bundle_id} on {device_uuid}."


def reboot_device(device_uuid: str) -> str:
    """Reboot a physical iOS device via devicectl."""
    _run_devicectl(
        ["device", "reboot", "--device", device_uuid],
        timeout=30.0,
    )
    return f"Reboot signal dispatched to device {device_uuid}."


# ---- Health Diagnostics -----------------------------------------------------


def health() -> dict[str, Any]:
    """Check Xcode, simctl, devicectl, and list active simulators and devices."""
    info: dict[str, Any] = {
        "developer_dir": None,
        "xcode_version": None,
        "simctl_available": False,
        "devicectl_available": False,
        "booted_simulators": [],
        "total_simulators": 0,
        "physical_devices": [],
    }

    try:
        dev_dir = resolve_developer_dir()
        info["developer_dir"] = str(dev_dir)
    except Exception as e:
        info["error"] = str(e)
        return info

    try:
        proc = subprocess.run(
            ["xcodebuild", "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if proc.returncode == 0:
            info["xcode_version"] = proc.stdout.strip().replace("\n", ", ")
    except Exception:
        pass

    # Check simctl
    try:
        sims = list_simulators()
        info["simctl_available"] = True
        info["total_simulators"] = len(sims)
        info["booted_simulators"] = [s for s in sims if s["state"] == "Booted"]
    except Exception as e:
        logger.warning(f"simctl check failed: {e}")

    # Check devicectl
    try:
        pdevs = list_physical_devices()
        info["devicectl_available"] = True
        info["physical_devices"] = pdevs
    except Exception as e:
        logger.warning(f"devicectl check failed: {e}")

    return info
