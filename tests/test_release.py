"""Release-system gate: version train, manifest sync, pinned docs, CI freshness.

Stdlib-only so it runs anywhere (no mcp dependency). Derive the expected
version from marketplace.json itself — never hardcode it here.
"""

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bump_version
import validate_marketplace as vm

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def marketplace_entries() -> list[dict]:
    data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    return data["plugins"]


def train_version() -> str:
    versions = {p["version"] for p in marketplace_entries()}
    assert len(versions) == 1, f"release train diverged: {sorted(versions)}"
    return next(iter(versions))


class TestReleaseTrain(unittest.TestCase):
    def test_single_train_version(self):
        self.assertRegex(train_version(), r"^\d+\.\d+\.\d+$")

    def test_bumper_validator_agree_on_scope(self):
        self.assertEqual(set(bump_version.PLUGINS), set(vm.PLUGINS))
        self.assertEqual(
            [p.relative_to(vm.ROOT) for p in bump_version.DOC_FILES],
            [p.relative_to(vm.ROOT) for p in vm.DOC_FILES],
        )


class TestManifestSync(unittest.TestCase):
    def test_no_duplicate_names_or_sources(self):
        names, sources = [], []
        for p in marketplace_entries():
            names.append(p["name"])
            sources.append(p["source"].rstrip("/"))
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(len(set(sources)), len(sources))

    def test_required_files_exist(self):
        for p in marketplace_entries():
            d = ROOT / p["source"].rstrip("/")
            for rel in vm.REQUIRED_PLUGIN_FILES:
                self.assertTrue((d / rel).is_file(), f"{p['name']}: missing {rel}")

    def test_name_sync(self):
        for p in marketplace_entries():
            d = ROOT / p["source"].rstrip("/")
            manifest = json.loads((d / ".claude-plugin" / "plugin.json").read_text())
            self.assertEqual(manifest["name"], p["name"])
            py_name = vm.pyproject_field(
                d / "pyproject.toml", vm.PYPROJECT_NAME_RE, "name"
            )
            self.assertEqual(py_name, p["name"])
            server_name, _ = vm.main_py_server(d / "main.py")
            self.assertEqual(server_name, p["name"])
            mcp_data = json.loads((d / ".mcp.json").read_text())
            self.assertEqual(set(mcp_data["mcpServers"]), {p["name"]})

    def test_version_sync(self):
        train = train_version()
        for p in marketplace_entries():
            self.assertEqual(p["version"], train)
            d = ROOT / p["source"].rstrip("/")
            manifest = json.loads((d / ".claude-plugin" / "plugin.json").read_text())
            self.assertEqual(manifest["version"], train)
            py_version = vm.pyproject_field(
                d / "pyproject.toml", vm.PYPROJECT_VERSION_RE, "version"
            )
            self.assertEqual(py_version, train)
            _, server_version = vm.main_py_server(d / "main.py")
            self.assertEqual(server_version, train)

    def test_description_sync(self):
        for p in marketplace_entries():
            d = ROOT / p["source"].rstrip("/")
            manifest = json.loads((d / ".claude-plugin" / "plugin.json").read_text())
            self.assertEqual(manifest["description"], p["description"])
            py_desc = vm.pyproject_field(
                d / "pyproject.toml", vm.PYPROJECT_DESC_RE, "description"
            )
            self.assertEqual(py_desc, p["description"])


class TestPinnedDocs(unittest.TestCase):
    def test_pinned_urls_match_train(self):
        train = train_version()
        for path in vm.DOC_FILES:
            text = path.read_text(encoding="utf-8")
            urls = vm.PINNED_URL_RE.findall(text)
            self.assertGreaterEqual(len(urls), 1, f"{path.name}: no pinned URLs")
            for v in urls:
                self.assertEqual(v, train, f"{path.name}: stale pinned URL v{v}")

    def test_prose_versions_match_train(self):
        train = train_version()
        for path in vm.DOC_FILES:
            for v in vm.doc_drift_versions(path.read_text(encoding="utf-8")):
                self.assertEqual(v, train, f"{path.name}: stale prose v{v}")


class TestBumperHelpers(unittest.TestCase):
    SAMPLE = (
        "pinned to `v1.2.3` (drop `@v1.2.3` to track `main`)\n"
        'run `uvx --from "git+https://github.com/x/claude-marketplace@v1.2.3#subdirectory=p" s`\n'
        "> Removed in v0.3.0 (were one-line aliases)\n"
        "keep releases (`@vX.Y.Z`)\n"
    )

    def test_stamps_current_and_preserves_history(self):
        new, counts = bump_version.bump_doc_text(self.SAMPLE, "9.9.9")
        self.assertIn("`v9.9.9`", new)
        self.assertIn("`@v9.9.9`", new)
        self.assertIn("@v9.9.9#subdirectory=", new)
        self.assertIn("Removed in v0.3.0", new)
        self.assertIn("`@vX.Y.Z`", new)
        self.assertGreaterEqual(counts["pinned_urls"], 1)

    def test_idempotent(self):
        once, _ = bump_version.bump_doc_text(self.SAMPLE, "9.9.9")
        twice, _ = bump_version.bump_doc_text(once, "9.9.9")
        self.assertEqual(once, twice)


class TestCIFreshness(unittest.TestCase):
    def test_no_hardcoded_module_lists(self):
        text = CI_YML.read_text(encoding="utf-8")
        self.assertNotIn("main.py android.py ios.py", text)
        self.assertNotIn("main.py notes.py", text)
        self.assertNotIn("-m py_compile plugins/", text)

    def test_uses_discovery_and_locks(self):
        text = CI_YML.read_text(encoding="utf-8")
        self.assertIn("compileall", text)
        self.assertIn("setup-uv", text)
        self.assertIn("uv sync --locked", text)
        self.assertIn("find ", text)

    def test_runs_release_tests_and_lints_them(self):
        text = CI_YML.read_text(encoding="utf-8")
        self.assertTrue(re.search(r"pytest\s+tests\b", text), "CI must run tests/")
        for line in text.splitlines():
            if line.strip().startswith("run: ruff"):
                self.assertIn("tests", line)


if __name__ == "__main__":
    unittest.main()
