"""Release gate: verify a git tag matches the repository's release version.

Usage:
  python3 scripts/validate_release.py v0.5.0
  python3 scripts/validate_release.py v0.5.0 --notes-file /tmp/release-notes.md
  GITHUB_REF_NAME=v0.5.0 python3 scripts/validate_release.py

Checks (fail-closed, non-zero exit on any failure):
  - tag format is exactly ``vX.Y.Z`` (leading ``v`` required)
  - ``.claude-plugin/marketplace.json`` versions all equal X.Y.Z
  - every ``plugin.json`` version equals X.Y.Z
  - every ``pyproject.toml`` version equals X.Y.Z
  - every MCP runtime version (``main.py`` ``MCPServer`` version,
    dynamic ``_package_version()`` aware) resolves to X.Y.Z
  - ``CHANGELOG.md`` contains a non-empty ``## vX.Y.Z`` section

Marketplace structure checks and the test suite run as separate release
workflow steps; this script reuses :mod:`validate_marketplace` helpers so
tag/version logic is not duplicated in YAML.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_marketplace as vm  # noqa: E402

TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")
_IGNORED_SOURCE_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "node_modules",
}


def parse_tag(tag: str) -> str:
    """Strip the leading ``v`` and return ``X.Y.Z``.

    Raises:
        ValueError: if the tag is not exactly ``vX.Y.Z``.
    """
    tag = (tag or "").strip()
    m = TAG_RE.fullmatch(tag)
    if not m:
        raise ValueError(
            f"invalid tag format {tag!r}: expected 'vX.Y.Z' (e.g. 'v0.5.0')"
        )
    return m.group(1)


def _is_source_path(path: Path, root: Path) -> bool:
    """Whether a discovered file belongs to repository source, not a build cache."""
    parts = path.relative_to(root).parts
    return not any(
        part in _IGNORED_SOURCE_PARTS or part.endswith(".egg-info") for part in parts
    )


def _key(
    found: dict[str, str | None], prefix: str, name: str, path: Path, root: Path
) -> str:
    """Keep familiar keys for normal plugins and disambiguate duplicate names."""
    base = f"{prefix}:{name}"
    if base not in found:
        return base
    return f"{base} ({path.relative_to(root)})"


def _main_py_version(main_py: Path, root: Path) -> tuple[str | None, str | None]:
    """Resolve a MCPServer name/version with validate_marketplace's logic."""
    old_root = vm.ROOT
    before = len(vm.errors)
    vm.ROOT = root
    try:
        return vm.main_py_server(main_py)
    finally:
        vm.ROOT = old_root
        # main_py_server reports parse errors through its module-level list;
        # return None below instead so this release validator owns reporting.
        del vm.errors[before:]


def collect_versions(root: Path = ROOT) -> dict[str, str | None]:
    """Map ``'<source>:<plugin>'`` to its declared version.

    Sources: ``marketplace``, ``plugin.json``, ``pyproject.toml``,
    ``runtime`` (``main.py`` MCPServer version, dynamic-aware). ``None``
    marks an unreadable entry; callers report it as an error.
    """
    found: dict[str, str | None] = {}
    marketplace_path = root / ".claude-plugin" / "marketplace.json"
    try:
        data = json.loads(marketplace_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return found
    plugins = data.get("plugins", [])
    if not isinstance(plugins, list):
        return found
    for entry in plugins:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not name:
            continue
        found[f"marketplace:{name}"] = entry.get("version")
    # Every plugin manifest in source must participate in a release, even
    # when it was accidentally omitted from marketplace.json.
    for manifest_path in sorted(root.rglob("plugin.json")):
        if manifest_path.parent.name != ".claude-plugin" or not _is_source_path(
            manifest_path, root
        ):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            name = manifest.get("name") if isinstance(manifest, dict) else None
            name = name or str(manifest_path.parent.parent.relative_to(root))
            found[_key(found, "plugin.json", name, manifest_path, root)] = (
                manifest.get("version") if isinstance(manifest, dict) else None
            )
        except (FileNotFoundError, json.JSONDecodeError):
            name = str(manifest_path.parent.parent.relative_to(root))
            found[_key(found, "plugin.json", name, manifest_path, root)] = None
    # All Python package metadata in source must carry the tag version; this
    # intentionally includes a future plugin before it is listed in catalog.
    for pyproject in sorted(root.rglob("pyproject.toml")):
        if not _is_source_path(pyproject, root):
            continue
        name = vm.pyproject_field(pyproject, vm.PYPROJECT_NAME_RE, "name")
        name = name or str(pyproject.parent.relative_to(root))
        found[_key(found, "pyproject.toml", name, pyproject, root)] = (
            vm.pyproject_field(pyproject, vm.PYPROJECT_VERSION_RE, "version")
        )
    # Only main modules that actually construct an MCP server have a runtime
    # version to validate. Non-MCP Python entry points are irrelevant here.
    for main_py in sorted(root.rglob("main.py")):
        if not _is_source_path(main_py, root):
            continue
        try:
            text = main_py.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        if "MCPServer(" not in text:
            continue
        name, version = _main_py_version(main_py, root)
        name = name or str(main_py.parent.relative_to(root))
        found[_key(found, "runtime", name, main_py, root)] = version
    return found


def changelog_section(root: Path, version: str) -> str | None:
    """Return the body of the ``## vX.Y.Z`` CHANGELOG section.

    Returns ``None`` when the heading is missing. Empty/whitespace-only
    bodies are returned as ``""`` so callers can reject generic releases.
    """
    path = root / "CHANGELOG.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    heading = f"## v{version}"
    start: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i
            break
    if start is None:
        return None
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()


def validate(tag: str, root: Path = ROOT) -> list[str]:
    """Validate ``tag`` against ``root``. Returns a list of errors (empty = OK)."""
    errors: list[str] = []
    try:
        expected = parse_tag(tag)
    except ValueError as e:
        return [str(e)]
    versions = collect_versions(root)
    if not versions:
        return [f"no plugin versions found under {root}"]
    for source, ver in sorted(versions.items()):
        if ver is None:
            errors.append(f"{source}: version unreadable or missing")
        elif ver != expected:
            errors.append(
                f"{source}: version '{ver}' != tag version '{expected}' (tag '{tag}')"
            )
    section = changelog_section(root, expected)
    if section is None:
        errors.append(f"CHANGELOG.md: missing section '## v{expected}' for tag '{tag}'")
    elif not section:
        errors.append(
            f"CHANGELOG.md: section '## v{expected}' is empty; "
            "release notes must not be generic/empty"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "tag",
        nargs="?",
        default=os.environ.get("GITHUB_REF_NAME", ""),
        help="release tag (e.g. v0.5.0); defaults to $GITHUB_REF_NAME",
    )
    parser.add_argument(
        "--notes-file",
        default=None,
        help="write the CHANGELOG section body to this file (fails if missing)",
    )
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="repository root (for tests)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not args.tag:
        print("ERROR: no tag given (pass vX.Y.Z or set GITHUB_REF_NAME)")
        return 1
    errors = validate(args.tag, root)
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        print(f"{len(errors)} release validation error(s) for tag '{args.tag}'")
        return 1
    expected = parse_tag(args.tag)
    print(
        f"release validation: OK (tag '{args.tag}' == repository version '{expected}')"
    )
    if args.notes_file:
        section = changelog_section(root, expected)
        if not section:
            print(f"ERROR: refusing to write empty release notes for '## v{expected}'")
            return 1
        Path(args.notes_file).write_text(section + "\n", encoding="utf-8")
        print(f"wrote release notes to {args.notes_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
