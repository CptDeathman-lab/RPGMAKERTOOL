"""Read-only MV choice structure discovery, independent of the GUI/editor."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChoiceBranch:
    option_index: int | None  # None is When Cancel (403).
    header_index: int
    start: int
    end: int


@dataclass(frozen=True)
class ChoiceGroup:
    header_index: int
    end_index: int
    indent: int
    labels: tuple[str, ...]
    settings: tuple
    branches: tuple[ChoiceBranch, ...]
    problem: str = ""


def choice_groups(commands: list) -> list[ChoiceGroup]:
    """Pair markers at the SAME indent; nested choices are separate groups.

    Invalid/custom structures are returned with a problem, never silently repaired.
    Branch spans exclude their 402/403 marker and the following marker/404.
    """
    groups = []
    for header, command in enumerate(commands):
        if not isinstance(command, dict) or command.get("code") != 102:
            continue
        params = command.get("parameters")
        valid_params = (isinstance(params, list) and len(params) >= 5
                        and isinstance(params[0], list) and bool(params[0])
                        and all(isinstance(label, str) for label in params[0]))
        labels = tuple(params[0]) if valid_params else ()
        settings = tuple(params[1:]) if valid_params else ()
        indent = command.get("indent")
        problem = "" if valid_params else "Unsupported Show Choices parameters."
        if type(indent) is not int or indent < 0:
            problem = "Unsupported choice indentation."
        markers = []
        end = header
        if type(indent) is int:
            for position in range(header + 1, len(commands)):
                item = commands[position]
                if not isinstance(item, dict) or type(item.get("indent")) is not int:
                    problem = "Unsupported command inside choice block."
                    break
                depth, code = item["indent"], item.get("code")
                if depth < indent:
                    break
                if depth != indent:
                    continue
                if code == 404:
                    end = position
                    break
                if code not in (402, 403):
                    problem = "Unexpected command at choice-marker indentation."
                    break
                markers.append(position)
        if end == header:
            problem = problem or "Matching End Choices (404) was not found."
        if markers and markers[0] != header + 1:
            problem = problem or "Unexpected commands before the first When branch."
        branches, seen, cancel_count = [], [], 0
        for offset, position in enumerate(markers):
            item = commands[position]
            option = None
            if item["code"] == 402:
                branch_params = item.get("parameters")
                if (not isinstance(branch_params, list) or len(branch_params) < 2
                        or type(branch_params[0]) is not int
                        or not 0 <= branch_params[0] < len(labels)
                        or not isinstance(branch_params[1], str)):
                    problem = "Unsupported When branch index or label."
                else:
                    option = branch_params[0]
                    seen.append(option)
                    if branch_params[1] != labels[option]:
                        problem = "Existing 102 and 402 labels disagree; editing is read-only."
            else:
                cancel_count += 1
            stop = markers[offset + 1] if offset + 1 < len(markers) else end
            branches.append(ChoiceBranch(option, position, position + 1, stop))
        if sorted(seen) != list(range(len(labels))) or len(seen) != len(labels):
            problem = problem or "Every option must have exactly one matching When branch."
        if valid_params:
            cancel, default, alignment, background = params[1:5]
            if (type(cancel) is not int or not -2 <= cancel < len(labels)
                    or type(default) is not int or not -1 <= default < len(labels)
                    or type(alignment) is not int or alignment not in (0, 1, 2)
                    or type(background) is not int or background not in (0, 1, 2)):
                problem = problem or "Unsupported cancel/default/window settings."
            if cancel_count != (1 if cancel == -2 else 0):
                problem = problem or "Cancel behavior and When Cancel markers disagree."
        groups.append(ChoiceGroup(header, end, indent, labels, settings, tuple(branches), problem))
    return groups


def choice_topology(commands: list):
    """Stable branch identity excluding only 401 line commands and label strings.

    Resizing text cannot change this fingerprint. Settings, branch order, branch
    indices, indentation, and the positions of all other commands are retained.
    """
    logic = [command for command in commands if not isinstance(command, dict) or command.get("code") != 401]
    return [(group.header_index, group.end_index, group.indent, len(group.labels), group.settings,
             [(branch.option_index, branch.header_index, branch.start, branch.end) for branch in group.branches],
             group.problem) for group in choice_groups(logic)]
