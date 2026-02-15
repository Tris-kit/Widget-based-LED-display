try:
    from typing import Iterable, List, Optional, Sequence, Tuple
except ImportError:
    from local.typing_compat import Iterable, List, Optional, Sequence, Tuple

from adafruit_display_text import label
from adafruit_bitmap_font import bitmap_font
import terminalio
import displayio


class SimpleTextLayout:
    def __init__(
        self,
        font_path: Optional[str] = None,
        color: int = 0xFFFFFF,
        line_spacing: int = 10,
        scale: int = 1,
        word_spacing_scale: float = 0.5,
        letter_spacing: int = 1,
        space_width: int = 3,
    ) -> None:
        """Create a text layout helper with custom spacing."""
        # Fail loudly if display dependencies are missing.
        self.font = None
        if font_path and bitmap_font is not None:
            try:
                self.font = bitmap_font.load_font(font_path)
            except Exception:
                self.font = None
        if self.font is None and terminalio is not None:
            self.font = terminalio.FONT
        if self.font is None and bitmap_font is not None:
            try:
                self.font = bitmap_font.load_font("/lib/fonts/LeagueSpartan-Bold-16.bdf")
            except Exception:
                self.font = None
        self.scale = scale
        self.color = color
        self.line_spacing = line_spacing
        self.word_spacing_scale = word_spacing_scale
        self.letter_spacing = letter_spacing
        self.space_width = space_width

    def _measure_text_width(self, text: str, scale: int) -> int:
        """Measure text width using the underlying font."""
        text_label = label.Label(self.font, text=text or "", color=self.color, scale=scale)
        try:
            bounds = text_label.bounding_box
            return bounds[2]
        except Exception:
            return len(text or "") * 6 * scale

    def _glyph_metrics(self, ch: str, scale: int) -> Tuple[None, int, int]:
        """Return custom width and trim values for a glyph."""
        # Manual width map to enforce fixed visual spacing on the LED grid.
        if ch == " ":
            return None, self.space_width * scale, 0
        narrow_chars = {"i", "l", "1"}
        medium_chars = {"t"}
        left_trim_chars = {"t", "i", "l", "1"}
        if ch in narrow_chars:
            width = 3
        elif ch in medium_chars:
            width = 4
        else:
            width = 5
        left_trim = 1 if ch in left_trim_chars else 0
        return None, width * scale, left_trim * scale

    def _space_width(self, scale: int) -> int:
        """Compute the pixel width of a space at the given scale."""
        width_with = self._measure_text_width("A A", scale)
        width_without = self._measure_text_width("AA", scale)
        base_width = width_with - width_without
        if base_width <= 0:
            base_width = self._measure_text_width(" ", scale)
        reduced = int(base_width * self.word_spacing_scale)
        return max(1, reduced)

    def _build_word_group(
        self,
        line: str,
        scale: int,
        color: Optional[int] = None,
    ) -> Tuple[displayio.Group, int]:
        """Build a group for a line of text using word spacing."""
        words = line.split(" ")
        space_width = self._space_width(scale)
        total_width = 0
        word_widths = []
        use_color = self.color if color is None else color
        for word in words:
            width = self._measure_text_width(word, scale) if word else 0
            word_widths.append(width)
            total_width += width
        total_width += space_width * max(0, len(words) - 1)

        line_group = displayio.Group()
        cursor_x = 0
        for index, word in enumerate(words):
            if word:
                text = label.Label(self.font, text=word, color=use_color, scale=scale)
                text.x = cursor_x
                text.y = 0
                line_group.append(text)
                cursor_x += word_widths[index]
            if index < len(words) - 1:
                cursor_x += space_width
        return line_group, total_width

    def _build_char_group(
        self,
        line: str,
        scale: int,
        color: Optional[int] = None,
    ) -> Tuple[displayio.Group, int]:
        """Build a group for a line of text using per-char spacing."""
        line_group = displayio.Group()
        cursor_x = 0
        prev_was_space = True
        use_color = self.color if color is None else color
        for ch in line:
            if ch == " ":
                # Word spacing uses a fixed 3px gap.
                cursor_x += (self.space_width * scale)
                prev_was_space = True
                continue
            if cursor_x > 0 and not prev_was_space:
                # Single-pixel gap between characters in a word.
                cursor_x += self.letter_spacing
            _, advance, left_trim = self._glyph_metrics(ch, scale)
            text = label.Label(self.font, text=ch, color=use_color, scale=scale)
            text.x = cursor_x - left_trim
            text.y = 0
            line_group.append(text)
            cursor_x += advance
            prev_was_space = False
        total_width = max(0, cursor_x)
        return line_group, total_width

    def build_group(
        self,
        lines: Sequence[str],
        x: int = 2,
        y: int = 16,
        width: int = 64,
        align: str = "center",
        padding_right: int = 2,
        scale: Optional[int] = None,
        color: Optional[int] = None,
    ) -> displayio.Group:
        """Build a displayio group containing the provided lines."""
        group = displayio.Group()
        cursor_y = y
        if scale is None:
            scale = self.scale
        use_color = self.color if color is None else color
        max_width = max(0, width - x - padding_right)
        for line in lines:
            if self.letter_spacing is not None:
                line_group, line_width = self._build_char_group(line or "", scale, use_color)
                text_x = x
                if align == "center":
                    text_x = x + max(0, (max_width - line_width) // 2)
                line_group.x = text_x
                line_group.y = cursor_y
                group.append(line_group)
            elif " " in (line or "") and self.word_spacing_scale < 1:
                line_group, line_width = self._build_word_group(line or "", scale, use_color)
                text_x = x
                if align == "center":
                    text_x = x + max(0, (max_width - line_width) // 2)
                line_group.x = text_x
                line_group.y = cursor_y
                group.append(line_group)
            else:
                text = label.Label(self.font, text=line, color=use_color, scale=scale)
                text_x = x
                if align == "center":
                    try:
                        bounds = text.bounding_box
                        text_width = bounds[2]
                        text_x = x + max(0, (max_width - text_width) // 2)
                    except Exception:
                        text_x = x
                text.x = text_x
                text.y = cursor_y
                group.append(text)
            cursor_y += self.line_spacing
        return group

    def measure_lines(self, lines: Sequence[str]) -> int:
        """Return the maximum pixel width of the provided lines."""
        max_width = 0
        for line in lines:
            text = label.Label(self.font, text=line or "", color=self.color, scale=self.scale)
            try:
                bounds = text.bounding_box
                width = bounds[2]
            except Exception:
                width = len(line or "") * 8
            if width > max_width:
                max_width = width
        return max_width
