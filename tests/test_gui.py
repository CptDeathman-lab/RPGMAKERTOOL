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


if __name__ == "__main__":
    unittest.main()
