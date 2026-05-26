from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_DIR = Path.home() / ".vcs_automover"
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"
S3_UPLOAD_ROOT = "New"

TRANSFER_TARGET_FOLDER = "folder"
TRANSFER_TARGET_S3 = "s3"
TRANSFER_TARGETS = {TRANSFER_TARGET_FOLDER, TRANSFER_TARGET_S3}


@dataclass
class WatcherRule:
    name: str
    source_folder: str
    destination_folder: str
    transfer_target: str
    s3_endpoint_url: str
    s3_bucket_name: str
    s3_access_key: str
    s3_secret_key: str
    s3_region: str
    extensions: list[str]
    move_mode: str
    delete_source_folder: bool
    delete_delay_seconds: int
    enabled: bool

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WatcherRule":
        transfer_target = str(data.get("transfer_target", TRANSFER_TARGET_FOLDER)).lower().strip()
        if transfer_target not in TRANSFER_TARGETS:
            transfer_target = TRANSFER_TARGET_FOLDER

        return WatcherRule(
            name=str(data.get("name", "Unnamed")),
            source_folder=str(data.get("source_folder", "")),
            destination_folder=str(data.get("destination_folder", "")),
            transfer_target=transfer_target,
            s3_endpoint_url=str(data.get("s3_endpoint_url", "")).strip(),
            s3_bucket_name=str(data.get("s3_bucket_name", "")).strip(),
            s3_access_key=str(data.get("s3_access_key", "")).strip(),
            s3_secret_key=str(data.get("s3_secret_key", "")),
            s3_region=str(data.get("s3_region", "us-east-1")).strip() or "us-east-1",
            extensions=[str(ext).lower().strip() for ext in data.get("extensions", []) if str(ext).strip()],
            move_mode=str(data.get("move_mode", "wait_for_stable")),
            delete_source_folder=bool(data.get("delete_source_folder", True)),
            delete_delay_seconds=int(data.get("delete_delay_seconds", 60)),
            enabled=bool(data.get("enabled", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["extensions"] = [ext if ext.startswith(".") else f".{ext}" for ext in self.extensions]
        return payload


DEFAULT_CONFIG: dict[str, Any] = {
    "startup_enabled": False,
    "language": "en",
    "zoom_conversion_timeout_seconds": 1200,
    "rules": [
        {
            "name": "Zoom",
            "source_folder": r"C:\Users\User\Documents\Zoom",
            "destination_folder": r"C:\Users\User\Yandex.Disk\VKS Recordings\Zoom",
            "transfer_target": TRANSFER_TARGET_FOLDER,
            "s3_endpoint_url": "",
            "s3_bucket_name": "",
            "s3_access_key": "",
            "s3_secret_key": "",
            "s3_region": "us-east-1",
            "extensions": [".mp4", ".m4a"],
            "move_mode": "wait_for_stable",
            "delete_source_folder": True,
            "delete_delay_seconds": 60,
            "enabled": False,
        },
        {
            "name": "Telemost",
            "source_folder": r"C:\Users\User\Documents\Telemost",
            "destination_folder": r"C:\Users\User\Yandex.Disk\VKS Recordings\Telemost",
            "transfer_target": TRANSFER_TARGET_FOLDER,
            "s3_endpoint_url": "",
            "s3_bucket_name": "",
            "s3_access_key": "",
            "s3_secret_key": "",
            "s3_region": "us-east-1",
            "extensions": [".webm"],
            "move_mode": "immediate",
            "delete_source_folder": True,
            "delete_delay_seconds": 60,
            "enabled": False,
        },
        {
            "name": "Kontur Talk",
            "source_folder": r"C:\Users\User\Documents\KTalk",
            "destination_folder": r"C:\Users\User\Yandex.Disk\VKS Recordings\KTalk",
            "transfer_target": TRANSFER_TARGET_FOLDER,
            "s3_endpoint_url": "",
            "s3_bucket_name": "",
            "s3_access_key": "",
            "s3_secret_key": "",
            "s3_region": "us-east-1",
            "extensions": [".mp4", ".m4a"],
            "move_mode": "wait_for_stable",
            "delete_source_folder": True,
            "delete_delay_seconds": 60,
            "enabled": False,
        },
    ],
}


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_app_dirs()
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data.setdefault("startup_enabled", False)
    data.setdefault("language", "en")
    data.setdefault("zoom_conversion_timeout_seconds", 1200)
    data.setdefault("rules", [])
    return data


def save_config(data: dict[str, Any]) -> None:
    ensure_app_dirs()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_rules(config: dict[str, Any]) -> list[WatcherRule]:
    return [WatcherRule.from_dict(rule) for rule in config.get("rules", [])]
