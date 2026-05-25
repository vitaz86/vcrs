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
            pystray.MenuItem(lambda _: self.app_state.t("open_settings"), self._open_settings),
            pystray.MenuItem(lambda _: self.app_state.t("view_log"), self._open_log),
            pystray.MenuItem(lambda _: self.app_state.t("resume") if self.app_state.paused else self.app_state.t("pause"), self._toggle_pause),
            pystray.MenuItem(lambda _: self.app_state.t("exit"), self._exit),
        )

    def _create_icon_image(self) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (34, 45, 56, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((12, 12, 52, 52), outline=(120, 220, 255, 255), width=3)
        draw.rectangle((20, 20, 44, 44), fill=(120, 220, 255, 255))
        return img

    def _refresh_title(self) -> None:
        active = len([r for r in self.app_state.rules if r.enabled])
        self.icon.title = self.app_state.t("watching_rules").format(count=active)

    def notify_move_event(self) -> None:
        self._refresh_title()
        self.icon.update_menu()

    def _open_settings(self, icon, item) -> None:
        threading.Thread(target=self.app_state.open_settings, daemon=True).start()

    def _open_log(self, icon, item) -> None:
        threading.Thread(target=self.app_state.open_logs, daemon=True).start()

    def _toggle_pause(self, icon, item) -> None:
        if self.app_state.paused:
            self.app_state.resume_watchers()
        else:
            self.app_state.pause_watchers()
        self.notify_move_event()

    def _exit(self, icon, item) -> None:
        self.app_state.shutdown()
        self.icon.stop()

    def run(self) -> None:
        self.icon.run()
