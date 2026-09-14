# Security policy

This repository ships privileged local infrastructure (`mobile-mcp`) and a
data-access server (`apple-notes-mcp`). Anyone who can call their tools
effectively holds the attached devices and the Notes library. Run pinned
releases (`@vX.Y.Z`), keep your MCP client's tool-approval prompts on, and
prefer test devices/emulators over daily-driver hardware.

## Threat model

- **Trusted:** your local machine, the attached test devices/simulators,
  and you (the operator approving tool calls).
- **Untrusted:** model-generated tool arguments (package names, paths,
  text, URLs, bundle IDs). Every value is validated or quoted server-side
  before it touches a shell, a device, or Notes.app.
- **Out of scope for the servers:** sandboxing the model itself, policing
  what you approve in your MCP client, or protecting a device you point at
  a hostile network. The servers assume the host is not compromised: an
  attacker with host code execution can read the same files the servers can.
- **No network attack surface:** both servers run over local stdio, make no
  outbound connections, and store nothing. The only secret in the repo's
  automation is GitHub's ephemeral `GITHUB_TOKEN` in the release workflow.

## Android shell

- `run_shell` is **disabled by default**. It refuses unless
  `ANDROID_ADB_ALLOW_SHELL=1` (or `true`).
- When enabled, the first token must be listed in
  `ANDROID_ADB_ALLOWED_COMMANDS` (default: `ls,cat,echo,pwd,pm,am,dumpsys,
  getprop,input,screencap,screenrecord,logcat,ps,wm,settings,uiautomator,
  cmd`). Anything else is rejected.
- Every subprocess runs as an `argv` vector (`shell=False`). All
  device-shell arguments pass through one central `shlex.quote` point, so
  values containing spaces, quotes, or metacharacters (`;`, `|`, `$`, …)
  stay inert data and can never inject a second command.
- Narrower allowlists compose: set both variables to confine the escape
  hatch to exactly the commands a task needs.

## Android filesystem

- `delete_file` requires an **absolute** device path and refuses protected
  roots and everything under them: `/` (exact match only), `/system`,
  `/vendor`, `/product`, `/apex`, `/data`, `/sbin`, `/proc`, `/sys`,
  `/dev`. `..` segments are normalized before the check, so traversal
  collapses into a refused prefix. Deleting under `/sdcard` or an app
  sandbox is allowed — and needs `confirm=true` (see below).
- `install_apk` only accepts `.apk` files living under
  `ANDROID_ADB_ALLOWED_INSTALL_DIRS` (default `/tmp/`, comma-separated).
  **Symlinks are rejected outright**, even when the target is allowed, and
  `--install-options` must match a flag pattern (`-g`, `-d`, …).
- `push_file` requires the host source to exist and the device destination
  to be absolute; `pull_file`/`list_files` require absolute device paths.
- `input_text` refuses shell metacharacters and non-ASCII; `key_event`
  accepts alphanumerics/underscores only; package, activity, AVD, property,
  and URL arguments are pattern-validated before use.

## iOS host filesystem

- `ios_install_app` (simulator `.app` bundles and device `.ipa`/`.app`
  files) is **deny-by-default**: with `IOS_ALLOWED_INSTALL_DIRS` unset or
  empty, every installation is refused.
- Set it to an `os.pathsep`-separated root list
  (`:` on macOS/Linux), e.g.
  `export IOS_ALLOWED_INSTALL_DIRS="$HOME/Developer/apps:$HOME/Developer/builds"`.
  `~` is expanded and every entry is resolved before comparison; nested
  paths inside an allowed root are accepted, anything else — including
  `..` traversal out of a root — is rejected.
- **Symlink policy:** symlinks are rejected outright (even when the target
  sits inside an allowed directory), matching Android's `install_apk`. Pass
  the real path.
- Execution stays shell-free: resolved paths travel as single `argv`
  elements to `simctl`/`devicectl`.
- Note: `ios_add_media` only reads existing host files into the Simulator
  Photos library; it is not allowlist-gated, so approve media paths as you
  would any file read.

## Physical device operations

- Physical-device tools (`ios_install_app`, `ios_uninstall_app`,
  `ios_launch_app`, `ios_terminate_app`, `ios_device_reboot`,
  `ios_device_info` with `device_type="device"`) require an explicit
  device `udid`/`device_uuid` and shell out to Apple's `devicectl`
  (Xcode 15+, iOS 17+); simulator tools use `simctl`.
- Uninstalling from, or rebooting, a physical device needs `confirm=true`.
  There is no remote access: the device must be USB-attached and trusted to
  the Mac. Prefer a dedicated test device.

## Destructive MCP operations

Server-side confirmation gates (checked in the server, not the prompt).
Without `confirm=true` the call fails with a `confirm_required` error and
**nothing executes**:

| Tool | Effect |
|---|---|
| `uninstall_app` | removes an Android app |
| `clear_app_data` | wipes an Android app's data |
| `delete_file` | deletes a device file |
| `reboot` | reboots the Android device |
| `ios_erase_simulator` | factory-resets a simulator |
| `ios_uninstall_app` | removes an iOS app |
| `ios_device_reboot` | reboots a physical iPhone/iPad |
| `update_note` | replaces an Apple Note's entire body |
| `delete_note` | moves an Apple Note to Recently Deleted |
| `delete_folder` | removes an empty Apple Notes folder |

Everything else acts **immediately** once called: taps, swipes, text input,
`launch_app`, `force_stop`, `install_apk`/`ios_install_app`, file
push/pull, permission/location/appearance changes, clipboard, and media
import. There is no undo. Your safety net for these is the MCP client's own
tool-approval flow — do not disable it for these servers.

## Apple Notes access

- By default the server can read and write **all** Notes. Set
  `APPLE_NOTES_MCP_ALLOWED_FOLDERS` (comma-separated names or full
  `Account/...` paths) to restrict it; `health_check` reports the active
  scope. Full-path entries match exactly (`iCloud/Work` does not grant
  `On My Mac/Work`); bare names match any folder with that leaf.
- Every read and write re-resolves the note's canonical `Account/...`
  folder live; out-of-scope notes fail closed, and `create_note` requires
  an explicit in-scope folder when scoped.
- `update_note` (full overwrite), `delete_note`, and `delete_folder` need
  `confirm=true`; `append_note` acts immediately. Deletes are soft
  (Recently Deleted, purged manually in Notes.app) but overwrites are not
  recoverable server-side.
- OS permission needed: one macOS Automation grant for controlling
  Notes.app. No Full Disk Access, no network, no stored data.

## Apple Events / JXA

- Notes automation runs one `osascript -l JavaScript` invocation per call
  (argv, never a shell string). All titles, bodies, folder names, and IDs
  are embedded via `json.dumps`, so values cannot break out of the script
  string context.
- Calls are serialized behind a lock (Notes.app accepts one scripting
  client at a time) with a configurable timeout
  (`APPLE_NOTES_MCP_TIMEOUT_MS`, default 30000). Permission denials surface
  as actionable errors (enable Automation for your terminal, then restart
  the server) rather than crashes.
- Simulator gestures use Quartz CoreGraphics mouse events plus AppleScript
  keystrokes, which require an Accessibility grant for your terminal/IDE.

## Credential handling

- There are no credentials to configure: no API keys, tokens, or passwords
  anywhere in either server. Environment variables carry only scope and
  safety configuration (`*_ALLOWED_*`, `*_ALLOW_SHELL`, timeouts).
- Installs default to pinned `@vX.Y.Z` URLs for reproducibility; per-plugin
  `uv.lock` files make `uv sync --project plugins/<name>` bit-identical to
  CI. `./scripts/verify.sh` runs the same gates locally that CI enforces.

## What the servers intentionally do not sandbox

- Non-destructive tools are ungated by design (see table above for what
  *is* gated). Taps, keystrokes, pastes, launches, installs, file
  transfers, and simulator setting changes happen on call.
- The servers do not rate-limit, audit-log, or multi-user-isolate: they are
  single-operator local tools. Do not expose them over a network boundary.

## Reporting security issues

Do not open a public issue for a suspected vulnerability. Email
bibutikoley@outlook.com with a description, affected version/tag, and
reproduction steps; allow reasonable time for a fix before disclosing.
General (non-sensitive) hardening ideas are welcome as public issues.
