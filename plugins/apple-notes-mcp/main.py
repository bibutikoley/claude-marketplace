"""MCP server: Apple Notes CRUD for Claude Code.

Run:  uv run main.py
Register:  claude mcp add apple-notes-mcp -s user -- uv run --project <this dir> main.py

First tool call makes macOS show an Automation prompt (control Notes) — click OK.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

import notes


def _package_version() -> str:
    """Single source of truth: ``pyproject.toml`` ``version``.

    Resolved via installed package metadata when the distribution is
    installed (``uvx`` / ``uv run --project``), with a source-checkout
    fallback that parses the sibling ``pyproject.toml`` so ``python
    main.py`` from a clone reports the same version.
    """
    dist_name = "apple-notes-mcp"
    try:
        return _dist_version(dist_name)
    except PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parent / "pyproject.toml"
    try:
        import tomllib

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return str(data["project"]["version"])
    except Exception as e:
        raise RuntimeError(
            f"cannot determine {dist_name} version: not installed and {pyproject} unreadable ({e})"
        ) from e


mcp = MCPServer("apple-notes-mcp", version=_package_version())


def _ok(text: str, **extra) -> CallToolResult:
    """Tool result: human-readable text + machine-readable structured fields."""
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=extra)


def _err(text: str, **extra) -> CallToolResult:
    """Tool error with a server-enforced structured confirmation signal."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        is_error=True,
        structured_content=extra if extra else None,
    )


def _require_confirm(confirm: bool, op: str) -> CallToolResult | None:
    """Server-side guard for irreversible Notes mutations."""
    if not confirm:
        return _err(
            f"{op} can permanently change Notes data. "
            "Re-invoke with confirm=true after user approval.",
            operation=op,
            confirm_required=True,
        )
    return None


@mcp.tool()
def health_check() -> CallToolResult:
    """Verify Notes.app is reachable, automation permission is granted, and
    report the configured access scope (allowed folders, or unrestricted)."""
    try:
        info = notes.health()
        scope = sorted(notes.ALLOWED_FOLDERS) if notes.scoped() else None
        scope_text = "unrestricted" if scope is None else "restricted to: " + ", ".join(scope)
        return _ok(
            f"OK: Notes.app reachable, {info['accounts']} account(s), access scope: {scope_text}.",
            accounts=info["accounts"],
            allowed_folders=scope,
        )
    except notes.NotesError as e:
        return _ok(f"FAIL: {e}", error=str(e))


@mcp.tool()
def list_folders() -> CallToolResult:
    """List all folders as full paths (Account/Folder/Subfolder)."""
    try:
        folders = notes.list_folders()
        text = "<br>".join(f"📁 {f}" for f in folders) or "(no folders)"
        return _ok(text, folders=folders, count=len(folders))
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def list_notes(
    folder: str | None = None, limit: int = 50, modified_since: str | None = None
) -> CallToolResult:
    """List notes (id, title, folder, modified). Optionally filter by exact folder
    path (e.g. \"iCloud/Work\") or by ISO-8601 modified date (e.g. \"2026-09-01\")."""
    try:
        page, total = notes.list_notes(folder=folder, limit=limit, modified_since=modified_since)
        lines = [f"- {n['name']} [id: {n['id']}]" for n in page]
        text = f"{len(page)} note(s)" + ("<br>" + "<br>".join(lines) if lines else "")
        return _ok(
            text,
            notes=page,
            count=len(page),
            truncated=total > len(page),
            scoped=notes.scoped(),
        )
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def get_note(note_id: str, format: str = "markdown") -> CallToolResult:
    """Get a note by its CoreData id (from list-notes / search-notes): title,
    HTML body, plaintext, folder, created/modified dates. With
    format="markdown" (default) also returns a Markdown rendering of the body;
    use format="plaintext" for HTML+plaintext only."""
    try:
        n = notes.get_note(note_id, format=format)
        extra = dict(
            id=n["id"],
            name=n["name"],
            html=n["body"],
            plaintext=n["plaintext"],
            folder=n["folder"],
            created=n["created"],
            modified=n["modified"],
        )
        if "markdown" in n:
            extra["markdown"] = n["markdown"]
            text = f"# {n['name']}\n\n{n['markdown']}"
        else:
            text = f"# {n['name']}\n\n{n['plaintext']}"
        return _ok(text, **extra)
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def create_note(
    title: str, content: str, folder: str | None = None, format: str = "markdown"
) -> CallToolResult:
    """Create a note. `title` becomes the note title; `content` is Markdown by
    default (format="markdown") or plaintext (format="plaintext", newlines
    become line breaks). Optionally `folder`: exact folder path (e.g.
    "iCloud/Work") — must already exist (see create_folder)."""
    try:
        result = notes.create_note(title, content, folder, format=format)
        return _ok(f"Created note '{result['name']}' [id: {result['id']}]", **result)
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def update_note(
    note_id: str,
    content: str,
    format: str = "markdown",
    confirm: bool = False,
) -> CallToolResult:
    """Replace a note's entire body. `content` is Markdown by default
    (format="markdown"); its first heading/line becomes the new title
    (Notes.app behavior). Use format="plaintext" for plain text. Use get_note
    first to see the current body — this call overwrites it and requires
    confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "update_note")) is not None:
        return denied
    try:
        result = notes.update_note(note_id, content, format=format)
        return _ok(f"Updated note '{result['name']}' [id: {result['id']}]", **result)
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def append_note(
    note_id: str, content: str, position: str = "after", format: str = "markdown"
) -> CallToolResult:
    """Append (position="after", default) or prepend (position="before")
    content to a note without replacing what is already there. `content` is
    Markdown by default, plaintext with format="plaintext"."""
    try:
        result = notes.append_note(note_id, content, position, format=format)
        return _ok(f"Appended to note '{result['name']}' [id: {result['id']}]", **result)
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def delete_note(note_id: str, confirm: bool = False) -> CallToolResult:
    """Delete a note (moves it to Recently Deleted). Irreversible from the
    agent's side — requires confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "delete_note")) is not None:
        return denied
    try:
        notes.delete_note(note_id)
        return _ok(f"Deleted note [id: {note_id}]")
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def search_notes(query: str, search_content: bool = False, limit: int = 50) -> CallToolResult:
    """Search note titles (default). With search_content=true, also searches the
    body text — slower: every note's text is fetched. `query` is a plain
    substring, case-insensitive."""
    try:
        results = notes.search_notes(query, search_content, limit)
        lines = [f"- {n['name']} [id: {n['id']}] (folder: {n['folder']})" for n in results]
        text = f"{len(results)} match(es)" + ("<br>" + "<br>".join(lines) if lines else "")
        return _ok(text, matches=results, count=len(results), scoped=notes.scoped())
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def create_folder(name: str) -> CallToolResult:
    """Create a folder at the default account's top level. Idempotent: an
    existing folder with the same name is left untouched."""
    try:
        result = notes.create_folder(name)
        return _ok(f"Folder '{result['name']}' ready [id: {result['id']}]", **result)
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


@mcp.tool()
def delete_folder(name: str, confirm: bool = False) -> CallToolResult:
    """Delete a folder by name. Refuses if Notes.app refuses (a folder holding
    notes cannot be deleted this way). Requires confirm=true after user approval."""
    if (denied := _require_confirm(confirm, "delete_folder")) is not None:
        return denied
    try:
        notes.delete_folder(name)
        return _ok(f"Deleted folder '{name}'")
    except notes.NotesError as e:
        return _ok(f"ERROR: {e}")


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
