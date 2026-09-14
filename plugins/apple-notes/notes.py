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

DEFAULT_FORMAT = "markdown"
VALID_FORMATS = ("plaintext", "markdown")

_DEFAULT_TIMEOUT = float(os.environ.get("APPLE_NOTES_MCP_TIMEOUT_MS", "30000")) / 1000.0
_lock = threading.Lock()


class NotesError(Exception):
    """Raised for any failure talking to Notes.app, with a human message."""


# ---- access scope ----------------------------------------------------------
# APPLE_NOTES_MCP_ALLOWED_FOLDERS restricts every tool to a folder allowlist:
# comma-separated folder names or full paths (e.g. "Notes,iCloud/Work"). When
# unset the server has unrestricted access. Canonical semantics:
# - A full-path entry (contains "/") matches ONLY that exact Account/... path.
# - A bare entry (no "/") matches any folder with that leaf name.
# So "iCloud/Work" does NOT grant "On My Mac/Work". Prefer full paths.
# No config files on disk — the environment variable is the only source.


def _load_scope() -> frozenset[str]:
    raw = os.environ.get("APPLE_NOTES_MCP_ALLOWED_FOLDERS")
    if not raw or not raw.strip():
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


ALLOWED_FOLDERS: frozenset[str] = _load_scope()


def scoped() -> bool:
    return bool(ALLOWED_FOLDERS)


def _bare_entries() -> set[str]:
    """Allowlist entries without a slash: these match by leaf name."""
    return {entry for entry in ALLOWED_FOLDERS if "/" not in entry}


def allowed_leaves() -> set[str]:
    """Bare entry names that count as in scope (full-path entries do NOT
    contribute leaves — use is_allowed_folder() for path checks)."""
    return set(_bare_entries())


def is_allowed_folder(full_path: str) -> bool:
    """Canonical authorization: exact full-path match, or leaf match against
    bare entries only. Unscoped (no allowlist) allows everything."""
    if not scoped():
        return True
    if full_path in ALLOWED_FOLDERS:
        return True
    return full_path.split("/")[-1] in _bare_entries()


def require_folder_in_scope(folder_ref: str) -> None:
    """Enforce scope for a folder reference (full path or bare leaf).

    Full paths require an exact allowlist match (or bare-leaf match).
    Bare names keep legacy compatibility: allowed when the leaf matches any
    entry's leaf — prefer full paths to be precise.
    """
    if not scoped():
        return
    if "/" in folder_ref:
        if is_allowed_folder(folder_ref):
            return
    else:
        if folder_ref in _bare_entries() or folder_ref in {
            e.split("/")[-1] for e in ALLOWED_FOLDERS
        }:
            return
    names = ", ".join(sorted(ALLOWED_FOLDERS)) or "(none)"
    raise NotesError(
        f"Folder '{folder_ref}' is outside the configured access scope "
        f"(APPLE_NOTES_MCP_ALLOWED_FOLDERS={names})."
    )


def _full_path_js(var_container: str = "c") -> str:
    """JXA snippet: build Account/Folder/... full path from a folder object."""
    return (
        f"var parts = [{var_container}.name()];\n"
        f"var p = null;\n"
        f"try {{ p = {var_container}.container(); }} catch (e) {{ p = null; }}\n"
        "var guard = 0;\n"
        "while (p && guard < 10) {\n"
        "    guard++;\n"
        "    try { parts.unshift(p.name());\n"
        f"        p = (typeof p.container !== 'undefined') ? p.container() : null; }}\n"
        "    catch (e) { break; }\n"
        "}\n"
        "parts.join('/')"
    )


def _require_note_in_scope(note_id: str) -> str:
    """Resolve a note's canonical folder full path and enforce the allowlist.
    Returns the full path."""
    js = _PREAMBLE + (
        "var n = Notes.notes.byId(__ID__);\n"
        "var c = n.container();\n"
        "if (!c) { JSON.stringify(null); }\n"
        "else {\n" + _full_path_js("c") + ";\n"
        "JSON.stringify(parts.join('/'));\n"
        "}"
    ).replace("__ID__", _js(note_id))
    full = json.loads(_run_jxa(js))
    if full is None:
        raise NotesError("note not found (may be purged from Recently Deleted)")
    if not scoped():
        return full
    if not is_allowed_folder(full):
        names = ", ".join(sorted(ALLOWED_FOLDERS)) or "(none)"
        raise NotesError(
            f"Folder '{full}' is outside the configured access scope "
            f"(APPLE_NOTES_MCP_ALLOWED_FOLDERS={names})."
        )
    return full


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


def _js(s: str | None) -> str:
    """Render a Python value as a JS literal (None -> null, for optional refs)."""
    return json.dumps(s, ensure_ascii=True)


_LIST_FOLDERS = (
    _PREAMBLE
    + r"""
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
)


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


_GET_NOTE_JS = (
    _PREAMBLE
    + r"""
var n = Notes.notes.byId(__ID__);
var container = n.container();
var folderLeaf = container ? container.name() : null;
var folderFull = null;
if (container) {
    var parts = [container.name()];
    var p = null;
    try { p = container.container(); } catch (e) { p = null; }
    var guard = 0;
    while (p && guard < 10) {
        guard++;
        try { parts.unshift(p.name());
            p = (typeof p.container !== 'undefined') ? p.container() : null; }
        catch (e) { break; }
    }
    folderFull = parts.join('/');
}
JSON.stringify({
    id: n.id(),
    name: n.name(),
    body: n.body(),
    plaintext: n.plaintext(),
    folder: folderLeaf,
    folder_full: folderFull,
    created: new Date(n.creationDate()).toISOString(),
    modified: new Date(n.modificationDate()).toISOString()
});
"""
)


def _set_body_js(note_id: str, body_html: str) -> str:
    return _PREAMBLE + (
        "var n = Notes.notes.byId(__ID__);\n"
        "n.body = __BODY__;\n"
        "JSON.stringify({id: n.id(), name: n.name()});"
    ).replace("__ID__", _js(note_id)).replace("__BODY__", _js(body_html))


def _delete_note_js(note_id: str) -> str:
    return _PREAMBLE + (
        "var n = Notes.notes.byId(__ID__);\nNotes.delete(n);\nJSON.stringify({deleted: true});"
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
        "var accounts = Notes.accounts();\nJSON.stringify({ok: true, accounts: accounts.length});"
    )


# ---- public API ------------------------------------------------------------


def list_folders() -> list[str]:
    paths = json.loads(_run_jxa(_LIST_FOLDERS))
    if scoped():
        paths = [p for p in paths if is_allowed_folder(p)]
    return paths


def create_note(title: str, content: str, folder: str | None, format: str = DEFAULT_FORMAT) -> dict:
    """Create a note. The title lives in the body as an <h1>, which is how
    Notes.app derives the note title — matching native editing behavior.

    `content` is Markdown by default (`format="markdown"`) or plaintext
    (`format="plaintext"`); it is converted to the HTML Notes.app stores.
    """
    if scoped() and folder is None:
        raise NotesError(
            "Access scope is restricted: name an explicit folder for the new note "
            f"(allowed: {', '.join(sorted(ALLOWED_FOLDERS))})."
        )
    if folder is not None:
        require_folder_in_scope(folder)
    body_html = content_to_html(content, format)
    html = f"<h1>{_escape(title)}</h1>"
    if body_html:
        html += "<div><br></div>" + body_html
    return json.loads(_run_jxa(_make_note_js(title, html, folder)))


def get_note(note_id: str, format: str = DEFAULT_FORMAT) -> dict:
    n = json.loads(_run_jxa(_GET_NOTE_JS.replace("__ID__", _js(note_id))))
    if n.get("folder") is None and n.get("folder_full") is None:
        raise NotesError("note not found (may be purged from Recently Deleted)")
    if scoped():
        if n.get("folder_full"):
            if not is_allowed_folder(n["folder_full"]):
                require_folder_in_scope(n["folder_full"])
        else:
            require_folder_in_scope(n.get("folder") or "")
    # Canonicalize: folder is the full Account/... path (matches list_folders);
    # folder_leaf keeps the immediate container for backward compatibility.
    if n.get("folder_full"):
        n["folder_leaf"] = n.get("folder")
        n["folder"] = n["folder_full"]
    if validate_format(format) == "markdown":
        n["markdown"] = html_to_markdown(n.get("body", ""))
    return n


def update_note(note_id: str, content: str, format: str = DEFAULT_FORMAT) -> dict:
    """Replace a note's entire body. First line / first <h1> becomes its title.

    `content` is Markdown by default, plaintext with `format="plaintext"`.
    """
    _require_note_in_scope(note_id)
    body_html = content_to_html(content, format)
    return json.loads(_run_jxa(_set_body_js(note_id, body_html)))


def append_note(
    note_id: str,
    content: str,
    position: str = "after",
    format: str = DEFAULT_FORMAT,
) -> dict:
    _require_note_in_scope(note_id)
    body_html = content_to_html(content, format)
    current = get_note(note_id, format="plaintext")
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
    require_folder_in_scope(name)
    _run_jxa(_delete_folder_js(name))


def _folders_for(note_ids: list[str]) -> list[str | None]:
    """Canonical folder full paths for specific notes, one AppleScript call."""
    if not note_ids:
        return []
    ids_js = ",".join(_js(i) for i in note_ids)
    js = _PREAMBLE + (
        "var ids = [" + ids_js + "];\n"
        "var out = [];\n"
        "for (var i = 0; i < ids.length; i++) {\n"
        "    try {\n"
        "        var c = Notes.notes.byId(ids[i]).container();\n"
        "        if (!c) { out.push(null); continue; }\n"
        "        var parts = [c.name()];\n"
        "        var p = null;\n"
        "        try { p = c.container(); } catch (e) { p = null; }\n"
        "        var guard = 0;\n"
        "        while (p && guard < 10) {\n"
        "            guard++;\n"
        "            try { parts.unshift(p.name());\n"
        "                p = (typeof p.container !== 'undefined') ? p.container() : null; }\n"
        "            catch (e) { break; }\n"
        "        }\n"
        "        out.push(parts.join('/'));\n"
        "    } catch (e) { out.push(null); }\n"
        "}\n"
        "JSON.stringify(out);"
    )
    return json.loads(_run_jxa(js))


def list_notes(
    folder: str | None = None,
    limit: int = 50,
    modified_since: str | None = None,
) -> tuple[list[dict], int]:
    """List notes (id, name, folder, modified). `folder` accepts a full path
    (e.g. "iCloud/Work") or a bare leaf (e.g. "Work"); folder is the canonical
    Account/... full path. Optionally filter by ISO-8601 modified date
    (e.g. "2026-09-01")."""
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
        all_notes = [n for n in all_notes if n.get("folder") and is_allowed_folder(n["folder"])]
    # Filter by folder: full path exact, or bare leaf suffix match.
    if folder is not None:
        if "/" in folder:
            all_notes = [n for n in all_notes if n.get("folder") == folder]
        else:
            all_notes = [n for n in all_notes if (n.get("folder") or "").split("/")[-1] == folder]
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
        matches = [m for m in matches if m.get("folder") and is_allowed_folder(m["folder"])]
    return matches[:limit]


def health() -> dict:
    return json.loads(_run_jxa(_health_js()))


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def validate_format(format: str) -> str:
    fmt = (format or "").lower()
    if fmt not in VALID_FORMATS:
        raise NotesError(f"Unknown format '{format}'. Use one of: {', '.join(VALID_FORMATS)}.")
    return fmt


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


def markdown_to_html(text: str) -> str:
    """Convert Markdown to HTML for Notes.app (CommonMark via `markdown` lib)."""
    if not text:
        return ""
    import markdown

    return markdown.markdown(text, extensions=["extra", "sane_lists"])


def html_to_markdown(html: str) -> str:
    """Convert Notes.app HTML body back to Markdown (via `markdownify`)."""
    if not html:
        return ""
    from markdownify import markdownify

    return markdownify(html, heading_style="ATX").strip()


def content_to_html(content: str, format: str = DEFAULT_FORMAT) -> str:
    """Convert user content to Notes HTML based on `format`.

    `format` is "markdown" (default) or "plaintext". Markdown is rendered
    with the `markdown` package; plaintext is escaped with <br> line breaks.
    """
    fmt = validate_format(format)
    if not content:
        return ""
    if fmt == "markdown":
        return markdown_to_html(content)
    return plaintext_to_html(content)
