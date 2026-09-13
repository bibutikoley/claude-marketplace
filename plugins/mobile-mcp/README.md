# mobile-mcp

MCP server for Android phone control, built for developers — Python +
[uv](https://github.com/astral-sh/uv) + the official `mcp` SDK, driving
devices through `adb` (from Android Studio's SDK) and the official
[`android` CLI](https://developer.android.com/tools/agents/android-cli)
(layout, screenshots, emulator, delta installs). Hybrid by design: `android`
CLI for observation and deployment, raw `adb` for input, files, and system.

Works with any MCP client: Claude Code, Claude Desktop, Cursor, VS Code
(Copilot), Windsurf, Cline, Roo Code, Codex CLI, Gemini CLI, opencode, and any
other client that supports stdio MCP servers.

## Prerequisites

This plugin targets developers. The primary requirement is **Android Studio
installed** — that takes care of the SDK dependency scenario:

1. **Android Studio** with SDK Platform-Tools installed (SDK Manager).
2. Environment (e.g. in `~/.zshrc`):

   ```bash
   # Android SDK
   export ANDROID_HOME="$HOME/Library/Android/sdk"
   export ANDROID_SDK_ROOT="$ANDROID_HOME"

   # Android SDK tools
   export PATH="$PATH:$ANDROID_HOME/emulator"
   export PATH="$PATH:$ANDROID_HOME/platform-tools"
   export PATH="$PATH:$ANDROID_HOME/cmdline-tools/latest/bin"
   ```

3. The **`android` CLI** (separate small install — not bundled with Studio):

   ```bash
   brew install --cask android-cli
   # or: curl -fsSL https://dl.google.com/android/cli/latest/darwin_arm64/install.sh | bash
   ```

4. A phone with **USB debugging** enabled (Developer options → USB debugging),
   connected via USB — tap **Allow** on the on-device RSA prompt. Or use an
   emulator (`emulator_list` / `emulator_start`).

No `brew install android-platform-tools`, no Node, Python ≥ 3.12 via uv.

## The agent loop (layout-first)

```
launch → get_layout → act (tap/swipe/text) → get_layout → …
```

* **Observe with `get_layout` first** — cheap structured JSON (`text`,
  `content-desc`, `resource-id`, `center`, `interactions`). Tap coordinates
  come from node `center`s.
* **`screenshot` is fallback-only** — when layout fails (WebView, animations)
  or the question is genuinely visual. Never screenshot alongside a successful
  layout (full-res PNGs are ~7MB a turn).
* **Target fallback** — `screenshot(annotate=true)` + `tap_element` resolves
  `#N` labels to coordinates when layout can't see an element.
* Re-observe with `get_layout` after every action; scroll slowly when hunting
  off-screen elements.

## Tools

| Domain | Tool | Notes |
|---|---|---|
| health | `health_check` | adb + `android` CLI + SDK resolution, device list |
| devices | `list_devices`, `device_info` | serial/state/model, Android/SDK/display |
| observe | `get_layout` | **Primary.** UI tree JSON; `flat`/`full` options |
| | `screenshot` | Inline PNG image. Fallback-only, 1 per 10s |
| | `tap_element` | Resolve `#N` from an annotated screenshot |
| input | `tap`, `swipe`, `key_event`, `input_text` | Coords from layout centers; field must be focused before typing |
| apps | `list_packages` | `third_party_only`, `filter` substring |
| | `launch_app` | By package (launcher intent) or `package` + `activity` |
| | `force_stop` | |
| | `clear_app_data`, `uninstall_app` | Destructive — confirm first |
| | `install_apk` | `android install` delta; path allowlisted (below) |
| files | `pull_file`, `push_file`, `list_files` | Absolute device paths |
| | `delete_file` | Refuses `/`, `/system`, `/data`, … Destructive — confirm first |
| emulator | `emulator_list`, `emulator_start`, `emulator_stop` | `start` blocks until ready (~5 min max) |
| system | `logcat` | Last N lines (default 200), 100KB cap; `clear` to wipe |
| | `get_prop` | One property or all |
| | `reboot` | normal / bootloader / recovery. Destructive — confirm first |
| escape hatch | `run_shell` | Opt-in only (below) |

Every device tool takes an optional `serial`. Omitted → `$ADB_SERIAL` →
auto-selected when exactly one device is online → otherwise an error listing
serials.

## Install

### Claude Code (native plugin)

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install mobile-mcp@apple-notes-mcp
```

Or standalone, without the marketplace (no clone needed):

```bash
claude mcp add mobile-mcp -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/mobile-mcp" mobile-mcp
```

### Other agents

Same shape as the apple-notes plugin — point your client at the repo and
`uvx` fetches, builds, and caches the server on first run:

```json
{
  "mcpServers": {
    "mobile-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/mobile-mcp", "mobile-mcp"]
    }
  }
}
```

With a local clone, replace the `--from` value with the absolute path to
`plugins/mobile-mcp`. Verify with `health_check` after connecting your phone.

## Security model

* **No always-on arbitrary shell.** `run_shell` is disabled unless
  `ANDROID_ADB_ALLOW_SHELL=1`, and then only for commands in
  `ANDROID_ADB_ALLOWED_COMMANDS` (default: `ls,cat,echo,pwd,pm,am,dumpsys,
  getprop,input,screencap,screenrecord,logcat,ps,wm,settings,uiautomator,cmd`).
* **Injection-hardened.** Every device-shell invocation is `shlex.quote`d at
  one central point — package names, paths, and text can never inject a second
  command. `input_text` additionally rejects shell metacharacters and
  non-ASCII.
* **Install allowlist.** `install_apk` only accepts APKs under
  `ANDROID_ADB_ALLOWED_INSTALL_DIRS` (default `/tmp/`, comma-separated) and
  rejects symlinks.
* **Guarded deletes.** `delete_file` refuses `/`, `/system`, `/data`,
  `/vendor`, and other protected roots.
* **Env vars only, no config files on disk:**

  | Variable | Default | Purpose |
  |---|---|---|
  | `ADB_SERIAL` | auto (if 1 device) | Default target device |
  | `ADB_PATH` / `ANDROID_CLI_PATH` | SDK-derived / PATH | Binary overrides |
  | `ANDROID_ADB_TIMEOUT_MS` | `30000` | Per-command timeout |
  | `ANDROID_ADB_ALLOW_SHELL` | off | Enable `run_shell` |
  | `ANDROID_ADB_ALLOWED_COMMANDS` | (see above) | Shell allowlist |
  | `ANDROID_ADB_ALLOWED_INSTALL_DIRS` | `/tmp/` | APK source allowlist |

* Only run against a phone you own. Never expose wireless ADB (`:5555`, which
  has no authentication) to the open internet.

## Behavior notes

* **Screenshots always write to an explicit path** (temp dir unless `save_to`
  is given) — the `android` CLI defaults to `./screenshot.png` otherwise.
  Temp captures are read and cleaned up server-side; the inline image is what
  the agent sees.
* **First `get_layout` is slow once** (installs a layout instrumentation
  server on device); afterwards it is the cheapest call in the toolbox.
* **`layout --diff` is deprecated upstream** and intentionally unused — always
  fetch the full tree and let the agent diff.
* `install_apk` / `emulator_start` allow long timeouts (3–5 min); `logcat`
  output is truncated at 100KB.
* Concurrency: ADB calls are serialized behind a lock (one scripting client
  at a time). Errors (unauthorized RSA, offline device, ambiguous serial)
  come back as clear MCP tool outputs, not crashes.

## Files

* `main.py` — MCP server: 27 tools on `mcp.server.mcpserver.MCPServer`
* `adb.py` — bridge: binary discovery, serial resolution, runners, guards

Verified end-to-end on macOS with a live OnePlus device over USB: full
`health_check → list_devices → device_info → get_layout → screenshot →
list_packages` round-trip through the MCP JSON-RPC protocol, image content
included.
