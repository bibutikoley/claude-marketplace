import ast
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import notes
import main


def with_scope(*entries):
    return patch.object(notes, "ALLOWED_FOLDERS", frozenset(entries))


class TestCanonicalScope(unittest.TestCase):
    def test_is_allowed_exact_and_bare(self):
        with with_scope("iCloud/Work", "Personal"):
            self.assertTrue(notes.is_allowed_folder("iCloud/Work"))
            # Full-path entry must NOT leak across accounts.
            self.assertFalse(notes.is_allowed_folder("On My Mac/Work"))
            # Bare entry matches any account.
            self.assertTrue(notes.is_allowed_folder("iCloud/Personal"))
            self.assertTrue(notes.is_allowed_folder("On My Mac/Personal"))
            self.assertFalse(notes.is_allowed_folder("iCloud/Other"))

    def test_unscoped_allows_everything(self):
        with with_scope():
            self.assertTrue(notes.is_allowed_folder("iCloud/Anything"))
            self.assertFalse(notes.scoped())

    def test_allowed_leaves_bare_only(self):
        with with_scope("iCloud/Work", "Personal"):
            # "Work" must NOT appear: full-path entries don't contribute leaves.
            self.assertEqual(notes.allowed_leaves(), {"Personal"})

    def test_require_full_path_exact(self):
        with with_scope("iCloud/Work"):
            notes.require_folder_in_scope("iCloud/Work")  # exact: ok
            with self.assertRaises(notes.NotesError):
                notes.require_folder_in_scope("On My Mac/Work")
            # Bare leaf keeps legacy compat (matches the entry's leaf).
            notes.require_folder_in_scope("Work")
            with self.assertRaises(notes.NotesError):
                notes.require_folder_in_scope("Other")

    def test_list_folders_filters_canonical(self):
        all_paths = ["iCloud/Work", "On My Mac/Work", "iCloud/Personal"]
        with with_scope("iCloud/Work"):
            with patch.object(notes, "_run_jxa", return_value=json.dumps(all_paths)):
                self.assertEqual(notes.list_folders(), ["iCloud/Work"])

    def test_create_note_requires_explicit_folder_when_scoped(self):
        with with_scope("iCloud/Work"):
            with self.assertRaises(notes.NotesError):
                notes.create_note("T", "body", None)

    def test_create_note_rejects_out_of_scope_full_path(self):
        with with_scope("iCloud/Work"):
            with patch.object(notes, "_run_jxa", side_effect=AssertionError("must not reach JXA")):
                with self.assertRaises(notes.NotesError):
                    notes.create_note("T", "body", "On My Mac/Work")

    def test_create_folder_gated_by_scope(self):
        with with_scope("iCloud/Work"):
            with patch.object(notes, "_run_jxa", side_effect=AssertionError("must not reach JXA")):
                with self.assertRaises(notes.NotesError):
                    notes.create_folder("Scratch")
            with patch.object(
                notes, "_run_jxa", return_value=json.dumps({"id": "1", "name": "Work"})
            ):
                notes.create_folder("Work")

    def test_require_note_in_scope_full_path(self):
        with with_scope("iCloud/Work"):
            with patch.object(notes, "_run_jxa", return_value=json.dumps("iCloud/Work")):
                self.assertEqual(notes._require_note_in_scope("some-id"), "iCloud/Work")
        with with_scope("On My Mac/Work"):
            with patch.object(notes, "_run_jxa", return_value=json.dumps("iCloud/Work")):
                with self.assertRaises(notes.NotesError):
                    notes._require_note_in_scope("some-id")

    def _list_side_effect(self, list_payload, folders_payload):
        def _run(script, timeout=None):
            if "modificationDate" in script:
                return json.dumps(list_payload)
            return json.dumps(folders_payload)

        return _run

    def test_list_notes_scope_and_filter(self):
        listing = [
            {"id": "1", "name": "A", "modified": "2026-09-01T00:00:00.000Z"},
            {"id": "2", "name": "B", "modified": "2026-09-02T00:00:00.000Z"},
        ]
        folders = ["iCloud/Work", "On My Mac/Work"]
        with with_scope("iCloud/Work"):
            with patch.object(
                notes,
                "_run_jxa",
                side_effect=self._list_side_effect(listing, folders),
            ):
                page, total = notes.list_notes()
                self.assertEqual(total, 1)
                self.assertEqual(page[0]["folder"], "iCloud/Work")
                # Full-path filter matches exactly.
                page2, _ = notes.list_notes(folder="iCloud/Work")
                self.assertEqual(len(page2), 1)
                page3, _ = notes.list_notes(folder="On My Mac/Work")
                self.assertEqual(len(page3), 0)
                # Bare-leaf filter matches the leaf segment.
                page4, _ = notes.list_notes(folder="Work")
                self.assertEqual(len(page4), 1)

    def test_get_note_enforces_full_path(self):
        note = {
            "id": "1",
            "name": "A",
            "body": "<div>x</div>",
            "plaintext": "x",
            "folder": "Work",
            "folder_full": "On My Mac/Work",
            "created": "2026-09-01T00:00:00.000Z",
            "modified": "2026-09-02T00:00:00.000Z",
        }
        with with_scope("iCloud/Work"):
            with patch.object(notes, "_run_jxa", return_value=json.dumps(note)):
                with self.assertRaises(notes.NotesError):
                    notes.get_note("1", format="plaintext")
        with with_scope("On My Mac/Work"):
            with patch.object(notes, "_run_jxa", return_value=json.dumps(dict(note))):
                got = notes.get_note("1", format="plaintext")
                # Canonicalized: folder is the full path.
                self.assertEqual(got["folder"], "On My Mac/Work")

    def test_search_notes_scope(self):
        matches = [{"id": "1", "name": "Alpha"}, {"id": "2", "name": "Alphabet"}]
        folders = ["iCloud/Work", "iCloud/Other"]
        with with_scope("iCloud/Work"):

            def _run(script, timeout=None):
                if "var q =" in script:
                    return json.dumps(matches)
                return json.dumps(folders)

            with patch.object(notes, "_run_jxa", side_effect=_run):
                out = notes.search_notes("alpha", False, 10)
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0]["folder"], "iCloud/Work")

    def test_main_tools_return_call_tool_result(self):
        main_py = Path(__file__).resolve().parent.parent / "main.py"
        tree = ast.parse(main_py.read_text(encoding="utf-8"))
        funcdefs = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        tool_funcs = [
            n
            for n in funcdefs
            if any(
                isinstance(d, ast.Call) and getattr(getattr(d, "func", None), "attr", "") == "tool"
                for d in n.decorator_list
            )
        ]
        self.assertGreaterEqual(len(tool_funcs), 11)
        for fn in tool_funcs:
            self.assertIsNotNone(fn.returns, f"tool {fn.name} must have a return annotation")
            self.assertEqual(
                ast.unparse(fn.returns),
                "CallToolResult",
                f"tool {fn.name} must be annotated -> CallToolResult",
            )

    def test_destructive_mutations_require_server_side_confirm(self):
        cases = [
            (main.update_note, {"note_id": "n1", "content": "replacement"}, "update_note"),
            (main.delete_note, {"note_id": "n1"}, "delete_note"),
            (main.delete_folder, {"name": "iCloud/Work"}, "delete_folder"),
        ]
        for tool, kwargs, attr in cases:
            with self.subTest(tool=tool.__name__):
                with patch.object(notes, attr, return_value={"name": "x", "id": "1"}) as mocked:
                    denied = tool(**kwargs)
                    self.assertTrue(denied.is_error)
                    self.assertTrue(denied.structured_content["confirm_required"])
                    mocked.assert_not_called()

                    allowed = tool(**kwargs, confirm=True)
                    self.assertFalse(allowed.is_error)
                    mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
