from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict


MoveMode = Literal["wait_for_stable", "immediate"]


class WatcherRule(TypedDict):
    name: str
    source_folder: str
    destination_folder: str
    extensions: list[str]
    move_mode: MoveMode
    delete_source_folder: bool
    delete_delay_seconds: int
    enabled: bool


class AppConfig(TypedDict, total=False):
    startup_enabled: bool
    rules: list[WatcherRule]


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    config_path: Path
    logs_dir: Path


APP_DIR_NAME = ".vcs_automover"


def get_app_paths() -> AppPaths:
    base_dir = Path.home() / APP_DIR_NAME
    return AppPaths(
        base_dir=base_dir,
        config_path=base_dir / "config.json",
        logs_dir=base_dir / "logs",
    )


def ensure_app_dirs(paths: AppPaths) -> None:
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)


def _normalize_exts(exts: list[str]) -> list[str]:
    out: list[str] = []
    for e in exts:
        e = (e or "").strip()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        out.append(e.lower())
    # preserve order while de-duping
    seen: set[str] = set()
    uniq: list[str] = []
    for e in out:
        if e not in seen:
            uniq.append(e)
            seen.add(e)
    return uniq


def _coerce_rule(raw: dict[str, Any]) -> WatcherRule:
    exts = raw.get("extensions") or []
    if isinstance(exts, str):
        exts = [x.strip() for x in exts.split(",")]
    if not isinstance(exts, list):
        exts = []

    move_mode: str = raw.get("move_mode") or "wait_for_stable"
    if move_mode not in ("wait_for_stable", "immediate"):
        move_mode = "wait_for_stable"

    return WatcherRule(
        name=str(raw.get("name") or "Rule"),
        source_folder=str(raw.get("source_folder") or ""),
        destination_folder=str(raw.get("destination_folder") or ""),
        extensions=_normalize_exts([str(x) for x in exts]),
        move_mode=move_mode,  # type: ignore[typeddict-item]
        delete_source_folder=bool(raw.get("delete_source_folder", True)),
        delete_delay_seconds=int(raw.get("delete_delay_seconds", 60) or 60),
        enabled=bool(raw.get("enabled", True)),
    )


def load_config(paths: AppPaths) -> AppConfig:
    ensure_app_dirs(paths)
    if not paths.config_path.exists():
        cfg: AppConfig = {"startup_enabled": False, "rules": []}
        save_config(paths, cfg)
        return cfg
    try:
        data = json.loads(paths.config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"startup_enabled": False, "rules": []}
        raw_rules = data.get("rules") or []
        rules: list[WatcherRule] = []
        if isinstance(raw_rules, list):
            for r in raw_rules:
                if isinstance(r, dict):
                    rules.append(_coerce_rule(r))
        return {
            "startup_enabled": bool(data.get("startup_enabled", False)),
            "rules": rules,
        }
    except Exception:
        return {"startup_enabled": False, "rules": []}


def save_config(paths: AppPaths, cfg: AppConfig) -> None:
    ensure_app_dirs(paths)
    rules = cfg.get("rules") or []
    safe: AppConfig = {
        "startup_enabled": bool(cfg.get("startup_enabled", False)),
        "rules": [_coerce_rule(dict(r)) for r in rules],
    }
    paths.config_path.write_text(json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8")


def config_location_hint(paths: AppPaths) -> str:
    return str(paths.config_path)


def is_startup_enabled(paths: AppPaths) -> bool:
    cfg = load_config(paths)
    return bool(cfg.get("startup_enabled", False))


def set_startup_enabled(app_name: str, enabled: bool) -> None:
    """
    Registers current python entrypoint as user startup. Best-effort; never raises.
    """
    try:
        if sys.platform.startswith("win"):
            _set_startup_windows(app_name, enabled)
        elif sys.platform == "darwin":
            _set_startup_macos(app_name, enabled)
        else:
            _set_startup_linux(app_name, enabled)
    except Exception:
        # best-effort; caller logs
        return


def _startup_command(app_name: str) -> str:
    exe = Path(sys.executable)
    main_py = Path(__file__).with_name("main.py")
    # Quote for spaces; works in Windows Run key and .desktop Exec.
    return f"\"{exe}\" \"{main_py}\""


def _set_startup_windows(app_name: str, enabled: bool) -> None:
    import winreg  # type: ignore

    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, app_name, 0, winreg.REG_SZ, _startup_command(app_name))
        else:
            try:
                winreg.DeleteValue(k, app_name)
            except FileNotFoundError:
                pass


def _set_startup_linux(app_name: str, enabled: bool) -> None:
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = autostart_dir / f"{app_name}.desktop"
    if not enabled:
        try:
            desktop_path.unlink()
        except FileNotFoundError:
            pass
        return

    cmd = _startup_command(app_name)
    contents = "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Version=1.0",
            f"Name={app_name}",
            f"Exec={cmd}",
            "X-GNOME-Autostart-enabled=true",
        ]
    )
    desktop_path.write_text(contents + "\n", encoding="utf-8")


def _set_startup_macos(app_name: str, enabled: bool) -> None:
    # Minimal launchd plist in user's LaunchAgents.
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / f"{app_name}.plist"
    if not enabled:
        try:
            plist_path.unlink()
        except FileNotFoundError:
            pass
        return

    cmd = _startup_command(app_name)
    python_exe, script = _split_cmd(cmd)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{app_name}</string>
    <key>ProgramArguments</key>
    <array>
      <string>{python_exe}</string>
      <string>{script}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
  </dict>
</plist>
"""
    plist_path.write_text(plist, encoding="utf-8")


def _split_cmd(cmd: str) -> tuple[str, str]:
    # cmd is always "\"exe\" \"script\""
    parts = [p for p in cmd.split("\"") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return sys.executable, str(Path(__file__).with_name("main.py"))

