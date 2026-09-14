#!/usr/bin/env bash
# Centralized repository verification: the same checks developers run
# locally and CI runs on every push/PR. Fail-closed (set -euo pipefail).
set -euo pipefail

cd "$(dirname "$0")/.."

python3 scripts/validate_marketplace.py

# compileall covers every current and future module — no file list to rot.
python3 -m compileall -q plugins scripts tests

# Locks are the reproducible install; --locked fails if a lock is stale.
uv sync --locked --project plugins/mobile-mcp
uv sync --locked --project plugins/apple-notes-mcp

# Runtime deps come from the locks (matches the README's
# `uv sync --project plugins/<name>` claim); pytest is provided
# ephemerally so it never leaks into the locks.
uv run --project plugins/mobile-mcp --with pytest -- python -m pytest plugins/mobile-mcp/tests -q
uv run --project plugins/apple-notes-mcp --with pytest -- python -m pytest plugins/apple-notes-mcp/tests -q
uv run --with pytest -- python -m pytest tests -q

uv run --with "ruff==0.14.5" -- ruff check plugins/mobile-mcp plugins/apple-notes-mcp scripts tests
uv run --with "ruff==0.14.5" -- ruff format --check plugins/mobile-mcp plugins/apple-notes-mcp scripts tests

# Top-level modules discovered via find so new modules are type-checked
# automatically (tests/ excluded: untyped test code). mypy runs inside the
# plugin's locked env so imports resolve exactly as shipped.
(cd plugins/mobile-mcp && uv run --with "mypy==1.18.1" -- python -m mypy $(find . -maxdepth 1 -name '*.py' | sort))
(cd plugins/apple-notes-mcp && uv run --with "mypy==1.18.1" -- python -m mypy $(find . -maxdepth 1 -name '*.py' | sort))
