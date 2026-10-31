"""Representative MV choices, including nested branches; not DragonTail game data."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from choice_support import choice_groups, choice_topology
from dialogue_core import MapDocument, SafetyError, decode, messages
from text_width import check_width


def command(code, parameters, indent=0):
    return dict(code=code, parameters=parameters, indent=indent)


def bedtime_commands():
    c = command
    return [
        c(101, ["", 0, 0, 2]), c(401, ["Do you want to go to bed?"]),
        c(102, [["Yes", "No"], -2, 0, 2, 0]),
        c(402, [0, "Yes"]), c(242, [2], 1), c(221, [], 1),
        c(101, ["Actor1", 2, 0, 2], 1), c(401, ["Time to rest."], 1),
        c(102, [["Sleep now", "Wait"], -1, 1, 2, 0], 1),
        c(402, [0, "Sleep now"], 1), c(122, [10, 10, 0, 0, 3], 2), c(0, [], 2),
        c(402, [1, "Wait"], 1), c(101, ["", 0, 0, 2], 2), c(401, ["Wait here."], 2), c(0, [], 2),
        c(404, [], 1), c(222, [], 1), c(0, [], 1),
        c(402, [1, "No"]), c(101, ["", 0, 0, 2], 1), c(401, ["Stay awake."], 1), c(0, [], 1),
        c(403, []), c(356, ["StoryProgress cancelBed"], 1), c(0, [], 1), c(404, []),
        c(102, [["Continue", "Leave"], 1, -1, 0, 1]),
        c(402, [0, "Continue"]), c(0, [], 1), c(402, [1, "Leave"]), c(0, [], 1), c(404, []), c(0, []),
    ]


class ChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        self.path = self.root / "data" / "Map002.json"
        self.commands = bedtime_commands()
        self.data = {"events": [None, None, None, None, {"id": 4, "name": "Bedtime", "pages": [
            {"conditions": {"switch1Id": 9}, "list": self.commands}, {"list": [command(0, [])]}]}]}
        self.raw = json.dumps(self.data, indent=2).encode()
        self.path.write_bytes(self.raw)
        self.doc = MapDocument(self.root, self.path)

    def test_detect_outer_nested_sequential_and_cancel_branch_spans(self):
        groups = choice_groups(self.commands)
        self.assertEqual([g.header_index for g in groups], [2, 8, 27])
        self.assertTrue(all(not g.problem for g in groups))
        self.assertEqual([(b.option_index, b.start, b.end) for b in groups[0].branches],
                         [(0, 4, 19), (1, 20, 23), (None, 24, 26)])
        self.assertEqual([b.header_index for b in groups[1].branches], [9, 12])
        self.assertEqual(groups[2].settings, (1, -1, 0, 1))

    def test_edit_exact_paired_labels_backup_and_all_logic_unchanged(self):
        self.doc.edit_choice(4, 0, 2, 0, "Yes, please")
        self.doc.edit_choice(4, 0, 2, 1, "Not yet")
        self.doc.edit_choice(4, 0, 8, 1, "Wait a while")
        expected = copy.deepcopy(self.data)
        commands = expected["events"][4]["pages"][0]["list"]
        commands[2]["parameters"][0] = ["Yes, please", "Not yet"]
        commands[3]["parameters"][1] = "Yes, please"
        commands[19]["parameters"][1] = "Not yet"
        commands[8]["parameters"][0][1] = "Wait a while"
        commands[12]["parameters"][1] = "Wait a while"
        backup = self.doc.save()
        self.assertEqual(backup.read_bytes(), self.raw)
        self.assertEqual(decode(self.path.read_bytes()), expected)
        self.assertEqual(choice_topology(commands), choice_topology(self.commands))
        self.assertIsNone(self.doc.save())

    def test_label_and_dialogue_resize_can_be_staged_in_either_order(self):
        for order in ["text-first", "choice-first"]:
            with self.subTest(order=order):
                doc = MapDocument(self.root, self.path)
                if order == "choice-first":
                    doc.edit_choice(4, 0, 2, 0, "Sleep")
                doc.edit(4, 0, 0, ["Question line one", "Do you want to go to bed?"])
                doc.edit(4, 0, 6, ["First", "Second", "Third", "Fourth"])
                doc.edit(4, 0, 13, ["Still waiting", "Here"])
                if order == "text-first":
                    doc.edit_choice(4, 0, 2, 0, "Sleep")
                doc.edit_choice(4, 0, 8, 0, "Sleep immediately")
                doc.validate(doc.data)
                edited = doc.page(4, 0)
                groups = choice_groups(edited)
                self.assertEqual(groups[0].labels, ("Sleep", "No"))
                self.assertEqual(groups[1].labels, ("Sleep immediately", "Wait"))
                self.assertEqual(choice_topology(edited), choice_topology(self.commands))
                self.assertEqual([len(m.lines) for m in messages(edited)], [2, 4, 2, 1])

    def test_no_adding_removing_reordering_settings_or_gameplay_changes(self):
        mutations = [
            lambda cs: cs[2]["parameters"][0].append("Extra"),
            lambda cs: cs[2]["parameters"][0].pop(),
            lambda cs: cs[2]["parameters"][0].reverse(),
            lambda cs: cs[3]["parameters"].__setitem__(0, 1),
            lambda cs: cs[19]["parameters"].__setitem__(0, 0),
            lambda cs: cs[2]["parameters"].__setitem__(1, -1),
            lambda cs: cs[2]["parameters"].__setitem__(2, 1),
            lambda cs: cs[2]["parameters"].__setitem__(3, 0),
            lambda cs: cs[2]["parameters"].__setitem__(4, 2),
            lambda cs: cs[10]["parameters"].__setitem__(4, 99),
            lambda cs: cs[24]["parameters"].__setitem__(0, "StoryProgress advance"),
            lambda cs: cs[19].__setitem__("indent", 1),
            lambda cs: cs.__setitem__(slice(4, 6), list(reversed(cs[4:6]))),
            lambda cs: cs[3]["parameters"].__setitem__(1, "Desynchronized"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                doc = MapDocument(self.root, self.path)
                doc.edit_choice(4, 0, 2, 0, "Absolutely")
                mutate(doc.page(4, 0))
                with self.assertRaises(SafetyError):
                    doc.save()
                self.assertEqual(self.path.read_bytes(), self.raw)

    def test_malformed_or_ambiguous_choices_are_readonly(self):
        mutations = [
            lambda cs: cs[3]["parameters"].__setitem__(0, 1),
            lambda cs: cs[3]["parameters"].__setitem__(0, True),
            lambda cs: cs[3]["parameters"].__setitem__(1, "Wrong label"),
            lambda cs: cs[26].__setitem__("code", 0),
            lambda cs: cs[19].__setitem__("code", 0),
            lambda cs: cs[23].__setitem__("code", 0),
            lambda cs: cs[2]["parameters"].__setitem__(1, -1),
            lambda cs: cs[2].__setitem__("parameters", []),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                data = copy.deepcopy(self.data)
                mutate(data["events"][4]["pages"][0]["list"])
                self.path.write_text(json.dumps(data))
                doc = MapDocument(self.root, self.path)
                self.assertTrue(choice_groups(doc.page(4, 0))[0].problem)
                with self.assertRaises(SafetyError):
                    doc.edit_choice(4, 0, 2, 0, "Changed")
                self.assertIsNone(doc.save())
                # Other text can still be proofread/edited without repairing choices.
                doc.edit(4, 0, 0, ["Rephrased question?"])
                doc.save()

    def test_duplicate_labels_use_indices_not_label_matching(self):
        data = copy.deepcopy(self.data)
        cs = data["events"][4]["pages"][0]["list"]
        cs[2]["parameters"][0] = ["Same", "Same"]
        cs[3]["parameters"][1] = cs[19]["parameters"][1] = "Same"
        self.path.write_text(json.dumps(data))
        doc = MapDocument(self.root, self.path)
        doc.edit_choice(4, 0, 2, 1, "Only second")
        self.assertEqual(doc.page(4, 0)[3]["parameters"][1], "Same")
        self.assertEqual(doc.page(4, 0)[19]["parameters"][1], "Only second")
        doc.save()

    def test_label_single_line_escape_codes_and_invalid_option(self):
        for option, label in [(-1, "No"), (2, "Extra"), (True, "No"), (0, "Yes\nplease"), (0, "Yes\rplease"), (0, r"\V[1]")]:
            with self.subTest(option=option, label=label), self.assertRaises(SafetyError):
                self.doc.edit_choice(4, 0, 2, option, label)
        self.doc.edit_choice(4, 0, 2, 0, "Changed")
        self.doc.edit_choice(4, 0, 2, 0, "Yes")
        self.assertIsNone(self.doc.save())
        self.assertFalse((self.root / "dialogue_backups").exists())

    def test_choices_with_escape_codes_preserve_codes(self):
        data = copy.deepcopy(self.data)
        cs = data["events"][4]["pages"][0]["list"]
        cs[2]["parameters"][0][0] = cs[3]["parameters"][1] = r"\I[1]Yes"
        self.path.write_text(json.dumps(data))
        doc = MapDocument(self.root, self.path)
        with self.assertRaises(SafetyError):
            doc.edit_choice(4, 0, 2, 0, r"\I[2]Yes")
        doc.edit_choice(4, 0, 2, 0, r"\I[1]Sure")
        doc.save()
        self.assertEqual(doc.page(4, 0)[3]["parameters"][1], r"\I[1]Sure")

    def test_actual_event_verifier_operates_only_on_temporary_map_copy(self):
        from verify_choices import verify_event
        result = verify_event(self.path, event_id=4, page_number=1)
        self.assertEqual(result["tested_labels"], 6)
        self.assertEqual(result["tested_dialogue_messages"], 4)
        self.assertEqual(result["labels"][0], ("Yes", "No"))
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertFalse((self.root / "dialogue_backups").exists())
        with self.assertRaises(SafetyError):
            verify_event(self.path, event_id=999)


class WidthTests(unittest.TestCase):
    @staticmethod
    def measure(text, size):
        return len(text) * size  # Predictable fake font isolates width rules.

    def test_choice_window_auto_size_cap_differs_from_message_portrait(self):
        text = "x" * 25
        choice = check_width(text, self.measure, choice=True)
        message = check_width(text, self.measure, portrait=True)
        self.assertEqual(choice.budget, 768)
        self.assertFalse(choice.overflow)
        self.assertEqual(message.budget, 612)
        self.assertTrue(message.overflow)
        self.assertTrue(check_width("x" * 30, self.measure, choice=True).overflow)
        self.assertEqual(check_width("x", self.measure, choice=True, screen_width=1280).budget, 1232)

    def test_escape_colors_waits_icons_font_sizes_and_unknown_values(self):
        self.assertEqual(check_width(r"\C[2]abc\C[0]\!", self.measure).pixels, 84)
        self.assertEqual(check_width(r"\I[1]x", self.measure).pixels, 64)
        self.assertEqual(check_width(r"\{x\}x", self.measure).pixels, 68)
        self.assertEqual(check_width("\\{x\nx", self.measure).pixels, 40)
        for text in [r"\V[1]", r"\N[1]", r"\G", r"\Plugin[99]"]:
            self.assertTrue(check_width(text, self.measure).uncertain)
        self.assertFalse(check_width("Ordinary choice", self.measure, choice=True).uncertain)


if __name__ == "__main__":
    unittest.main()
