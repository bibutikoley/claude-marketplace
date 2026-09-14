"""Validate the marketplace catalog against the plugin sources.

Catches: duplicate plugin names, duplicate sources, name/version/
description drift between marketplace.json <-> plugin.json <->
pyproject.toml <-> main.py server strings, .mcp.json server-key drift,
missing source dirs/files, invalid JSON, and pinned/prose version drift
in the living docs (root README, plugin READMEs, site/index.html).

The release train rule: every marketplace entry carries the same version
(single-source releases via scripts/bump_version.py). CHANGELOG.md is
history prose and is deliberately excluded from the doc checks.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

PLUGINS = ["mobile-mcp", "apple-notes-mcp"]

# Living docs that carry the current pinned version (URLs + prose).
# CHANGELOG.md is history and is intentionally NOT in this list.
DOC_FILES = [
    ROOT / "README.md",
    ROOT / "plugins" / "mobile-mcp" / "README.md",
    ROOT / "plugins" / "apple-notes-mcp" / "README.md",
    ROOT / "site" / "index.html",
]

REQUIRED_PLUGIN_FILES = [
    ".claude-plugin/plugin.json",
    ".mcp.json",
    "pyproject.toml",
    "main.py",
    "README.md",
]

MCP_SERVER_RE = re.compile(r'MCPServer\("([^"]+)", version="([^"]+)"\)')
MCP_SERVER_NAME_RE = re.compile(r'MCPServer\("([^"]+)"')
MCP_SERVER_DYNAMIC_RE = re.compile(
    r'MCPServer\("([^"]+)",\s*version\s*=\s*_package_version\(\)\)'
)
PYPROJECT_NAME_RE = re.compile(r'(?m)^name\s*=\s*["\']([^"\']+)["\']')
PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*["\']([^"\']+)["\']')
PYPROJECT_DESC_RE = re.compile(r'(?m)^description\s*=\s*["\']([^"\']+)["\']')
PINNED_URL_RE = re.compile(r"claude-marketplace@v(\d+\.\d+\.\d+)#subdirectory=")
AT_VERSION_RE = re.compile(r"@v(\d+\.\d+\.\d+)")
BACKTICK_VERSION_RE = re.compile(r"`@?v?(\d+\.\d+\.\d+)`")
CODE_TAG_VERSION_RE = re.compile(r"<code>@?v(\d+\.\d+\.\d+)</code>")
SPAN_VERSION_RE = re.compile(r'<span class="version">v(\d+\.\d+\.\d+)</span>')

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


def pyproject_field(
    pyproject: Path, pattern: re.Pattern[str], field: str
) -> str | None:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    m = pattern.search(text)
    if not m:
        try:
            rel = pyproject.relative_to(ROOT)
        except ValueError:
            # Release-validation tests intentionally operate on a temporary
            # repository root; preserve a useful warning there as well.
            rel = pyproject
        warn(f"could not read {field} from {rel}")
        return None
    return m.group(1)


def main_py_server(main_py: Path) -> tuple[str | None, str | None]:
    """Return (server_name, version) from the MCPServer(...) call.

    Supports two shapes:
    - legacy literal: ``MCPServer("name", version="X.Y.Z")`` → returns X.Y.Z.
    - dynamic single-source: ``MCPServer("name",
      version=_package_version())`` with an ``importlib.metadata``-backed
      ``_package_version()`` that resolves ``pyproject.toml`` ``version``.
      Returns the sibling ``pyproject.toml`` version, which is what the
      runtime resolves to once installed (source-checkout fallback reads
      the same file). A mismatched distribution name or a missing
      derivation is a hard failure so runtime/package drift cannot recur
      silently.
    """
    try:
        text = main_py.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    m = MCP_SERVER_RE.search(text)
    if m:
        return m.group(1), m.group(2)
    m_dyn = MCP_SERVER_DYNAMIC_RE.search(text)
    if not m_dyn:
        m_name = MCP_SERVER_NAME_RE.search(text)
        if not m_name:
            fail(f"{main_py.relative_to(ROOT)}: no MCPServer(name, version=...) found")
            return None, None
        fail(
            f"{main_py.relative_to(ROOT)}: MCPServer version must be a "
            '"X.Y.Z" literal or version=_package_version() '
            "(single source of truth via importlib.metadata)"
        )
        return m_name.group(1), None
    name = m_dyn.group(1)
    if "importlib.metadata" not in text or "_package_version" not in text:
        fail(
            f"{main_py.relative_to(ROOT)}: dynamic MCPServer version "
            "requires an importlib.metadata-backed _package_version()"
        )
        return name, None
    m_dist = re.search(r'dist_name\s*=\s*["\']([^"\']+)["\']', text)
    if not m_dist:
        fail(
            f"{main_py.relative_to(ROOT)}: _package_version() must define "
            'dist_name = "<plugin>"'
        )
        return name, None
    if m_dist.group(1) != name:
        fail(
            f"{main_py.relative_to(ROOT)}: _package_version() dist_name "
            f"'{m_dist.group(1)}' != MCPServer name '{name}'"
        )
        return name, None
    pyproject = main_py.parent / "pyproject.toml"
    py_version = pyproject_field(pyproject, PYPROJECT_VERSION_RE, "version")
    if py_version is None:
        fail(
            f"{main_py.relative_to(ROOT)}: dynamic version cannot be resolved "
            "(sibling pyproject.toml has no version)"
        )
        return name, None
    return name, py_version


def doc_drift_versions(text: str) -> list[str]:
    """Every current-version mention in a living doc, excluding history.

    Covers @vX.Y.Z pins (URLs + prose), backticked `vX.Y.Z` / `X.Y.Z`
    prose, <code>vX.Y.Z</code> labels, and <span class="version"> badges.
    Lines with "Removed in" are history prose and are skipped.
    """
    found: list[str] = []
    found.extend(AT_VERSION_RE.findall(text))
    found.extend(SPAN_VERSION_RE.findall(text))
    for line in text.splitlines():
        if "Removed in" in line:
            continue
        found.extend(BACKTICK_VERSION_RE.findall(line))
    for line in text.splitlines():
        if "Removed in" in line:
            continue
        found.extend(CODE_TAG_VERSION_RE.findall(line))
    return found


def check_doc_files(train_version: str) -> None:
    for path in DOC_FILES:
        rel = path.relative_to(ROOT)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            fail(f"missing doc file: {rel}")
            continue
        urls = PINNED_URL_RE.findall(text)
        if not urls:
            fail(f"{rel}: no pinned claude-marketplace@vX.Y.Z URLs found")
        for v in urls:
            if v != train_version:
                fail(
                    f"{rel}: pinned URL version 'v{v}' != release train 'v{train_version}'"
                )
        for v in doc_drift_versions(text):
            if v != train_version:
                fail(f"{rel}: prose version 'v{v}' != release train 'v{train_version}'")


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

    names = {p["name"] for p in marketplace["plugins"] if isinstance(p, dict)}
    if names != set(PLUGINS):
        fail(f"marketplace plugins {sorted(names)} != expected {PLUGINS}")

    # Single release train: every entry carries the same version.
    train_versions = {p.get("version") for p in plugins if isinstance(p, dict)}
    train_version: str | None = None
    if len(train_versions) == 1:
        train_version = next(iter(train_versions))
    else:
        fail(
            f"marketplace entries diverge from a single release train: {sorted(train_versions)}"
        )

    seen_names: dict[str, str] = {}
    seen_sources: dict[str, str] = {}

    for entry in plugins:
        name = entry.get("name")
        source = entry.get("source")
        version = entry.get("version")
        description = entry.get("description")
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
        if manifest.get("name") != name:
            fail(
                f"plugin '{name}': marketplace name does not match "
                f"plugin.json name '{manifest.get('name')}'"
            )
        if version != manifest.get("version"):
            fail(
                f"plugin '{name}': marketplace version '{version}' != "
                f"plugin.json version '{manifest.get('version')}'"
            )
        if description and manifest.get("description") != description:
            fail(
                f"plugin '{name}': marketplace description does not match "
                f"plugin.json description (duplicate manifest drift)"
            )

        pyproject = plugin_dir / "pyproject.toml"
        py_name = pyproject_field(pyproject, PYPROJECT_NAME_RE, "name")
        if py_name is not None and py_name != name:
            fail(f"plugin '{name}': pyproject.toml name '{py_name}' != '{name}'")
        py_version = pyproject_field(pyproject, PYPROJECT_VERSION_RE, "version")
        if py_version is not None and version != py_version:
            fail(
                f"plugin '{name}': marketplace version '{version}' != "
                f"pyproject.toml version '{py_version}'"
            )
        py_desc = pyproject_field(pyproject, PYPROJECT_DESC_RE, "description")
        if py_desc is not None and description and py_desc != description:
            fail(
                f"plugin '{name}': marketplace description does not match "
                f"pyproject.toml description (duplicate manifest drift)"
            )

        server_name, server_version = main_py_server(plugin_dir / "main.py")
        if server_name is not None and server_name != name:
            fail(f"plugin '{name}': main.py MCPServer name '{server_name}' != '{name}'")
        if server_version is not None and version != server_version:
            fail(
                f"plugin '{name}': marketplace version '{version}' != "
                f"main.py MCPServer version '{server_version}'"
            )

        mcp_json = plugin_dir / ".mcp.json"
        if mcp_json.is_file():
            mcp_data = load_json(mcp_json)
            if mcp_data is not None:
                servers = mcp_data.get("mcpServers")
                if not isinstance(servers, dict) or set(servers) != {name}:
                    fail(
                        f"plugin '{name}': .mcp.json mcpServers keys "
                        f"{sorted(servers) if isinstance(servers, dict) else servers!r} "
                        f"!= ['{name}']"
                    )

    if train_version is not None:
        check_doc_files(train_version)

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
