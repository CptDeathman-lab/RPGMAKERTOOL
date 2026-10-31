"""DragonTail Dialogue Manager 0.1 — run with Python 3.12+."""
import json
from pathlib import Path
import re
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dialogue_core import MapDocument, SafetyError, create_working_copy, decode, messages


class Application:
    def __init__(self, window):
        self.window = window
        window.title("DragonTail Dialogue Manager 0.1")
        window.geometry("1100x780")
        self.root = self.document = self.selection = None
        self.editors = []
        self.busy = False
        self.results = queue.Queue()
        bar = ttk.Frame(window, padding=8)
        bar.pack(fill="x")
        self.open_button = ttk.Button(bar, text="Open Project", command=self.open_project)
        self.open_button.pack(side="left")
        ttk.Button(bar, text="Select Event", command=self.select_event).pack(side="left", padx=6)
        ttk.Button(bar, text="Edit Dialogue", command=self.focus_editor).pack(side="left")
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=6)
        ttk.Button(bar, text="Revert Page", command=self.revert).pack(side="left")
        self.status = tk.StringVar(value="Open a source project to create a disposable working copy. Source is never edited.")
        ttk.Label(window, textvariable=self.status, wraplength=1050, padding=8).pack(fill="x")
        panes = ttk.Panedwindow(window, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(panes)
        panes.add(left, weight=1)
        ttk.Label(left, text="Maps → Events → Pages (double-click a page)").pack(anchor="w")
        self.tree = ttk.Treeview(left, selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewOpen>>", self.expand_map)
        self.tree.bind("<Double-1>", lambda event: self.select_event())
        right = ttk.Frame(panes)
        panes.add(right, weight=3)
        self.canvas = tk.Canvas(right, highlightthickness=0)
        scrollbar = ttk.Scrollbar(right, command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas)
        self.content_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.content_id, width=event.width))
        window.protocol("WM_DELETE_WINDOW", self.close)

    def dirty(self):
        return any(widget.get("1.0", "end-1c") != "\n".join(message.lines) for message, widget in self.editors)

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
        preferred = Path(r"E:\Project DragonTail\Dialogue Workspace")
        parent = filedialog.askdirectory(title="Select Dialogue Workspace; a NEW disposable copy will be created here",
                                         initialdir=str(preferred) if preferred.is_dir() else str(Path(source).parent))
        if not parent:
            return
        from datetime import datetime
        destination = Path(parent) / (Path(source).name + "-DialogueCopy-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        self.busy = True
        self.open_button.configure(state="disabled")
        self.status.set(f"Copying project to {destination} … Please wait.")
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
        self.clear_editor()
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
        if not self.root or ":" in node:
            return
        placeholder = node + ":placeholder"
        if not self.tree.exists(placeholder):
            return
        try:
            document = MapDocument(self.root, self.root / "data" / node)
            entries = []
            for index, item in enumerate(document.data["events"]):
                if not isinstance(item, dict):
                    continue
                pages = item.get("pages", [])
                entries.append((index, item, pages))
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

    def clear_editor(self):
        for child in self.content.winfo_children():
            child.destroy()
        self.editors = []

    def render(self, blocks):
        self.clear_editor()
        ttk.Label(self.content, text="Keep line count and escape codes unchanged. Each box is one existing message.", wraplength=650).pack(anchor="w", padx=8, pady=8)
        if not blocks:
            ttk.Label(self.content, text="This page has no supported Show Text dialogue.").pack()
        for number, block in enumerate(blocks, 1):
            frame = ttk.LabelFrame(self.content, text=f"Message {number} — command {block.header_index}", padding=8)
            frame.pack(fill="x", padx=8, pady=6)
            ttk.Label(frame, text="Face / index / background / position: " + json.dumps(block.settings, ensure_ascii=False), wraplength=650).pack(anchor="w")
            text = tk.Text(frame, height=max(3, len(block.lines) + 1), wrap="none", undo=True, font=("Consolas", 11))
            text.insert("1.0", "\n".join(block.lines))
            text.pack(fill="x", pady=6)
            horizontal = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
            horizontal.pack(fill="x")
            text.configure(xscrollcommand=horizontal.set)
            self.editors.append((block, text))
        self.canvas.yview_moveto(0)

    def focus_editor(self):
        if self.editors and not self.busy:
            self.editors[0][1].focus_set()

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
        try:
            # Start from disk so validation failure never leaves a partially staged document.
            document = MapDocument(self.root, self.document.path)
            if document.raw != self.document.raw:
                raise SafetyError("Map changed externally. Revert/reopen before editing again.")
            for block, widget in self.editors:
                document.edit(*self.selection, block.header_index, widget.get("1.0", "end-1c").split("\n"))
            backup = document.save()
            self.document = document
            self.render(messages(document.page(*self.selection)))
            self.status.set(f"Saved and verified. Original bytes backed up: {backup}" if backup else "No dialogue changes to save.")
            return True
        except Exception as error:
            messagebox.showerror("Save refused", str(error))
            return False

    def close(self):
        if self.can_leave():
            self.window.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    Application(window)
    window.mainloop()
