from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, DirCreatedEvent
from watchdog.observers import Observer

from config import WatcherRule


def wait_until_stable(path: str, poll_interval: int = 5, timeout: int = 1800) -> bool:
    elapsed = 0
    while elapsed < timeout:
        try:
            with open(path, "rb"):
                return True
        except (PermissionError, OSError):
            time.sleep(poll_interval)
            elapsed += poll_interval
    return False


def _iter_matching_files(folder: Path, extensions: set[str]) -> Iterable[Path]:
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in extensions:
                yield p
    except FileNotFoundError:
        return


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SubdirContext:
    rule_name: str
    source_subdir: Path
    dest_subdir: Path
    extensions: set[str]
    delete_source_folder: bool
    delete_delay_seconds: int


class _SubdirHandler(FileSystemEventHandler):
    def __init__(self, ctx: SubdirContext, logger: logging.Logger, on_move_event: Callable[[], None]) -> None:
        self._ctx = ctx
        self._log = logger
        self._on_move_event = on_move_event
        self._lock = threading.Lock()
        self._deletion_scheduled = False

    def on_created(self, event):  # type: ignore[override]
        if getattr(event, "is_directory", False):
            return
        if not isinstance(event, FileCreatedEvent):
            return
        p = Path(event.src_path)
        if p.suffix.lower() not in self._ctx.extensions:
            return
        self._log.info("[%s] file detected: %s", self._ctx.rule_name, p)
        threading.Thread(target=self._process_file, args=(p,), daemon=True).start()

    def initial_scan(self) -> None:
        for p in _iter_matching_files(self._ctx.source_subdir, self._ctx.extensions):
            self._log.info("[%s] existing file found: %s", self._ctx.rule_name, p)
            threading.Thread(target=self._process_file, args=(p,), daemon=True).start()

    def _process_file(self, src_file: Path) -> None:
        try:
            if not wait_until_stable(str(src_file), poll_interval=5, timeout=1800):
                self._log.warning("[%s] file not stable (timeout): %s", self._ctx.rule_name, src_file)
                return
            self._log.info("[%s] file stable: %s", self._ctx.rule_name, src_file)

            dst_file = self._ctx.dest_subdir / src_file.name
            _safe_mkdir(self._ctx.dest_subdir)

            if not _move_with_retry(src_file, dst_file, self._log, self._ctx.rule_name):
                return

            self._on_move_event()
            self._maybe_schedule_delete()
        except FileNotFoundError:
            self._log.warning("[%s] file disappeared before move: %s", self._ctx.rule_name, src_file)
        except Exception as e:
            self._log.exception("[%s] unexpected error processing %s: %s", self._ctx.rule_name, src_file, e)

    def _maybe_schedule_delete(self) -> None:
        if not self._ctx.delete_source_folder:
            return
        with self._lock:
            if self._deletion_scheduled:
                return
            remaining = list(_iter_matching_files(self._ctx.source_subdir, self._ctx.extensions))
            if remaining:
                return
            self._deletion_scheduled = True
        threading.Thread(target=self._delete_after_delay, daemon=True).start()

    def _delete_after_delay(self) -> None:
        time.sleep(max(0, int(self._ctx.delete_delay_seconds)))
        try:
            # Re-check after delay.
            remaining = list(_iter_matching_files(self._ctx.source_subdir, self._ctx.extensions))
            if remaining:
                with self._lock:
                    self._deletion_scheduled = False
                self._log.info("[%s] delete skipped (new files appeared): %s", self._ctx.rule_name, self._ctx.source_subdir)
                return
            shutil.rmtree(self._ctx.source_subdir)
            self._log.info("[%s] source subdirectory deleted: %s", self._ctx.rule_name, self._ctx.source_subdir)
        except FileNotFoundError:
            self._log.info("[%s] source subdirectory already gone: %s", self._ctx.rule_name, self._ctx.source_subdir)
        except PermissionError as e:
            with self._lock:
                self._deletion_scheduled = False
            self._log.error("[%s] cannot delete source subdirectory %s: %s", self._ctx.rule_name, self._ctx.source_subdir, e)
        except OSError as e:
            with self._lock:
                self._deletion_scheduled = False
            self._log.error("[%s] error deleting source subdirectory %s: %s", self._ctx.rule_name, self._ctx.source_subdir, e)


def _move_with_retry(src: Path, dst: Path, logger: logging.Logger, rule_name: str) -> bool:
    started = time.time()
    while True:
        try:
            shutil.move(str(src), str(dst))
            logger.info("[%s] file moved: %s -> %s", rule_name, src, dst)
            return True
        except FileNotFoundError:
            logger.warning("[%s] move failed (missing): %s", rule_name, src)
            return False
        except (PermissionError, shutil.Error, OSError) as e:
            elapsed = time.time() - started
            if elapsed >= 600:
                logger.error("[%s] move failed (timeout after 10 min): %s (%s)", rule_name, src, e)
                return False
            logger.warning("[%s] move failed, retrying in 30s: %s (%s)", rule_name, src, e)
            time.sleep(30)


class _SourceHandler(FileSystemEventHandler):
    def __init__(
        self,
        rule: WatcherRule,
        logger: logging.Logger,
        attach_subdir: Callable[[WatcherRule, Path], None],
    ) -> None:
        self._rule = rule
        self._log = logger
        self._attach_subdir = attach_subdir

    def on_created(self, event):  # type: ignore[override]
        if not getattr(event, "is_directory", False):
            return
        if not isinstance(event, DirCreatedEvent):
            return
        subdir = Path(event.src_path)
        self._log.info("[%s] subdirectory detected: %s", self._rule["name"], subdir)
        self._attach_subdir(self._rule, subdir)


class WatchManager:
    def __init__(self, logger: logging.Logger, on_move_event: Callable[[], None] | None = None) -> None:
        self._log = logger
        self._on_move_event = on_move_event or (lambda: None)
        self._lock = threading.Lock()
        self._observers: list[Observer] = []
        self._paused = False

    def start(self, rules: list[WatcherRule]) -> None:
        with self._lock:
            self.stop()
            self._paused = False
            for rule in rules:
                if not rule.get("enabled", True):
                    continue
                self._start_rule(rule)
            self._log.info("watchers started: %d rules", self.active_rule_count(rules))

    def stop(self) -> None:
        for obs in self._observers:
            try:
                obs.stop()
            except Exception:
                pass
        for obs in self._observers:
            try:
                obs.join(timeout=5)
            except Exception:
                pass
        self._observers = []

    def pause(self) -> None:
        with self._lock:
            if self._paused:
                return
            self._paused = True
            self.stop()
            self._log.info("watchers paused")

    def resume(self, rules: list[WatcherRule]) -> None:
        with self._lock:
            if not self._paused:
                return
            self._paused = False
            for rule in rules:
                if not rule.get("enabled", True):
                    continue
                self._start_rule(rule)
            self._log.info("watchers resumed")

    def is_paused(self) -> bool:
        return self._paused

    @staticmethod
    def active_rule_count(rules: list[WatcherRule]) -> int:
        return sum(1 for r in rules if r.get("enabled", True))

    def _start_rule(self, rule: WatcherRule) -> None:
        src = Path(rule["source_folder"])
        if not src.exists():
            self._log.warning("[%s] source folder does not exist: %s", rule["name"], src)
            return
        extensions = {e.lower() for e in rule.get("extensions", [])}
        if not extensions:
            self._log.warning("[%s] no extensions configured; skipping", rule["name"])
            return

        handler = _SourceHandler(rule, self._log, self._attach_subdir)
        obs = Observer()
        obs.schedule(handler, str(src), recursive=False)
        try:
            obs.daemon = True
        except Exception:
            pass
        obs.start()
        self._observers.append(obs)

        # Startup scan: attach existing subdirectories with unprocessed files.
        try:
            for p in src.iterdir():
                if p.is_dir():
                    if any(_iter_matching_files(p, extensions)):
                        self._log.info("[%s] existing subdirectory with files: %s", rule["name"], p)
                        self._attach_subdir(rule, p)
        except PermissionError as e:
            self._log.error("[%s] cannot scan source folder %s: %s", rule["name"], src, e)
        except FileNotFoundError:
            return

    def _attach_subdir(self, rule: WatcherRule, source_subdir: Path) -> None:
        try:
            if not source_subdir.exists() or not source_subdir.is_dir():
                return

            src_root = Path(rule["source_folder"]).resolve()
            try:
                rel = source_subdir.resolve().relative_to(src_root)
            except Exception:
                rel = Path(source_subdir.name)

            dest_root = Path(rule["destination_folder"])
            dest_subdir = dest_root / rel
            _safe_mkdir(dest_subdir)
            self._log.info("[%s] destination subdirectory ensured: %s", rule["name"], dest_subdir)

            ctx = SubdirContext(
                rule_name=rule["name"],
                source_subdir=source_subdir,
                dest_subdir=dest_subdir,
                extensions={e.lower() for e in rule.get("extensions", [])},
                delete_source_folder=bool(rule.get("delete_source_folder", True)),
                delete_delay_seconds=int(rule.get("delete_delay_seconds", 60) or 60),
            )
            sub_handler = _SubdirHandler(ctx, self._log, self._on_move_event)
            sub_obs = Observer()
            sub_obs.schedule(sub_handler, str(source_subdir), recursive=False)
            try:
                sub_obs.daemon = True
            except Exception:
                pass
            sub_obs.start()
            self._observers.append(sub_obs)

            # Initial scan for already-present files.
            sub_handler.initial_scan()
        except PermissionError as e:
            self._log.error("[%s] permission error attaching %s: %s", rule["name"], source_subdir, e)
        except FileNotFoundError:
            return
        except Exception as e:
            self._log.exception("[%s] unexpected error attaching %s: %s", rule["name"], source_subdir, e)

