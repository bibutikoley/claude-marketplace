"""Validate the marketplace catalog against the plugin sources.

Catches: duplicate plugin names, duplicate sources, name/version drift
between marketplace.json <-> plugin.json <-> pyproject.toml, missing
source dirs/files, invalid JSON.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

REQUIRED_PLUGIN_FILES = [
    ".claude-plugin/plugin.json",
    "pyproject.toml",
    "main.py",
    "README.md",
]

errors: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)
    print(f"ERROR: {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"WARN: {msg}")


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as e:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {e}")
    return None


def pyproject_version(pyproject: Path) -> str | None:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else None


def main() -> int:
    if not MARKETPLACE.is_file():
        fail("missing .claude-plugin/marketplace.json")
        return 1

    marketplace = load_json(MARKETPLACE)
    if marketplace is None:
        return 1

    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        fail("marketplace.json: 'plugins' must be a non-empty list")
        return 1

    seen_names: dict[str, str] = {}
    seen_sources: dict[str, str] = {}

    for entry in plugins:
        name = entry.get("name")
        source = entry.get("source")
        version = entry.get("version")
        if not name or not source:
            fail(f"marketplace entry missing name/source: {entry!r}")
            continue

        if name in seen_names:
            fail(
                f"duplicate marketplace plugin name '{name}' "
                f"(also defined for source '{seen_names[name]}')"
            )
        else:
            seen_names[name] = source

        norm_source = source.rstrip("/")
        if norm_source in seen_sources and seen_sources[norm_source] != name:
            fail(
                f"duplicate marketplace source '{source}' used by both "
                f"'{seen_sources[norm_source]}' and '{name}' "
                "(each source directory must map to exactly one plugin name)"
            )
        else:
            seen_sources.setdefault(norm_source, name)

        plugin_dir = (ROOT / norm_source).resolve()
        try:
            plugin_dir.relative_to(ROOT.resolve())
        except ValueError:
            fail(f"plugin '{name}': source '{source}' escapes the repository root")
            continue
        if not plugin_dir.is_dir():
            fail(f"plugin '{name}': source directory '{source}' does not exist")
            continue

        for rel in REQUIRED_PLUGIN_FILES:
            if not (plugin_dir / rel).is_file():
                fail(f"plugin '{name}': missing required file '{source}/{rel}'")

        manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
        manifest = load_json(manifest_path)
        if manifest is None:
            continue
        manifest_name = manifest.get("name")
        manifest_version = manifest.get("version")
        if manifest_name != name:
            fail(
                f"plugin '{name}': marketplace name does not match "
                f"plugin.json name '{manifest_name}'"
            )
        if version != manifest_version:
            fail(
                f"plugin '{name}': marketplace version '{version}' != "
                f"plugin.json version '{manifest_version}'"
            )

        py_version = pyproject_version(plugin_dir / "pyproject.toml")
        if py_version is None:
            warn(f"plugin '{name}': could not read version from pyproject.toml")
        elif version != py_version:
            fail(
                f"plugin '{name}': marketplace version '{version}' != "
                f"pyproject.toml version '{py_version}'"
            )

        mcp_json = plugin_dir / ".mcp.json"
        if mcp_json.is_file():
            load_json(mcp_json)

    print(f"validated {len(plugins)} plugin(s): {', '.join(sorted(seen_names))}")
    if warnings and not errors:
        print(f"{len(warnings)} warning(s), 0 errors")
    if errors:
        print(f"{len(errors)} error(s)")
        return 1
    print("marketplace validation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
