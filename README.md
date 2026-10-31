# DragonTail Dialogue Manager 0.2

A lightweight Windows desktop editor for **existing RPG Maker MV 1.6.3 Show Text** messages. Python and Tkinter only; no pip dependencies, server, or RPG Maker installation required.

**v0.1 is preserved:** the [v0.1 tag](https://github.com/CptDeathman-lab/RPGMAKERTOOL/tree/v0.1) and `main` branch retain the original working version. v0.2 lives separately on the `v0.2` branch and tag. Extract each version into its own application folder; keep your v0.1 folder until you are happy with v0.2. Neither version modifies your original game project.

## Run on Windows

1. Install Python 3.12 or newer from python.org with **Tcl/Tk and the Python launcher** enabled. If v0.1 already runs, you have everything needed for v0.2.
2. Extract the app into its own folder, for example `F:\Project DragonTail\Dialogue Workspace\Dialogue Manager v0.2`.
3. Double-click `Run DragonTail Dialogue Manager.bat`, or run `py -3 dragontail_dialogue_manager.py` from the application folder.
4. Click **Open Project**. Select your source project folder, such as `F:\Project DragonTail\DragonTail RPG`, containing `Game.rpgproject` and `data`.
5. Select `F:\Project DragonTail\Dialogue Workspace` as the destination parent. It must be **outside the source project**. The app checks available space, then makes a new timestamped **full project copy**, including media. It needs the project's full size plus a small safety margin. Only the copy is editable. Do not repeatedly open the original unless you want another full copy.
6. Expand a **map → event → page**. Double-click the page or click **Select Event**.
7. Read the compact page overview. Click any message to edit it below; use **Previous / Next**, **Ctrl+↑ / Ctrl+↓**, or **Find Next** to move around. Draft edits stay with their messages until you save or discard the page.
8. Rewrite a message using **one to four explicit lines**. Press Enter to add a line, or delete line breaks to shorten it. The counter turns red above four lines, and Save refuses the edit. A blank message remains one blank line; messages cannot be deleted or created. There is no automatic wrapping or splitting into new message windows.
9. Click **Save**. The app validates the complete map, creates and verifies a backup, and writes the disposable copy. Navigating to another event/page or closing prompts to save/discard unsaved edits.
10. Open `Game.rpgproject` in the timestamped **`DragonTail RPG-DialogueCopy-…`** folder shown by the app, then playtest there. This tool never merges changes back into the original.

**Continue existing work:** every Open Project operation creates a new copy. To continue edits in a previous copy, select that copy as the source and choose a workspace outside it. The new copy includes those saved edits. This version does not open a project for direct editing in place.

## What's new in v0.2

- **Flexible line count:** expand/shrink existing messages to one–four lines. Each original code 101 header remains in place and retains its portrait/settings. Only its immediately following code 401 text lines may be inserted or removed. No event logic is added, deleted, moved, or changed.
- **Portrait previews:** display the actual 144×144 face selected by the message's filename and index in `img/faces/*.png`. Standard MV sheets have four columns and two rows. No portrait is shown for a blank filename. Missing, encrypted (`.rpgmvp`), malformed, or unsupported portraits show a notice; text editing still works. No image dependencies or decryption are required.
- **Page overview:** one readable transcript and one focused editor replace dozens of individual editor boxes. Click-to-jump, Previous/Next, and case-insensitive Find Next work across messages on the selected page. Changes update the overview.
- **Copy-space check:** insufficient free space is detected before copying starts. The app still makes a **full copy**, so media assets still require space. Changes in available space or copy errors can still leave a partial copy; the source is unchanged.

## Safety and scope

- **Escape codes must remain intact and in the same order within each original message.** They can move between lines as part of rewriting, but cannot move to another message or be added/removed/changed. Example: `Hello, \N[1]!` can become two lines `Hello,` and `\N[1]!`. This includes plugin-style backslash codes. The app does not render escape codes or simulate plugin behavior.
- Existing message boundaries, portrait filename/index, background, position, indentation, and all unrelated event commands remain unchanged. Switches, variables, branches, choices, movement routes, plugin commands, and Story Progress are never edited.
- The overview follows **command order on the selected event page**, with branch depth and markers for intervening commands. It does **not** evaluate page conditions, alternate branches, choices, jumps, common event calls, or the game's actual execution path. It is a proofreading view, not a simulated conversation.
- Messages already exceeding four lines are read-only. Messages with custom metadata on their code 401 commands cannot change line count. Malformed/unsupported message structures are refused. No editing choices, scrolling text, common events, troop events, scripts, settings, or plugin commands.
- The four-line check counts explicit newlines, not pixel width. Long lines and escape-code effects still need playtesting in RPG Maker, especially with portraits or message plugins.
- Map JSON is parsed strictly. Save reconstructs the expected map from its original snapshot and explicit message edits, then compares the entire modified map. Unrelated values and commands must match exactly, including JSON types. JSON whitespace/formatting is normalized on save.
- Before each changed save, the previous map's exact bytes are written and verified in the **copy's** `dialogue_backups` folder. Filenames include map name, UTC timestamp, and a content hash. Save uses a validated temporary file and atomic replacement. External changes detected before replacement cause refusal. Do not edit the same working map in RPG Maker or another editor simultaneously.
- **Revert Page** discards unsaved edits and reloads the map currently on disk. It does not undo an earlier save. To restore a saved version: close the app and RPG Maker, copy a chosen backup over the corresponding `data/MapXXX.json` **in the disposable copy**, then reopen. Keep backups until playtesting succeeds.
- Source projects containing symbolic links or junctions are refused. The app reads the selected source only to copy it; all map writes and backups stay in the new copy.
- No executable bundle or installer is included. The cloud workspace cannot access your Windows `F:` drive or your actual DragonTail files.

## Development and validation

From this folder run:

```console
python -m unittest discover -s tests -v
```

The core tests cover resizing multiple messages in either order, preservation of non-dialogue commands and JSON types, backups, Unicode, escape-code restrictions, line limits, external changes, failed replacement, copy isolation, low disk space, and face-sheet coordinates. GUI tests require a desktop display and skip on headless Linux unless a virtual display is supplied, for example:

```console
xvfb-run -a python -m unittest discover -s tests -v
```

For v0.2, all 26 core and real Tk GUI tests passed under a Linux virtual display, including editing/navigating/saving messages and checking actual cropped portrait pixels for every slot of a synthetic face sheet. No actual DragonTail event data or Windows runtime was available. Windows interaction and game playtesting remain required before trusting changes for the original project.
