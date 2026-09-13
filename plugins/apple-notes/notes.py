"""Apple Notes bridge: drives Notes.app through JXA (osascript -l JavaScript).

All user-supplied values are embedded into scripts with json.dumps(), which
produces valid JS string literals (no quoting/escaping bugs possible).
Property reads on whole collections broadcast in one Apple event
(e.g. Notes.notes.name()), which keeps enumeration fast.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading

_DEFAULT_TIMEOUT = float(os.environ.get("APPLE_NOTES_MCP_TIMEOUT_MS", "30000")) / 1000.0
_lock = threading.Lock()


class NotesError(Exception):
    """Raised for any failure talking to Notes.app, with a human message."""


# ---- access scope ----------------------------------------------------------
# APPLE_NOTES_MCP_ALLOWED_FOLDERS restricts every tool to a folder allowlist:
# comma-separated folder names or full paths (e.g. "Notes,iCloud/Work"). When
# unset the server has unrestricted access. Entries match a folder if the full
# path equals the entry, or the folder's leaf name equals the entry. A note is
# in scope when its container's leaf name matches. No config files on disk —
# the environment variable is the only source.

def _load_scope() -> frozenset[str]:
    raw = os.environ.get("APPLE_NOTES_MCP_ALLOWED_FOLDERS")
    if not raw or not raw.strip():
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


ALLOWED_FOLDERS: frozenset[str] = _load_scope()


def scoped() -> bool:
    return bool(ALLOWED_FOLDERS)


def allowed_leaves() -> set[str]:
    """Leaf folder names that count as in scope."""
    return {entry.split("/")[-1] for entry in ALLOWED_FOLDERS}


def require_folder_in_scope(leaf_name: str) -> None:
    if not scoped():
        return
    if leaf_name not in allowed_leaves():
        names = ", ".join(sorted(ALLOWED_FOLDERS)) or "(none)"
        raise NotesError(
            f"Folder '{leaf_name}' is outside the configured access scope "
            f"(APPLE_NOTES_MCP_ALLOWED_FOLDERS={names})."
        )


def _require_note_in_scope(note_id: str) -> str:
    """Resolve a note's container leaf and enforce the allowlist. Returns the leaf."""
    js = _PREAMBLE + (
        "var n = Notes.notes.byId(__ID__);\n"
        "var c = n.container();\n"
        "JSON.stringify(c ? c.name() : null);"
    ).replace("__ID__", _js(note_id))
    leaf = json.loads(_run_jxa(js))
    if leaf is None:
        raise NotesError("note not found (may be purged from Recently Deleted)")
    require_folder_in_scope(leaf)
    return leaf


def _run_jxa(script: str, timeout: float | None = None) -> str:
    """Run one JXA script against Notes.app. Serialized: Notes accepts one
    scripting client at a time, and concurrent osascript errors look random."""
    timeout = timeout or _DEFAULT_TIMEOUT
    with _lock:
        try:
            proc = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise NotesError(
                f"Notes.app did not respond within {int(timeout)}s (APPLE_NOTES_MCP_TIMEOUT_MS). "
                "Is Notes.app frozen or mid iCloud sync?"
            ) from None
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "-1743" in err:
            raise NotesError(
                "Not authorized to control Notes. Grant automation permission in "
                "System Settings > Privacy & Security > Automation (enable it for "
                "Terminal, and restart the MCP server afterwards)."
            )
        from re import sub as _sub

        err = _sub(r"\s+", " ", err)[:400]
        raise NotesError(f"Notes.app error: {err}")
    return proc.stdout


# ---- JXA snippets ----------------------------------------------------------

_PREAMBLE = """\
var Notes = Application('Notes');
"""


def _js(s: str) -> str:
    return json.dumps(s, ensure_ascii=True)


_LIST_FOLDERS = _PREAMBLE + r"""
function walk(folders, prefix, out) {
    for (var i = 0; i < folders.length; i++) {
        var name = folders[i].name();
        var path = prefix ? prefix + '/' + name : name;
        out.push(path);
        walk(folders[i].folders(), path, out);
    }
}
var out = [];
var accounts = Notes.accounts();
for (var a = 0; a < accounts.length; a++) {
    walk(accounts[a].folders(), accounts[a].name(), out);
}
JSON.stringify(out);
"""


def _folder_ref_js(name: str | None) -> str:
    """JS expression resolving an account-qualified folder path (as returned by
    list_folders, e.g. "iCloud/Work/Clients") to a folder specifier, or null."""
    if name is None:
        return "null /* default location */"
    return (
        "(function(){"
        "var parts = __PATH__.split('/');"
        "if (parts.length === 1) {"
        "    parts = [Notes.defaultAccount().name(), parts[0]];"
        "}"
        "var accountName = parts.shift();"
        "var accounts = Notes.accounts();"
        "var account = null;"
        "for (var a = 0; a < accounts.length; a++)"
        "    { if (accounts[a].name() === accountName) { account = accounts[a]; break; } }"
        "if (!account) return null;"
        "var level = account.folders();"
        "var match = null;"
        "for (var p = 0; p < parts.length; p++) {"
        "    match = null;"
        "    for (var i = 0; i < level.length; i++)"
        "        { if (level[i].name() === parts[p]) { match = level[i]; break; } }"
        "    if (!match) return null;"
        "    level = match.folders();"
        "}"
        "return match;"
        "})()"
    ).replace("__PATH__", _js(name))


def _make_note_js(title: str, body_html: str, folder: str | None) -> str:
    return _PREAMBLE + (
        "var target = " + _folder_ref_js(folder) + ";\n"
        "if (__FOLDER__ !== null && target === null) "
        "{ throw new Error('folder not found: ' + __FOLDER__); }\n"
        "var n = target === null\n"
        "    ? Notes.make({new: 'note', withProperties: {body: __BODY__}})\n"
        "    : Notes.make({new: 'note', at: target, withProperties: {body: __BODY__}});\n"
        "JSON.stringify({id: n.id(), name: n.name()});"
    ).replace("__FOLDER__", _js(folder)).replace("__BODY__", _js(body_html))


_GET_NOTE_JS = _PREAMBLE + r"""
var n = Notes.notes.byId(__ID__);
var container = n.container();
JSON.stringify({
    id: n.id(),
    name: n.name(),
    body: n.body(),
    plaintext: n.plaintext(),
    folder: container ? container.name() : null,
    created: new Date(n.creationDate()).toISOString(),
    modified: new Date(n.modificationDate()).toISOString()
});
"""


def _set_body_js(note_id: str, body_html: str) -> str:
    return _PREAMBLE + (
        "var n = Notes.notes.byId(__ID__);\n"
        "n.body = __BODY__;\n"
        f"JSON.stringify({{id: n.id(), name: n.name()}});"
    ).replace("__ID__", _js(note_id)).replace("__BODY__", _js(body_html))


def _delete_note_js(note_id: str) -> str:
    return _PREAMBLE + (
        "var n = Notes.notes.byId(__ID__);\n"
        "Notes.delete(n);\n"
        "JSON.stringify({deleted: true});"
    ).replace("__ID__", _js(note_id))


def _make_folder_js(name: str) -> str:
    return _PREAMBLE + (
        "var acc = Notes.defaultAccount();\n"
        "var existing = acc.folders().find(function(f){ return f.name() === __NAME__; });\n"
        "if (existing) { JSON.stringify({id: existing.id(), name: existing.name(), existing: true}); }\n"
        "else {\n"
        "var f = Notes.make({new: 'folder', at: acc, withProperties: {name: __NAME__}});\n"
        "JSON.stringify({id: f.id(), name: f.name(), existing: false});\n"
        "}"
    ).replace("__NAME__", _js(name))


def _delete_folder_js(name: str) -> str:
    ref = _folder_ref_js(name)
    return _PREAMBLE + (
        "var target = " + ref + ";\n"
        f"if (target === null) {{ throw new Error('folder not found: {_js(name)}'); }}\n"
        "Notes.delete(target);\n"
        "JSON.stringify({deleted: true});"
    )


def _health_js() -> str:
    return _PREAMBLE + (
        "var accounts = Notes.accounts();\n"
        "JSON.stringify({ok: true, accounts: accounts.length});"
    )


# ---- public API ------------------------------------------------------------


def list_folders() -> list[str]:
    paths = json.loads(_run_jxa(_LIST_FOLDERS))
    if scoped():
        leaves = allowed_leaves()
        paths = [p for p in paths if p in ALLOWED_FOLDERS or p.split("/")[-1] in leaves]
    return paths


def create_note(title: str, body_html: str, folder: str | None) -> dict:
    """Create a note. The title lives in the body as an <h1>, which is how
    Notes.app derives the note title — matching native editing behavior."""
    if scoped() and folder is None:
        raise NotesError(
            "Access scope is restricted: name an explicit folder for the new note "
            f"(allowed: {', '.join(sorted(ALLOWED_FOLDERS))})."
        )
    if folder is not None:
        require_folder_in_scope(folder.split("/")[-1])
    html = f"<h1>{_escape(title)}</h1>"
    if body_html:
        html += "<div><br></div>" + body_html
    return json.loads(_run_jxa(_make_note_js(title, html, folder)))


def get_note(note_id: str) -> dict:
    n = json.loads(_run_jxa(_GET_NOTE_JS.replace("__ID__", _js(note_id))))
    require_folder_in_scope(n["folder"])
    return n


def update_note(note_id: str, body_html: str) -> dict:
    """Replace a note's entire body. First line of the new body becomes its title."""
    _require_note_in_scope(note_id)
    return json.loads(_run_jxa(_set_body_js(note_id, body_html)))


def append_note(note_id: str, body_html: str, position: str = "after") -> dict:
    _require_note_in_scope(note_id)
    current = get_note(note_id)
    sep = "<div><br></div>"
    new_body = (
        current["body"] + sep + body_html
        if position == "after"
        else body_html + sep + current["body"]
    )
    return json.loads(_run_jxa(_set_body_js(note_id, new_body)))


def delete_note(note_id: str) -> None:
    _require_note_in_scope(note_id)
    _run_jxa(_delete_note_js(note_id))


def create_folder(name: str) -> dict:
    """Create (or reuse) a folder at the default account's top level."""
    return json.loads(_run_jxa(_make_folder_js(name)))


def delete_folder(name: str) -> None:
    require_folder_in_scope(name.split("/")[-1])
    _run_jxa(_delete_folder_js(name))


def _folders_for(note_ids: list[str]) -> list[str | None]:
    """Folders for specific notes, one AppleScript call, inside-JS loop."""
    if not note_ids:
        return []
    ids_js = ",".join(_js(i) for i in note_ids)
    js = _PREAMBLE + (
        "var ids = [" + ids_js + "];\n"
        "var out = [];\n"
        "for (var i = 0; i < ids.length; i++) {\n"
        "    var c = Notes.notes.byId(ids[i]).container();\n"
        "    out.push(c ? c.name() : null);\n"
        "}\n"
        "JSON.stringify(out);"
    )
    return json.loads(_run_jxa(js))


def list_notes(
    folder: str | None = None,
    limit: int = 50,
    modified_since: str | None = None,
) -> list[dict]:
    """List notes (id, name, folder, modified). Optionally filter by exact folder
    name (the immediate container, e.g. \"Notes\" or \"Recently Deleted\") or by
    ISO-8601 modified date (e.g. \"2026-09-01\")."""
    js = _PREAMBLE + (
        "var ids = Notes.notes.id();\n"
        "var names = Notes.notes.name();\n"
        "var dts = Notes.notes.modificationDate();\n"
        "var out = [];\n"
        "for (var i = 0; i < ids.length; i++) {\n"
        "    out.push({id: ids[i], name: names[i],\n"
        "              modified: new Date(dts[i]).toISOString()});\n"
        "}\n"
        "JSON.stringify(out);"
    )
    all_notes = json.loads(_run_jxa(js))
    if all_notes:
        container_names = _folders_for([n["id"] for n in all_notes])
        for n, c in zip(all_notes, container_names):
            n["folder"] = c
    if scoped():
        leaves = allowed_leaves()
        all_notes = [n for n in all_notes if n.get("folder") in leaves]
    # Filter by folder (immediate container name)
    if folder is not None:
        all_notes = [n for n in all_notes if n.get("folder") == folder]
    # Filter by modified_since
    if modified_since:
        all_notes = [n for n in all_notes if n["modified"] >= modified_since]
    # Apply limit
    page = all_notes[:limit]
    return page, len(all_notes)


def search_notes(query: str, search_content: bool, limit: int) -> list[dict]:
    """Search note titles (default). With search_content=true, also searches the
    body text — slower: every note's text is fetched. `query` is a plain
    substring, case-insensitive. Returns matches with id, name, folder."""
    js = _PREAMBLE + (
        "var ids = Notes.notes.id();\n"
        "var names = Notes.notes.name();\n"
        + ("var bodies = Notes.notes.plaintext();\n" if search_content else "")
        + "var out = [];\n"
        f"var q = {_js(query.lower())};\n"
        "for (var i = 0; i < ids.length; i++) {\n"
        "    if (names[i].toLowerCase().indexOf(q) !== -1"
        + ("|| bodies[i].toLowerCase().indexOf(q) !== -1" if search_content else "")
        + ") {\n"
        "        out.push({id: ids[i], name: names[i]});\n"
        "    }\n"
        "}\n"
        "JSON.stringify(out);"
    )
    matches = json.loads(_run_jxa(js))
    if matches:
        container_names = _folders_for([m["id"] for m in matches])
        for m, c in zip(matches, container_names):
            m["folder"] = c
    if scoped():
        leaves = allowed_leaves()
        matches = [m for m in matches if m.get("folder") in leaves]
    return matches[:limit]


def health() -> dict:
    return json.loads(_run_jxa(_health_js()))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plaintext_to_html(text: str) -> str:
    """Convert plaintext to the loose HTML Notes.app accepts."""
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        if line == "":
            lines.append("<div><br></div>")
        else:
            lines.append(_escape(line))
    return "<br>".join(lines)