"""Stamp a release version across every place that carries one.

Single source of truth is the argument: manifests, packaging metadata,
MCP server strings, and pinned install URLs all follow it. History prose
(e.g. "Removed in v0.3.0") is deliberately left alone.

Usage:  python3 scripts/bump_version.py 0.4.0
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ["mobile-mcp", "apple-notes-mcp"]


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
    path.write_text(new, encoding="utf-8")
    print(f"OK: {rel} ({count})")
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
        ok &= sub_exact(
            pdir / "main.py",
            r'MCPServer\("([^"]+)", version="\d+\.\d+\.\d+"\)',
            rf'MCPServer("\1", version="{version}")',
            1,
        )

    # Pinned install URLs: git+https://...@vX.Y.Z#subdirectory=...
    url_files = [
        ROOT / "README.md",
        ROOT / "site" / "index.html",
    ] + [ROOT / "plugins" / p / "README.md" for p in PLUGINS]
    for path in url_files:
        text = path.read_text(encoding="utf-8")
        new, count = re.subn(
            r"claude-marketplace@v\d+\.\d+\.\d+#subdirectory=",
            f"claude-marketplace@v{version}#subdirectory=",
            text,
        )
        if count < 1:
            print(f"ERROR: {path.relative_to(ROOT)}: no pinned URLs found")
            ok = False
            continue
        path.write_text(new, encoding="utf-8")
        print(f"OK: {path.relative_to(ROOT)} ({count} URLs)")

    if not ok:
        return 1
    print(f"\nStamped {version}. Now run: python3 scripts/validate_marketplace.py")
    print("Remember: prose history notes and CHANGELOG.md still need a human.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
