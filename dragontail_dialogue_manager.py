"""DragonTail Dialogue Manager 0.3 — Python 3.12+, standard library only."""
import json
from pathlib import Path
import re
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

from dialogue_core import MapDocument, SafetyError, create_working_copy, decode, messages, face_region
from choice_support import choice_groups
from text_width import check_width


COMMAND_NAMES = {
    102: "Choices", 103: "Number input", 104: "Item selection", 105: "Scrolling text",
    111: "Conditional branch", 112: "Loop", 113: "Break loop", 115: "Exit event",
    117: "Common event", 118: "Label", 119: "Jump to label", 121: "Switches",
    122: "Variables", 123: "Self switch", 201: "Transfer player", 205: "Move route",
    221: "Fade out screen", 222: "Fade in screen", 241: "Play BGM", 242: "Fade out BGM",
    243: "Save BGM", 244: "Replay BGM", 245: "Play BGS", 246: "Fade out BGS",
    249: "Play ME", 250: "Play SE", 230: "Wait", 355: "Script", 356: "Plugin command", 402: "Choice branch",
    403: "Cancel branch", 411: "Else", 412: "End branch", 413: "Repeat loop",
}


class Application:
    def __init__(self, window):
        self.window = window
        window.title("DragonTail Dialogue Manager 0.3")
        window.geometry("1200x850")
        window.minsize(900, 700)
        self.root = self.document = self.selection = None
        self.blocks, self.drafts = [], []
        self.current = -1
        self.active_choice = None
        self.groups, self.choice_drafts = [], {}
        self.collapsed_branches = set()
        self.collapse_tags, self.branch_ranges, self.choice_ranges = [], [], {}
        self.fonts = {}
        self.busy = False
        self.refresh_job = None
        self.results = queue.Queue()
        self.portrait_image = None
        self.scene_ranges = []
        bar = ttk.Frame(window, padding=8)
        bar.pack(fill="x")
        self.open_button = ttk.Button(bar, text="Open Project", command=self.open_project)
        self.open_button.pack(side="left")
        ttk.Button(bar, text="Select Event", command=self.select_event).pack(side="left", padx=6)
        ttk.Button(bar, text="Edit Dialogue", command=self.focus_editor).pack(side="left")
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=6)
        ttk.Button(bar, text="Revert Page", command=self.revert).pack(side="left")
        self.status = tk.StringVar(value="Open a source project to create a disposable working copy. Source is never edited.")
        ttk.Label(window, textvariable=self.status, wraplength=1100, padding=8).pack(fill="x")
        panes = ttk.Panedwindow(window, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(panes, width=280)
        panes.add(left, weight=1)
        ttk.Label(left, text="Maps → Events → Pages").pack(anchor="w")
        self.tree = ttk.Treeview(left, selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewOpen>>", self.expand_map)
        self.tree.bind("<Double-1>", lambda event: self.select_event())
        right = ttk.Frame(panes)
        panes.add(right, weight=3)
        self.page_title = tk.StringVar(value="Select an event page")
        ttk.Label(right, textvariable=self.page_title, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(right, text="Page overview — command order, including alternate branches. Click dialogue or an option to edit; click When headings to collapse.", wraplength=750).pack(anchor="w")
        search = ttk.Frame(right)
        search.pack(fill="x", pady=4)
        ttk.Label(search, text="Find text:").pack(side="left")
        self.query = ttk.Entry(search)
        self.query.pack(side="left", fill="x", expand=True, padx=6)
        self.query.bind("<Return>", lambda event: self.find_next())
        ttk.Button(search, text="Find Next", command=self.find_next).pack(side="left")
        width_bar = ttk.Frame(right)
        width_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(width_bar, text="Width estimate · screen px:").pack(side="left")
        self.screen_width = tk.IntVar(value=816)
        ttk.Spinbox(width_bar, from_=320, to=4096, width=6, textvariable=self.screen_width).pack(side="left", padx=4)
        ttk.Label(width_bar, text="font px:").pack(side="left")
        self.font_pixels = tk.IntVar(value=28)
        ttk.Spinbox(width_bar, from_=12, to=108, width=4, textvariable=self.font_pixels).pack(side="left", padx=4)
        ttk.Label(width_bar, text="Arial estimate; verify game font/plugins", foreground="#666666").pack(side="left")
        scene_frame = ttk.Frame(right)
        scene_frame.pack(fill="both", expand=True)
        self.scene = tk.Text(scene_frame, wrap="word", state="disabled", font=("Segoe UI", 10), height=16)
        scene_scroll = ttk.Scrollbar(scene_frame, command=self.scene.yview)
        scene_scroll.pack(side="right", fill="y")
        self.scene.pack(fill="both", expand=True)
        self.scene.configure(yscrollcommand=scene_scroll.set)
        self.scene.tag_configure("heading", foreground="#214b76", font=("Segoe UI", 10, "bold"))
        self.scene.tag_configure("context", foreground="#666666", spacing1=5, spacing3=5)
        self.scene.tag_configure("warning", foreground="#a00000")
        self.scene.tag_configure("current", background="#e1efff")
        self.scene.bind("<Button-1>", self.scene_click)
        navigation = ttk.Frame(right)
        navigation.pack(fill="x", pady=6)
        self.previous = ttk.Button(navigation, text="← Previous", command=lambda: self.navigate(-1))
        self.previous.pack(side="left")
        self.position = tk.StringVar(value="No message selected")
        ttk.Label(navigation, textvariable=self.position).pack(side="left", padx=12)
        self.next = ttk.Button(navigation, text="Next →", command=lambda: self.navigate(1))
        self.next.pack(side="left")
        ttk.Label(navigation, text="Ctrl+↑ / Ctrl+↓").pack(side="right")
        editor_frame = ttk.LabelFrame(right, text="Edit the selected message or choice label", padding=8)
        editor_frame.pack(fill="x")
        portrait_frame = ttk.Frame(editor_frame, width=160)
        portrait_frame.pack(side="left", anchor="n", padx=(0, 10))
        self.portrait = ttk.Label(portrait_frame, text="No portrait", width=20, anchor="center")
        self.portrait.pack()
        self.portrait_note = ttk.Label(portrait_frame, text="", wraplength=155)
        self.portrait_note.pack()
        edit_area = ttk.Frame(editor_frame)
        edit_area.pack(fill="both", expand=True)
        self.settings = tk.StringVar()
        ttk.Label(edit_area, textvariable=self.settings, wraplength=560).pack(anchor="w")
        self.editor = tk.Text(edit_area, height=5, wrap="none", undo=True, font=("Consolas", 11), state="disabled")
        self.editor.pack(fill="x", pady=6)
        horizontal = ttk.Scrollbar(edit_area, orient="horizontal", command=self.editor.xview)
        horizontal.pack(fill="x")
        self.editor.configure(xscrollcommand=horizontal.set)
        self.editor.bind("<<Modified>>", self.editor_changed)
        self.line_count = ttk.Label(edit_area, text="One to four lines per message; escape codes must stay intact and in order.", wraplength=560)
        self.line_count.pack(anchor="w", pady=4)
        self.width_warning = ttk.Label(edit_area, text="", wraplength=560)
        self.width_warning.pack(anchor="w")
        self.screen_width.trace_add("write", self.width_settings_changed)
        self.font_pixels.trace_add("write", self.width_settings_changed)
        window.bind("<Control-Up>", lambda event: self.navigate(-1))
        window.bind("<Control-Down>", lambda event: self.navigate(1))
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.update_navigation()

    def stash(self):
        if self.active_choice is not None:
            header, option = self.active_choice
            self.choice_drafts[header][option] = self.editor.get("1.0", "end-1c")
        elif 0 <= self.current < len(self.drafts):
            self.drafts[self.current] = self.editor.get("1.0", "end-1c")

    def dirty(self):
        self.stash()
        return (any(draft != "\n".join(block.lines) for block, draft in zip(self.blocks, self.drafts))
                or any(tuple(self.choice_drafts[group.header_index]) != group.labels for group in self.groups))

    def can_leave(self):
        if self.busy:
            return False
        if not self.dirty():
            return True
        answer = messagebox.askyesnocancel("Unsaved dialogue", "Save your edits before continuing?\nNo discards the current page edits.")
        if answer is None:
            return False
        return self.save() if answer else True

    def open_project(self):
        if not self.can_leave():
            return
        source = filedialog.askdirectory(title="Select SOURCE RPG Maker MV project (read only)")
        if not source:
            return
        preferred = Path(r"F:\Project DragonTail\Dialogue Workspace")
        parent = filedialog.askdirectory(title="Select Dialogue Workspace; a NEW disposable copy will be created here",
                                         initialdir=str(preferred) if preferred.is_dir() else str(Path(source).parent))
        if not parent:
            return
        from datetime import datetime
        destination = Path(parent) / (Path(source).name + "-DialogueCopy-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        self.busy = True
        self.open_button.configure(state="disabled")
        self.status.set(f"Checking space, then copying the FULL project to {destination} … Please wait.")
        def work():
            try:
                self.results.put((create_working_copy(Path(source), destination), None))
            except Exception as error:
                self.results.put((None, str(error)))
        threading.Thread(target=work, daemon=True).start()
        self.window.after(100, self.copy_finished)

    def copy_finished(self):
        try:
            root, error = self.results.get_nowait()
        except queue.Empty:
            self.window.after(100, self.copy_finished)
            return
        self.busy = False
        self.open_button.configure(state="normal")
        if error:
            self.status.set("Copy failed. Source was not changed. Any partial destination can be deleted.")
            messagebox.showerror("Cannot open project", error)
            return
        self.root, self.document, self.selection = root, None, None
        self.render([])
        self.tree.delete(*self.tree.get_children())
        names = {}
        try:
            infos = decode((root / "data" / "MapInfos.json").read_bytes())
            names = {item["id"]: item.get("name", "") for item in infos if isinstance(item, dict)}
        except (OSError, ValueError, TypeError, KeyError):
            pass
        for path in sorted((root / "data").glob("Map*.json")):
            if re.fullmatch(r"Map\d{3,}\.json", path.name):
                self.tree.insert("", "end", iid=path.name, text=f"{path.stem} — {names.get(int(path.stem[3:]), '')}")
                self.tree.insert(path.name, "end", iid=path.name + ":placeholder", text="Expand to read events")
        self.status.set(f"DISPOSABLE COPY: {root}")

    def expand_map(self, event=None):
        node = self.tree.focus()
        if self.busy or not self.root or ":" in node or not node:
            return
        placeholder = node + ":placeholder"
        if not self.tree.exists(placeholder):
            return
        try:
            document = MapDocument(self.root, self.root / "data" / node)
            entries = []
            for index, item in enumerate(document.data["events"]):
                if isinstance(item, dict):
                    entries.append((index, item, item.get("pages", [])))
            self.tree.delete(placeholder)
            for index, item, pages in entries:
                event_id = f"{node}:{index}"
                self.tree.insert(node, "end", iid=event_id, text=f"Event {item.get('id', index)}: {item.get('name', '')}")
                for page_index, page in enumerate(pages):
                    self.tree.insert(event_id, "end", iid=f"{event_id}:{page_index}", text=f"Page {page_index + 1}")
        except Exception as error:
            messagebox.showerror("Cannot read map", str(error))

    def select_event(self):
        selected = self.tree.selection()
        if not selected or len(selected[0].split(":")) != 3:
            return
        if not self.can_leave():
            return
        name, event, page = selected[0].split(":")
        try:
            document = MapDocument(self.root, self.root / "data" / name)
            blocks = messages(document.page(int(event), int(page)))
            self.document, self.selection = document, (int(event), int(page))
            self.render(blocks)
            self.status.set(f"COPY: {self.root} | {name}, event index {event}, page {int(page)+1}")
        except Exception as error:
            messagebox.showerror("Cannot edit page", str(error))

    def render(self, blocks):
        self.cancel_refresh()
        self.blocks = blocks
        self.drafts = ["\n".join(block.lines) for block in blocks]
        self.current = -1
        self.active_choice = None
        commands = self.document.page(*self.selection) if self.document and self.selection else []
        if self.document and self.selection:
            event, page = self.selection
            item = self.document.data["events"][event]
            event_id = str(item.get("id", event)).zfill(3)
            self.page_title.set(f"{self.document.path.stem} · Event {event_id} · Page {page+1} — {item.get('name', '')}")
        else:
            self.page_title.set("Select an event page")
        self.groups = choice_groups(commands)
        self.choice_drafts = {group.header_index: list(group.labels) for group in self.groups}
        self.collapsed_branches = set()
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.edit_modified(False)
        self.editor.configure(state="disabled")
        self.settings.set("")
        self.position.set("No message selected")
        self.portrait.configure(image="", text="No portrait")
        self.portrait_note.configure(text="")
        self.portrait_image = None
        self.line_count.configure(text="One to four lines per message; escape codes stay intact and in order.", foreground="")
        self.update_overview()
        if self.navigation_items():
            self.go_item(self.navigation_items()[0])
        else:
            self.width_warning.configure(text="")
            self.update_navigation()

    def update_overview(self):
        self.cancel_refresh()
        view = self.scene.yview()[0]
        self.scene.configure(state="normal")
        self.scene.delete("1.0", "end")
        for tag in self.collapse_tags:
            self.scene.tag_delete(tag)
        self.collapse_tags, self.branch_ranges, self.choice_ranges = [], [], {}
        self.scene_ranges = [None] * len(self.blocks)
        if not self.blocks and not self.groups:
            self.scene.insert("end", "This page has no supported Show Text dialogue or choices.\n", "context")
        commands = self.document.page(*self.selection) if self.document and self.selection else []
        by_message = {block.header_index: (number, block) for number, block in enumerate(self.blocks)}
        by_choice = {group.header_index: group for group in self.groups}

        def span(start, stop, level=0):
            margin = f"level_{level}"
            self.scene.tag_configure(margin, lmargin1=level * 16, lmargin2=level * 16)
            span_start = self.scene.index("end-1c")
            position = start
            while position < stop:
                if position in by_message:
                    number, block = by_message[position]
                    first = self.scene.index("end-1c")
                    face = str(block.settings[0]) if block.settings and block.settings[0] else "No face"
                    self.scene.insert("end", f"Dialogue {number + 1} · {face} · command {position}\n", "heading")
                    self.scene.insert("end", self.drafts[number] + "\n\n")
                    self.scene_ranges[number] = (first, self.scene.index("end-1c"))
                    position = block.line_indices[-1] + 1
                    continue
                group = by_choice.get(position)
                if group:
                    self.scene.insert("end", f"Show Choices · command {position}\n", "heading")
                    settings = "Settings (read-only): " + json.dumps(group.settings)
                    if not group.problem:
                        cancel, default, alignment, background = group.settings[:4]
                        cancel_text = "Disabled" if cancel == -1 else "When Cancel branch" if cancel == -2 else f"Option {cancel+1}"
                        default_text = "None" if default == -1 else f"Option {default+1}"
                        settings = (f"Read-only settings · Cancel: {cancel_text} · Default: {default_text} · "
                                    f"Position: {('Left', 'Center', 'Right')[alignment]} · "
                                    f"Background: {('Window', 'Dim', 'Transparent')[background]}")
                    self.scene.insert("end", settings + "\n", "context")
                    if group.problem:
                        self.scene.insert("end", "READ-ONLY: " + group.problem + "\n", "context")
                    for option, label in enumerate(self.choice_drafts[position]):
                        first = self.scene.index("end-1c")
                        report, warning = self.width_text(label, choice=True)
                        self.scene.insert("end", f"  {option+1}. {label}\n")
                        if warning:
                            self.scene.insert("end", "     " + warning + "\n", "warning" if report and report.overflow else "context")
                        if not group.problem:
                            self.choice_ranges[position, option] = (first, self.scene.index("end-1c"))
                    if not group.problem and group.end_index < stop:
                        for branch in group.branches:
                            key = position, branch.header_index
                            first = self.scene.index("end-1c")
                            label = ("Cancel (cancel action)" if branch.option_index is None else
                                     f"{self.choice_drafts[position][branch.option_index]} (option {branch.option_index+1})")
                            symbol = "+" if key in self.collapsed_branches else "−"
                            self.scene.insert("end", f"[{symbol}] When {label} · commands {branch.start}–{branch.end-1}\n", "heading")
                            self.branch_ranges.append((first, self.scene.index("end-1c"), key))
                            body_start = self.scene.index("end-1c")
                            span(branch.start, branch.end, level + 1)
                            if self.scene.index("end-1c") == body_start:
                                self.scene.insert("end", "  (Empty branch — no additional commands.)\n", "context")
                            body_end = self.scene.index("end-1c")
                            if key in self.collapsed_branches:
                                tag = f"collapse_{position}_{branch.header_index}"
                                self.scene.tag_configure(tag, elide=True)
                                self.scene.tag_add(tag, body_start, body_end)
                                self.collapse_tags.append(tag)
                        self.scene.insert("end", f"End Choices · command {group.end_index}\n\n", "context")
                        position = group.end_index + 1
                        continue
                    position += 1
                    continue
                item = commands[position]
                if isinstance(item, dict) and item.get("code") != 0:
                    code = item.get("code")
                    name = COMMAND_NAMES.get(code, f"Code {code}")
                    params = json.dumps(item.get("parameters", []), ensure_ascii=False)
                    if len(params) > 180:
                        params = params[:177] + "…"
                    depth = item.get("indent", 0)
                    self.scene.insert("end", f"  {name} ({code}) · command {position} · depth {depth}: {params}\n", "context")
                position += 1
            self.scene.tag_add(margin, span_start, self.scene.index("end-1c"))
        span(0, len(commands))
        self.scene.configure(state="disabled")
        self.highlight_current()
        self.scene.yview_moveto(view)

    def highlight_current(self):
        self.scene.tag_remove("current", "1.0", "end")
        selected = self.choice_ranges.get(self.active_choice) if self.active_choice else (
            self.scene_ranges[self.current] if 0 <= self.current < len(self.scene_ranges) else None)
        if selected:
            self.scene.tag_add("current", *selected)

    def scene_click(self, event):
        if self.busy:
            return
        self.stash()
        position = self.scene.index(f"@{event.x},{event.y}")
        def contains(bounds):
            return self.scene.compare(position, ">=", bounds[0]) and self.scene.compare(position, "<", bounds[1])
        for start, end, key in self.branch_ranges:
            if contains((start, end)):
                if key in self.collapsed_branches:
                    self.collapsed_branches.remove(key)
                else:
                    self.collapsed_branches.add(key)
                self.update_overview()
                return
        for key, bounds in self.choice_ranges.items():
            if contains(bounds):
                self.go_choice(*key)
                return
        for index, bounds in enumerate(self.scene_ranges):
            if bounds and contains(bounds):
                self.go_message(index)
                return

    def navigation_items(self):
        items = [(block.header_index, 0, ("message", index)) for index, block in enumerate(self.blocks)]
        items += [(group.header_index, option+1, ("choice", group.header_index, option))
                  for group in self.groups if not group.problem for option in range(len(group.labels))]
        return [item[2] for item in sorted(items)]

    def active_item(self):
        return ("choice", *self.active_choice) if self.active_choice is not None else ("message", self.current)

    def update_navigation(self):
        items = self.navigation_items()
        current = items.index(self.active_item()) if self.active_item() in items else -1
        self.previous.configure(state="normal" if current > 0 else "disabled")
        self.next.configure(state="normal" if 0 <= current < len(items) - 1 else "disabled")

    def go_item(self, item):
        if item[0] == "message":
            self.go_message(item[1])
        else:
            self.go_choice(*item[1:])

    def reveal_command(self, command_index):
        for group in self.groups:
            for branch in group.branches:
                if branch.start <= command_index < branch.end:
                    self.collapsed_branches.discard((group.header_index, branch.header_index))

    def go_choice(self, header, option):
        group = next((g for g in self.groups if g.header_index == header), None)
        if self.busy or group is None or group.problem or not 0 <= option < len(group.labels):
            return
        self.stash()
        self.active_choice = header, option
        self.current = -1
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.choice_drafts[header][option])
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.position.set(f"Choice {option+1} / {len(group.labels)} · Show Choices command {header}")
        self.settings.set("Single-line label; its existing When branch is synchronized on save. Branch index: " + str(option))
        self.portrait.configure(image="", text="Choice label")
        self.portrait_note.configure(text="Gameplay settings are read-only.")
        self.portrait_image = None
        self.reveal_command(header)
        self.update_line_count()
        self.update_navigation()
        self.update_overview()
        self.scene.see(self.choice_ranges[header, option][0])

    def go_message(self, index):
        if self.busy or not 0 <= index < len(self.blocks):
            return
        self.stash()
        self.active_choice = None
        self.current = index
        block = self.blocks[index]
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", self.drafts[index])
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.position.set(f"Message {index + 1} / {len(self.blocks)}")
        self.settings.set("Face / index / background / position: " + json.dumps(block.settings, ensure_ascii=False))
        if len(block.lines) > 4:
            self.editor.configure(state="disabled")
        self.update_line_count()
        self.show_portrait(block.settings)
        self.update_navigation()
        self.reveal_command(block.header_index)
        self.update_overview()
        self.scene.see(self.scene_ranges[index][0])

    def navigate(self, direction):
        items = self.navigation_items()
        if self.active_item() in items:
            position = items.index(self.active_item()) + direction
            if 0 <= position < len(items):
                self.go_item(items[position])
        return "break"

    def editor_changed(self, event=None):
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.stash()
        self.update_line_count()
        if self.refresh_job:
            self.window.after_cancel(self.refresh_job)
        self.refresh_job = self.window.after(200, self.update_overview)

    def cancel_refresh(self):
        if self.refresh_job:
            self.window.after_cancel(self.refresh_job)
            self.refresh_job = None

    def width_text(self, text, *, choice=False, portrait=False):
        try:
            screen, size = self.screen_width.get(), self.font_pixels.get()
            if not 320 <= screen <= 4096 or not 12 <= size <= 108:
                raise ValueError()
            def measure(plain, pixels):
                if pixels not in self.fonts:
                    self.fonts[pixels] = tkfont.Font(root=self.window, family="Arial", size=-pixels)
                return self.fonts[pixels].measure(plain)
            report = check_width(text, measure, screen_width=screen, font_px=size, portrait=portrait, choice=choice)
            kind = "Choice window" if choice else "Message"
            warning = f"{kind} overflow estimate: {report.pixels}px > {report.budget}px." if report.overflow else ""
            if report.uncertain:
                warning += " Dynamic/unknown escape codes: final width requires playtesting."
            return report, warning.strip()
        except (ValueError, tk.TclError):
            return None, "Enter a screen width of 320–4096 and a font size of 12–108."

    def width_settings_changed(self, *args):
        self.update_line_count()
        if self.refresh_job:
            self.window.after_cancel(self.refresh_job)
        self.refresh_job = self.window.after(200, self.update_overview)

    def update_line_count(self):
        text = self.editor.get("1.0", "end-1c")
        count = len(text.split("\n"))
        is_choice = self.active_choice is not None
        readonly = self.current >= 0 and len(self.blocks[self.current].lines) > 4
        if is_choice:
            description = "Choice labels must stay on one line; option order and branch indices are locked."
        else:
            description = "Read-only: original message exceeds four lines." if readonly else f"{count} / 4 lines — keep escape codes intact and in order within this message."
        invalid = count > (1 if is_choice else 4)
        self.line_count.configure(text=description, foreground="#a00000" if readonly or invalid else "")
        portrait = (not is_choice and self.current >= 0 and bool(self.blocks[self.current].settings)
                    and bool(self.blocks[self.current].settings[0]))
        report, warning = self.width_text(text, choice=is_choice, portrait=portrait)
        if not warning and report:
            warning = f"Estimated width: {report.pixels} / {report.budget}px. Verify the actual game font and plugins."
        self.width_warning.configure(text=warning, foreground="#a00000" if report and report.overflow else "#666666")

    def show_portrait(self, settings):
        self.portrait.configure(image="", text="No portrait")
        self.portrait_note.configure(text="")
        self.portrait_image = None
        if not settings or not settings[0]:
            return
        try:
            name = settings[0]
            if not isinstance(name, str) or any(c in name for c in ('/', '\\', ':')) or name in (".", ".."):
                raise SafetyError("Unsupported portrait filename.")
            directory = (self.root / "img" / "faces").resolve()
            path = (directory / (name + ".png")).resolve()
            if not directory.is_relative_to(self.root) or path.parent != directory:
                raise SafetyError("Portrait must be inside the working copy.")
            if not path.is_file():
                raise SafetyError("PNG missing or encrypted. Dialogue remains editable.")
            region = face_region(settings[1])
            sheet = tk.PhotoImage(master=self.window, file=str(path))
            if sheet.width() < 576 or sheet.height() < 288:
                raise SafetyError("Unsupported face sheet size; expected at least 576×288.")
            portrait = tk.PhotoImage(master=self.window, width=144, height=144)
            portrait.tk.call(str(portrait), "copy", str(sheet), "-from", *region)
            self.portrait_image = portrait
            self.portrait.configure(image=portrait, text="")
            self.portrait_note.configure(text=f"{name} · face {settings[1]}")
        except (OSError, ValueError, IndexError, TypeError, tk.TclError) as error:
            self.portrait.configure(image="", text="Preview unavailable")
            self.portrait_note.configure(text=str(error))

    def find_next(self):
        items = self.navigation_items()
        if self.busy or not items:
            return
        self.stash()
        query = self.query.get().casefold()
        if not query:
            self.query.focus_set()
            return
        start = items.index(self.active_item()) if self.active_item() in items else -1
        for step in range(1, len(items) + 1):
            item = items[(start + step) % len(items)]
            text = self.drafts[item[1]] if item[0] == "message" else self.choice_drafts[item[1]][item[2]]
            if query in text.casefold():
                self.go_item(item)
                return
        messagebox.showinfo("Find text", "No matching dialogue or choice on this page.")

    def focus_editor(self):
        if self.navigation_items() and not self.busy:
            self.editor.focus_set()

    def revert(self):
        if self.busy or not self.document:
            return
        if self.dirty() and not messagebox.askyesno("Revert page", "Discard unsaved changes on this page?"):
            return
        try:
            document = MapDocument(self.root, self.document.path)
            blocks = messages(document.page(*self.selection))
            self.document = document
            self.render(blocks)
        except Exception as error:
            messagebox.showerror("Cannot revert page", str(error))

    def save(self):
        if self.busy or not self.document:
            return False
        self.stash()
        try:
            document = MapDocument(self.root, self.document.path)
            if document.raw != self.document.raw:
                raise SafetyError("Map changed externally. Revert/reopen before editing again.")
            for block, draft in zip(self.blocks, self.drafts):
                if draft != "\n".join(block.lines):
                    document.edit(*self.selection, block.header_index, draft.split("\n"))
            for group in self.groups:
                for option, label in enumerate(self.choice_drafts[group.header_index]):
                    if label != group.labels[option]:
                        document.edit_choice(*self.selection, group.header_index, option, label)
            backup = document.save()
            selected = self.active_item()
            choice_ordinal = next((i for i, g in enumerate(self.groups) if selected[0] == "choice" and g.header_index == selected[1]), None)
            self.document = document
            self.render(messages(document.page(*self.selection)))
            # Message/choice command positions may shift when dialogue resizes.
            if selected[0] == "message":
                self.go_message(selected[1])
            else:
                if choice_ordinal is not None:
                    self.go_choice(self.groups[choice_ordinal].header_index, selected[2])
            self.status.set(f"Saved and verified. Original bytes backed up: {backup}" if backup else "No dialogue or choice changes to save.")
            return True
        except Exception as error:
            messagebox.showerror("Save refused", str(error))
            return False

    def close(self):
        if self.can_leave():
            self.cancel_refresh()
            self.window.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    Application(window)
    window.mainloop()
