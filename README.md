# claude-marketplace

**[Live demo →](https://bibutikoley.github.io/claude-marketplace/)**

Claude Code plugin marketplace. Currently ships one plugin: **apple-notes** —
an MCP server giving Claude Code CRUD access to Apple Notes on macOS
(Python + `uv` + the official `mcp` SDK, driving Notes.app through JXA).
No RAG, no vector index, no Full Disk Access: Notes.app is the source of
truth, queried live on every call, all locally.

## Prerequisites

- macOS with Notes.app
- [uv](https://github.com/astral-sh/uv) installed (Python ≥ 3.12)

## Install

Add the marketplace, then install the plugin:

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install apple-notes@apple-notes-mcp
```

On the first tool call, click **OK** on the macOS Automation prompt
("‹your terminal› would like to control Notes"). That one grant is all the
access the server needs.

Standalone alternative (without the marketplace):

```bash
claude mcp add apple-notes -s user -- uvx --from <path-to>/plugins/apple-notes apple-notes-mcp
```

## Contents

| Path | Purpose |
|------|---------|
| `.claude-plugin/marketplace.json` | Marketplace catalog |
| `plugins/apple-notes/` | The plugin (MCP server + `.mcp.json` + manifest) |
| `plugins/apple-notes/README.md` | Tool reference and behavior notes |
| `site/` | Landing page (Vite + Three.js, deployed to GitHub Pages) |

## Site development

```bash
cd site
npm install
npm run dev       # http://127.0.0.1:5173
npm run build     # production build → site/dist/
```

Pushes to `main` deploy `site/dist/` to GitHub Pages automatically
(Settings → Pages → Source: "GitHub Actions" on first setup).

## Versioning

The plugin is version-pinned (`0.1.0` in both `marketplace.json` and the
plugin's `plugin.json`). Users receive updates when the version is bumped.

## License

MIT — see [LICENSE](LICENSE).
