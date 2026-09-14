# Contributing

## Development setup

- [uv](https://github.com/astral-sh/uv) installed; Python ≥ 3.12.
- Clone, then sync a plugin's locked environment —
  `uv sync --project plugins/<name>` — CI installs from the same `uv.lock`,
  so it reproduces the shipped dependency set exactly.

## The one command: `./scripts/verify.sh`

One entry point for every gate; developers run it locally, CI runs it on
every push/PR, and the release workflow re-runs it before publishing. It
covers, in order:

1. `scripts/validate_marketplace.py` — catalog + per-plugin manifest sync.
2. `python3 -m compileall` — every module under `plugins/`, `scripts/`, `tests/`.
3. `uv sync --locked` per plugin — fails on a stale `uv.lock`.
4. pytest — both plugin suites plus the release-system suite in `tests/`.
5. `ruff check` + `ruff format --check` (versions pinned in the script).
6. `mypy` — each plugin's top-level modules, inside its locked environment.

Run it before you commit and before you push.

## Release train

Everything ships at one version: `marketplace.json`, each plugin's
`plugin.json` / `pyproject.toml`, the `.mcp.json` server keys, the pinned
install URLs and current-version prose in `README.md`, the plugin READMEs,
and `site/index.html`. Runtime `MCPServer` versions derive from installed
package metadata (`_package_version()` in each `main.py`) — never hardcode
them.

To release:

1. Write user-visible changes under `## Unreleased` in `CHANGELOG.md`.
2. Stamp the train: `python3 scripts/bump_version.py <X.Y.Z>` (idempotent;
   never hand-edit the pinned URLs or version prose in the stamped docs).
3. A human renames `## Unreleased` to `## v<X.Y.Z>` in `CHANGELOG.md` —
   history prose is never auto-stamped.
4. `./scripts/verify.sh`, commit, then tag `v<X.Y.Z>` and push the tag.
5. `.github/workflows/release.yml` validates the tag against every
   manifest, re-runs `verify.sh`, and publishes a GitHub release from the
   matching changelog section — an empty or missing section fails the
   release.

## Dependencies

Bounds live in each plugin's `pyproject.toml` (e.g. `mcp>=1.0,<3`): lower
bounds are the oldest verified-working releases, upper bounds hold back the
next major. To upgrade: adjust the bound, run
`uv lock --upgrade-package <pkg> --project plugins/<name>`, and let the
ruff + mypy + pytest gates prove the new version safe. Dependabot submits
weekly minor/patch bumps for both plugins, the site, and the actions.

## Adding a plugin

Each plugin directory must contain (enforced by
`scripts/validate_marketplace.py`):

- `.claude-plugin/plugin.json` — the plugin manifest
- `.mcp.json` — stdio server definition; its `mcpServers` key must be
  exactly the plugin name
- `pyproject.toml` — name/version/description matching the marketplace
  entry and manifest
- `main.py` — server entrypoint (`MCPServer("<name>", version=_package_version())`)
- `README.md`

Then wire it into the train:

1. Add the entry to `.claude-plugin/marketplace.json` (unique source path
   inside the repo root).
2. Add the name to the `PLUGINS` lists in **both**
   `scripts/validate_marketplace.py` and `scripts/bump_version.py` — a
   release-suite test keeps the two set-equal.
3. Add its `uv sync --locked` + pytest lines and its mypy block to
   `scripts/verify.sh`.
4. Add its directory under the `uv` ecosystem in `.github/dependabot.yml`.
5. Document it with a pinned install snippet
   (`uvx --from "git+https://github.com/bibutikoley/claude-marketplace@vX.Y.Z#subdirectory=plugins/<name>"`)
   in the stamped docs above — `bump_version.py` maintains those pins.

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately per its
policy — never through public issues.
