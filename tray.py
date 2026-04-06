from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

import pystray
from PIL import Image, ImageDraw


@dataclass(frozen=True)
class TrayCallbacks:
    open_settings: Callable[[], None]
    view_log: Callable[[], None]
    toggle_pause: Callable[[], None]
    exit_app: Callable[[], None]


class TrayApp:
    def __init__(self, logger: logging.Logger, callbacks: TrayCallbacks) -> None:
        self._log = logger
        self._cb = callbacks
        self._icon = pystray.Icon(
            "vcs_automover",
            icon=_generate_icon(),
            title="VCS AutoMover",
            menu=pystray.Menu(
                pystray.MenuItem("Open Settings", lambda: self._safe(self._cb.open_settings)),
                pystray.MenuItem("View Log", lambda: self._safe(self._cb.view_log)),
                pystray.MenuItem(
                    lambda item: "Resume" if item.checked else "Pause",
                    lambda: self._safe(self._cb.toggle_pause),
                    checked=lambda item: False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", lambda: self._safe(self._cb.exit_app)),
            ),
        )
        self._paused = False
        self._rules_watching = 0

        # pystray uses checked state as a function; we update via attribute access.
        pause_item = self._icon.menu.items[2]  # type: ignore[index]
        pause_item.checked = lambda item: self._paused  # type: ignore[assignment]

    def run_detached(self) -> None:
        try:
            self._icon.run_detached()
        except Exception:
            # Fallback: run in background thread.
            threading.Thread(target=self._icon.run, daemon=True).start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._update_title()

    def set_rules_watching(self, n: int) -> None:
        self._rules_watching = max(0, int(n))
        self._update_title()

    def bump_move_event(self) -> None:
        self._update_title()

    def _update_title(self) -> None:
        status = "paused" if self._paused else f"watching {self._rules_watching} rules"
        self._icon.title = f"VCS AutoMover — {status}"

    def _safe(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:
            self._log.exception("tray callback error: %s", e)


def _generate_icon() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), radius=12, fill=(45, 125, 240, 255))
    d.polygon([(20, 22), (44, 32), (20, 42)], fill=(255, 255, 255, 255))
    return img

