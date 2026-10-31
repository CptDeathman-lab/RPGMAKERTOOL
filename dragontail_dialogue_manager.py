"""DragonTail Dialogue Manager 0.2 — Python 3.12+, standard library only."""
import json
from pathlib import Path
import re
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dialogue_core import MapDocument, SafetyError, create_working_copy, decode, messages, face_region


COMMAND_NAMES = {
    102: "Choices", 103: "Number input", 104: "Item selection", 105: "Scrolling text",
    111: "Conditional branch", 112: "Loop", 113: "Break loop", 115: "Exit event",
    117: "Common event", 118: "Label", 119: "Jump to label", 121: "Switches",
    122: "Variables", 123: "Self switch", 201: "Transfer player", 205: "Move route",
    230: "Wait", 355: "Script", 356: "Plugin command", 402: "Choice branch",
    403: "Cancel branch", 411: "Else", 412: "End branch", 413: "Repeat loop",
}


class Application:
    def __init__(self, window):
        self.window = window
        window.title("DragonTail Dialogue Manager 0.2")
        window.geometry("1200x850")
        window.minsize(900, 700)
        self.root = self.document = self.selection = None
        self.blocks, self.drafts = [], []
        self.current = -1
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
        ttk.Label(right, text="Page overview — command order, including alternate branches. Click dialogue to edit.", wraplength=750).pack(anchor="w")
        search = ttk.Frame(right)
        search.pack(fill="x", pady=4)
        ttk.Label(search, text="Find dialogue:").pack(side="left")
        self.query = ttk.Entry(search)
        self.query.pack(side="left", fill="x", expand=True, padx=6)
        self.query.bind("<Return>", lambda event: self.find_next())
        ttk.Button(search, text="Find Next", command=self.find_next).pack(side="left")
        scene_frame = ttk.Frame(right)
        scene_frame.pack(fill="both", expand=True)
        self.scene = tk.Text(scene_frame, wrap="word", state="disabled", font=("Segoe UI", 10), height=16)
        scene_scroll = ttk.Scrollbar(scene_frame, command=self.scene.yview)
        scene_scroll.pack(side="right", fill="y")
        self.scene.pack(fill="both", expand=True)
        self.scene.configure(yscrollcommand=scene_scroll.set)
        self.scene.tag_configure("heading", foreground="#214b76", font=("Segoe UI", 10, "bold"))
        self.scene.tag_configure("context", foreground="#666666", spacing1=5, spacing3=5)
        self.scene.tag_configure("current", background="#e1efff")
        self.scene.bind("<Button-1>", self.scene_click)
        navigation = ttk.Frame(right)
        navigation.pack(fill="x", pady=6)
        self.previous = ttk.Button(navigation, text="← Previous", command=lambda: self.go_message(self.current - 1))
        self.previous.pack(side="left")
        self.position = tk.StringVar(value="No message selected")
        ttk.Label(navigation, textvariable=self.position).pack(side="left", padx=12)
        self.next = ttk.Button(navigation, text="Next →", command=lambda: self.go_message(self.current + 1))
        self.next.pack(side="left")
        ttk.Label(navigation, text="Ctrl+↑ / Ctrl+↓").pack(side="right")
        editor_frame = ttk.LabelFrame(right, text="Edit the selected message", padding=8)
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
        window.bind("<Control-Up>", lambda event: self.navigate(-1))
        window.bind("<Control-Down>", lambda event: self.navigate(1))
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.update_navigation()

    def stash(self):
        if 0 <= self.current < len(self.drafts):
            self.drafts[self.current] = self.editor.get("1.0", "end-1c")

    def dirty(self):
        self.stash()
        return any(draft != "\n".join(block.lines) for block, draft in zip(self.blocks, self.drafts))

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
        if blocks:
            self.go_message(0)
        else:
            self.update_navigation()

    def update_overview(self):
        self.cancel_refresh()
        view = self.scene.yview()[0]
        self.scene.configure(state="normal")
        self.scene.delete("1.0", "end")
        self.scene_ranges = []
        if not self.blocks:
            self.scene.insert("end", "This page has no supported Show Text dialogue.\n", "context")
        cursor = 0
        commands = self.document.page(*self.selection) if self.document and self.selection else []
        def show_gap(start, end):
            labels = list(dict.fromkeys(COMMAND_NAMES.get(c.get("code"), f"Code {c.get('code')}")
                                        for c in commands[start:end] if isinstance(c, dict) and c.get("code") != 0))
            if labels:
                self.scene.insert("end", f"[Commands {start}–{end-1}: {', '.join(labels)}]\n", "context")
        for number, (block, draft) in enumerate(zip(self.blocks, self.drafts)):
            show_gap(cursor, block.header_index)
            start = self.scene.index("end-1c")
            indent = commands[block.header_index].get("indent", 0)
            face = str(block.settings[0]) if block.settings and block.settings[0] else "No face"
            self.scene.insert("end", f"{number + 1}. {face} · command {block.header_index} · branch depth {indent}\n", "heading")
            self.scene.insert("end", draft + "\n\n")
            end = self.scene.index("end-1c")
            self.scene_ranges.append((start, end))
            cursor = block.line_indices[-1] + 1
        if self.blocks:
            show_gap(cursor, len(commands))
            self.scene.insert("end", "[End of page dialogue. Other commands and page conditions remain unchanged.]\n", "context")
        self.scene.configure(state="disabled")
        self.highlight_current()
        self.scene.yview_moveto(view)

    def highlight_current(self):
        self.scene.tag_remove("current", "1.0", "end")
        if 0 <= self.current < len(self.scene_ranges):
            self.scene.tag_add("current", *self.scene_ranges[self.current])

    def scene_click(self, event):
        position = self.scene.index(f"@{event.x},{event.y}")
        for index, (start, end) in enumerate(self.scene_ranges):
            if self.scene.compare(position, ">=", start) and self.scene.compare(position, "<", end):
                self.go_message(index)
                break

    def update_navigation(self):
        self.previous.configure(state="normal" if self.current > 0 else "disabled")
        self.next.configure(state="normal" if 0 <= self.current < len(self.blocks) - 1 else "disabled")

    def go_message(self, index):
        if self.busy or not 0 <= index < len(self.blocks):
            return
        self.stash()
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
        self.update_overview()
        self.scene.see(self.scene_ranges[index][0])

    def navigate(self, direction):
        self.go_message(self.current + direction)
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

    def update_line_count(self):
        count = len(self.editor.get("1.0", "end-1c").split("\n"))
        readonly = self.current >= 0 and len(self.blocks[self.current].lines) > 4
        text = "Read-only: original message exceeds four lines." if readonly else f"{count} / 4 lines — keep escape codes intact and in order within this message."
        self.line_count.configure(text=text, foreground="#a00000" if readonly or count > 4 else "")

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
        if self.busy or not self.blocks:
            return
        self.stash()
        query = self.query.get().casefold()
        if not query:
            self.query.focus_set()
            return
        for step in range(1, len(self.blocks) + 1):
            index = (self.current + step) % len(self.blocks)
            if query in self.drafts[index].casefold():
                self.go_message(index)
                return
        messagebox.showinfo("Find dialogue", "No matching dialogue on this page.")

    def focus_editor(self):
        if self.blocks and not self.busy:
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
            backup = document.save()
            selected = self.current
            self.document = document
            self.render(messages(document.page(*self.selection)))
            self.go_message(selected)
            self.status.set(f"Saved and verified. Original bytes backed up: {backup}" if backup else "No dialogue changes to save.")
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
