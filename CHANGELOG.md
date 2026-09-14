# Changelog

## Unreleased

## v0.5.0

- Release hardening: `scripts/validate_release.py` verifies a `vX.Y.Z` tag
  against `marketplace.json`, every `plugin.json` / `pyproject.toml`, the
  MCP runtime versions, and a non-empty `## vX.Y.Z` changelog section.
  `release.yml` now runs tag validation → marketplace validation → the
  full `./scripts/verify.sh` suite → strict changelog extraction before
  creating a GitHub release; generic/empty release notes are refused.
- Single source of truth for MCP runtime versions: both servers derive
  `MCPServer` `version` from installed package metadata
  (`importlib.metadata`) with a `pyproject.toml` source-checkout fallback,
  and `validate_marketplace.py` rejects runtime/package drift.
- iOS host install allowlist: `ios_install_app` (simulator and device) is
  deny-by-default without `IOS_ALLOWED_INSTALL_DIRS`
  (`os.pathsep`-separated roots, `~` expanded, resolved before
  authorization); symlinks rejected like Android `install_apk`, traversal
  outside allowed roots refused.
- `./scripts/verify.sh` centralizes every Python-side gate (marketplace
  validation, `compileall`, locked `uv sync`, pytest suites, ruff, mypy);
  CI calls it instead of duplicating command blocks. CI actions moved to
  `checkout@v5` / `setup-python@v6` / `setup-node@v5` /
  `setup-uv@v7` with Node 24 for the site build.
- Attack-oriented regression tests: Android shell allowlist/quoting,
  filesystem traversal and symlink rejection, iOS bundle-ID/URL/install
  validation, and confirm-gating for every destructive mobile and Apple
  Notes mutation (`update_note`, `delete_note`, `delete_folder`).
- New `SECURITY.md` documenting the threat model and every control.
- Fixed `delete_file` refusing `/sdcard` paths: the `/` protected root
  prefix matched every absolute path; it is now exact-match only while all
  system roots stay refused.

## v0.4.0

- Rename `apple-notes` plugin and directory to `apple-notes-mcp`
  (`plugins/apple-notes-mcp/`); all instance names, config keys,
  prompts, and subdirectory URLs unified.
- Dependency bounds (`mcp>=1.0,<3`, `markdown>=3.10.3,<4`,
  `markdownify>=1.2.3,<2`) with per-plugin `uv.lock`.
- `scripts/bump_version.py`: one-command releases (manifests,
  packaging, server strings, pinned URLs).
- Security-model documentation for both plugins.
- Real-device integration guides (USB Android, physical iOS).
- Mobile README tool tables audited against implementations.

## v0.3.0

Breaking: `mobile-mcp` drops 15 one-line alias tools (81 → 66 tools).
Migration: `take_screenshot`→`screenshot`,
`press_*`→`key_event`, `open_app`→`launch_app`,
`stop_app`→`force_stop`, `list_installed_apps`→`list_packages`,
`file_*`→`push_file`/`pull_file`/`list_files`/`delete_file`.

- Ruff (`check` + `format`) and mypy gates in CI, configs in both
  `pyproject.toml` files.
- Bugs found by the new gates and fixed: `ios_clipboard_paste`
  `TypeError` on success, `ios_device_info` `**info` splat risk,
  `file_pull` crash on omitted destination (now defaults to cwd),
  wire-alias constructor kwargs, `list_notes` return annotation.

## v0.2.0

- Server-side `confirm=true` gates on 7 destructive `mobile-mcp`
  tools (`uninstall_app`, `clear_app_data`, `delete_file`, `reboot`,
  `ios_erase_simulator`, `ios_uninstall_app`, `ios_device_reboot`).
- Canonical `Account/...` folder authorization in Apple Notes
  (full-path entries match exactly; `create_folder` scope-gated).
- `apple-notes-mcp` tools standardized on `-> CallToolResult`.
- `scripts/validate_marketplace.py` + CI gate (duplicate
  names/sources, version sync, required files).
- 21 new tests for scope and destructive-confirm behavior.
- Pinned `@vX.Y.Z` install snippets everywhere.
- Removed duplicate `apple-notes` marketplace entry.

## v0.1.0

- Initial marketplace: `mobile-mcp` (unified Android ADB +
  `android` CLI and iOS `simctl`/`devicectl`/Quartz automation) and
  Apple Notes CRUD via JXA with Notes.app as source of truth.
