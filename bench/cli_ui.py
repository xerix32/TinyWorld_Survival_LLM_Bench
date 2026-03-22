"""Terminal UI helpers for CLI status/progress output."""

from __future__ import annotations

import os
import re
import sys


def use_color(disable_color: bool = False) -> bool:
    if disable_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def colorize(text: str, ansi_code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\x1b[{ansi_code}m{text}\x1b[0m"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "--"

    total_seconds = max(0, int(round(seconds)))
    if total_seconds < 60:
        return f"{total_seconds} sec"

    minutes, secs = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes} min {secs} sec"

    hours, mins = divmod(minutes, 60)
    return f"{hours} hour {mins} min {secs} sec"


class StatusLine:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._active = False
        self._last_visible_len = 0

    @staticmethod
    def _visible_len(text: str) -> int:
        # Strip ANSI color codes so padding works correctly.
        stripped = re.sub(r"\x1b\[[0-9;]*m", "", text)
        return len(stripped)

    def write(self, text: str) -> None:
        if self.enabled:
            visible_len = self._visible_len(text)
            pad = max(0, self._last_visible_len - visible_len)
            sys.stdout.write("\r" + text + (" " * pad))
            sys.stdout.flush()
            self._active = True
            self._last_visible_len = visible_len
            return
        print(text)

    def finish(self, text: str | None = None) -> None:
        if self.enabled:
            if text is not None:
                visible_len = self._visible_len(text)
                pad = max(0, self._last_visible_len - visible_len)
                sys.stdout.write("\r" + text + (" " * pad))
            elif self._last_visible_len > 0:
                sys.stdout.write("\r" + (" " * self._last_visible_len))
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._active = False
            self._last_visible_len = 0
            return
        if text is not None:
            print(text)

    def clear(self) -> None:
        if self.enabled and self._active:
            width = max(self._last_visible_len, 1)
            sys.stdout.write("\r" + (" " * width) + "\r")
            sys.stdout.flush()
            self._active = False
            self._last_visible_len = 0
