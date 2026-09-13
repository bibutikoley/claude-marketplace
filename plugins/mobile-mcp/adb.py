"""Android bridge: drives phones/emulators through `adb` (platform-tools,
from Android Studio's SDK) and the official `android` CLI (layout, screen,
emulator, delta install).

Layout-first policy: `layout` is the primary observation channel (cheap
structured JSON). Screenshots are fallback-only (WebView/animation screens
where layout fails, or genuinely visual questions) — never captured
alongside a successful layout.

All device-shell invocations go through one central quoting point
(`shlex.quote`), so user-supplied values (package names, paths, text) can
never inject a second command. Raw shell is opt-in only.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

_DEFAULT_TIMEOUT = float(os.environ.get("ANDROID_ADB_TIMEOUT_MS", "30000")) / 1000.0
_EMULATOR_START_TIMEOUT = 300.0
_MAX_OUTPUT = 100 * 1024  # truncate device output (logcat/dumpsys) at 100KB
_SCREENSHOT_MIN_INTERVAL = 10.0  # rate-limit captures: 1 per 10s

_lock = threading.Lock()
_last_capture = 0.0

_DEFAULT_ALLOWED_COMMANDS = (
    "ls,cat,echo,pwd,pm,am,dumpsys,getprop,input,screencap,screenrecord,"
    "logcat,ps,wm,settings,uiautomator,cmd"
)

_PROTECTED_DELETE_ROOTS = (
    "/", "/system", "/vendor", "/product", "/apex",
    "/data", "/sbin", "/proc", "/sys", "/dev",
)

_VALID_KEYCODE = re.compile(r"^[A-Za-z0-9_]+$")
_FORBIDDEN_TEXT_CHARS = set("$()`;|&<>'\"\\\n\r\t")


class AdbError(Exception):
    """Raised for any failure talking to the device, with a human message."""


# ---- binary / SDK discovery -----------------------------------------------
# Studio-first: adb comes from Android Studio's SDK (ANDROID_HOME), never
# from brew. The `android` CLI is the one separate install.


def sdk_root() -> str | None:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(var)
        if val and Path(val).is_dir():
            return val
    home_sdk = Path.home() / "Library" / "Android" / "sdk"
    if home_sdk.is_dir():
        return str(home_sdk)
    return None


def resolve_adb() -> str:
    """Path to the adb binary. Studio SDK first, PATH last."""
    candidates: list[str] = []
    env = os.environ.get("ADB_PATH")
    if env:
        candidates.append(env)
    root = sdk_root()
    if root:
        candidates.append(str(Path(root) / "platform-tools" / "adb"))
    which = shutil.which("adb")
    if which:
        candidates.append(which)
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    raise AdbError(
        "adb not found. Install Android Studio and the SDK Platform-Tools "
        "(SDK Manager), then export ANDROID_HOME=$HOME/Library/Android/sdk "
        "and add $ANDROID_HOME/platform-tools to PATH."
    )


def resolve_android_cli() -> str:
    """Path to the `android` CLI (layout/screen/emulator/delta install)."""
    env = os.environ.get("ANDROID_CLI_PATH")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    which = shutil.which("android")
    if which:
        return which
    raise AdbError(
        "`android` CLI not found. Install it from "
        "https://developer.android.com/tools/agents/android-cli/download "
        "(e.g. `brew install --cask android-cli`), then re-run."
    )


# ---- runners ----------------------------------------------------------------


def _classify_adb_error(stderr: str) -> str | None:
    low = stderr.lower()
    if "unauthorized" in low:
        return (
            "Device unauthorized: on the phone, tap 'Allow' on the "
            "'Allow USB debugging?' (RSA fingerprint) prompt, then retry. "
            "Check 'Always allow from this computer' to stop this recurring."
        )
    if "offline" in low:
        return "Device is offline: unplug/replug USB, toggle USB debugging, retry."
    if "no devices" in low or "no online devices" in low:
        return (
            "No device attached: connect a phone with USB debugging enabled, "
            "or start an emulator (`emulator_start`)."
        )
    if "device not found" in low or "device '" in low:
        return f"Unknown device serial. Pick one from list_devices. ({stderr[:160]})"
    return None


def _run_adb_base(argv: list[str], timeout: float | None = None) -> str:
    adb = resolve_adb()
    timeout = timeout or _DEFAULT_TIMEOUT
    with _lock:
        try:
            proc = subprocess.run(
                [adb] + argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise AdbError(
                f"adb did not respond within {timeout:g}s "
                "(ANDROID_ADB_TIMEOUT_MS). Is the device stuck or cable loose?"
            ) from None
        except FileNotFoundError:
            raise AdbError(f"adb binary vanished at {adb}. Reinstall SDK Platform-Tools.")
    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip()
        human = _classify_adb_error(err)
        if human:
            raise AdbError(human)
        err = re.sub(r"\s+", " ", err)[:400]
        raise AdbError(f"adb error: {err}")
    out = proc.stdout
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + f"\n…[truncated at {_MAX_OUTPUT // 1024}KB]"
    return out


def _parse_devices_short() -> list[tuple[str, str]]:
    out = _run_adb_base(["devices"])
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def list_devices() -> list[dict]:
    """Connected devices (serial, state, model/product where reported)."""
    out = _run_adb_base(["devices", "-l"])
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        entry: dict = {"serial": parts[0], "state": parts[1]}
        for token in parts[2:]:
            if ":" in token:
                k, v = token.split(":", 1)
                entry[k] = v
        devices.append(entry)
    return devices


def resolve_serial(serial: str | None = None) -> str | None:
    """Serial to target, or None when exactly one device is online (omit -s)."""
    if serial:
        return serial
    env = os.environ.get("ADB_SERIAL")
    if env:
        return env
    online = [s for s, state in _parse_devices_short() for _ in [0] if state == "device"]
    if len(online) == 1:
        return None  # unambiguous: talk to the only device
    if not online:
        raise AdbError(
            "No device attached: connect a phone with USB debugging enabled, "
            "or start an emulator (`emulator_start`)."
        )
    serials = ", ".join(online)
    raise AdbError(
        f"Multiple devices online ({serials}). Pass serial= explicitly "
        "or set ADB_SERIAL."
    )


def _run_adb(
    argv: list[str], serial: str | None = None, timeout: float | None = None
) -> str:
    target = resolve_serial(serial)
    if target:
        argv = ["-s", target] + argv
    return _run_adb_base(argv, timeout)


def run_device_shell(
    parts: list[str], serial: str | None = None, timeout: float | None = None
) -> str:
    """Run one device-shell command. Central quoting point: every argument is
    shlex.quote'd and joined, so values can never inject extra commands."""
    quoted = " ".join(shlex.quote(p) for p in parts)
    return _run_adb(["shell", quoted], serial, timeout)


def _run_android(argv: list[str], timeout: float | None = None) -> str:
    cli = resolve_android_cli()
    timeout = timeout or _DEFAULT_TIMEOUT
    with _lock:
        try:
            proc = subprocess.run(
                [cli] + argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise AdbError(
                f"`android` CLI did not respond within {timeout:g}s."
            ) from None
    if proc.returncode != 0:
        err = (proc.stderr.strip() or proc.stdout.strip())
        human = _classify_adb_error(err)
        if human:
            raise AdbError(human)
        err = re.sub(r"\s+", " ", err)[:400]
        raise AdbError(f"`android` CLI error: {err}")
    return proc.stdout


# ---- health -----------------------------------------------------------------


def health() -> dict:
    adb = resolve_adb()
    try:
        version_out = _run_adb_base(["version"]).splitlines()[0]
    except AdbError:
        version_out = "unknown"
    try:
        cli = resolve_android_cli()
        cli_out = _run_android(["--version"]).strip().splitlines()[0]
    except AdbError as e:
        cli, cli_out = None, str(e)
    devices = list_devices()
    return {
        "adb": adb,
        "adb_version": version_out,
        "android_cli": cli,
        "android_cli_version": cli_out,
        "sdk_root": sdk_root(),
        "devices": devices,
        "device_count": len(devices),
    }


# ---- observe: layout-first ---------------------------------------------------


def get_layout(
    serial: str | None = None, flat: bool = False, full: bool = False
) -> list | dict:
    """UI hierarchy as parsed JSON. Primary observation channel — prefer this
    over screenshots. First call installs a layout instrumentation server on
    the device (slow once). Fails on WebView/animation screens: callers must
    then fall back to an annotated screenshot."""
    argv = ["layout"]
    target = resolve_serial(serial)
    if target:
        argv.append(f"--device={target}")
    if flat:
        argv.append("--flat")
    if full:
        argv.append("--full")
    raw = _run_android(argv, timeout=max(_DEFAULT_TIMEOUT, 60.0))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise AdbError(
            "Could not read layout (often a WebView or animation on screen). "
            "Fall back to screenshot(annotate=true). "
            f"Raw head: {raw[:200].strip()}"
        )


def png_dimensions(png: bytes) -> tuple[int | None, int | None]:
    """Width/height from the PNG IHDR chunk (no imaging deps needed)."""
    if len(png) >= 24 and png[:8] == b"\x89PNG\r\n\x1a\n":
        import struct

        w, h = struct.unpack(">II", png[16:24])
        return w, h
    return None, None


def take_screenshot(
    serial: str | None = None,
    annotate: bool = False,
    save_to: str | None = None,
) -> dict:
    """Capture the screen. Fallback-only: call only when get_layout fails or
    the question is genuinely visual. ALWAYS writes to an explicit path —
    the CLI defaults to ./screenshot.png (repo pollution) when --output is
    omitted. Rate-limited to 1 capture per 10s."""
    global _last_capture
    now = time.monotonic()
    wait = _SCREENSHOT_MIN_INTERVAL - (now - _last_capture)
    if wait > 0:
        raise AdbError(
            f"Screenshot rate-limited: retry in {wait:.0f}s. "
            "Prefer get_layout for re-observation."
        )
    target = resolve_serial(serial)
    if save_to:
        dest = Path(save_to)
        if dest.suffix.lower() not in (".png", ""):
            raise AdbError("save_to must be a .png path.")
        if dest.suffix == "":
            dest = dest.with_suffix(".png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = False
    else:
        tmpdir = tempfile.mkdtemp(prefix="mobile-mcp-")
        dest = Path(tmpdir) / "screenshot.png"
        tmp = True
    argv = ["screen", "capture", f"--output={dest}"]
    if annotate:
        argv.append("--annotate")
    if target:
        argv.append(f"--device={target}")
    _run_android(argv, timeout=max(_DEFAULT_TIMEOUT, 60.0))
    _last_capture = time.monotonic()
    data = dest.read_bytes()
    w, h = png_dimensions(data)
    return {"data": data, "path": str(dest), "width": w, "height": h, "tmp": tmp}


def cleanup_screenshot(path: str, tmp: bool) -> None:
    if tmp:
        try:
            Path(path).unlink(missing_ok=True)
            Path(path).parent.rmdir()
        except OSError:
            pass


def tap_element(screenshot_path: str, template: str) -> str:
    """Substitute #N labels from an annotated screenshot into a command
    template, e.g. template="input tap #3"."""
    if not Path(screenshot_path).is_file():
        raise AdbError(f"Screenshot not found: {screenshot_path}")
    return _run_android(
        ["screen", "resolve", f"--screenshot={screenshot_path}", f"--string={template}"]
    ).strip()


# ---- input -------------------------------------------------------------------


def tap(x: int, y: int, serial: str | None = None) -> str:
    return run_device_shell(["input", "tap", str(x), str(y)], serial)


def swipe(
    x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300,
    serial: str | None = None,
) -> str:
    return run_device_shell(
        ["input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
        serial,
    )


def key_event(code: str, serial: str | None = None) -> str:
    """Send a keyevent: BACK, HOME, ENTER, SLEEP, WAKEUP, APP_SWITCH, …"""
    code = code.strip()
    if not _VALID_KEYCODE.match(code):
        raise AdbError(f"Invalid key code '{code}'. Use alphanumeric/underscore only.")
    if not code.startswith("KEYCODE_"):
        code = "KEYCODE_" + code.upper()
    return run_device_shell(["input", "keyevent", code], serial)


def input_text(text: str, serial: str | None = None) -> str:
    """Type into the focused field. ASCII only; spaces become %s (adb
    convention). Shell metacharacters are rejected — focus the field first
    (tap its layout center) and keep payloads simple."""
    if not text:
        raise AdbError("Nothing to type: text is empty.")
    bad = sorted({c for c in text if c in _FORBIDDEN_TEXT_CHARS or ord(c) > 127})
    if bad:
        raise AdbError(
            f"Refusing to type characters {bad!r} (injection-unsafe for "
            "`input text`). Type a simpler string."
        )
    return run_device_shell(["input", "text", text.replace(" ", "%s")], serial)


# ---- apps --------------------------------------------------------------------


def list_packages(
    serial: str | None = None,
    third_party_only: bool = False,
    filter: str | None = None,
) -> list[str]:
    argv = ["pm", "list", "packages"]
    if third_party_only:
        argv.append("-3")
    # Filtering is done in Python (not `pm … | grep`) to keep device-shell
    # args injection-safe.
    out = run_device_shell(argv, serial)
    pkgs = [
        line.partition(":")[2].strip()
        for line in out.splitlines()
        if line.startswith("package:")
    ]
    if filter:
        q = filter.lower()
        pkgs = [p for p in pkgs if q in p.lower()]
    return pkgs


def launch_app(
    package: str, activity: str | None = None, serial: str | None = None
) -> str:
    """Launch an installed app. Explicit activity → `am start -n`; otherwise
    the launcher intent via `monkey`."""
    if not re.fullmatch(r"[A-Za-z0-9_.]+", package):
        raise AdbError(f"Invalid package name '{package}'.")
    if activity:
        if not re.fullmatch(r"[A-Za-z0-9_./]+", activity):
            raise AdbError(f"Invalid activity '{activity}'.")
        # am wants pkg/.Activity, pkg/pkg.Activity, or a fully-qualified name.
        if activity.startswith("."):
            name = package + activity
        elif "/" in activity or activity.startswith(package):
            name = activity
        else:
            name = f"{package}/{activity}"
        return run_device_shell(["am", "start", "-W", "-n", name], serial)
    out = run_device_shell(
        ["monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        serial,
    )
    if "No activities found" in out:
        raise AdbError(
            f"No launchable activity for '{package}'. Pass activity= explicitly."
        )
    return out.strip()


def force_stop(package: str, serial: str | None = None) -> str:
    _require_package(package)
    return run_device_shell(["am", "force-stop", package], serial) or "stopped"


def clear_app_data(package: str, serial: str | None = None) -> str:
    """Wipe an app's data (destructive — confirm with the user first)."""
    _require_package(package)
    return run_device_shell(["pm", "clear", package], serial).strip()


def uninstall_app(package: str, serial: str | None = None) -> str:
    """Remove an app (destructive — confirm with the user first)."""
    _require_package(package)
    return _run_adb(["uninstall", package], serial).strip()


def _require_package(package: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.]+", package or ""):
        raise AdbError(f"Invalid package name '{package}'.")


def _allowed_install_dirs() -> list[Path]:
    raw = os.environ.get("ANDROID_ADB_ALLOWED_INSTALL_DIRS", "/tmp/")
    return [Path(p.strip()).resolve() for p in raw.split(",") if p.strip()]


def install_apk(
    host_path: str, serial: str | None = None, install_options: str | None = None
) -> str:
    """Delta-install APK(s) via `android install` (faster than adb install).
    host_path must live under ANDROID_ADB_ALLOWED_INSTALL_DIRS (default /tmp/)
    — symlink escapes are rejected. Comma-separated paths allowed."""
    first = host_path.split(",")[0].strip()
    p = Path(first).expanduser()
    if p.is_symlink():
        raise AdbError(f"Refusing symlinked APK path: {first}")
    resolved = p.resolve()
    allowed = _allowed_install_dirs()
    if not resolved.is_file() or resolved.suffix.lower() != ".apk":
        raise AdbError(f"APK not found (must end .apk): {first}")
    if not any(
        resolved == d or (d.is_dir() and resolved.is_relative_to(d)) for d in allowed
    ):
        names = ", ".join(str(d) for d in allowed)
        raise AdbError(
            f"APK outside allowed install dirs ({names}). "
            "Set ANDROID_ADB_ALLOWED_INSTALL_DIRS to include it."
        )
    argv = ["install", f"--apks={host_path}"]
    target = resolve_serial(serial)
    if target:
        argv.append(f"--device={target}")
    if install_options:
        if not re.fullmatch(r"[A-Za-z0-9\-, ]+", install_options):
            raise AdbError("install_options may only contain flags like -g,-d.")
        argv.append(f"--install-options={install_options}")
    return _run_android(argv, timeout=max(_DEFAULT_TIMEOUT, 180.0)).strip()


# ---- files --------------------------------------------------------------------


def pull_file(device_path: str, host_dest: str, serial: str | None = None) -> str:
    _require_abs_device_path(device_path)
    dest = Path(host_dest).expanduser()
    if dest.suffix == "" or host_dest.endswith("/"):
        dest.mkdir(parents=True, exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
    return _run_adb(["pull", device_path, str(dest)], serial).strip()


def push_file(host_src: str, device_dest: str, serial: str | None = None) -> str:
    src = Path(host_src).expanduser()
    if not src.is_file():
        raise AdbError(f"Host file not found: {host_src}")
    _require_abs_device_path(device_dest)
    return _run_adb(["push", str(src), device_dest], serial).strip()


def list_files(device_path: str, serial: str | None = None) -> str:
    _require_abs_device_path(device_path)
    return run_device_shell(["ls", "-la", device_path], serial)


def delete_file(device_path: str, serial: str | None = None) -> str:
    """Delete a file on device. Refuses protected roots. Destructive —
    confirm with the user first."""
    norm = os.path.normpath(device_path)
    if norm in _PROTECTED_DELETE_ROOTS or not norm.startswith("/"):
        raise AdbError(
            f"Refusing to delete protected path '{device_path}'. "
            "Delete a specific file under /sdcard or the app sandbox."
        )
    return run_device_shell(["rm", norm], serial) or "deleted"


def _require_abs_device_path(p: str) -> None:
    if not p or not os.path.normpath(p).startswith("/"):
        raise AdbError(f"Device path must be absolute: '{p}'.")


# ---- emulator ------------------------------------------------------------------


def emulator_list(long: bool = False) -> str:
    argv = ["emulator", "list"]
    if long:
        argv.append("--long")
    return _run_android(argv).strip() or "(no virtual devices)"


def emulator_start(avd: str, cold: bool = False) -> str:
    """Start an AVD. Blocks until the emulator is ready (up to ~5 min)."""
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", avd or ""):
        raise AdbError(f"Invalid AVD name '{avd}'.")
    argv = ["emulator", "start"]
    if cold:
        argv.append("--cold")
    argv.append(avd)
    return _run_android(argv, timeout=_EMULATOR_START_TIMEOUT).strip()


def emulator_stop(device: str | None = None) -> str:
    argv = ["emulator", "stop"]
    if device:
        argv.append(device)
    return _run_android(argv).strip()


# ---- system ---------------------------------------------------------------------


def logcat(
    serial: str | None = None, lines: int = 200, clear: bool = False
) -> str:
    if clear:
        _run_adb(["logcat", "-c"], serial)
        return "logcat buffer cleared"
    out = _run_adb(["logcat", "-d"], serial)
    tail = out.splitlines()[-max(1, lines):]
    return "\n".join(tail)


def get_prop(name: str | None = None, serial: str | None = None) -> str:
    if name:
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
            raise AdbError(f"Invalid property name '{name}'.")
        return run_device_shell(["getprop", name], serial).strip()
    return run_device_shell(["getprop"], serial)


def device_info(serial: str | None = None) -> dict:
    target = resolve_serial(serial)
    props = run_device_shell(
        ["getprop"], target
    )
    want = {
        "ro.product.manufacturer": None,
        "ro.product.model": None,
        "ro.build.version.release": None,
        "ro.build.version.sdk": None,
    }
    for line in props.splitlines():
        m = re.match(r"\[(.+?)\]: \[(.*)\]", line)
        if m and m.group(1) in want:
            want[m.group(1)] = m.group(2)
    try:
        size = run_device_shell(["wm", "size"], target).strip()
    except AdbError:
        size = "unknown"
    return {
        "serial": target or "(single device)",
        "manufacturer": want["ro.product.manufacturer"],
        "model": want["ro.product.model"],
        "android": want["ro.build.version.release"],
        "sdk": want["ro.build.version.sdk"],
        "display": size,
    }


def reboot(mode: str | None = None, serial: str | None = None) -> str:
    """Reboot the device (destructive — confirm with the user first).
    mode: bootloader | recovery | None (normal)."""
    argv = ["reboot"]
    if mode:
        if mode not in ("bootloader", "recovery"):
            raise AdbError("mode must be 'bootloader' or 'recovery'.")
        argv.append(mode)
    _run_adb(argv, serial)
    return f"rebooting ({mode or 'normal'})"


# ---- opt-in raw shell ------------------------------------------------------------


def shell_allowed() -> tuple[bool, list[str]]:
    allowed = [
        c.strip() for c in os.environ.get(
            "ANDROID_ADB_ALLOWED_COMMANDS", _DEFAULT_ALLOWED_COMMANDS
        ).split(",") if c.strip()
    ]
    on = os.environ.get("ANDROID_ADB_ALLOW_SHELL", "").lower() in ("1", "true")
    return on, allowed


def run_shell(
    command: str, args: list[str] | None = None, serial: str | None = None
) -> str:
    """Escape hatch. OFF unless ANDROID_ADB_ALLOW_SHELL=1, and the first token
    must be in ANDROID_ADB_ALLOWED_COMMANDS. Args are centrally quoted."""
    on, allowed = shell_allowed()
    if not on:
        raise AdbError(
            "Raw shell is disabled. Set ANDROID_ADB_ALLOW_SHELL=1 to enable, "
            "optionally narrowing ANDROID_ADB_ALLOWED_COMMANDS."
        )
    if (command or "").strip() not in allowed:
        raise AdbError(
            f"Command '{command}' not in ANDROID_ADB_ALLOWED_COMMANDS "
            f"({', '.join(allowed)})."
        )
    return run_device_shell([command] + list(args or []), serial)
