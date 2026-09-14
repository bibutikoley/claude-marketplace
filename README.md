# claude-marketplace

**[Live demo →](https://bibutikoley.github.io/claude-marketplace/)**

Cross-platform MCP tools for AI coding agents — mobile device
automation, Apple Notes, and more. Currently ships two plugins: **mobile-mcp**,
a unified MCP server for cross-platform mobile device control covering
both Android (ADB + `android` CLI) and iOS (Xcode `simctl` + `devicectl` +
native Quartz UI automation; see
[`plugins/mobile-mcp/README.md`](plugins/mobile-mcp/README.md)) —
and **apple-notes-mcp**, an MCP server giving CRUD access to Apple Notes
on macOS (Python + `uv` + the official `mcp` SDK, driving Notes.app
through JXA).
No RAG, no vector index, no Full Disk Access: Notes.app is the source of
truth, queried live on every call, all locally. Works with Claude Code
natively, and with any other MCP client (Claude Desktop, Cursor, VS Code,
Windsurf, Cline, Roo Code, Codex CLI, Gemini CLI, opencode — see
[`plugins/apple-notes-mcp/README.md`](plugins/apple-notes-mcp/README.md#other-agents)).

## Prerequisites

- **General:** [uv](https://github.com/astral-sh/uv) installed (Python ≥ 3.12)
- **apple-notes-mcp:** macOS with Notes.app and Automation permissions
- **mobile-mcp (Android):** Android SDK command-line / platform-tools (`adb`) in `PATH`, USB debugging enabled or Android Emulator
- **mobile-mcp (iOS):** macOS with Xcode 15+ (`xcrun simctl` for Simulators, `xcrun devicectl` for physical iOS 17+ devices)

> [!NOTE]
> By default `apple-notes-mcp` has access to **all** your Apple Notes.
> Set `APPLE_NOTES_MCP_ALLOWED_FOLDERS` (comma-separated folder names or full
> paths) in the server's environment to restrict it to specific folders — see
> [`plugins/apple-notes-mcp/README.md`](plugins/apple-notes-mcp/README.md#access-scope).

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

Standalone alternative (without the marketplace, no clone needed).
Pinned to `v0.4.0` (recommended — reproducible; substitute a newer tag to upgrade):

```bash
# mobile-mcp
claude mcp add mobile-mcp -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace@v0.4.0#subdirectory=plugins/mobile-mcp" mobile-mcp

# apple-notes-mcp
claude mcp add apple-notes-mcp -s user -- uvx --from "git+https://github.com/bibutikoley/claude-marketplace@v0.4.0#subdirectory=plugins/apple-notes-mcp" apple-notes-mcp
```

To track `main` instead (mutable — you get updates without bumping, but
builds are not reproducible), drop the `@v0.4.0` from the URL.

### Other agents

Any MCP client can run the servers over stdio — no marketplace needed. Just `uv` installed (provides `uvx`).

Option A — no clone (recommended, pinned to `v0.4.0`):

```json
{
  "mcpServers": {
    "mobile-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.4.0#subdirectory=plugins/mobile-mcp", "mobile-mcp"]
    },
    "apple-notes-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.4.0#subdirectory=plugins/apple-notes-mcp", "apple-notes-mcp"]
    }
  }
}
```

Option B — local clone: `git clone https://github.com/bibutikoley/claude-marketplace.git`,
then use `"--from", "<ABSOLUTE-PATH>/plugins/mobile-mcp"` or `plugins/apple-notes-mcp` as the `args` value above
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
      "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.4.0#subdirectory=plugins/mobile-mcp", "mobile-mcp"]
    },
    "apple-notes-mcp": {
      "type": "local",
      "command": ["uvx", "--from", "git+https://github.com/bibutikoley/claude-marketplace@v0.4.0#subdirectory=plugins/apple-notes-mcp", "apple-notes-mcp"],
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
or [`plugins/apple-notes-mcp/README.md`](plugins/apple-notes-mcp/README.md#other-agents).

## Contents

| Path | Purpose |
|------|---------|
| `.claude-plugin/marketplace.json` | Marketplace catalog |
| `plugins/apple-notes-mcp/` | The plugin (MCP server + `.mcp.json` + manifest) |
| `plugins/apple-notes-mcp/README.md` | Tool reference and behavior notes |
| `plugins/mobile-mcp/` | The plugin (Unified Android + iOS mobile device automation) |
| `plugins/mobile-mcp/README.md` | Tool reference, agent loop, and security model |
| `site/` | Landing page (Vite + Three.js, deployed to GitHub Pages — see [site/README.md](site/README.md)) |

## Versioning

Single release train: `0.4.0` everywhere — `marketplace.json`, each
plugin's `plugin.json` / `pyproject.toml`, the MCP server versions
(derived from `pyproject.toml` via installed package metadata at runtime,
with a source-checkout fallback), `.mcp.json` server keys, and the pinned
install URLs plus current-version prose in the READMEs and `site/index.html`. Releases are
stamped with one command — `python3 scripts/bump_version.py <X.Y.Z>` —
and checked by `scripts/validate_marketplace.py` (names, versions,
descriptions, server strings, `.mcp.json` keys, pinned URLs/prose) plus
the release-system suite `tests/test_release.py`. CI installs from the
per-plugin `uv.lock` files (`uv sync --locked`), so
`uv sync --project plugins/<name>` reproduces CI exactly. All install
snippets default to the pinned
`git+https://...@v0.4.0#subdirectory=...` form; drop the `@v0.4.0` to
track `main`. History prose (`Removed in v0.3.0`, CHANGELOG headings) is
never auto-stamped. Tag the release after CI passes (`git tag vX.Y.Z`).

## Dependencies

Each plugin pins reproducible installs with its own `uv.lock`
(`uv sync --project plugins/<name>` reproduces CI exactly).
`pyproject.toml` bounds are `mcp>=1.0,<3`, `markdown>=3.10.3,<4`,
`markdownify>=1.2.3,<2`: lower bounds are the oldest verified working
releases, upper bounds hold back the next major. To upgrade a
dependency, bump the bound, run `uv lock --project plugins/<name>`,
and let the ruff + mypy + pytest gate prove the new version safe.

## License

MIT — see [LICENSE](LICENSE).

Built by [Bibuti Koley](https://bibutikoley.github.io).
