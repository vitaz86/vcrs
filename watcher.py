from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import WatcherRule


class RuleState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.moved_files: set[Path] = set()
        self.in_progress: set[Path] = set()


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


class RecordingSubdirHandler(FileSystemEventHandler):
    def __init__(self, manager: "WatcherManager", rule: WatcherRule, source_subdir: Path):
        self.manager = manager
        self.rule = rule
        self.source_subdir = source_subdir

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self.manager.handle_file_candidate(self.rule, Path(event.src_path), self.source_subdir)


class SourceRootHandler(FileSystemEventHandler):
    def __init__(self, manager: "WatcherManager", rule: WatcherRule):
        self.manager = manager
        self.rule = rule

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            return
        self.manager.handle_new_subdir(self.rule, Path(event.src_path))


class WatcherManager:
    def __init__(self, logger: logging.Logger, on_move_callback=None):
        self.logger = logger
        self.on_move_callback = on_move_callback
        self.observers: list[Observer] = []
        self.rule_states: dict[str, RuleState] = {}
        self.paused = False

    def start(self, rules: list[WatcherRule]) -> None:
        self.stop()
        self.paused = False
        active_rules = [rule for rule in rules if rule.enabled]
        for rule in active_rules:
            self._start_rule(rule)
            self._scan_existing_subdirs(rule)

    def stop(self) -> None:
        for observer in self.observers:
            observer.stop()
        for observer in self.observers:
            observer.join(timeout=2)
        self.observers = []

    def pause(self) -> None:
        self.paused = True
        self.stop()

    def resume(self, rules: list[WatcherRule]) -> None:
        self.start(rules)

    def _start_rule(self, rule: WatcherRule) -> None:
        source = Path(rule.source_folder)
        if not source.exists() or not source.is_dir():
            self.logger.warning("Rule=%s source folder not available: %s", rule.name, source)
            return

        self.rule_states[rule.name] = RuleState()
        observer = Observer()
        observer.schedule(SourceRootHandler(self, rule), str(source), recursive=False)
        observer.start()
        self.observers.append(observer)
        self.logger.info("Rule=%s watching source root: %s", rule.name, source)

    def _scan_existing_subdirs(self, rule: WatcherRule) -> None:
        source = Path(rule.source_folder)
        try:
            for child in source.iterdir():
                if child.is_dir():
                    self.handle_new_subdir(rule, child)
        except (PermissionError, FileNotFoundError) as exc:
            self.logger.error("Rule=%s scan error for %s: %s", rule.name, source, exc)

    def handle_new_subdir(self, rule: WatcherRule, source_subdir: Path) -> None:
        if self.paused:
            return
        destination_subdir = Path(rule.destination_folder) / source_subdir.name
        try:
            destination_subdir.mkdir(parents=True, exist_ok=True)
            self.logger.info("Rule=%s folder detected: %s -> %s", rule.name, source_subdir, destination_subdir)
        except (PermissionError, OSError) as exc:
            self.logger.error("Rule=%s cannot create destination dir %s: %s", rule.name, destination_subdir, exc)
            return

        observer = Observer()
        observer.schedule(RecordingSubdirHandler(self, rule, source_subdir), str(source_subdir), recursive=False)
        observer.start()
        self.observers.append(observer)

        try:
            for item in source_subdir.iterdir():
                if item.is_file():
                    self.handle_file_candidate(rule, item, source_subdir)
        except (PermissionError, FileNotFoundError) as exc:
            self.logger.error("Rule=%s cannot read subdir %s: %s", rule.name, source_subdir, exc)

    def handle_file_candidate(self, rule: WatcherRule, file_path: Path, source_subdir: Path) -> None:
        if self.paused or not file_path.exists() or not file_path.is_file():
            return
        if file_path.suffix.lower() not in {ext.lower() for ext in rule.extensions}:
            return

        state = self.rule_states.setdefault(rule.name, RuleState())
        with state.lock:
            if file_path in state.in_progress or file_path in state.moved_files:
                return
            state.in_progress.add(file_path)

        thread = threading.Thread(
            target=self._process_file,
            args=(rule, file_path, source_subdir),
            daemon=True,
        )
        thread.start()

    def _process_file(self, rule: WatcherRule, file_path: Path, source_subdir: Path) -> None:
        state = self.rule_states.setdefault(rule.name, RuleState())
        try:
            self.logger.info("Rule=%s file detected: %s", rule.name, file_path)
            stable = wait_until_stable(str(file_path))
            if not stable:
                self.logger.warning("Rule=%s stability timeout: %s", rule.name, file_path)
                return
            self.logger.info("Rule=%s file stable: %s", rule.name, file_path)

            destination = Path(rule.destination_folder) / source_subdir.name / file_path.name
            if self._move_with_retry(rule, file_path, destination):
                with state.lock:
                    state.moved_files.add(file_path)
                if self.on_move_callback:
                    self.on_move_callback()
                self.logger.info("Rule=%s file moved: %s -> %s", rule.name, file_path, destination)
                self._schedule_delete_if_done(rule, source_subdir)
        finally:
            with state.lock:
                state.in_progress.discard(file_path)

    def _move_with_retry(self, rule: WatcherRule, src: Path, dst: Path) -> bool:
        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                return True
            except (PermissionError, FileNotFoundError, shutil.Error, OSError) as exc:
                self.logger.warning("Rule=%s move retry for %s -> %s: %s", rule.name, src, dst, exc)
                time.sleep(30)
        self.logger.error("Rule=%s move failed after retries: %s -> %s", rule.name, src, dst)
        return False

    def _schedule_delete_if_done(self, rule: WatcherRule, source_subdir: Path) -> None:
        if not rule.delete_source_folder:
            return
        thread = threading.Thread(target=self._delete_if_done_worker, args=(rule, source_subdir), daemon=True)
        thread.start()

    def _delete_if_done_worker(self, rule: WatcherRule, source_subdir: Path) -> None:
        try:
            pending = [
                p for p in source_subdir.iterdir() if p.is_file() and p.suffix.lower() in {ext.lower() for ext in rule.extensions}
            ]
            if pending:
                return
            time.sleep(rule.delete_delay_seconds)
            pending_after = [
                p for p in source_subdir.iterdir() if p.is_file() and p.suffix.lower() in {ext.lower() for ext in rule.extensions}
            ]
            if pending_after:
                return
            shutil.rmtree(source_subdir)
            self.logger.info("Rule=%s folder deleted: %s", rule.name, source_subdir)
        except (PermissionError, FileNotFoundError, shutil.Error, OSError) as exc:
            self.logger.error("Rule=%s folder delete failed: %s (%s)", rule.name, source_subdir, exc)
