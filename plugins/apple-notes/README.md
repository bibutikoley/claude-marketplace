# apple-notes-mcp

MCP server giving CRUD access to Apple Notes on macOS — built from
scratch (Python + [uv](https://github.com/astral-sh/uv) + the official `mcp` SDK),
driving Notes.app through JXA (`osascript -l JavaScript`). No RAG, no vector
index, no Full Disk Access: Notes.app itself is the source of truth, queried
live on every call, all locally.

Works with any MCP client: Claude Code, Claude Desktop, Cursor, VS Code
(Copilot), Windsurf, Cline, Roo Code, Codex CLI, Gemini CLI, opencode, and any other
client that supports stdio MCP servers.

> [!NOTE]
> By default the server has access to **all** your Apple Notes.
> To limit it to specific folders, set `APPLE_NOTES_MCP_ALLOWED_FOLDERS`
> (comma-separated folder names or full paths, e.g.
> `iCloud/Work,iCloud/Personal`) in the server's environment — see
> [Access scope](#access-scope).

## Tools

| Tool | Purpose |
|------|---------|
| `list_notes` | Notes by id/title/folder/modified; filter by folder or date, limit |
| `get_note` | Full note: HTML body, plaintext, Markdown (default), folder, created/modified, id |
| `create_note` | Create with title + Markdown (default) or plaintext body, optionally in a folder path |
| `update_note` | Replace entire body (Markdown by default); first heading/line becomes the new title (Notes semantics) |
| `append_note` | Append/prepend Markdown (default) or plaintext without replacing existing content |
| `delete_note` | Delete (moves to **Recently Deleted** — note stays resolvable there) |
| `search_notes` | Case-insensitive substring search on titles, or bodies (`search_content`) |
| `list_folders` | All folders as `Account/Folder/Subfolder` paths |
| `create_folder` | Create folder at default account root (idempotent) |
| `delete_folder` | Delete an empty folder; bare name or full path |
| `health_check` | Reachability + automation permission diagnostics |

## Install

### Claude Code (native plugin, recommended for Claude Code users)

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install apple-notes-mcp@claude-marketplace
```

Or standalone, without the marketplace (no clone needed), pinned to `v0.3.0`
(recommended — reproducible; drop `@v0.3.0` to track `main`):

```bash
claude mcp add apple-notes -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes" apple-notes-mcp
```

Then restart Claude Code (or `/mcp` to reload), and on the first tool call click
**OK** on the macOS Automation prompt ("‹your terminal› would like to control
Notes"). That one grant is all the access the server needs.

### Other agents

Claude Desktop, Cursor, VS Code, Windsurf, Cline, Roo Code, Codex CLI,
Gemini CLI, opencode, or any other stdio MCP client.

No clone needed — point your client straight at the repo and `uvx` fetches,
builds, and caches the server on first run (needs
[uv](https://github.com/astral-sh/uv) installed, which provides `uvx`).
Prefer a local checkout instead (e.g. for development)? See
[Option B](#option-b--local-clone) — same configs, just a different
`--from` value.

#### Let your agent configure itself

Paste the block below to your agent as-is. It detects which client it is
running in, writes the entry into that client's own MCP config (backing it
up first), and tells you how to activate it.

```text
You are an AI agent running inside an MCP client (Claude Code, Claude Desktop, Cursor, VS Code with Copilot, Windsurf Cascade, Cline, Roo Code, Codex CLI, Gemini CLI, opencode, or another MCP-compatible app). Configure the "apple-notes" MCP server for YOURSELF — write it into the MCP configuration of the client you are currently running in. Make the edit yourself; do not just print instructions.

Step 1 — OS check. Run `uname -s`. If the result is not `Darwin`, STOP and tell me this server needs macOS with Notes.app.

Step 2 — Prerequisite check. Run `uvx --version`. If uvx is missing, STOP and tell me to install uv first from https://github.com/astral-sh/uv, then re-run this prompt once it is available.

Step 3 — Detect your client and pick ONE config target (default to global/user scope unless I ask for project scope):
- Claude Code CLI: just run `claude mcp add apple-notes -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes" apple-notes-mcp`, then skip to Step 6.
- Claude Desktop: file ~/Library/Application Support/Claude/claude_desktop_config.json, JSON shape {"mcpServers": {...}}.
- Cursor: file ~/.cursor/mcp.json (global) or .cursor/mcp.json in the current project, JSON shape {"mcpServers": {...}}.
- VS Code (Copilot/Agent): file .vscode/mcp.json in the current project. NOTE: this file uses a "servers" key, NOT "mcpServers".
- Windsurf: file ~/.codeium/windsurf/mcp_config.json, JSON shape {"mcpServers": {...}}.
- Cline: the extension's MCP settings file (cline_mcp_settings.json), JSON shape {"mcpServers": {...}}.
- Roo Code: global MCP settings (mcp_settings.json) or project .roo/mcp.json, JSON shape {"mcpServers": {...}}.
- Codex CLI: file ~/.codex/config.toml, TOML table [mcp_servers.apple-notes] (key mcp_servers with underscore).
- Gemini CLI: file ~/.gemini/settings.json (global) or .gemini/settings.json (project), JSON shape {"mcpServers": {...}}.
- opencode: file opencode.json — project ./opencode.json (or .opencode/opencode.json) or global ~/.config/opencode/opencode.json, JSON shape {"mcp": {...}} with type "local". NOTE: opencode does NOT use "mcpServers", "servers", "command"+"args", or "env" — it uses "mcp", "command" as one array, and "environment".
- Anything else: ASK me which file your client reads for MCP servers before writing anything. If you cannot determine your client, ASK me instead of guessing.

Step 4 — Back up, then merge. If the file exists, back it up with a .bak suffix first. Add ONLY the "apple-notes" entry and preserve every existing entry. Create parent folders if needed. Minimal new-file skeletons: {"mcpServers": {}} for mcpServers clients, {"servers": {}} for VS Code, {"mcp": {}} for opencode (plus "$schema": "https://opencode.ai/config.json"), and for Codex just the table below in an empty file.

Entry values (default, no clone needed):
- command: uvx
- args: ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
- Codex TOML form:
  [mcp_servers.apple-notes]
  command = "uvx"
  args = ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
- opencode form (merge under top-level "mcp"):
  {"mcp": {"apple-notes": {"type": "local", "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"]}}}

If I say I have a local clone of bibutikoley/claude-marketplace, use it instead: replace the --from value with the absolute path to its plugins/apple-notes directory (absolute path only, never relative).

If I give you a folder allowlist, add env {"APPLE_NOTES_MCP_ALLOWED_FOLDERS": "the comma-separated list I gave you"} to the entry — except opencode, where the key is "environment" (not "env").

Step 5 — Validate. Re-read the file and prove it still parses: for a JSON file run python3 -m json.tool with the file as its argument; for a TOML file run python3 -c "import tomllib,sys; tomllib.load(open(sys.argv[1],'rb'))" with the file path as its argument. Show me the entry you added.

Step 6 — Tell me how to activate it in THIS client (fully quit and reopen Claude Desktop with Cmd-Q; restart Cursor / Windsurf / VS Code; /mcp or `claude mcp list` for Claude Code; /mcp list for Gemini; quit and restart opencode; MCP panel for Cline/Roo), remind me to click OK when macOS asks to let my terminal control Notes.app, and offer to call the health_check tool to confirm it works.
```

#### Option A — no clone (recommended)

Canonical config — works for most clients (`mcpServers` shape):

```json
{
  "mcpServers": {
    "apple-notes": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
    }
  }
}
```

With an access-scope allowlist (optional):

```json
{
  "mcpServers": {
    "apple-notes": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"],
      "env": {
        "APPLE_NOTES_MCP_ALLOWED_FOLDERS": "iCloud/Work,iCloud/Personal"
      }
    }
  }
}
```

| Client | Where to put it |
|--------|-----------------|
| **Claude Desktop** | `~/Library/Application Support/Claude/claude_desktop_config.json` — paste under `mcpServers`, then fully quit (`Cmd-Q`) and reopen. |
| **Cursor** | `~/.cursor/mcp.json` (global, every project) or `.cursor/mcp.json` (project-only). Same `mcpServers` shape. Or Settings → Tools & Integrations → New MCP Server. Restart Cursor. |
| **VS Code (Copilot / Agent)** | `.vscode/mcp.json` (workspace) or `MCP: Open User Configuration` (global). VS Code uses a `servers` key instead of `mcpServers`: |
| **Windsurf (Cascade)** | `~/.codeium/windsurf/mcp_config.json` (macOS/Linux). Same `mcpServers` shape. Or Cascade panel → `…` → View raw config. Restart Windsurf. |
| **Cline** | Cline panel → MCP Servers icon → Configure tab → Configure MCP Servers (opens `cline_mcp_settings.json`). Same `mcpServers` shape. Or CLI: `~/.cline/data/settings/cline_mcp_settings.json`. |
| **Roo Code** | Roo pane → ⚙️ → MCP Servers → Edit Global MCP (`mcp_settings.json`) or Edit Project MCP (`.roo/mcp.json`). Same `mcpServers` shape. |
| **Codex CLI** | `~/.codex/config.toml` uses TOML under `mcp_servers` (see snippet below). |
| **Gemini CLI** | `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project). Same `mcpServers` shape. Then `/mcp list` to verify. |
| **opencode** | `opencode.json` — project `./opencode.json` (or `.opencode/opencode.json`) or global `~/.config/opencode/opencode.json`. Uses `mcp` + `type: local` (see snippet below). Quit and restart opencode. |
| **Any other stdio MCP client** (Zed, Amp, Goose, …) | Paste the canonical config wherever the client reads `mcpServers`. |

VS Code (`.vscode/mcp.json`) variant:

```json
{
  "servers": {
    "apple-notes": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
    }
  }
}
```

Codex CLI (`~/.codex/config.toml`) variant:

```toml
[mcp_servers.apple-notes]
command = "uvx"
args = ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
```

opencode (`opencode.json`) variant — note `mcp` (not `mcpServers`),
`command` as one array, and `environment` (not `env`):

```json
{
  "mcp": {
    "apple-notes": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"],
      "environment": {
        "APPLE_NOTES_MCP_ALLOWED_FOLDERS": ""
      }
    }
  }
}
```

With an access-scope allowlist, set the value instead of leaving it blank:

```json
{
  "mcp": {
    "apple-notes": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.3.0#subdirectory=plugins/apple-notes", "apple-notes-mcp"],
      "environment": {
        "APPLE_NOTES_MCP_ALLOWED_FOLDERS": "iCloud/Work,iCloud/Personal"
      }
    }
  }
}
```

#### Option B — local clone

Clone once, then use the checkout's absolute path as the `--from` value
(`uvx --from` needs an absolute path, not a relative one):

```bash
git clone https://github.com/bibutikoley/claude-marketplace.git
# e.g. /Users/you/claude-marketplace/plugins/apple-notes
```

```json
{
  "mcpServers": {
    "apple-notes": {
      "command": "uvx",
      "args": ["--from", "<ABSOLUTE-PATH>/plugins/apple-notes", "apple-notes-mcp"]
    }
  }
}
```

Same swap applies to the other shapes: in the VS Code (`servers`), Codex
(`mcp_servers`), and opencode (`mcp`) snippets above, replace the `git+https://…` value with
`<ABSOLUTE-PATH>/plugins/apple-notes`.

Notes:

- First start of Option A takes ~30s (clone + build + dependency install);
  after that `uvx` reuses its cache and starts fast. To pick up updates, run
  `uv tool update apple-notes-mcp` or bump the pin below.
- All snippets above default to the pinned `@v0.3.0` form. To track `main`
  instead (mutable, not reproducible), drop the `@v0.3.0` from the URL.
  To move to another ref, swap in `@<commit-or-tag>` before the `#`.

After configuring any client, trigger one tool (e.g. ask it to list folders) and
click **OK** on the macOS Automation prompt. Verify with the `health_check`
tool. macOS + Notes.app only; no Node required.

## Behavior notes

- **Format** (`format="markdown"` default, or `"plaintext"`): `create_note`,
  `update_note`, `append_note` accept Markdown by default (rendered to HTML
  with the `markdown` package: `extra` + `sane_lists`) or plaintext
  (`format="plaintext"`). `get_note` returns `html` + `plaintext` plus
  `markdown` (via `markdownify`, ATX headings) when `format="markdown"`.
  Notes.app itself only stores HTML — Markdown is converted on write and
  re-derived on read, so round-trips are lossy for exotic constructs.
- **Titles** live in the body as the first line — exactly like editing in
  Notes.app. `create_note` writes `<h1>title</h1>`; `update_note` derives the
  new title from `content`'s first heading/line.
- **Folders** are addressed by the full paths `list_folders` returns
  (`iCloud/Work`); a bare name resolves under the default account.
- **Delete is soft**: notes land in Recently Deleted, remain listable/gettable,
  and must be purged manually in Notes.app (AppleScript can't empty trash).
- **Performance**: scans broadcast one Apple event per property
  (`Notes.notes.name()`, `Notes.notes.id()`); folders resolve per note, so
  folder-filtered lists are slower than unfiltered ones. Raise
  `APPLE_NOTES_MCP_TIMEOUT_MS` (default 30000) for very large libraries.
- Plaintext (`format="plaintext"`) converts newlines to `<br>`; `&`, `<`, `>`
  are HTML-escaped. Body writes are HTML under the hood, matching how Notes
  stores them.

## Access scope

Set `APPLE_NOTES_MCP_ALLOWED_FOLDERS` to restrict every tool to a folder
allowlist (comma-separated names or full paths). Unset = unrestricted.

```bash
APPLE_NOTES_MCP_ALLOWED_FOLDERS="iCloud/Work,iCloud/Personal" claude
```

Or for a standalone install:

```bash
claude mcp add apple-notes -s user \
  -e APPLE_NOTES_MCP_ALLOWED_FOLDERS="iCloud/Work,iCloud/Personal" \
  -- uvx --from <path-to>/plugins/apple-notes apple-notes-mcp
```

Entries match by full path or bare leaf name: a full-path entry like
`iCloud/Work` matches ONLY `iCloud/Work` (not `On My Mac/Work`), while a
bare entry like `Work` matches any folder whose last segment is `Work` —
prefer full paths like `iCloud/Work` to be precise). In scope: `list_notes` / `search_notes` / `list_folders` only
return allowed folders; anything outside fails with an "outside the
configured access scope" error. `create_note` then requires an explicit
`folder`. Confirm the active scope any time with `health_check`.

## Runtime notes

- macOS + Notes.app only; Node not required, Python ≥ 3.12 via uv.
- Concurrency: AppleScript calls are serialized behind a lock (Notes accepts one
  scripting client at a time).
- Errors (permission denied, folder missing, note gone) come back as clear MCP
  tool outputs, not crashes.

## Files

- `main.py` — MCP server: 11 tools on `mcp.server.mcpserver.MCPServer`
- `notes.py` — JXA bridge: script generation, escaping, timeouts, error mapping

Verified end-to-end on macOS Sequoia 26 with a live iCloud account: full CRUD
round-trip (create → search → get → append → update → delete) through the MCP
JSON-RPC protocol.