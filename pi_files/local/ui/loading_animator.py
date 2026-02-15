import time
try:
    from typing import Optional, Sequence
except ImportError:
    from local.typing_compat import Optional, Sequence

from local.ui.display_helpers import build_loading_group


class LoadingAnimator:
    """Loading animation state helper (no display side effects)."""

    def __init__(
        self,
        frames: Optional[Sequence[str]] = None,
        interval: float = 0.25,
    ) -> None:
        self.frames = tuple(frames) if frames else ("|", "/", "-", "\\")
        self.interval = interval
        self.index = 0
        self.last = 0.0

    def next_group(self, layout):
        """Return the next loading group when it's time, or None if not."""
        if not layout:
            return None
        now = time.monotonic()
        if now - self.last < self.interval and self.last > 0:
            return None
        group = build_loading_group(layout, self.frames[self.index])
        self.index = (self.index + 1) % len(self.frames)
        self.last = now
        return group
