# apple-notes-mcp

MCP server giving Claude Code CRUD access to Apple Notes on macOS — built from
scratch (Python + [uv](https://github.com/astral-sh/uv) + the official `mcp` SDK),
driving Notes.app through JXA (`osascript -l JavaScript`). No RAG, no vector
index, no Full Disk Access: Notes.app itself is the source of truth, queried
live on every call, all locally.

## Tools

| Tool | Purpose |
|------|---------|
| `list_notes` | Notes by id/title/folder/modified; filter by folder or date, limit |
| `get_note` | Full note: HTML body, plaintext, folder, created/modified, id |
| `create_note` | Create with title + plaintext body, optionally in a folder path |
| `update_note` | Replace entire body; first line becomes the new title (Notes semantics) |
| `append_note` | Append/prepend without replacing existing content |
| `delete_note` | Delete (moves to **Recently Deleted** — note stays resolvable there) |
| `search_notes` | Case-insensitive substring search on titles, or bodies (`search_content`) |
| `list_folders` | All folders as `Account/Folder/Subfolder` paths |
| `create_folder` | Create folder at default account root (idempotent) |
| `delete_folder` | Delete an empty folder; bare name or full path |
| `health_check` | Reachability + automation permission diagnostics |

## Install

Via this marketplace (recommended):

```bash
/plugin marketplace add bibutikoley/claude-marketplace
/plugin install apple-notes@apple-notes-mcp
```

Or standalone, without the marketplace:

```bash
claude mcp add apple-notes -s user -- uv run --project <path-to>/plugins/apple-notes main.py
```

Then restart Claude Code (or `/mcp` to reload), and on the first tool call click
**OK** on the macOS Automation prompt ("‹your terminal› would like to control
Notes"). That one grant is all the access the server needs.

## Behavior notes

- **Titles** live in the body as the first line — exactly like editing in
  Notes.app. `create_note` writes `<h1>title</h1>`; `update_note` derives the
  new title from `content`'s first line.
- **Folders** are addressed by the full paths `list_folders` returns
  (`iCloud/Work`); a bare name resolves under the default account.
- **Delete is soft**: notes land in Recently Deleted, remain listable/gettable,
  and must be purged manually in Notes.app (AppleScript can't empty trash).
- **Performance**: scans broadcast one Apple event per property
  (`Notes.notes.name()`, `Notes.notes.id()`); folders resolve per note, so
  folder-filtered lists are slower than unfiltered ones. Raise
  `APPLE_NOTES_MCP_TIMEOUT_MS` (default 30000) for very large libraries.
- Plaintext converts newlines to `<br>`; `&`, `<`, `>` are HTML-escaped.
  Body writes are HTML under the hood, matching how Notes stores them.

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