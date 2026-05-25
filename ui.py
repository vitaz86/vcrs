from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from config import CONFIG_PATH, LOG_DIR, WatcherRule, save_config


def _display_path(path: str) -> str:
    return path.replace('/', '\\') if sys.platform.startswith('win') else path


def _store_path(path: str) -> str:
    return path.replace('\\', '/') if sys.platform.startswith('win') else path


def set_startup_enabled(enabled: bool) -> None:
    app_name = "VCSAutoMover"
    script_cmd = f'"{sys.executable}" "{Path(__file__).resolve().parent / "main.py"}"'
    if sys.platform.startswith("win"):
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, script_cmd)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
    elif sys.platform == "darwin":
        launch_agents = Path.home() / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True, exist_ok=True)
        plist_path = launch_agents / "com.vcs.automover.plist"
        if enabled:
            plist = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict><key>Label</key><string>com.vcs.automover</string>
<key>ProgramArguments</key><array><string>{sys.executable}</string><string>{Path(__file__).resolve().parent / 'main.py'}</string></array>
<key>RunAtLoad</key><true/></dict></plist>"""
            plist_path.write_text(plist, encoding="utf-8")
        else:
            plist_path.unlink(missing_ok=True)
    else:
        autostart = Path.home() / ".config" / "autostart"
        autostart.mkdir(parents=True, exist_ok=True)
        desktop_path = autostart / "vcs-automover.desktop"
        if enabled:
            desktop = "[Desktop Entry]\nType=Application\nName=VCS AutoMover\n" f"Exec={script_cmd}\nX-GNOME-Autostart-enabled=true\n"
            desktop_path.write_text(desktop, encoding="utf-8")
        else:
            desktop_path.unlink(missing_ok=True)


class RuleDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, app_state, title_key: str, rule: dict | None = None):
        super().__init__(master)
        self.app_state = app_state
        self.title(self.app_state.t(title_key))
        self.result = None
        self.resizable(False, False)
        self.vars = {
            "name": tk.StringVar(value=(rule or {}).get("name", "")),
            "source_folder": tk.StringVar(value=_display_path((rule or {}).get("source_folder", ""))),
            "destination_folder": tk.StringVar(value=_display_path((rule or {}).get("destination_folder", ""))),
            "extensions": tk.StringVar(value=", ".join((rule or {}).get("extensions", [".mp4"]))),
            "move_mode": tk.StringVar(value=(rule or {}).get("move_mode", "wait_for_stable")),
            "delete_source_folder": tk.BooleanVar(value=(rule or {}).get("delete_source_folder", True)),
            "delete_delay_seconds": tk.StringVar(value=str((rule or {}).get("delete_delay_seconds", 60))),
            "enabled": tk.BooleanVar(value=(rule or {}).get("enabled", False)),
        }
        self._build_form()
        self.transient(master)
        self.grab_set()

    def _build_form(self) -> None:
        frame = ttk.Frame(self, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        rows = [("name_label", "name"), ("source_label", "source_folder"), ("destination_label", "destination_folder"), ("extensions_label", "extensions"), ("move_mode_label", "move_mode"), ("delete_delay_label", "delete_delay_seconds")]
        for idx, (label_key, key) in enumerate(rows):
            ttk.Label(frame, text=self.app_state.t(label_key)).grid(row=idx, column=0, sticky="w", pady=2)
            if key == "move_mode":
                ttk.Combobox(frame, textvariable=self.vars[key], values=["wait_for_stable", "immediate"], state="readonly").grid(row=idx, column=1, sticky="ew", pady=2)
            else:
                ttk.Entry(frame, textvariable=self.vars[key], width=50).grid(row=idx, column=1, sticky="ew", pady=2)
            if key in {"source_folder", "destination_folder"}:
                ttk.Button(frame, text=self.app_state.t("browse"), command=lambda k=key: self._browse(k)).grid(row=idx, column=2, padx=4)
        ttk.Checkbutton(frame, text=self.app_state.t("delete_source_folder"), variable=self.vars["delete_source_folder"]).grid(row=len(rows), column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text=self.app_state.t("enabled"), variable=self.vars["enabled"]).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w")
        btn = ttk.Frame(frame)
        btn.grid(row=len(rows) + 2, column=0, columnspan=3, pady=(8, 0), sticky="e")
        ttk.Button(btn, text=self.app_state.t("ok"), command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text=self.app_state.t("cancel"), command=self.destroy).pack(side=tk.LEFT)

    def _browse(self, key: str) -> None:
        path = filedialog.askdirectory()
        if path:
            self.vars[key].set(_display_path(path))

    def _on_ok(self) -> None:
        try:
            exts = [ext.strip().lower() for ext in self.vars["extensions"].get().split(",") if ext.strip()]
            self.result = {
                "name": self.vars["name"].get().strip(),
                "source_folder": _store_path(self.vars["source_folder"].get().strip()),
                "destination_folder": _store_path(self.vars["destination_folder"].get().strip()),
                "extensions": [e if e.startswith(".") else f".{e}" for e in exts],
                "move_mode": self.vars["move_mode"].get(),
                "delete_source_folder": bool(self.vars["delete_source_folder"].get()),
                "delete_delay_seconds": int(self.vars["delete_delay_seconds"].get()),
                "enabled": bool(self.vars["enabled"].get()),
            }
        except ValueError:
            messagebox.showerror(self.app_state.t("invalid_value"), self.app_state.t("delay_error"))
            return
        self.destroy()


class SettingsWindow:
    def __init__(self, app_state):
        self.app_state = app_state
        self.root = tk.Tk()
        self.root.title(self.app_state.t("settings_title"))
        self.root.geometry("1120x430")
        self.startup_var = tk.BooleanVar(value=self.app_state.config.get("startup_enabled", False))
        self.language_var = tk.StringVar(value=self.app_state.config.get("language", "en"))
        self._build_ui()
        self._load_rules()

    def _build_ui(self) -> None:
        cols = ("name", "source", "destination", "extensions", "enabled")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings")
        for key in cols:
            self.tree.heading(key, text=self.app_state.t(key))
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.tree.bind("<Double-1>", self._on_double_click)
        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(ctrl, text=self.app_state.t("add_rule"), command=self._add_rule).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text=self.app_state.t("edit_rule"), command=self._edit_rule).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text=self.app_state.t("delete_rule"), command=self._delete_rule).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text=self.app_state.t("save"), command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Checkbutton(ctrl, text=self.app_state.t("run_startup"), variable=self.startup_var).pack(side=tk.RIGHT, padx=8)
        ttk.Label(ctrl, text=self.app_state.t("language")).pack(side=tk.RIGHT)
        ttk.Combobox(ctrl, textvariable=self.language_var, values=["en", "ru"], width=6, state="readonly").pack(side=tk.RIGHT, padx=6)

    def _on_double_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self._edit_rule()

    def _load_rules(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        yes, no = self.app_state.t("yes"), self.app_state.t("no")
        for idx, rule in enumerate(self.app_state.config.get("rules", [])):
            self.tree.insert("", tk.END, iid=str(idx), values=(rule.get("name", ""), _display_path(rule.get("source_folder", "")), _display_path(rule.get("destination_folder", "")), ", ".join(rule.get("extensions", [])), yes if rule.get("enabled", False) else no))

    def _add_rule(self) -> None:
        dialog = RuleDialog(self.root, self.app_state, "add_rule")
        self.root.wait_window(dialog)
        if dialog.result:
            self.app_state.config.setdefault("rules", []).append(dialog.result)
            self._load_rules()

    def _edit_rule(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        dialog = RuleDialog(self.root, self.app_state, "edit_rule", self.app_state.config["rules"][idx])
        self.root.wait_window(dialog)
        if dialog.result:
            self.app_state.config["rules"][idx] = dialog.result
            self._load_rules()

    def _delete_rule(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        del self.app_state.config["rules"][int(sel[0])]
        self._load_rules()

    def _save(self) -> None:
        self.app_state.config["startup_enabled"] = bool(self.startup_var.get())
        self.app_state.config["language"] = self.language_var.get()
        self.app_state.set_language(self.language_var.get())
        save_config(self.app_state.config)
        set_startup_enabled(self.app_state.config["startup_enabled"])
        self.app_state.apply_config(self.app_state.config)
        messagebox.showinfo(self.app_state.t("saved"), f"{self.app_state.t('saved_to')} {CONFIG_PATH}")

    def run(self) -> None:
        self.root.mainloop()


class LogViewerWindow:
    def __init__(self, app_state):
        self.app_state = app_state
        self.root = tk.Tk()
        self.root.title(self.app_state.t("log_title"))
        self.root.geometry("900x520")
        frame = ttk.Frame(self.root, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(frame, wrap="none", state="disabled")
        self.text.pack(fill=tk.BOTH, expand=True)
        ttk.Button(frame, text=self.app_state.t("refresh"), command=self.refresh).pack(pady=6)
        self.refresh()

    def refresh(self) -> None:
        from datetime import datetime, timezone
        log_path = LOG_DIR / f"log_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"
        content = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.text.see(tk.END)
        self.text.config(state="disabled")

    def run(self) -> None:
        self.root.mainloop()
