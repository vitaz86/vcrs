from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import S3_UPLOAD_ROOT, TRANSFER_TARGET_FOLDER, TRANSFER_TARGET_S3, WatcherRule


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
    def __init__(self, logger: logging.Logger, zoom_conversion_timeout_seconds: int = 1200, on_move_callback=None):
        self.logger = logger
        self.zoom_conversion_timeout_seconds = zoom_conversion_timeout_seconds
        self.on_move_callback = on_move_callback
        self.observers: list[Observer] = []
        self.rule_states: dict[str, RuleState] = {}
        self.paused = False
        self.rules: list[WatcherRule] = []
        self.health_thread: threading.Thread | None = None
        self._stop_health = threading.Event()

    def start(self, rules: list[WatcherRule]) -> None:
        self.stop()
        self.paused = False
        self.rules = rules
        for rule in [r for r in rules if r.enabled]:
            self._start_rule(rule)
            self._scan_existing_subdirs(rule)
        self._start_health_monitor()

    def stop(self) -> None:
        self._stop_health.set()
        if self.health_thread and self.health_thread.is_alive():
            self.health_thread.join(timeout=2)
        self.health_thread = None
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

    def _start_health_monitor(self) -> None:
        self._stop_health.clear()
        self.health_thread = threading.Thread(target=self._health_worker, daemon=True)
        self.health_thread.start()

    def _health_worker(self) -> None:
        while not self._stop_health.wait(60):
            if self.paused:
                continue
            dead = [obs for obs in self.observers if not obs.is_alive()]
            if dead:
                self.logger.warning("Observer health check detected %s dead observers, restarting", len(dead))
                self.start(self.rules)
                return

    def _start_rule(self, rule: WatcherRule) -> None:
        source = Path(rule.source_folder)
        if not source.exists() or not source.is_dir():
            self.logger.warning("Rule=%s source folder not available: %s", rule.name, source)
            return
        if not self._is_transfer_config_valid(rule):
            return
        self.rule_states[rule.name] = RuleState()
        observer = Observer()
        observer.schedule(SourceRootHandler(self, rule), str(source), recursive=False)
        observer.start()
        self.observers.append(observer)
        self.logger.info("Rule=%s watching source root: %s", rule.name, source)

    def _scan_existing_subdirs(self, rule: WatcherRule) -> None:
        try:
            for child in Path(rule.source_folder).iterdir():
                if child.is_dir():
                    self.handle_new_subdir(rule, child)
        except (PermissionError, FileNotFoundError) as exc:
            self.logger.error("Rule=%s scan error: %s", rule.name, exc)

    def handle_new_subdir(self, rule: WatcherRule, source_subdir: Path) -> None:
        if self.paused:
            return
        if rule.transfer_target == TRANSFER_TARGET_S3:
            self.logger.info(
                "Rule=%s folder detected for S3 upload: %s -> s3://%s/%s/%s/",
                rule.name,
                source_subdir,
                rule.s3_bucket_name,
                S3_UPLOAD_ROOT,
                source_subdir.name,
            )
        else:
            dst_subdir = Path(rule.destination_folder) / source_subdir.name
            try:
                dst_subdir.mkdir(parents=True, exist_ok=True)
                self.logger.info("Rule=%s folder detected: %s -> %s", rule.name, source_subdir, dst_subdir)
            except (PermissionError, OSError) as exc:
                self.logger.error("Rule=%s cannot create destination dir %s: %s", rule.name, dst_subdir, exc)
                return

        observer = Observer()
        observer.schedule(RecordingSubdirHandler(self, rule, source_subdir), str(source_subdir), recursive=False)
        observer.start()
        self.observers.append(observer)

        self._schedule_zoom_conversion_if_needed(rule, source_subdir)
        try:
            for item in source_subdir.iterdir():
                if item.is_file():
                    self.handle_file_candidate(rule, item, source_subdir)
        except (PermissionError, FileNotFoundError) as exc:
            self.logger.error("Rule=%s cannot read subdir %s: %s", rule.name, source_subdir, exc)

    def _schedule_zoom_conversion_if_needed(self, rule: WatcherRule, source_subdir: Path) -> None:
        if rule.move_mode != "wait_for_stable":
            return
        threading.Thread(target=self._zoom_conversion_worker, args=(rule, source_subdir), daemon=True).start()

    def _zoom_conversion_worker(self, rule: WatcherRule, source_subdir: Path) -> None:
        time.sleep(self.zoom_conversion_timeout_seconds)
        if not source_subdir.exists():
            return
        zoom_files = sorted(source_subdir.glob("*.zoom"))
        output_files = [p for p in source_subdir.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".m4a"}]
        if not zoom_files or output_files:
            return
        launcher = source_subdir / "double_click_to_convert_01.zoom"
        target = launcher if launcher.exists() else zoom_files[0]
        try:
            self._open_file(target)
            self.logger.info("Rule=%s forced zoom conversion launch: %s", rule.name, target)
        except (OSError, subprocess.SubprocessError) as exc:
            self.logger.error("Rule=%s failed to launch zoom conversion file %s: %s", rule.name, target, exc)

    def _open_file(self, path: Path) -> None:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True)
        else:
            subprocess.run(["xdg-open", str(path)], check=True)

    def handle_file_candidate(self, rule: WatcherRule, file_path: Path, source_subdir: Path) -> None:
        if self.paused or not file_path.exists() or not file_path.is_file():
            return
        if file_path.suffix.lower() not in {e.lower() for e in rule.extensions}:
            return
        state = self.rule_states.setdefault(rule.name, RuleState())
        with state.lock:
            if file_path in state.in_progress or file_path in state.moved_files:
                return
            state.in_progress.add(file_path)
        threading.Thread(target=self._process_file, args=(rule, file_path, source_subdir), daemon=True).start()

    def _process_file(self, rule: WatcherRule, file_path: Path, source_subdir: Path) -> None:
        state = self.rule_states.setdefault(rule.name, RuleState())
        try:
            self.logger.info("Rule=%s file detected: %s", rule.name, file_path)
            if not wait_until_stable(str(file_path)):
                self.logger.warning("Rule=%s stability timeout: %s", rule.name, file_path)
                return
            self.logger.info("Rule=%s file stable: %s", rule.name, file_path)
            if self._transfer_with_retry(rule, file_path, source_subdir):
                with state.lock:
                    state.moved_files.add(file_path)
                if self.on_move_callback:
                    self.on_move_callback()
                self._schedule_delete_if_done(rule, source_subdir)
        finally:
            with state.lock:
                state.in_progress.discard(file_path)

    def _is_transfer_config_valid(self, rule: WatcherRule) -> bool:
        if rule.transfer_target == TRANSFER_TARGET_FOLDER:
            if not rule.destination_folder.strip():
                self.logger.error("Rule=%s folder transfer requires a destination folder", rule.name)
                return False
            return True

        if rule.transfer_target != TRANSFER_TARGET_S3:
            self.logger.error("Rule=%s unsupported transfer target: %s", rule.name, rule.transfer_target)
            return False

        errors = []
        parsed_endpoint = urlparse(rule.s3_endpoint_url)
        if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
            errors.append("server address must be a full http(s) URL")
        if not rule.s3_bucket_name:
            errors.append("bucket name is required")
        if not rule.s3_access_key:
            errors.append("access key is required")
        if not rule.s3_secret_key:
            errors.append("secret key is required")

        if errors:
            self.logger.error("Rule=%s invalid S3 settings: %s", rule.name, "; ".join(errors))
            return False
        return True

    def _transfer_with_retry(self, rule: WatcherRule, src: Path, source_subdir: Path) -> bool:
        if rule.transfer_target == TRANSFER_TARGET_S3:
            key = self._build_s3_key(source_subdir, src)
            if self._upload_to_s3_with_retry(rule, src, key):
                self.logger.info("Rule=%s file uploaded: %s -> s3://%s/%s", rule.name, src, rule.s3_bucket_name, key)
                return True
            return False

        dst = Path(rule.destination_folder) / source_subdir.name / src.name
        if self._move_with_retry(rule, src, dst):
            self.logger.info("Rule=%s file moved: %s -> %s", rule.name, src, dst)
            return True
        return False

    def _build_s3_key(self, source_subdir: Path, file_path: Path) -> str:
        return f"{S3_UPLOAD_ROOT}/{source_subdir.name}/{file_path.name}"

    def _upload_to_s3_with_retry(self, rule: WatcherRule, src: Path, key: str) -> bool:
        if not self._is_transfer_config_valid(rule):
            return False
        client = self._create_s3_client(rule)
        if client is None:
            return False

        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                client.upload_file(str(src), rule.s3_bucket_name, key)
                return self._remove_uploaded_source_with_retry(rule, src)
            except Exception as exc:
                if self._is_permanent_s3_error(exc):
                    self.logger.error(
                        "Rule=%s permanent S3 upload error for s3://%s/%s: %s",
                        rule.name,
                        rule.s3_bucket_name,
                        key,
                        exc,
                    )
                    return False
                self.logger.warning(
                    "Rule=%s S3 upload retry for %s -> s3://%s/%s: %s",
                    rule.name,
                    src,
                    rule.s3_bucket_name,
                    key,
                    exc,
                )
                time.sleep(30)
        self.logger.error("Rule=%s S3 upload failed after retries: %s -> s3://%s/%s", rule.name, src, rule.s3_bucket_name, key)
        return False

    def _remove_uploaded_source_with_retry(self, rule: WatcherRule, src: Path) -> bool:
        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                src.unlink()
                return True
            except FileNotFoundError:
                return True
            except OSError as exc:
                self.logger.warning("Rule=%s source delete retry after S3 upload for %s: %s", rule.name, src, exc)
                time.sleep(30)
        self.logger.error("Rule=%s source delete failed after S3 upload: %s", rule.name, src)
        return False

    def _is_permanent_s3_error(self, exc: Exception) -> bool:
        response = getattr(exc, "response", {})
        code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
        return code in {
            "AccessDenied",
            "AuthorizationHeaderMalformed",
            "InvalidAccessKeyId",
            "InvalidBucketName",
            "NoSuchBucket",
            "SignatureDoesNotMatch",
        }

    def _create_s3_client(self, rule: WatcherRule):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            self.logger.error("Rule=%s cannot upload to S3 because boto3 is not installed: %s", rule.name, exc)
            return None

        try:
            return boto3.client(
                "s3",
                endpoint_url=rule.s3_endpoint_url,
                aws_access_key_id=rule.s3_access_key,
                aws_secret_access_key=rule.s3_secret_key,
                region_name=rule.s3_region,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        except Exception as exc:
            self.logger.error("Rule=%s cannot create S3 client: %s", rule.name, exc)
            return None

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
        if rule.delete_source_folder:
            threading.Thread(target=self._delete_if_done_worker, args=(rule, source_subdir), daemon=True).start()

    def _delete_if_done_worker(self, rule: WatcherRule, source_subdir: Path) -> None:
        try:
            exts = {e.lower() for e in rule.extensions}
            pending = [p for p in source_subdir.iterdir() if p.is_file() and p.suffix.lower() in exts]
            if pending:
                return
            time.sleep(rule.delete_delay_seconds)
            pending_after = [p for p in source_subdir.iterdir() if p.is_file() and p.suffix.lower() in exts]
            if pending_after:
                return
            shutil.rmtree(source_subdir)
            self.logger.info("Rule=%s folder deleted: %s", rule.name, source_subdir)
        except (PermissionError, FileNotFoundError, shutil.Error, OSError) as exc:
            self.logger.error("Rule=%s folder delete failed: %s (%s)", rule.name, source_subdir, exc)
