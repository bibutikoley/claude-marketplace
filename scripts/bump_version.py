"""Stamp a release version across every place that carries one.

Single source of truth is the argument: manifests, packaging metadata,
MCP server strings, pinned install URLs, and current-version prose in the
living docs all follow it. History prose ("Removed in v0.3.0",
CHANGELOG.md headings) is deliberately left alone.

Usage:  python3 scripts/bump_version.py 0.4.0
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ["mobile-mcp", "apple-notes-mcp"]

# Living docs that carry the current version. CHANGELOG.md is history
# and is intentionally NOT in this list (same list as validate_marketplace).
DOC_FILES = [
    ROOT / "README.md",
    ROOT / "plugins" / "mobile-mcp" / "README.md",
    ROOT / "plugins" / "apple-notes-mcp" / "README.md",
    ROOT / "site" / "index.html",
]

HISTORY_MARKER = "Removed in"

PINNED_URL_RE = r"claude-marketplace@v\d+\.\d+\.\d+#subdirectory="
# Prose @v mentions that are NOT part of a pinned URL (drop-@v notes,
# ...@v ellipsis examples, <code>@v</code> labels). Placeholders like
# @vX.Y.Z contain no digits and never match.
PROSE_AT_VERSION_RE = r"(?<!claude-marketplace)@v\d+\.\d+\.\d+"
PROSE_CODE_TAG_RE = r"(<code>)v\d+\.\d+\.\d+(</code>)"
PROSE_SPAN_TAG_RE = r'(<span class="version">)v\d+\.\d+\.\d+(</span>)'


def sub_version_json(path: Path, expect: int, version: str) -> bool:
    """Replace `"version": "x.y.z"` lines, preserving indent and commas."""
    return sub_exact(
        path,
        r'(?m)^(\s*"version": ")[0-9]+\.[0-9]+\.[0-9]+(",?)$',
        rf"\g<1>{version}\g<2>",
        expect,
    )


def fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 1


def sub_exact(path: Path, pattern: str, repl: str, expect: int) -> bool:
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, repl, text)
    rel = path.relative_to(ROOT)
    if count != expect:
        print(f"ERROR: {rel}: expected {expect} replacement(s), got {count}")
        return False
    if new != text:
        path.write_text(new, encoding="utf-8")
    print(f"OK: {rel} ({count})")
    return True


def bump_doc_text(text: str, version: str) -> tuple[str, dict[str, int]]:
    """Stamp prose version mentions; history lines are left alone.

    Returns (new_text, counts) with per-pattern replacement counts.
    Pure (no I/O) so release tests can exercise it directly.
    """
    counts: dict[str, int] = {}

    text, counts["pinned_urls"] = re.subn(
        PINNED_URL_RE,
        f"claude-marketplace@v{version}#subdirectory=",
        text,
    )
    text, counts["prose_at"] = re.subn(
        PROSE_AT_VERSION_RE,
        f"@v{version}",
        text,
    )
    text, counts["code_tags"] = re.subn(
        PROSE_CODE_TAG_RE,
        rf"\g<1>v{version}\g<2>",
        text,
    )
    text, counts["version_badges"] = re.subn(
        PROSE_SPAN_TAG_RE,
        rf"\g<1>v{version}\g<2>",
        text,
    )

    # Backticked prose (`vX.Y.Z`, `X.Y.Z`, `@vX.Y.Z`): line-wise so
    # history lines ("Removed in v0.3.0") are preserved.
    backtick_ticked = 0
    bare_ticked = 0
    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        if HISTORY_MARKER not in line:
            line, n1 = re.subn(r"`v\d+\.\d+\.\d+`", f"`v{version}`", line)
            backtick_ticked += n1
            line, n2 = re.subn(r"`@v\d+\.\d+\.\d+`", f"`@v{version}`", line)
            backtick_ticked += n2
            line, n3 = re.subn(r"`\d+\.\d+\.\d+`", f"`{version}`", line)
            bare_ticked += n3
        kept.append(line)
    counts["prose_backtick"] = backtick_ticked
    counts["prose_bare"] = bare_ticked
    return "".join(kept), counts


def bump_doc_file(path: Path, version: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new, counts = bump_doc_text(text, version)
    rel = path.relative_to(ROOT)
    if counts["pinned_urls"] < 1:
        print(f"ERROR: {rel}: no pinned URLs found")
        return False
    if new != text:
        path.write_text(new, encoding="utf-8")
    print(f"OK: {rel} ({counts})")
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        return fail("usage: python3 scripts/bump_version.py <X.Y.Z>")
    version = argv[1]
    ok = True

    # Marketplace catalog: every plugin entry version (surgical, keeps formatting).
    marketplace = ROOT / ".claude-plugin" / "marketplace.json"
    data = json.loads(marketplace.read_text(encoding="utf-8"))
    names = {p["name"] for p in data["plugins"]}
    if names != set(PLUGINS):
        return fail(f"marketplace plugins {sorted(names)} != expected {PLUGINS}")
    ok &= sub_version_json(marketplace, len(PLUGINS), version)

    for plugin in PLUGINS:
        pdir = ROOT / "plugins" / plugin

        ok &= sub_version_json(pdir / ".claude-plugin" / "plugin.json", 1, version)

        ok &= sub_exact(
            pdir / "pyproject.toml",
            r'(?m)^version = "\d+\.\d+\.\d+"$',
            f'version = "{version}"',
            1,
        )
        # MCP runtime version is single-sourced from pyproject.toml via an
        # importlib.metadata-backed _package_version() in main.py. Legacy
        # checkouts may still carry a literal MCPServer(..., version="X").
        main_py = pdir / "main.py"
        main_text = main_py.read_text(encoding="utf-8")
        if "version=_package_version()" in main_text:
            if f'dist_name = "{plugin}"' not in main_text:
                print(f"ERROR: {main_py.relative_to(ROOT)}: dynamic version mismatch")
                ok = False
            else:
                print(f"OK: {main_py.relative_to(ROOT)} (dynamic, from pyproject)")
        else:
            ok &= sub_exact(
                main_py,
                r'MCPServer\("([^"]+)", version="\d+\.\d+\.\d+"\)',
                rf'MCPServer("\1", version="{version}")',
                1,
            )

    # Pinned install URLs + current-version prose in the living docs.
    for path in DOC_FILES:
        ok &= bump_doc_file(path, version)

    if not ok:
        return 1
    print(f"\nStamped {version}. Now run: python3 scripts/validate_marketplace.py")
    print("Remember: prose history notes and CHANGELOG.md still need a human.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
