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
    for root, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise SafetyError("Project contains links or junctions; copying refused for safety.")
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
        self.allowed: set[tuple[int, int, int]] = set()

    def page(self, event_index: int, page_index: int):
        return self.data["events"][event_index]["pages"][page_index]["list"]

    def edit(self, event_index: int, page_index: int, header_index: int, lines: list[str]):
        commands = self.page(event_index, page_index)
        message = next((m for m in messages(commands) if m.header_index == header_index), None)
        if message is None or len(lines) != len(message.lines):
            raise SafetyError("Keep the existing number of dialogue lines and message boundaries.")
        original_commands = self.original["events"][event_index]["pages"][page_index]["list"]
        for index, line in zip(message.line_indices, lines):
            old = original_commands[index]["parameters"][0]
            if not isinstance(line, str) or "\n" in line or "\r" in line:
                raise SafetyError("Each existing Show Text command must remain one line.")
            if escape_codes(old) != escape_codes(line):
                raise SafetyError("Escape codes must remain identical and in the same order on each line.")
        for index, line in zip(message.line_indices, lines):
            commands[index]["parameters"][0] = line
            self.allowed.add((event_index, page_index, index))

    def validate(self, candidate):
        expected = copy.deepcopy(self.original)
        for event, page, command in self.allowed:
            target = expected["events"][event]["pages"][page]["list"][command]
            updated = candidate["events"][event]["pages"][page]["list"][command]
            old, new = target["parameters"][0], updated["parameters"][0]
            if target.get("code") != 401 or not isinstance(new, str) or "\n" in new or "\r" in new:
                raise SafetyError("Invalid dialogue modification.")
            if escape_codes(old) != escape_codes(new):
                raise SafetyError("Escape codes changed.")
            target["parameters"][0] = new
        if candidate != expected:
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
        self.allowed.clear()
        return backup
