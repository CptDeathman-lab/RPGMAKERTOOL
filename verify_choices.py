r"""Verify a real MV event by round-tripping ONLY a temporary copy of its map.

Usage: py -3 verify_choices.py "F:\...\data\Map002.json" --event 4 --page 1
The supplied file is never written. No media/project copy is needed for this test.
"""
import argparse
import hashlib
from pathlib import Path
import tempfile

from choice_support import choice_groups, choice_topology
from dialogue_core import MapDocument, SafetyError, decode, messages


def verify_event(path: Path, event_id=4, page_number=1):
    path = Path(path).resolve()
    raw = path.read_bytes()
    data = decode(raw)
    event_index = next((index for index, event in enumerate(data["events"])
                        if isinstance(event, dict) and event.get("id") == event_id), None)
    if event_index is None:
        raise SafetyError(f"Event {event_id} was not found.")
    pages = data["events"][event_index]["pages"]
    if not 1 <= page_number <= len(pages):
        raise SafetyError("Requested page was not found (page numbers start at 1).")
    original = pages[page_number - 1]["list"]
    groups = choice_groups(original)
    if not groups:
        raise SafetyError("No Show Choices command on the requested event page.")
    if any(group.problem for group in groups):
        raise SafetyError("Read-only choice structure: " + "; ".join(group.problem for group in groups if group.problem))
    original_topology = choice_topology(original)
    labels = [group.labels for group in groups]
    edited_messages = 0
    with tempfile.TemporaryDirectory(prefix="dragontail-choice-check-") as folder:
        root = Path(folder)
        (root / "data").mkdir()
        copied_map = root / "data" / path.name
        copied_map.write_bytes(raw)
        document = MapDocument(root, copied_map)
        for block in messages(original):
            if len(block.lines) <= 4:
                lines = list(block.lines)
                lines[0] = "[verification only] " + lines[0]
                document.edit(event_index, page_number - 1, block.header_index, lines)
                edited_messages += 1
        for group in groups:
            for option, label in enumerate(group.labels):
                document.edit_choice(event_index, page_number - 1, group.header_index, option,
                                     "[verification only] " + label)
        backup = document.save()
        if backup is None or backup.read_bytes() != raw:
            raise SafetyError("Backup round-trip verification failed.")
        reopened = MapDocument(root, copied_map)
        after = reopened.page(event_index, page_number - 1)
        if choice_topology(after) != original_topology:
            raise SafetyError("Choice mapping changed during the round-trip.")
        after_groups = choice_groups(after)
        for before, after_group in zip(groups, after_groups):
            if after_group.labels != tuple("[verification only] " + label for label in before.labels):
                raise SafetyError("Choice label round-trip failed.")
    if path.read_bytes() != raw:
        raise SafetyError("Source map changed externally during verification.")
    return {"event": event_id, "page": page_number, "choice_groups": len(groups),
            "labels": labels, "tested_labels": sum(len(group.labels) for group in groups),
            "tested_dialogue_messages": edited_messages, "source_sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description="Test choice edits and backups using a temporary copy; supplied map is read-only.")
    parser.add_argument("map", type=Path)
    parser.add_argument("--event", type=int, default=4)
    parser.add_argument("--page", type=int, default=1)
    args = parser.parse_args()
    try:
        result = verify_event(args.map, args.event, args.page)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        parser.exit(1, f"Verification failed: {error}\n")
    print(f"PASS: Event {result['event']}, page {result['page']}; {result['choice_groups']} choice groups, "
          f"{result['tested_labels']} labels, {result['tested_dialogue_messages']} dialogue messages.")
    print("Verified paired labels, original branch mapping/settings, backup bytes, and unchanged source map.")
    for number, labels in enumerate(result["labels"], 1):
        print(f"  Choices {number}: {labels}")
    print("Source SHA256:", result["source_sha256"])
    print("All test changes were made in a temporary copy and discarded. Playtest the GUI's working copy separately.")


if __name__ == "__main__":
    main()
