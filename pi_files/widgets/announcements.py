import time
try:
    from typing import List, Optional, Sequence
except ImportError:
    from local.typing_compat import List, Optional, Sequence

try:
    import displayio
except Exception:
    displayio = None

from local.ui.progress_bar import ProgressBar
from local.ui.sprite_sheet_player import SpriteSheetPlayer
from local.ui.display_helpers import build_error_group


class CronSchedule:
    """Minimal cron matcher for 5-field schedules (min hour dom mon dow)."""

    def __init__(self, expr: str) -> None:
        """Parse a 5-field cron expression and cache value sets."""
        fields = (expr or "* * * * *").strip().split()
        if len(fields) != 5:
            print("Bad cron (expected 5 fields):", expr)
            fields = ["*", "*", "*", "*", "*"]
        self._minute = _parse_field(fields[0], 0, 59)
        self._hour = _parse_field(fields[1], 0, 23)
        self._dom = _parse_field(fields[2], 1, 31)
        self._month = _parse_field(fields[3], 1, 12)
        self._dow = _parse_field(fields[4], 0, 7)
        # Cron allows 0 or 7 for Sunday; normalize both to 0.
        if self._dow is not None and 7 in self._dow:
            self._dow.add(0)

    def matches(self, tm) -> bool:
        """Return True when the given time tuple matches this schedule."""
        if tm is None:
            return False
        # time.localtime().tm_wday is 0=Mon..6=Sun; cron is 0=Sun..6=Sat.
        dow = (tm.tm_wday + 1) % 7
        return (
            _match_field(self._minute, tm.tm_min)
            and _match_field(self._hour, tm.tm_hour)
            and _match_field(self._dom, tm.tm_mday)
            and _match_field(self._month, tm.tm_mon)
            and _match_field(self._dow, dow)
        )


def _match_field(values: Optional[set], value: int) -> bool:
    """Return True if value is allowed by the parsed field."""
    if values is None:
        return True
    return value in values


def _parse_field(field: str, min_value: int, max_value: int) -> Optional[set]:
    """Parse a cron field into a set of allowed values, or None for wildcard."""
    field = (field or "").strip()
    if not field or field == "*":
        return None
    values = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        expanded = _expand_part(part, min_value, max_value)
        if expanded is None:
            return None
        values.update(expanded)
    if not values:
        return None
    return values


def _expand_part(part: str, min_value: int, max_value: int) -> Optional[Sequence[int]]:
    """Expand a field fragment into a numeric range or list."""
    if part == "*":
        return range(min_value, max_value + 1)
    step = None
    base = part
    if "/" in part:
        base, step_text = part.split("/", 1)
        try:
            step = int(step_text)
        except Exception:
            step = None
    if base == "*":
        start = min_value
        end = max_value
    elif "-" in base:
        start_text, end_text = base.split("-", 1)
        try:
            start = int(start_text)
            end = int(end_text)
        except Exception:
            return None
    else:
        try:
            value = int(base)
        except Exception:
            return None
        if step and step > 1:
            return range(value, max_value + 1, step)
        return [value]

    if step is None or step <= 0:
        step = 1
    return range(start, end + 1, step)


class Announcement:
    def __init__(
        self,
        label: str,
        cron: str,
        image: Optional[str],
        x_image_offset: int = 0,
        y_image_offset: int = 0,
        duration_seconds: Optional[int] = None,
        frame_delay_seconds: Optional[float] = None,
        text_color: Optional[int] = None,
    ) -> None:
        """Store announcement content and its schedule."""
        self.label = (label or "").strip()
        self.image = (image or "").strip() or None
        self.cron_expr = cron or "* * * * *"
        self.schedule = CronSchedule(self.cron_expr)
        try:
            self.x_image_offset = int(x_image_offset)
        except Exception:
            self.x_image_offset = 0
        try:
            self.y_image_offset = int(y_image_offset)
        except Exception:
            self.y_image_offset = 0
        try:
            self.duration_seconds = int(duration_seconds) if duration_seconds is not None else None
        except Exception:
            self.duration_seconds = None
        try:
            self.frame_delay_seconds = float(frame_delay_seconds) if frame_delay_seconds is not None else None
        except Exception:
            self.frame_delay_seconds = None
        self.text_color = text_color


class AnnouncementsWidget:
    """Shows scheduled announcements with optional GIFs and a progress bar."""

    def __init__(
        self,
        announcements: Optional[Sequence[dict]] = None,
        rotation_seconds: int = 10,
        progress_color: int = 0x00FF00,
        text_color: Optional[int] = None,
    ) -> None:
        """Create the widget and prepare the announcement list."""
        self.rotation_seconds = max(1, int(rotation_seconds))
        self.frame_delay_seconds = 0.05
        self.text_color = _parse_color(text_color)
        self.progress_bar = ProgressBar(width=64, height=1, color=progress_color)
        if self.progress_bar.group is not None:
            self.progress_bar.group.x = 0
            self.progress_bar.group.y = 63

        self._announcements = self._parse_announcements(announcements)
        self._fallback = Announcement("No messages", "* * * * *", None)
        self._active = []
        self._current_index = 0
        self._current = None
        self._start_monotonic = time.monotonic()
        self._last_minute_key = None
        self._group = None
        self._image_player = None
        self._image_group = None
        self._image_error = False
        self._background = None
        self._dirty = True
        self._paused = False

    def _parse_announcements(self, raw: Optional[Sequence[dict]]) -> List[Announcement]:
        """Convert config entries into Announcement objects."""
        items: List[Announcement] = []
        if not raw:
            return items
        for entry in raw:
            try:
                label = entry.get("label", "")
            except Exception:
                label = ""
            try:
                cron = entry.get("cron", "* * * * *")
            except Exception:
                cron = "* * * * *"
            try:
                image = entry.get("image")
            except Exception:
                image = None
            try:
                x_offset = entry.get("x_image_offset", 0)
            except Exception:
                x_offset = 0
            try:
                y_offset = entry.get("y_image_offset", 0)
            except Exception:
                y_offset = 0
            try:
                duration_seconds = entry.get("duration_seconds")
            except Exception:
                duration_seconds = None
            try:
                frame_delay_seconds = entry.get("frame_delay_seconds")
            except Exception:
                frame_delay_seconds = None
            try:
                text_color = entry.get("text_color")
            except Exception:
                text_color = None
            items.append(
                Announcement(
                    label,
                    cron,
                    image,
                    x_offset,
                    y_offset,
                    duration_seconds,
                    frame_delay_seconds,
                    _parse_color(text_color),
                )
            )
        return items

    def handle_button(self, action: str) -> None:
        """Handle widget-specific button events."""
        if action == "click":
            self._advance(force=True)
            print("Announcements widget -> next")
        elif action == "hold":
            self._paused = not self._paused
            print("Announcements widget -> paused:", self._paused)

    def update(self, now_monotonic: float) -> None:
        """Update schedule, rotation timer, GIF animation, and progress bar."""
        now_epoch = _safe_time()
        minute_key = None
        if now_epoch is not None:
            minute_key = int(now_epoch // 60)

        if minute_key != self._last_minute_key:
            self._refresh_active(now_epoch)
            self._last_minute_key = minute_key

        if not self._paused:
            elapsed = now_monotonic - self._start_monotonic
            if elapsed >= self._current_duration_seconds():
                self._advance()

        if self._image_player is not None:
            self._image_player.next_frame(now_monotonic)

        if not self._paused:
            # Progress bar fills over the rotation interval.
            progress = 0.0
            try:
                duration = float(self._current_duration_seconds())
                if duration <= 0:
                    duration = 1.0
                progress = (now_monotonic - self._start_monotonic) / duration
            except Exception:
                progress = 0.0
            self.progress_bar.set_progress(progress)

    def render(self, layout):
        """Build (or update) the display group when needed."""
        if displayio is None or layout is None:
            return None
        if self._image_error:
            return build_error_group(layout)
        if self._group is None or self._dirty:
            self._group = self._build_group(layout)
            self._dirty = False
            return self._group
        return None

    def force_refresh(self) -> None:
        """Force a rebuild of the display group on the next render."""
        self._dirty = True
        self._start_monotonic = time.monotonic()

    def _refresh_active(self, now_epoch: Optional[int]) -> None:
        """Recompute which announcements are active for the current minute."""
        active = []
        tm = None
        if now_epoch is not None:
            try:
                tm = time.localtime(now_epoch)
            except Exception:
                tm = None
        for ann in self._announcements:
            if tm is not None and ann.schedule.matches(tm):
                active.append(ann)
        if not active:
            active = [self._fallback]
        self._active = active
        if self._current not in self._active:
            self._current_index = 0
            self._set_current(self._active[0])

    def _advance(self, force: bool = False) -> None:
        """Advance to the next active announcement."""
        if not self._active:
            self._set_current(self._fallback)
            return
        if not force:
            if (time.monotonic() - self._start_monotonic) < self._current_duration_seconds():
                return
        self._current_index = (self._current_index + 1) % len(self._active)
        self._set_current(self._active[self._current_index])

    def _set_current(self, announcement: Announcement) -> None:
        """Switch the active announcement and reset timers/resources."""
        self._current = announcement
        self._start_monotonic = time.monotonic()
        self._dirty = True
        if self._image_player is not None:
            self._image_player.deinit()
        self._image_player = None
        self._image_group = None
        self._image_error = False
        if announcement and announcement.image:
            self._image_player = SpriteSheetPlayer(
                announcement.image,
                frame_height=64,
                frame_delay=self._frame_delay_seconds(announcement),
            )
            if self._image_player.tilegrid is None:
                self._image_error = True
                print(
                    "Announcement image error:",
                    announcement.image,
                    self._image_player.last_error,
                )
                return
            self._image_player.reset()
            if (
                self._image_player is not None
                and self._image_player.tilegrid is not None
                and displayio is not None
            ):
                # Prebuild image group so GIF frame updates keep the same tilegrid.
                image_group = displayio.Group()
                image_group.append(self._image_player.tilegrid)
                w = self._image_player.frame_width or 0
                h = self._image_player.display_height or 0
                # Center the image, then apply offsets.
                base_x = (64 - w) // 2
                base_y = (64 - h) // 2
                x_offset = 0
                y_offset = 0
                if announcement is not None:
                    x_offset = getattr(announcement, "x_image_offset", 0) or 0
                    y_offset = getattr(announcement, "y_image_offset", 0) or 0
                # Allow negative offsets to pan within oversized images.
                if w >= 64:
                    min_x = 64 - w
                    max_x = 0
                else:
                    min_x = 0
                    max_x = 64 - w
                if h >= 64:
                    min_y = 64 - h
                    max_y = 0
                else:
                    min_y = 0
                    max_y = 64 - h
                pos_x = base_x + x_offset
                pos_y = base_y + y_offset
                if pos_x < min_x:
                    pos_x = min_x
                elif pos_x > max_x:
                    pos_x = max_x
                if pos_y < min_y:
                    pos_y = min_y
                elif pos_y > max_y:
                    pos_y = max_y
                image_group.x = pos_x
                image_group.y = pos_y
                self._image_group = image_group

    def _frame_delay_seconds(self, announcement: Announcement) -> float:
        """Pick the frame delay for the current announcement."""
        try:
            value = getattr(announcement, "frame_delay_seconds", None)
        except Exception:
            value = None
        if value is None:
            return self.frame_delay_seconds
        try:
            return max(0.02, float(value))
        except Exception:
            return self.frame_delay_seconds

    def _resolve_text_color(self) -> Optional[int]:
        """Return the color to use for announcement text."""
        if self._current is not None and self._current.text_color is not None:
            return self._current.text_color
        return self.text_color

    def _current_duration_seconds(self) -> int:
        """Return the duration for the active announcement (fallback to default)."""
        if self._current is not None and self._current.duration_seconds:
            return max(1, int(self._current.duration_seconds))
        return max(1, int(self.rotation_seconds))

    def _build_group(self, layout):
        """Assemble the image, label, and progress bar into a display group."""
        group = self._group if self._group is not None else displayio.Group()
        while len(group):
            group.pop()
        if self._current is None:
            self._set_current(self._fallback)
        if self._background is None:
            try:
                bg_bitmap = displayio.Bitmap(64, 64, 1)
                bg_palette = displayio.Palette(1)
                bg_palette[0] = 0x000000
                self._background = displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette)
            except Exception:
                self._background = None
        if self._background is not None:
            group.append(self._background)
        if self._image_group is not None:
            group.append(self._image_group)

        label_lines = _wrap_label_to_width(
            layout,
            self._current.label if self._current else "",
            max_width=64,
            max_lines=2,
        )
        if label_lines:
            # Center the text within the visible area (leave row 63 for progress).
            line_height = layout.line_spacing
            total_height = line_height * len(label_lines)
            available_height = 63
            start_y = max(0, (available_height - total_height) // 2)
            color = self._resolve_text_color()
            label_group = layout.build_group(
                label_lines,
                x=0,
                y=start_y,
                width=64,
                align="center",
                scale=1,
                color=color,
            )
            group.append(label_group)

        if self.progress_bar.group is not None:
            group.append(self.progress_bar.group)
        return group


def _safe_time() -> Optional[int]:
    """Return epoch time or None if time isn't available."""
    try:
        return int(time.time())
    except Exception:
        return None


def _wrap_label_to_width(
    layout,
    text: str,
    max_width: int = 64,
    max_lines: int = 2,
) -> List[str]:
    """Word-wrap a label based on actual pixel width, not char count."""
    text = (text or "").strip()
    if not text or layout is None:
        return []

    words = [word for word in text.split() if word]
    lines: List[str] = []
    current = ""

    def _fits(candidate: str) -> bool:
        try:
            return layout.measure_lines([candidate]) <= max_width
        except Exception:
            # Fallback: approximate 6px per character.
            return len(candidate) * 6 <= max_width

    def _break_long_word(word: str) -> List[str]:
        """Split a single word that exceeds the width into pieces."""
        pieces: List[str] = []
        piece = ""
        for ch in word:
            candidate = piece + ch
            if _fits(candidate):
                piece = candidate
            else:
                if piece:
                    pieces.append(piece)
                piece = ch
        if piece:
            pieces.append(piece)
        return pieces

    for word in words:
        if current:
            candidate = "{} {}".format(current, word)
        else:
            candidate = word

        if _fits(candidate):
            current = candidate
            continue

        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                break

        # If the word itself is too long, split it across lines.
        if not _fits(word):
            for part in _break_long_word(word):
                if len(lines) >= max_lines:
                    break
                if current:
                    lines.append(current)
                    current = ""
                    if len(lines) >= max_lines:
                        break
                current = part
                if _fits(current):
                    lines.append(current)
                    current = ""
            continue

        current = word
        if len(lines) >= max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _parse_color(value) -> Optional[int]:
    """Parse a color from int or hex string like 0xRRGGBB or #RRGGBB."""
    if value is None:
        return None
    if isinstance(value, int):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("#"):
        text = "0x" + text[1:]
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except Exception:
        return None
