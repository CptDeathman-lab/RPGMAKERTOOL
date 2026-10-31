import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dialogue_core import MapDocument, SafetyError, create_working_copy, decode, messages, escape_codes


def command(code, parameters, indent=0):
    return dict(code=code, indent=indent, parameters=parameters)


class DialogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "DragonTail-original"
        (self.source / "data").mkdir(parents=True)
        (self.source / "Game.rpgproject").write_text("RPGMV 1.6.3")
        commands = [command(111, [1, 10, 0, 2, 0]),
                    command(101, ["Actor1", 2, 0, 2], 1),
                    command(401, [r"Hello, \N[1]!"], 1),
                    command(401, [r"\C[2]DragonTail\C[0] awaits.\!"], 1),
                    command(121, [4, 4, 0], 1),
                    command(122, [10, 10, 0, 0, 3], 1),
                    command(205, [-1, {"list": [{"code": 1}], "repeat": False}], 1),
                    command(356, ["StoryProgress advance"], 1),
                    command(0, [], 1), command(412, []),
                    command(101, ["", 0, 1, 0]), command(401, ["Second message."]), command(0, [])]
        self.map = {"displayName": "Forest", "events": [None, {"id": 1, "name": "Guide", "pages": [
            {"conditions": {"switch1Id": 4}, "list": commands}, {"list": [command(0, [])]}]}]}
        self.raw = json.dumps(self.map, indent=2).encode()
        (self.source / "data" / "Map001.json").write_bytes(self.raw)
        self.root = create_working_copy(self.source, self.base / "copy")
        self.path = self.root / "data" / "Map001.json"
        self.doc = MapDocument(self.root, self.path)

    def test_edit_backup_and_exact_unrelated_preservation(self):
        blocks = messages(self.doc.page(1, 0))
        self.assertEqual(len(blocks), 2)
        lines = [r"Welcome, \N[1]!", r"\C[2]DragonTail\C[0] calls.\!"]
        self.doc.edit(1, 0, blocks[0].header_index, lines)
        backup = self.doc.save()
        self.assertEqual(backup.read_bytes(), self.raw)
        self.assertEqual((self.source / "data" / "Map001.json").read_bytes(), self.raw)
        expected = copy.deepcopy(self.map)
        for index, line in zip((2, 3), lines):
            expected["events"][1]["pages"][0]["list"][index]["parameters"][0] = line
        self.assertEqual(decode(self.path.read_bytes()), expected)
        self.assertIsNone(self.doc.save())
        self.doc.edit(1, 0, 10, ["Another message."])
        second_backup = self.doc.save()
        self.assertEqual(decode(second_backup.read_bytes()), expected)

    def test_reject_added_lines_and_modified_escape_codes(self):
        for lines in [["Extra", "line", "here"], ["Lost code", r"\C[2]DragonTail\C[0] awaits.\!"],
                      [r"Hi \N[2]", r"\C[2]DragonTail\C[0] awaits.\!"],
                      ["Hello\nthere", "Next"]]:
            with self.subTest(lines=lines), self.assertRaises(SafetyError):
                self.doc.edit(1, 0, 1, lines)
        self.assertEqual(self.doc.data, self.map)

    def test_unrelated_changes_rejected(self):
        for index in [0, 1, 4, 5, 6, 7]:
            with self.subTest(index=index):
                doc = MapDocument(self.root, self.path)
                doc.page(1, 0)[index]["parameters"] = ["tampered"]
                with self.assertRaises(SafetyError):
                    doc.save()
                self.assertEqual(self.path.read_bytes(), self.raw)

    def test_concurrent_edit_refused(self):
        self.doc.edit(1, 0, 10, ["Edited"])
        self.path.write_bytes(b"{}")
        with self.assertRaises(SafetyError):
            self.doc.save()
        self.assertEqual(self.path.read_bytes(), b"{}")

    def test_failed_atomic_replace_preserves_file_and_backup(self):
        self.doc.edit(1, 0, 10, ["Edited"])
        with patch("dialogue_core.os.replace", side_effect=OSError("locked file")):
            with self.assertRaises(OSError):
                self.doc.save()
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(next((self.root / "dialogue_backups").iterdir()).read_bytes(), self.raw)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_copy_rejects_source_nested_and_existing_destinations(self):
        for destination in [self.source, self.source / "nested", self.root]:
            with self.subTest(destination=destination), self.assertRaises(SafetyError):
                create_working_copy(self.source, destination)

    def test_map_paths_and_links_rejected(self):
        with self.assertRaises(SafetyError):
            MapDocument(self.root, self.source / "data" / "Map001.json")
        (self.source / "linked").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(SafetyError):
            create_working_copy(self.source, self.base / "new-copy")

    def test_strict_json(self):
        for raw in [b'{"x":1,"x":2}', b'{"x":NaN}']:
            with self.assertRaises(SafetyError):
                decode(raw)

    def test_escape_tokens_include_plugin_codes_and_trailing_slash(self):
        text = "\\N[1] \\Custom[hero] \\! \\{ \\\\ end\\"
        self.assertEqual(escape_codes(text), ["\\N[1]", "\\Custom[hero]", "\\!", "\\{", "\\\\", "\\"])

    def test_backup_failure_does_not_modify_map(self):
        self.doc.edit(1, 0, 10, ["Edited"])
        (self.root / "dialogue_backups").write_text("Not a directory")
        with self.assertRaises(OSError):
            self.doc.save()
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_message_structure_rejected_when_malformed(self):
        commands = self.doc.page(1, 0)
        commands[2]["indent"] = 0
        with self.assertRaises(SafetyError):
            messages(commands)

    def test_unicode_blank_line_and_bom(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + self.raw)
        doc = MapDocument(self.root, self.path)
        doc.edit(1, 0, 10, ["Grüße — 龍"])
        backup = doc.save()
        self.assertTrue(backup.read_bytes().startswith(b"\xef\xbb\xbf"))
        doc.edit(1, 0, 10, [""])
        doc.save()
        self.assertEqual(decode(self.path.read_bytes())["events"][1]["pages"][0]["list"][11]["parameters"], [""])


if __name__ == "__main__":
    unittest.main()
