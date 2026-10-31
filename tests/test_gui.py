"""Real Tk integration checks. Require a desktop DISPLAY (or Xvfb) on Linux."""
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from dialogue_core import MapDocument, create_working_copy, decode, messages
from dragontail_dialogue_manager import Application


def command(code, parameters, indent=0):
    return {"code": code, "parameters": parameters, "indent": indent}


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Needs a real or virtual desktop display")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "original"
        (self.source / "data").mkdir(parents=True)
        (self.source / "img" / "faces").mkdir(parents=True)
        (self.source / "Game.rpgproject").write_text("RPGMV 1.6.3")
        self.commands = [command(111, [0, 4, 0]), command(101, ["Actors", 5, 0, 2], 1),
                         command(401, [r"Hello \N[1]."], 1), command(121, [4, 4, 0], 1),
                         command(411, []), command(101, ["", 0, 0, 2], 1),
                         command(401, ["Farewell."], 1), command(412, []),
                         command(356, ["StoryProgress unchanged"]), command(0, [])]
        data = {"events": [None, {"id": 1, "name": "Guide", "pages": [{"list": self.commands}]}]}
        (self.source / "data" / "Map001.json").write_text(json.dumps(data))
        self.source_raw = (self.source / "data" / "Map001.json").read_bytes()
        self.window = tk.Tk()
        self.addCleanup(self.window.destroy)
        self.callback_errors = []
        self.window.report_callback_exception = lambda *error: self.callback_errors.append(error)
        # Synthetic face sheet: distinct color for every one of MV's eight slots.
        sheet = tk.PhotoImage(master=self.window, width=576, height=288)
        colors = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff", "#444444", "#ffffff"]
        for index, color in enumerate(colors):
            x, y = index % 4 * 144, index // 4 * 144
            sheet.put(color, to=(x, y, x+144, y+144))
        sheet.write(str(self.source / "img" / "faces" / "Actors.png"), format="png")
        self.root = create_working_copy(self.source, base / "copy")
        self.app = Application(self.window)
        self.addCleanup(self.app.cancel_refresh)
        self.app.root = self.root
        self.app.selection = (1, 0)
        self.app.document = MapDocument(self.root, self.root / "data" / "Map001.json")
        self.app.render(messages(self.app.document.page(1, 0)))
        self.window.update()

    def tearDown(self):
        self.assertEqual(self.callback_errors, [], "Tk callback failures")

    def edit(self, text):
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", text)
        self.window.update()

    def test_navigation_keeps_drafts_and_saves_resized_messages(self):
        self.edit("Hello\n\\N[1].\nThird line\nFourth line")
        self.assertTrue(self.app.dirty())
        self.app.go_message(1)
        self.edit("Goodbye.\nSee you soon.")
        self.app.go_message(0)
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "Hello\n\\N[1].\nThird line\nFourth line")
        self.assertTrue(self.app.save())
        self.window.update()
        data = decode((self.root / "data" / "Map001.json").read_bytes())
        edited = data["events"][1]["pages"][0]["list"]
        self.assertEqual([c for c in edited if c["code"] != 401], [c for c in self.commands if c["code"] != 401])
        self.assertEqual([len(m.lines) for m in messages(edited)], [4, 2])
        self.assertFalse(self.app.dirty())
        self.assertEqual((self.source / "data" / "Map001.json").read_bytes(), self.source_raw)
        self.assertEqual(len(list((self.root / "dialogue_backups").glob("*.json"))), 1)

    def test_portrait_pixels_all_slots_and_missing_image(self):
        expected = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                    (255, 0, 255), (0, 255, 255), (68, 68, 68), (255, 255, 255)]
        for index, rgb in enumerate(expected):
            self.app.show_portrait(("Actors", index, 0, 2))
            self.assertEqual(self.app.portrait_image.get(70, 70), rgb)
            self.assertEqual((self.app.portrait_image.width(), self.app.portrait_image.height()), (144, 144))
        self.app.show_portrait(("Missing", 0, 0, 2))
        self.assertIsNone(self.app.portrait_image)
        self.assertEqual(self.app.portrait.cget("text"), "Preview unavailable")
        self.assertEqual(str(self.app.editor.cget("state")), "normal")
        self.app.show_portrait(("", 0, 0, 2))
        self.assertEqual(self.app.portrait.cget("text"), "No portrait")

    def test_overview_find_next_and_click_to_jump(self):
        overview = self.app.scene.get("1.0", "end-1c")
        self.assertIn("Conditional branch", overview)
        self.assertIn("Else", overview)
        self.assertIn("Plugin command", overview)
        self.assertIn("Farewell.", overview)
        self.app.query.insert(0, "FAREWELL")
        self.app.find_next()
        self.assertEqual(self.app.current, 1)
        self.app.scene.see(self.app.scene_ranges[0][0])
        self.window.update()
        bounds = self.app.scene.bbox(self.app.scene_ranges[0][0])
        self.assertIsNotNone(bounds)
        self.app.scene.event_generate("<Button-1>", x=bounds[0]+2, y=bounds[1]+2)
        self.window.update()
        self.assertEqual(self.app.current, 0)

    def test_invalid_edit_and_external_change_never_write(self):
        self.edit("One\nTwo\nThree\nFour\nFive")
        with patch("dragontail_dialogue_manager.messagebox.showerror") as error:
            self.assertFalse(self.app.save())
            error.assert_called_once()
        self.assertFalse((self.root / "dialogue_backups").exists())
        self.assertEqual((self.root / "data" / "Map001.json").read_bytes(), self.source_raw)
        self.edit(r"Hello \N[1]!")
        (self.root / "data" / "Map001.json").write_bytes(b"{}")
        with patch("dragontail_dialogue_manager.messagebox.showerror"):
            self.assertFalse(self.app.save())
        self.assertEqual((self.root / "data" / "Map001.json").read_bytes(), b"{}")

    def test_empty_page_and_unsaved_navigation_cancel(self):
        self.edit(r"Welcome \N[1].")
        with patch("dragontail_dialogue_manager.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.app.can_leave())
        self.assertTrue(self.app.dirty())
        self.app.render([])
        self.window.update()
        self.assertFalse(self.app.dirty())
        self.assertEqual(str(self.app.editor.cget("state")), "disabled")
        self.assertIn("no supported", self.app.scene.get("1.0", "end-1c"))

    def test_open_project_copy_map_event_page_workflow(self):
        workspace = Path(self.temp.name) / "workspace"
        workspace.mkdir()
        with patch("dragontail_dialogue_manager.filedialog.askdirectory", side_effect=[str(self.source), str(workspace)]):
            self.app.open_project()
        deadline = time.monotonic() + 5
        while self.app.busy and time.monotonic() < deadline:
            self.window.update()
            time.sleep(0.01)
        self.assertFalse(self.app.busy, "Copy did not finish")
        self.assertEqual(self.app.root.parent, workspace)
        self.assertTrue(self.app.tree.exists("Map001.json"))
        self.app.tree.focus("Map001.json")
        self.app.expand_map()
        self.assertTrue(self.app.tree.exists("Map001.json:1:0"))
        self.app.tree.selection_set("Map001.json:1:0")
        self.app.select_event()
        self.window.update()
        self.assertEqual(len(self.app.blocks), 2)
        self.assertIsNotNone(self.app.portrait_image)
        self.assertEqual((self.source / "data" / "Map001.json").read_bytes(), self.source_raw)


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Needs a real or virtual desktop display")
class ChoiceGuiTests(unittest.TestCase):
    # Reuse the desktop/project setup without inheriting the message-only tests.
    edit = GuiTests.edit
    tearDown = GuiTests.tearDown

    def setUp(self):
        GuiTests.setUp(self)
        from test_choices import bedtime_commands
        self.commands = bedtime_commands()
        data = {"events": [None, None, None, None, {"id": 4, "name": "Bedtime", "pages": [{"list": self.commands}]}]}
        self.source_raw = json.dumps(data).encode()
        (self.source / "data" / "Map002.json").write_bytes(self.source_raw)
        (self.root / "data" / "Map002.json").write_bytes(self.source_raw)
        self.app.selection = (4, 0)
        self.app.document = MapDocument(self.root, self.root / "data" / "Map002.json")
        self.app.render(messages(self.app.document.page(4, 0)))
        self.window.update()

    def test_overview_choices_branch_ownership_and_gameplay_details(self):
        overview = self.app.scene.get("1.0", "end-1c")
        for text in ["Do you want to go to bed?", "Show Choices", "1. Yes", "2. No", "When Yes", "When No", "When Cancel",
                     "Fade out BGM (242)", "Fade out screen (221)", "Variables (122)", "StoryProgress cancelBed"]:
            self.assertIn(text, overview)
        self.assertLess(overview.index("When Yes"), overview.index("Fade out BGM"))
        self.assertLess(overview.index("Fade out BGM"), overview.index("When No"))
        self.assertGreater(overview.index("Stay awake."), overview.index("When No"))
        self.assertGreater(overview.index("StoryProgress cancelBed"), overview.index("When Cancel"))
        self.assertIn((2, 0), self.app.choice_ranges)
        self.assertIn((8, 1), self.app.choice_ranges)
        self.assertIn("Map002 · Event 004 · Page 1", self.app.page_title.get())

    def test_choice_and_branch_dialogue_edits_survive_navigation_and_save(self):
        from choice_support import choice_groups, choice_topology
        self.app.go_choice(2, 0)
        self.edit("Yes, please")
        self.assertTrue(self.app.dirty())
        self.app.go_message(0)
        self.edit("A question:\nDo you want to go to bed?")
        self.app.go_message(1)
        self.edit("Sleep well.\nGood night.")
        self.app.go_choice(8, 1)
        self.edit("Wait a little")
        self.assertTrue(self.app.save())
        self.window.update()
        cs = self.app.document.page(4, 0)
        groups = choice_groups(cs)
        self.assertEqual(groups[0].labels[0], "Yes, please")
        self.assertEqual(groups[1].labels[1], "Wait a little")
        self.assertEqual(choice_topology(cs), choice_topology(self.commands))
        self.assertEqual(self.app.active_choice, (groups[1].header_index, 1))
        self.assertFalse(self.app.dirty())
        self.assertEqual((self.source / "data" / "Map002.json").read_bytes(), self.source_raw)
        self.assertEqual(next((self.root / "dialogue_backups").glob("Map002*.json")).read_bytes(), self.source_raw)

    def test_collapse_and_nested_dialogue_navigation_reveal_ancestors(self):
        self.app.collapsed_branches.update({(2, 3), (8, 12)})
        self.app.update_overview()
        self.assertEqual(str(self.app.scene.tag_cget("collapse_2_3", "elide")), "1")
        self.app.go_message(2)  # The nested Wait branch's dialogue.
        self.assertNotIn((2, 3), self.app.collapsed_branches)
        self.assertNotIn((8, 12), self.app.collapsed_branches)
        # Toggle the outer branch through its real mouse binding.
        first, last, key = next(r for r in self.app.branch_ranges if r[2] == (2, 3))
        self.app.scene.see(first)
        self.window.update()
        bounds = self.app.scene.bbox(first)
        self.assertIsNotNone(bounds)
        self.app.scene.event_generate("<Button-1>", x=bounds[0]+2, y=bounds[1]+2)
        self.window.update()
        self.assertIn(key, self.app.collapsed_branches)
        self.assertFalse(self.app.dirty())
        self.app.query.insert(0, "Wait a")
        # Search a choice label hidden inside the collapsed outer branch.
        self.app.query.delete(0, "end")
        self.app.query.insert(0, "Sleep now")
        self.app.find_next()
        self.assertEqual(self.app.active_choice, (8, 0))
        self.assertNotIn((2, 3), self.app.collapsed_branches)

    def test_live_choice_width_warning_is_advisory_and_newline_is_refused(self):
        self.app.go_choice(2, 0)
        self.edit("W" * 100)
        self.assertIn("Choice window overflow", self.app.width_warning.cget("text"))
        self.app.update_overview()
        self.assertIn("Choice window overflow", self.app.scene.get("1.0", "end-1c"))
        self.assertTrue(self.app.save())  # Width warning does not silently truncate or reject text.
        self.edit("Two\nlines")
        before = (self.root / "data" / "Map002.json").read_bytes()
        with patch("dragontail_dialogue_manager.messagebox.showerror") as error:
            self.assertFalse(self.app.save())
            error.assert_called_once()
        self.assertEqual((self.root / "data" / "Map002.json").read_bytes(), before)

    def test_choice_only_page_supports_editing_and_unsaved_cancel(self):
        cs = [command(102, [["Yes", "No"], -1, 0, 2, 0]), command(402, [0, "Yes"]),
              command(0, [], 1), command(402, [1, "No"]), command(0, [], 1), command(404, []), command(0, [])]
        data = {"events": [None, None, None, None, {"id": 4, "pages": [{"list": cs}]}]}
        path = self.root / "data" / "Map002.json"
        path.write_text(json.dumps(data))
        self.app.document = MapDocument(self.root, path)
        self.app.render([])
        self.assertEqual(self.app.active_choice, (0, 0))
        self.assertEqual(str(self.app.editor.cget("state")), "normal")
        self.edit("Certainly")
        with patch("dragontail_dialogue_manager.messagebox.askyesnocancel", return_value=None):
            self.assertFalse(self.app.can_leave())
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.document.page(4, 0)[1]["parameters"], [0, "Certainly"])
        self.app.revert()
        self.assertEqual(self.app.editor.get("1.0", "end-1c"), "Certainly")

    def test_malformed_choice_labels_are_displayed_but_not_editable(self):
        path = self.root / "data" / "Map002.json"
        data = decode(path.read_bytes())
        data["events"][4]["pages"][0]["list"][3]["parameters"][1] = "Out of sync"
        path.write_text(json.dumps(data))
        self.app.document = MapDocument(self.root, path)
        self.app.render(messages(self.app.document.page(4, 0)))
        self.assertIn("READ-ONLY", self.app.scene.get("1.0", "end-1c"))
        self.assertNotIn((2, 0), self.app.choice_ranges)
        self.app.go_choice(2, 0)
        self.assertIsNone(self.app.active_choice)
        self.assertEqual(self.app.current, 0)


if __name__ == "__main__":
    unittest.main()
