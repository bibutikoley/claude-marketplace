# claude-marketplace

**[Live demo →](https://bibutikoley.github.io/claude-marketplace/)**

Claude Code plugin marketplace. Currently ships two plugins: **apple-notes** —
an MCP server giving CRUD access to Apple Notes on macOS
(Python + `uv` + the official `mcp` SDK, driving Notes.app through JXA).
No RAG, no vector index, no Full Disk Access: Notes.app is the source of
truth, queried live on every call, all locally. Works with Claude Code
natively, and with any other MCP client (Claude Desktop, Cursor, VS Code,
Windsurf, Cline, Roo Code, Codex CLI, Gemini CLI, opencode — see
[`plugins/apple-notes/README.md`](plugins/apple-notes/README.md#other-agents)) —
and **mobile-mcp**, a unified MCP server for cross-platform mobile device
control covering both Android (ADB + `android` CLI) and iOS (Xcode `simctl` +
`devicectl` + native Quartz UI automation; see
[`plugins/mobile-mcp/README.md`](plugins/mobile-mcp/README.md)).

## Prerequisites

- **General:** [uv](https://github.com/astral-sh/uv) installed (Python ≥ 3.12)
- **apple-notes:** macOS with Notes.app and Automation permissions
- **mobile-mcp (Android):** Android SDK command-line / platform-tools (`adb`) in `PATH`, USB debugging enabled or Android Emulator
- **mobile-mcp (iOS):** macOS with Xcode 15+ (`xcrun simctl` for Simulators, `xcrun devicectl` for physical iOS 17+ devices)

> [!NOTE]
> By default `apple-notes` has access to **all** your Apple Notes.
> Set `APPLE_NOTES_MCP_ALLOWED_FOLDERS` (comma-separated folder names or full
> paths) in the server's environment to restrict it to specific folders — see
> [`plugins/apple-notes/README.md`](plugins/apple-notes/README.md#access-scope).

## Install

### Claude Code

Add the marketplace, then install the plugins:

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install mobile-mcp@claude-marketplace
/plugin install apple-notes-mcp@claude-marketplace
```

On the first tool call, click **OK** on any macOS Automation prompts
(e.g., "‹your terminal› would like to control Notes"). That grant is all the
access the server needs.

Standalone alternative (without the marketplace, no clone needed):

```bash
# mobile-mcp
claude mcp add mobile-mcp -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/mobile-mcp" mobile-mcp

# apple-notes
claude mcp add apple-notes -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/apple-notes" apple-notes-mcp
```

### Other agents

Any MCP client can run the servers over stdio — no marketplace needed. Just `uv` installed (provides `uvx`).

Option A — no clone (recommended):

```json
{
  "mcpServers": {
    "mobile-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/mobile-mcp", "mobile-mcp"]
    },
    "apple-notes": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
    }
  }
}
```

Option B — local clone: `git clone https://github.com/bibutikoley/claude-marketplace.git`,
then use `"--from", "<ABSOLUTE-PATH>/plugins/mobile-mcp"` or `plugins/apple-notes` as the `args` value above
(absolute path required).

Easiest of all: paste the self-install prompt from the [live site](https://bibutikoley.github.io/claude-marketplace/)
to your agent and let it configure itself.

opencode (`opencode.json` — project `./opencode.json` or global
`~/.config/opencode/opencode.json`, quit and restart after editing):

```json
{
  "mcp": {
    "mobile-mcp": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/mobile-mcp", "mobile-mcp"]
    },
    "apple-notes": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/apple-notes", "apple-notes-mcp"],
      "environment": {
        "APPLE_NOTES_MCP_ALLOWED_FOLDERS": ""
      }
    }
  }
}
```

Full per-client guide (config file paths for Claude Desktop, Cursor, VS Code,
Windsurf, Cline, Roo Code, Codex CLI, Gemini CLI, opencode, plus the VS Code `servers`,
Codex TOML, and opencode `mcp` variants): see the [live site](https://bibutikoley.github.io/claude-marketplace/)
or [`plugins/apple-notes/README.md`](plugins/apple-notes/README.md#other-agents).

## Contents

| Path | Purpose |
|------|---------|
| `.claude-plugin/marketplace.json` | Marketplace catalog |
| `plugins/apple-notes/` | The plugin (MCP server + `.mcp.json` + manifest) |
| `plugins/apple-notes/README.md` | Tool reference and behavior notes |
| `plugins/mobile-mcp/` | The plugin (Unified Android + iOS mobile device automation) |
| `plugins/mobile-mcp/README.md` | Tool reference, agent loop, and security model |
| `site/` | Landing page (Vite + Three.js, deployed to GitHub Pages — see [site/README.md](site/README.md)) |

## Versioning

The plugin is version-pinned (`0.1.0` in both `marketplace.json` and the
plugin's `plugin.json`). Users receive updates when the version is bumped.

## License

MIT — see [LICENSE](LICENSE).

Built by [Bibuti Koley](https://bibutikoley.github.io).
