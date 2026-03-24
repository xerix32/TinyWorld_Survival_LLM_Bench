"""Terminal UI helpers for CLI status/progress output."""

from __future__ import annotations

import os
import re
import shutil
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

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def _fit_to_terminal(self, text: str) -> str:
        cleaned = text.replace("\n", " ").replace("\r", " ")
        try:
            columns = shutil.get_terminal_size(fallback=(160, 24)).columns
        except OSError:
            columns = 160
        if columns <= 1:
            return cleaned
        max_visible = max(20, columns - 1)
        visible_len = self._visible_len(cleaned)
        if visible_len <= max_visible:
            return cleaned

        # Keep output single-line and avoid terminal wrapping artifacts.
        plain = self._strip_ansi(cleaned)
        if max_visible <= 1:
            return plain[:max_visible]
        return plain[: max_visible - 1] + "…"

    def write(self, text: str) -> None:
        if self.enabled:
            fitted = self._fit_to_terminal(text)
            visible_len = self._visible_len(fitted)
            pad = max(0, self._last_visible_len - visible_len)
            sys.stdout.write("\r" + fitted + (" " * pad))
            sys.stdout.flush()
            self._active = True
            self._last_visible_len = visible_len
            return
        print(text)

    def finish(self, text: str | None = None) -> None:
        if self.enabled:
            if text is not None:
                fitted = self._fit_to_terminal(text)
                visible_len = self._visible_len(fitted)
                pad = max(0, self._last_visible_len - visible_len)
                sys.stdout.write("\r" + fitted + (" " * pad))
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
