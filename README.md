# DragonTail Dialogue Manager 0.1

A small Windows desktop editor for **existing RPG Maker MV 1.6.3 Show Text** commands. Uses Python and Tkinter only; no pip dependencies, server, or RPG Maker installation required.

## Run on Windows

1. Install Python 3.12 or newer from python.org with **Tcl/Tk and the Python launcher** enabled.
2. Put this application's files in `E:\Project DragonTail\Dialogue Workspace\DragonTail Dialogue Manager` (or any convenient application folder).
3. Double-click `Run DragonTail Dialogue Manager.bat`. Alternatively run `py -3 dragontail_dialogue_manager.py` from the application folder.
4. Click **Open Project** and select the original project folder containing `Game.rpgproject` and `data`. Then select `E:\Project DragonTail\Dialogue Workspace` as the destination parent. **This must be outside the original project.** The app creates a new timestamped, disposable full copy. Only that copy is editable. Copying a large project can take time and requires enough free disk space.
5. Expand a map, then an event. Select a page and click **Select Event**, or double-click the page. **Edit Dialogue** focuses the first message editor.
6. Edit existing text and click **Save**. **Revert Page** reloads the copy's current map from disk. Navigation prompts to save or discard unsaved edits.
7. Playtest the disposable copy in RPG Maker MV before considering any manual transfer. This tool does not merge or copy changes back to the original.

Every Open Project operation creates a fresh disposable copy; to continue an earlier copy, select that copy as the source and create a new copy from it. The working copy path is shown in the window. The application never writes to the selected source.

## Safety and scope

- Edits affect only string parameter 0 of existing code **401** lines immediately following a **101** header. Portrait filename/index, background, position, indentation, pages, message boundaries, and every other event command remain unchanged.
- Keep the exact number of lines in each message. Blank lines are supported. Escape sequences must remain identical and in the same order **on each line**, including plugin-style backslash codes. No creating/deleting messages or editing settings, choices, scrolling text, common events, troop events, scripts, or plugin commands.
- Map JSON is parsed strictly. Before saving, a full structural comparison allows only the selected dialogue string changes. JSON whitespace/formatting is normalized on save; unrelated JSON values are preserved.
- Before each changed save, the previous map's exact bytes are written and verified in the **copy's** `dialogue_backups` folder. Each filename includes map name, UTC timestamp, and a content hash. Saving uses a validated temporary file and atomic replacement. External file changes detected before replacement cause refusal. Avoid editing the same working map in RPG Maker or another editor simultaneously; filesystem saves cannot coordinate with unrelated programs.
- To restore: close this app and RPG Maker, copy the chosen backup over the corresponding `data/MapXXX.json` **in the disposable copy**, then reopen. Keep the backup until playtesting succeeds.
- Source projects containing symbolic links or junctions are refused. Malformed/unsupported message structures are refused. There is no executable bundle or installer in v0.1.

## Development and validation

Run `python -m unittest discover -s tests -v` from this folder. Tests create temporary MV-shaped projects and verify backups, exact preservation of unrelated commands (including Story Progress-style plugin commands), escape/line restrictions, external-change refusal, failed replacement, Unicode, and copy isolation. No actual DragonTail data was available during development, so these are representative fixtures, not a claim of DragonTail playtest compatibility. Windows GUI interaction and actual game playtesting remain required on your machine.

The Windows `E:` directory is not accessible from the cloud workspace. The application is built here; copy these files to that directory to run it there.
