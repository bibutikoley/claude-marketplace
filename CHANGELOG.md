# Changelog

## Unreleased

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
