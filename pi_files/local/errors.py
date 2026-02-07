try:
    from typing import List, Optional, Sequence
except ImportError:
    from local.typing_compat import List, Optional, Sequence


class DisplayError(Exception):
    """Error that should be surfaced on the LED matrix."""

    def __init__(self, message: str, lines: Optional[Sequence[str]] = None) -> None:
        super().__init__(message)
        if lines:
            self.lines = list(lines)
        else:
            self.lines = _wrap_message(message)


def _wrap_message(message: str, max_len: int = 16, max_lines: int = 2) -> List[str]:
    words = [word for word in (message or "").split() if word]
    if not words:
        return ["Error"]

    lines: List[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        if len(current) + 1 + len(word) <= max_len:
            current = "{} {}".format(current, word)
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break

    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        return [message[:max_len]]
    return lines
