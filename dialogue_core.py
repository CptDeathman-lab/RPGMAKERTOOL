"""Conservative RPG Maker MV dialogue editing; no GUI dependencies."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from choice_support import choice_groups, choice_topology


class SafetyError(ValueError):
    pass


def decode(raw: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SafetyError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise SafetyError(f"Invalid JSON number: {value}")
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                      parse_constant=invalid)


def escape_codes(text: str) -> list[str]:
    # Preserve all backslash sequences, including plugin-style named codes.
    return re.findall(r"\\(?:[A-Za-z]+(?:\[[^\]\r\n]*\])?|.|$)", text)


@dataclass(frozen=True)
class Message:
    header_index: int
    line_indices: tuple[int, ...]
    settings: tuple
    lines: tuple[str, ...]


def messages(commands: list) -> list[Message]:
    result = []
    i = 0
    while i < len(commands):
        command = commands[i]
        if not isinstance(command, dict) or command.get("code") != 101:
            i += 1
            continue
        header = i
        indices, lines = [], []
        i += 1
        while i < len(commands) and isinstance(commands[i], dict) and commands[i].get("code") == 401:
            params = commands[i].get("parameters")
            if (not isinstance(params, list) or len(params) != 1
                    or not isinstance(params[0], str)
                    or "\n" in params[0] or "\r" in params[0]):
                raise SafetyError("Unsupported Show Text line structure; editing refused.")
            if commands[i].get("indent") != command.get("indent"):
                raise SafetyError("Inconsistent Show Text indentation; editing refused.")
            indices.append(i)
            lines.append(params[0])
            i += 1
        if indices:
            result.append(Message(header, tuple(indices), tuple(command.get("parameters", [])), tuple(lines)))
    return result


def create_working_copy(source: Path, destination: Path) -> Path:
    source, destination = source.resolve(), destination.resolve()
    if not (source / "Game.rpgproject").is_file() or not (source / "data").is_dir():
        raise SafetyError("Select an RPG Maker MV project containing Game.rpgproject and data/.")
    if source == destination or source in destination.parents or destination in source.parents:
        raise SafetyError("Working copy must be outside the source project.")
    if destination.exists():
        raise SafetyError("Destination already exists. Choose a new folder for this disposable copy.")
    # Links can lead saves outside the copy. Refuse them, including Windows junctions.
    size = 0
    def walk_error(error):
        raise error
    for root, dirs, files in os.walk(source, followlinks=False, onerror=walk_error):
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise SafetyError("Project contains links or junctions; copying refused for safety.")
            if path.is_file():
                size += path.stat().st_size
    available = shutil.disk_usage(destination.parent).free
    required = size + max(64 * 1024 * 1024, size // 100)
    if available < required:
        gib = 1024 ** 3
        raise SafetyError(f"Not enough free space. Full project copy needs about {required / gib:.2f} GiB "
                          f"including a safety margin; destination has {available / gib:.2f} GiB free. "
                          "No copy was started. Choose a drive with more space.")
    shutil.copytree(source, destination)
    return destination


class MapDocument:
    def __init__(self, working_root: Path, path: Path):
        self.root = working_root.resolve()
        self.path = path.resolve()
        if self.path.parent != self.root / "data" or not re.fullmatch(r"Map\d{3,}\.json", self.path.name):
            raise SafetyError("Only map JSON files inside the working copy can be edited.")
        self.raw = self.path.read_bytes()
        self.original = decode(self.raw)
        if not isinstance(self.original, dict) or not isinstance(self.original.get("events"), list):
            raise SafetyError("Unsupported map structure.")
        self.data = copy.deepcopy(self.original)
        # Keys refer to ORIGINAL command positions, so resizing one message cannot
        # shift the identity of subsequent messages or unrelated commands.
        self.edits: dict[tuple[int, int, int], tuple[str, ...]] = {}
        self.choice_edits: dict[tuple[int, int, int], tuple[str, ...]] = {}

    def page(self, event_index: int, page_index: int):
        return self.data["events"][event_index]["pages"][page_index]["list"]

    def edit(self, event_index: int, page_index: int, header_index: int, lines: list[str]):
        self.validate(self.data)
        commands = self.original["events"][event_index]["pages"][page_index]["list"]
        message = next((m for m in messages(commands) if m.header_index == header_index), None)
        if message is None:
            raise SafetyError("Only existing Show Text messages can be edited.")
        if tuple(lines) == message.lines:
            proposed = dict(self.edits)
            proposed.pop((event_index, page_index, header_index), None)
            self.data = self._expected(proposed)
            self.edits = proposed
            return
        if not 1 <= len(lines) <= 4 or len(message.lines) > 4:
            raise SafetyError("Each message must contain one to four lines. Existing messages over four lines are read-only.")
        for line in lines:
            if not isinstance(line, str) or "\n" in line or "\r" in line:
                raise SafetyError("Each existing Show Text command must remain one line.")
        old_codes = [code for line in message.lines for code in escape_codes(line)]
        new_codes = [code for line in lines for code in escape_codes(line)]
        if old_codes != new_codes:
            raise SafetyError("Escape codes must remain identical and in the same order within this message.")
        if len(lines) != len(message.lines) and any(set(commands[i]) != {"code", "indent", "parameters"}
                                                  for i in message.line_indices):
            raise SafetyError("Message has custom command metadata; changing its line count is unsafe.")
        proposed = dict(self.edits)
        proposed[event_index, page_index, header_index] = tuple(lines)
        self.data = self._expected(proposed)
        self.edits = proposed

    def edit_choice(self, event_index: int, page_index: int, header_index: int, option_index: int, label: str):
        self.validate(self.data)
        commands = self.original["events"][event_index]["pages"][page_index]["list"]
        group = next((g for g in choice_groups(commands) if g.header_index == header_index), None)
        if group is None or group.problem:
            raise SafetyError(group.problem if group else "No existing choice group at that command.")
        if type(option_index) is not int or not 0 <= option_index < len(group.labels):
            raise SafetyError("Only existing choice labels can be edited; no adding/removing/reordering options.")
        if not isinstance(label, str) or "\n" in label or "\r" in label:
            raise SafetyError("A choice label must remain a single line.")
        if escape_codes(label) != escape_codes(group.labels[option_index]):
            raise SafetyError("Choice escape codes must remain intact and in the same order.")
        key = event_index, page_index, header_index
        proposed = dict(self.choice_edits)
        labels = list(proposed.get(key, group.labels))
        labels[option_index] = label
        if tuple(labels) == group.labels:
            proposed.pop(key, None)
        else:
            proposed[key] = tuple(labels)
        self.data = self._expected(choice_edits=proposed)
        self.choice_edits = proposed

    def _expected(self, edits=None, choice_edits=None):
        edits = self.edits if edits is None else edits
        choice_edits = self.choice_edits if choice_edits is None else choice_edits
        expected = copy.deepcopy(self.original)
        # Apply paired label edits at ORIGINAL offsets before any 401 splicing.
        for (event, page, header), labels in choice_edits.items():
            original = self.original["events"][event]["pages"][page]["list"]
            group = next(g for g in choice_groups(original) if g.header_index == header)
            target = expected["events"][event]["pages"][page]["list"]
            target[header]["parameters"][0] = list(labels)
            for branch in group.branches:
                if branch.option_index is not None:
                    target[branch.header_index]["parameters"][1] = labels[branch.option_index]
        # Descending ORIGINAL positions avoid index drift across multiple edits.
        for (event, page, header), lines in sorted(edits.items(), reverse=True):
            original = self.original["events"][event]["pages"][page]["list"]
            message = next(m for m in messages(original) if m.header_index == header)
            replacement = []
            for index, line in enumerate(lines):
                template = original[message.line_indices[min(index, len(message.line_indices) - 1)]]
                command = copy.deepcopy(template)
                command["parameters"][0] = line
                replacement.append(command)
            target = expected["events"][event]["pages"][page]["list"]
            target[message.line_indices[0]:message.line_indices[-1] + 1] = replacement
        return expected

    def validate(self, candidate):
        expected = self._expected()
        touched = {(event, page) for event, page, _ in (*self.edits, *self.choice_edits)}
        for event, page in touched:
            before = self.original["events"][event]["pages"][page]["list"]
            after = candidate["events"][event]["pages"][page]["list"]
            if choice_topology(before) != choice_topology(after):
                raise SafetyError("Choice branch mapping or gameplay settings changed. Save refused.")
        # Serialized comparison also distinguishes JSON booleans from numbers.
        if json.dumps(candidate, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
            raise SafetyError("Changes outside the intended dialogue detected. Save refused.")

    def save(self) -> Path | None:
        self.validate(self.data)
        if self.data == self.original:
            return None
        if self.path.resolve() != self.path or self.path.parent.resolve() != self.root / "data":
            raise SafetyError("Working file location changed; reopen the project.")
        if self.path.read_bytes() != self.raw:
            raise SafetyError("Map changed on disk. Reopen the project before saving.")
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.validate(decode(payload))
        backup_dir = self.root / "dialogue_backups"
        if backup_dir.is_symlink() or (hasattr(backup_dir, "is_junction") and backup_dir.is_junction()):
            raise SafetyError("Backup directory must not be a link.")
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_dir / f"{self.path.stem}.{stamp}.{hashlib.sha256(self.raw).hexdigest()[:12]}.json"
        with backup.open("xb") as stream:
            stream.write(self.raw)
            stream.flush()
            os.fsync(stream.fileno())
        if backup.read_bytes() != self.raw:
            raise SafetyError("Backup verification failed; save refused.")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".dialogue-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            self.validate(decode(temporary.read_bytes()))
            if self.path.read_bytes() != self.raw:
                raise SafetyError("Map changed during save; replacement refused.")
            os.replace(temporary, self.path)
            temporary = None
            if self.path.read_bytes() != payload:
                raise SafetyError(f"Saved file verification failed. Original backup: {backup}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.raw = payload
        self.original = copy.deepcopy(self.data)
        self.edits.clear()
        self.choice_edits.clear()
        return backup


def face_region(index: int) -> tuple[int, int, int, int]:
    """MV's 4-column, 2-row face sheet uses fixed 144px cells."""
    if type(index) is not int or not 0 <= index <= 7:
        raise SafetyError("Unsupported face index; expected 0–7.")
    x, y = index % 4 * 144, index // 4 * 144
    return x, y, x + 144, y + 144
