# DragonTail Dialogue Manager 0.3 — Choices preview

A lightweight Windows desktop editor for **existing RPG Maker MV 1.6.3 map-event dialogue and choices**. Uses Python 3.12+ and Tkinter only; no pip dependencies, server, or RPG Maker installation required.

**Previous versions are preserved unchanged:** [v0.1](https://github.com/CptDeathman-lab/RPGMAKERTOOL/tree/v0.1) remains on `main` and tag `v0.1`; [v0.2](https://github.com/CptDeathman-lab/RPGMAKERTOOL/tree/v0.2) remains on its own branch and tag. The choices preview is on branch `v0.3`. Extract it into a separate application folder and keep your working version.

## Run on Windows

1. If v0.1/v0.2 already runs, you have the required Python/Tkinter setup. Otherwise install Python 3.12+ from python.org with **Tcl/Tk and the Python launcher** enabled.
2. Extract into its own application folder, for example `F:\Project DragonTail\Dialogue Workspace\Dialogue Manager v0.3`.
3. Double-click `Run DragonTail Dialogue Manager.bat`, or run `py -3 dragontail_dialogue_manager.py` from that folder.
4. Click **Open Project** and select the source project, e.g. `F:\Project DragonTail\DragonTail RPG`, containing `Game.rpgproject` and `data`.
5. Select `F:\Project DragonTail\Dialogue Workspace` as the destination parent. It must be **outside the source project**. After checking free space, the app makes a new timestamped **full project copy**, including media. It needs the project's full size plus a safety margin. Only this disposable copy is editable.
6. Expand a **map → event → page**. Double-click the page or click **Select Event**. The title identifies the map, event ID, page, and event name.
7. Use the overview, **Previous / Next**, **Ctrl+↑ / Ctrl+↓**, or case-insensitive **Find Next** to select messages or choice labels. Drafts survive navigation within the page.
8. Click **Save** to validate the complete map, create and verify a backup, and write the disposable copy. Changing pages or closing prompts to save/discard unsaved edits.
9. Open `Game.rpgproject` inside the timestamped **`DragonTail RPG-DialogueCopy-…`** folder shown by the app and playtest there. The tool never merges changes back into your original.

Every Open Project operation creates another full copy. To continue saved work, select that existing copy as the source and choose a workspace outside it; the new copy includes its edits. This version does not open projects for direct editing in place. Failed copies can leave a partial destination if disk space changes or copying fails; the source remains untouched.

## Read and edit a choice event

For the bedtime interaction, navigate to **Map002 → Event 004 → Page 1**:

- The question appears as normal dialogue.
- **Show Choices** lists the actual option labels read from code 102. Click an option to edit its single-line text. Options cannot be added, deleted, or reordered.
- Each **When … (option N)** heading contains only that branch's dialogue and read-only gameplay commands. Click the heading to collapse or expand it. Empty branches are explicitly marked. Nested choices have nested sections; a separate When Cancel section appears when present.
- Named commands and their parameters (for example Fade out BGM, Fade out screen, Variables, Plugin command) stay visible within their owning branch. Long parameters are abbreviated for display only. All gameplay commands are read-only.
- Click dialogue within a branch to use the normal one–four-line editor, including portrait previews. Finding or navigating to text inside a collapsed branch reveals its ancestors.
- Choice labels are paired by their original **branch index**, not their wording. Save updates the label in 102 and the corresponding label in 402 together. Duplicate labels and nested choices remain distinct.
- Cancel behavior, default selection, window position/background, branch indices, indentation, and branch commands are locked. Unsupported or inconsistent choice structures are shown as **READ-ONLY**, with the reason. The app never silently repairs them.

The overview follows event-page **command order**, including alternate paths. It does not execute page conditions, choices, branches, common event calls, jumps, scripts, or plugins; it is a proofreading view, not a gameplay simulator. Labels such as Yes/No are illustrative until read from your actual file.

## Text and width checks

- Existing messages can expand/shrink to **one–four explicit lines**, without creating/removing message windows. Blank messages remain one blank line. More than four lines is refused on save. Existing over-four-line messages are read-only; custom 401 metadata prevents resizing.
- Choice labels must stay on **one explicit line**. Escape codes must remain intact and in the same order within the same original label/message. Message escape codes can move between lines, but not between messages or options.
- The available v0.2 code contained no live width checker, so this version adds a shared **advisory estimate** for dialogue and choice text. Adjust screen width and base font size in the toolbar to match your project; defaults are MV's 816px and 28px. These controls do not change game settings.
- Measurements use an Arial/Tk font approximation, not your actual GameFont. Standard message padding, portrait space, choice-window padding, icons, color codes, waits, and font-size changes are considered. A choice window auto-sizes up to the screen width, so choice overflow is checked against that cap rather than the narrower portrait-dialogue budget.
- Red warnings flag estimated overflow. Variables, actor/party names, currency, and unknown/plugin escape codes flag uncertain width. Missing/encrypted portraits show a notice without blocking text editing. Width warnings **do not truncate text or block saving**; playtest with your game's actual fonts, resolution, and plugins.

## Save safety and backups

- The complete modified map must match a reconstruction of the original plus the explicitly selected dialogue and paired choice-label edits. Validation separately compares choice topology after excluding only 401 text lines, so resizing cannot authorize branch remapping. JSON types are compared strictly.
- Only existing message 401 text lines and selected label strings in 102/402 can change. No gameplay commands, switches, variables, choices' gameplay settings, branches, movement routes, plugin commands, or Story Progress are changed.
- Before each changed save, the previous map's **exact bytes** are written and verified in the copy's `dialogue_backups` folder. Backup filenames include map, UTC timestamp, and a content hash. A validated temporary file and atomic replacement are used for saving. JSON whitespace is normalized; unrelated JSON values remain unchanged.
- External map changes detected before replacement cause refusal. Avoid editing the same working map simultaneously in RPG Maker or another editor.
- **Revert Page** discards unsaved page edits and reloads the current saved map. To undo a save, close the app and RPG Maker and copy a chosen backup over the matching `data/MapXXX.json` **inside the disposable copy**. Keep backups until playtesting succeeds.
- Source projects with symbolic links/junctions are refused. No original-project writes, automatic merging, choice creation, message creation, editing of settings/gameplay commands, common/troop event editing, or executable installer are included.

## Test the actual DragonTail choice event

The cloud cannot access your Windows `F:` drive. **Actual DragonTail testing is still pending** until `Map002.json` from the disposable copy is supplied or tested locally. No full game/media upload is necessary.

A read-only verifier is included. Open a terminal in the app folder and run this, replacing `YOUR-DISPOSABLE-COPY` with the actual timestamped folder name:

```bat
py -3 verify_choices.py "F:\Project DragonTail\Dialogue Workspace\YOUR-DISPOSABLE-COPY\data\Map002.json" --event 4 --page 1
```

This reads Event ID 4 (not a guessed array position), copies only the map to a temporary directory, exercises label and dialogue edits, verifies synchronized branches/settings and exact backup bytes, checks the supplied map stayed unchanged, then discards the temporary files. It prints the actual labels found and exits nonzero on failure. It does not replace GUI or gameplay testing.

After that, in the GUI's disposable copy, proofread each option, expand each branch, make a small label/text edit, save, reopen the page, and confirm the labels are synchronized. In RPG Maker, verify both option paths, default selection, and cancellation. Keep the original game and older application versions unchanged during testing.

## Automated development checks

From this folder:

```console
python -m unittest discover -s tests -v
```

GUI tests require a desktop display. On headless Linux use a virtual display, e.g. `xvfb-run -a python -m unittest discover -s tests -v`; without one, GUI tests are explicitly skipped.

The suite covers nested/sequential choices, separate-cancel/disabled-cancel/option-cancel modes, duplicate labels, paired saves, malformed structures, forbidden logic changes, dialogue resizing across choices, backups, external changes, original-source isolation, portrait pixels, live width warnings, collapsible sections, search, navigation, and the temporary-map verifier. Fixtures are representative MV data; they are **not** the actual DragonTail bedtime event. Linux/Tk checks do not establish Windows or game-runtime compatibility.
