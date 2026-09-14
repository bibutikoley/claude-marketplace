"""Release-system gate: version train, manifest sync, pinned docs, CI freshness.

Stdlib-only so it runs anywhere (no mcp dependency). Derive the expected
version from marketplace.json itself — never hardcode it here.
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bump_version
import validate_marketplace as vm
import validate_release as vr

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

    def test_stamps_version_badges(self):
        new, counts = bump_version.bump_doc_text(
            '<span class="version">v1.2.3</span>\n', "9.9.9"
        )
        self.assertIn('<span class="version">v9.9.9</span>', new)
        self.assertEqual(counts["version_badges"], 1)
        twice, _ = bump_version.bump_doc_text(new, "9.9.9")
        self.assertEqual(new, twice)

    def test_span_badges_track_train(self):
        for path in vm.DOC_FILES:
            for v in vm.SPAN_VERSION_RE.findall(path.read_text(encoding="utf-8")):
                self.assertEqual(v, train_version(), f"{path.name}: stale badge v{v}")


class TestCIFreshness(unittest.TestCase):
    def test_no_hardcoded_module_lists(self):
        text = CI_YML.read_text(encoding="utf-8")
        self.assertNotIn("main.py android.py ios.py", text)
        self.assertNotIn("main.py notes.py", text)
        self.assertNotIn("-m py_compile plugins/", text)

    def test_uses_current_actions_and_node_lts(self):
        text = CI_YML.read_text(encoding="utf-8")
        self.assertIn("actions/checkout@v5", text)
        self.assertIn("actions/setup-python@v6", text)
        self.assertIn("actions/setup-node@v5", text)
        self.assertIn("setup-uv", text)
        self.assertNotIn("actions/checkout@v4", text)
        self.assertNotIn("actions/setup-python@v5", text)
        self.assertNotIn("actions/setup-node@v4", text)
        self.assertNotIn("node-version: 20", text)
        self.assertTrue(
            re.search(r"node-version:\s*2[24]", text),
            "CI must use a current Node LTS (22/24), not stale Node 20",
        )

    def test_ci_calls_central_verify(self):
        text = CI_YML.read_text(encoding="utf-8")
        self.assertIn("./scripts/verify.sh", text)
        verify = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
        self.assertIn("validate_marketplace", verify)
        self.assertIn("compileall", verify)
        self.assertIn("uv sync --locked", verify)
        self.assertIn("find ", verify)

    def test_verify_runs_release_tests_and_lints_them(self):
        verify = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
        self.assertTrue(
            re.search(r"pytest\s+tests\b", verify), "verify.sh must run tests/"
        )
        self.assertIn("plugins/mobile-mcp/tests", verify)
        self.assertIn("plugins/apple-notes-mcp/tests", verify)
        for line in verify.splitlines():
            if "ruff check" in line or "ruff format" in line:
                self.assertIn("tests", line)


MAIN_PY_DYNAMIC = """from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

def _package_version() -> str:
    dist_name = "{name}"
    try:
        return _dist_version(dist_name)
    except PackageNotFoundError:
        pass
    return "0.0.0"

mcp = MCPServer("{name}", version=_package_version())
"""


def _make_repo(base: Path, version: str = "0.5.0") -> Path:
    """Minimal repo layout that validate_release.validate() accepts."""
    (base / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (base / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "name": "mobile-mcp",
                        "source": "./plugins/mobile-mcp",
                        "version": version,
                    },
                    {
                        "name": "apple-notes-mcp",
                        "source": "./plugins/apple-notes-mcp",
                        "version": version,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    for name in ("mobile-mcp", "apple-notes-mcp"):
        pdir = base / "plugins" / name
        (pdir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (pdir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": name, "version": version}), encoding="utf-8"
        )
        (pdir / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8"
        )
        (pdir / "main.py").write_text(
            MAIN_PY_DYNAMIC.format(name=name), encoding="utf-8"
        )
    (base / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## v{version}\n\n- Test release notes.\n", encoding="utf-8"
    )
    return base


class TestValidateRelease(unittest.TestCase):
    def test_valid_repository_state_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            self.assertEqual(vr.validate("v0.5.0", root), [])

    def test_real_repository_valid_for_current_train(self):
        self.assertEqual(vr.validate(f"v{train_version()}", ROOT), [])

    def test_all_plugin_versions_equal_release_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            versions = vr.collect_versions(root)
            self.assertGreaterEqual(len(versions), 8)  # 4 sources x 2 plugins
            self.assertEqual(set(versions.values()), {"0.5.0"})

    def test_mismatched_plugin_json_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            bad = root / "plugins" / "mobile-mcp" / ".claude-plugin" / "plugin.json"
            bad.write_text(json.dumps({"name": "mobile-mcp", "version": "0.4.9"}))
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("plugin.json:mobile-mcp" in e for e in errors), errors)

    def test_marketplace_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            mp = root / ".claude-plugin" / "marketplace.json"
            data = json.loads(mp.read_text(encoding="utf-8"))
            data["plugins"][0]["version"] = "0.4.0"
            mp.write_text(json.dumps(data), encoding="utf-8")
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("marketplace:mobile-mcp" in e for e in errors), errors)

    def test_unlisted_manifest_and_pyproject_mismatches_rejected(self):
        """Discovery covers release files accidentally omitted from catalog."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            future = root / "plugins" / "future-mcp"
            (future / ".claude-plugin").mkdir(parents=True)
            (future / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": "future-mcp", "version": "0.4.0"})
            )
            (future / "pyproject.toml").write_text(
                '[project]\nname = "future-mcp"\nversion = "0.4.0"\n'
            )
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("plugin.json:future-mcp" in e for e in errors), errors)
            self.assertTrue(
                any("pyproject.toml:future-mcp" in e for e in errors), errors
            )

    def test_pyproject_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            pp = root / "plugins" / "apple-notes-mcp" / "pyproject.toml"
            pp.write_text('[project]\nname = "apple-notes-mcp"\nversion = "0.1.0"\n')
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(
                any("pyproject.toml:apple-notes-mcp" in e for e in errors), errors
            )

    def test_runtime_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            # Legacy literal with a stale version must not slip through.
            (root / "plugins" / "mobile-mcp" / "main.py").write_text(
                'mcp = MCPServer("mobile-mcp", version="0.4.0")\n', encoding="utf-8"
            )
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("runtime:mobile-mcp" in e for e in errors), errors)

    def test_unlisted_runtime_version_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            future = root / "plugins" / "future-mcp"
            future.mkdir(parents=True)
            (future / "main.py").write_text(
                'mcp = MCPServer("future-mcp", version="0.4.0")\n', encoding="utf-8"
            )
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("runtime:future-mcp" in e for e in errors), errors)

    def test_dynamic_runtime_resolves_pyproject_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            versions = vr.collect_versions(root)
            self.assertEqual(versions["runtime:mobile-mcp"], "0.5.0")
            self.assertEqual(versions["runtime:apple-notes-mcp"], "0.5.0")

    def test_missing_changelog_entry_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            (root / "CHANGELOG.md").write_text("# Changelog\n\n## v0.4.0\n\n- Old.\n")
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("CHANGELOG" in e for e in errors), errors)

    def test_empty_changelog_section_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            (root / "CHANGELOG.md").write_text("# Changelog\n\n## v0.5.0\n\n")
            errors = vr.validate("v0.5.0", root)
            self.assertTrue(any("CHANGELOG" in e for e in errors), errors)

    def test_invalid_tag_format_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_repo(Path(tmp), "0.5.0")
            for bad in ("0.5.0", "v0.5", "v0.5.0.1", "vX.Y.Z", "", "release-0.5.0"):
                with self.subTest(tag=bad):
                    self.assertNotEqual(vr.validate(bad, root), [])
                    with self.assertRaises(ValueError):
                        vr.parse_tag(bad)

    def test_parse_tag_strips_leading_v(self):
        self.assertEqual(vr.parse_tag("v0.5.0"), "0.5.0")

    def test_release_workflow_fails_closed(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("validate_release.py", text)
        self.assertIn("validate_marketplace.py", text)
        self.assertIn("verify.sh", text)
        # No silent generic-notes fallback.
        self.assertNotIn("Release ${GITHUB_REF_NAME}", text)


if __name__ == "__main__":
    unittest.main()
