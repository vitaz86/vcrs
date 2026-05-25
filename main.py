from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from config import LOG_DIR, WatcherRule, get_rules, load_config
from i18n import tr
from tray import TrayApp
from ui import LogViewerWindow, SettingsWindow
from watcher import WatcherManager


class AppState:
    def __init__(self) -> None:
        self.config = load_config()
        self.rules = get_rules(self.config)
        self.paused = False
        self.language = self.config.get("language", "en")

        self.logger = self._setup_logger()
        self.watcher_manager = WatcherManager(
            self.logger,
            zoom_conversion_timeout_seconds=int(self.config.get("zoom_conversion_timeout_seconds", 1200)),
            on_move_callback=self._on_move_event,
        )
        self.tray = TrayApp(self)

    def t(self, key: str) -> str:
        return tr(self.language, key)

    def set_language(self, language: str) -> None:
        self.language = language if language in {"en", "ru"} else "en"
        self.config["language"] = self.language
        self.tray.notify_move_event()

    def _setup_logger(self) -> logging.Logger:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("vcs_automover")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        log_file = LOG_DIR / f"log_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s UTC | %(levelname)s | %(message)s", "%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def start_watchers(self) -> None:
        self.watcher_manager.start(self.rules)

    def apply_config(self, config: dict) -> None:
        self.config = config
        self.rules = get_rules(self.config)
        self.watcher_manager.zoom_conversion_timeout_seconds = int(self.config.get("zoom_conversion_timeout_seconds", 1200))
        self.start_watchers()
        self.tray.notify_move_event()

    def restart_watchers(self, rules: list[WatcherRule]) -> None:
        self.rules = rules
        self.start_watchers()
        self.tray.notify_move_event()

    def pause_watchers(self) -> None:
        self.paused = True
        self.watcher_manager.pause()
        self.logger.info("All watchers paused")

    def resume_watchers(self) -> None:
        self.paused = False
        self.watcher_manager.resume(self.rules)
        self.logger.info("All watchers resumed")

    def open_settings(self) -> None:
        SettingsWindow(self).run()

    def open_logs(self) -> None:
        LogViewerWindow(self).run()

    def _on_move_event(self) -> None:
        self.tray.notify_move_event()

    def shutdown(self) -> None:
        self.watcher_manager.stop()
        self.logger.info("Application exiting")


def main() -> None:
    app = AppState()
    app.start_watchers()
    app.tray.run()


if __name__ == "__main__":
    main()
