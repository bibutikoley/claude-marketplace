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
and **mobile-mcp**, an MCP server for Android phone control via ADB + the
`android` CLI (requires Android Studio + SDK; see
[`plugins/mobile-mcp/README.md`](plugins/mobile-mcp/README.md)).

## Prerequisites

- macOS with Notes.app
- [uv](https://github.com/astral-sh/uv) installed (Python ≥ 3.12)

> [!NOTE]
> By default the server has access to **all** your Apple Notes.
> Set `APPLE_NOTES_MCP_ALLOWED_FOLDERS` (comma-separated folder names or full
> paths) in the server's environment to restrict it to specific folders — see
> [`plugins/apple-notes/README.md`](plugins/apple-notes/README.md#access-scope).

## Install

### Claude Code

Add the marketplace, then install the plugin:

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install apple-notes@apple-notes-mcp
/plugin install mobile-mcp@apple-notes-mcp
```

On the first tool call, click **OK** on the macOS Automation prompt
("‹your terminal› would like to control Notes"). That one grant is all the
access the server needs.

Standalone alternative (without the marketplace, no clone needed):

```bash
claude mcp add apple-notes -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/apple-notes" apple-notes-mcp
```

### Other agents

Any MCP client can run the server over stdio — no marketplace needed. Just `uv` installed (provides `uvx`).

Option A — no clone (recommended):

```json
{
  "mcpServers": {
    "apple-notes": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace#subdirectory=plugins/apple-notes", "apple-notes-mcp"]
    }
  }
}
```

Option B — local clone: `git clone https://github.com/bibutikoley/claude-marketplace.git`,
then use `"--from", "<ABSOLUTE-PATH>/plugins/apple-notes"` as the `args` value above
(absolute path required).

Easiest of all: paste the [self-install prompt](plugins/apple-notes/README.md#let-your-agent-configure-itself)
to your agent and let it configure itself.

opencode (`opencode.json` — project `./opencode.json` or global
`~/.config/opencode/opencode.json`, quit and restart after editing):

```json
{
  "mcp": {
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
Codex TOML, and opencode `mcp` variants): see
[`plugins/apple-notes/README.md`](plugins/apple-notes/README.md#other-agents).

## Contents

| Path | Purpose |
|------|---------|
| `.claude-plugin/marketplace.json` | Marketplace catalog |
| `plugins/apple-notes/` | The plugin (MCP server + `.mcp.json` + manifest) |
| `plugins/apple-notes/README.md` | Tool reference and behavior notes |
| `plugins/mobile-mcp/` | The plugin (Android control via ADB + `android` CLI) |
| `plugins/mobile-mcp/README.md` | Tool reference, agent loop, and security model |
| `site/` | Landing page (Vite + Three.js, deployed to GitHub Pages — see [site/README.md](site/README.md)) |

## Versioning

The plugin is version-pinned (`0.1.0` in both `marketplace.json` and the
plugin's `plugin.json`). Users receive updates when the version is bumped.

## License

MIT — see [LICENSE](LICENSE).

Built by [Bibuti Koley](https://bibutikoley.github.io).
