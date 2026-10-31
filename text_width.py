"""Advisory MV width estimates. No claim to execute game fonts or plugins."""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WidthReport:
    pixels: int
    budget: int
    uncertain: bool

    @property
    def overflow(self):
        return self.pixels > self.budget


def check_width(text, measure, *, screen_width=816, font_px=28, portrait=False, choice=False):
    """measure(plain_text, font_pixel_size) -> pixel width, supplied by the UI.

    MV pads windows by 18px, reserves 168px for a message face, and choices
    reserve text padding (6px on each side) within their auto-sized window.
    Variables/names/currency and unknown plugin codes are deliberately uncertain.
    """
    budget = max(0, screen_width - 36 - (12 if choice else 168 if portrait else 0))
    maximum, uncertain, size = 0, False, font_px
    for line in text.split("\n"):
        pixels, cursor = 0, 0
        for match in re.finditer(r"\\(?:[A-Za-z]+(?:\[[^\]\r\n]*\])?|.|$)", line):
            pixels += measure(line[cursor:match.start()], size)
            token = match.group()[1:]
            if token == "\\":
                pixels += measure("\\", size)
            elif token == "{":
                if size <= 96:
                    size += 12
            elif token == "}":
                if size >= 24:
                    size -= 12
            elif re.fullmatch(r"[Ii]\[\d+\]", token):
                pixels += 36  # MV's 32px icon plus 4px spacing.
            elif re.fullmatch(r"[Cc]\[\d+\]", token) or token in ("$", ".", "|", "!", ">", "<", "^"):
                pass
            else:
                uncertain = True
            cursor = match.end()
        pixels += measure(line[cursor:], size)
        maximum = max(maximum, pixels)
    return WidthReport(round(maximum), budget, uncertain)
