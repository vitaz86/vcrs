from __future__ import annotations

import threading

import pystray
from PIL import Image, ImageDraw


class TrayApp:
    def __init__(self, app_state):
        self.app_state = app_state
        self.icon = pystray.Icon("vcs_automover")
        self._refresh_title()

        self.icon.icon = self._create_icon_image()
        self.icon.menu = pystray.Menu(
            pystray.MenuItem("Open Settings", self._open_settings),
            pystray.MenuItem("View Log", self._open_log),
            pystray.MenuItem(lambda _: "Resume" if self.app_state.paused else "Pause", self._toggle_pause),
            pystray.MenuItem("Exit", self._exit),
        )

    def _create_icon_image(self) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (34, 45, 56, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((12, 12, 52, 52), outline=(120, 220, 255, 255), width=3)
        draw.rectangle((20, 20, 44, 44), fill=(120, 220, 255, 255))
        return img

    def _refresh_title(self) -> None:
        active = len([r for r in self.app_state.rules if r.enabled])
        self.icon.title = f"VCS AutoMover — watching {active} rules"

    def notify_move_event(self) -> None:
        self._refresh_title()

    def _open_settings(self, icon, item) -> None:
        threading.Thread(target=self.app_state.open_settings, daemon=True).start()

    def _open_log(self, icon, item) -> None:
        threading.Thread(target=self.app_state.open_logs, daemon=True).start()

    def _toggle_pause(self, icon, item) -> None:
        if self.app_state.paused:
            self.app_state.resume_watchers()
        else:
            self.app_state.pause_watchers()
        self._refresh_title()

    def _exit(self, icon, item) -> None:
        self.app_state.shutdown()
        self.icon.stop()

    def run(self) -> None:
        self.icon.run()
