from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import tkinter as tk

from config import AppConfig, WatcherRule, get_app_paths, load_config, save_config, set_startup_enabled
from tray import TrayApp, TrayCallbacks
from ui import LogViewerWindow, SettingsWindow, UiCallbacks
from watcher import WatchManager


APP_NAME = "vcs_automover"


class DailyFileHandler(logging.Handler):
    def __init__(self, logs_dir: Path) -> None:
        super().__init__()
        self._logs_dir = logs_dir
        self._current_date: str | None = None
        self._fh: logging.FileHandler | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
            if date_str != self._current_date:
                self._switch(date_str)
            if self._fh:
                self._fh.emit(record)
        except Exception:
            return

    def _switch(self, date_str: str) -> None:
        path = self._logs_dir / f"log_{date_str}.txt"
        new_fh = logging.FileHandler(path, encoding="utf-8")
        new_fh.setFormatter(self.formatter)

        old = self._fh
        self._fh = new_fh
        self._current_date = date_str

        if old:
            try:
                old.close()
            except Exception:
                pass

    def close(self) -> None:
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
        super().close()


def get_today_log_file(logs_dir: Path) -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return logs_dir / f"log_{date_str}.txt"


def setup_logging(logs_dir: Path) -> logging.Logger:
    logger = logging.getLogger("vcs_automover")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    fmt.converter = time.gmtime  # UTC timestamps

    daily = DailyFileHandler(logs_dir)
    daily.setFormatter(fmt)
    logger.addHandler(daily)

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(fmt)
    logger.addHandler(stderr)

    return logger


def main() -> None:
    paths = get_app_paths()
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(paths.logs_dir)
    logger.info("app start; config: %s", paths.config_path)

    root = tk.Tk()
    root.withdraw()

    cfg: AppConfig = load_config(paths)
    rules: list[WatcherRule] = list(cfg.get("rules") or [])

    tray_app: TrayApp | None = None

    def on_move_event() -> None:
        if tray_app:
            tray_app.bump_move_event()

    manager = WatchManager(logger, on_move_event=on_move_event)
    manager.start(rules)

    def restart_watchers(new_rules: list[WatcherRule]) -> None:
        nonlocal rules
        rules = list(new_rules)
        if manager.is_paused():
            return
        manager.start(rules)
        if tray_app:
            tray_app.set_rules_watching(WatchManager.active_rule_count(rules))

    def apply_startup(enabled: bool) -> None:
        try:
            set_startup_enabled(APP_NAME, enabled)
            logger.info("startup %s", "enabled" if enabled else "disabled")
        except Exception as e:
            logger.error("startup change failed: %s", e)

    def save_cfg(new_cfg: AppConfig) -> None:
        save_config(paths, new_cfg)
        logger.info("config saved")

    def load_cfg() -> AppConfig:
        return load_config(paths)

    ui_cb = UiCallbacks(
        load_config=load_cfg,
        save_config=save_cfg,
        apply_startup=apply_startup,
        restart_watchers=restart_watchers,
        current_log_file=lambda: get_today_log_file(paths.logs_dir),
    )

    settings_win = SettingsWindow(root, logger, ui_cb)
    log_win = LogViewerWindow(root, logger, ui_cb)

    def open_settings() -> None:
        root.after(0, settings_win.show)

    def view_log() -> None:
        root.after(0, log_win.show)

    def toggle_pause() -> None:
        if manager.is_paused():
            manager.resume(rules)
            if tray_app:
                tray_app.set_paused(False)
                tray_app.set_rules_watching(WatchManager.active_rule_count(rules))
        else:
            manager.pause()
            if tray_app:
                tray_app.set_paused(True)

    def exit_app() -> None:
        logger.info("exit requested")
        try:
            manager.stop()
        except Exception:
            pass
        if tray_app:
            tray_app.stop()
        root.after(0, root.quit)

    tray_app = TrayApp(
        logger,
        TrayCallbacks(
            open_settings=open_settings,
            view_log=view_log,
            toggle_pause=toggle_pause,
            exit_app=exit_app,
        ),
    )
    tray_app.set_rules_watching(WatchManager.active_rule_count(rules))
    tray_app.set_paused(manager.is_paused())
    tray_app.run_detached()

    root.mainloop()


if __name__ == "__main__":
    main()

