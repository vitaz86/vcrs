from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from config import CONFIG_PATH, LOG_DIR, WatcherRule, get_rules, save_config


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
            desktop = (
                "[Desktop Entry]\nType=Application\nName=VCS AutoMover\n"
                f"Exec={script_cmd}\nX-GNOME-Autostart-enabled=true\n"
            )
            desktop_path.write_text(desktop, encoding="utf-8")
        else:
            desktop_path.unlink(missing_ok=True)


class RuleDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, title: str, rule: dict | None = None):
        super().__init__(master)
        self.title(title)
        self.result = None
        self.resizable(False, False)

        self.vars = {
            "name": tk.StringVar(value=(rule or {}).get("name", "")),
            "source_folder": tk.StringVar(value=(rule or {}).get("source_folder", "")),
            "destination_folder": tk.StringVar(value=(rule or {}).get("destination_folder", "")),
            "extensions": tk.StringVar(value=", ".join((rule or {}).get("extensions", [".mp4"]))),
            "move_mode": tk.StringVar(value=(rule or {}).get("move_mode", "wait_for_stable")),
            "delete_source_folder": tk.BooleanVar(value=(rule or {}).get("delete_source_folder", True)),
            "delete_delay_seconds": tk.StringVar(value=str((rule or {}).get("delete_delay_seconds", 60))),
            "enabled": tk.BooleanVar(value=(rule or {}).get("enabled", True)),
        }

        self._build_form()
        self.transient(master)
        self.grab_set()

    def _build_form(self) -> None:
        frame = ttk.Frame(self, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")

        rows = [
            ("Name", "name"),
            ("Source Folder", "source_folder"),
            ("Destination Folder", "destination_folder"),
            ("Extensions (comma)", "extensions"),
            ("Move Mode", "move_mode"),
            ("Delete Delay (sec)", "delete_delay_seconds"),
        ]

        for idx, (label, key) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=idx, column=0, sticky="w", pady=2)
            if key == "move_mode":
                cb = ttk.Combobox(frame, textvariable=self.vars[key], values=["wait_for_stable", "immediate"], state="readonly")
                cb.grid(row=idx, column=1, sticky="ew", pady=2)
            else:
                entry = ttk.Entry(frame, textvariable=self.vars[key], width=50)
                entry.grid(row=idx, column=1, sticky="ew", pady=2)

            if key in {"source_folder", "destination_folder"}:
                ttk.Button(frame, text="Browse", command=lambda k=key: self._browse(k)).grid(row=idx, column=2, padx=4)

        ttk.Checkbutton(frame, text="Delete Source Folder", variable=self.vars["delete_source_folder"]).grid(
            row=len(rows), column=0, columnspan=2, sticky="w"
        )
        ttk.Checkbutton(frame, text="Enabled", variable=self.vars["enabled"]).grid(
            row=len(rows) + 1, column=0, columnspan=2, sticky="w"
        )

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=len(rows) + 2, column=0, columnspan=3, pady=(8, 0), sticky="e")
        ttk.Button(btn_row, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Cancel", command=self.destroy).pack(side=tk.LEFT)

    def _browse(self, key: str) -> None:
        path = filedialog.askdirectory()
        if path:
            self.vars[key].set(path)

    def _on_ok(self) -> None:
        try:
            exts = [ext.strip().lower() for ext in self.vars["extensions"].get().split(",") if ext.strip()]
            exts = [ext if ext.startswith(".") else f".{ext}" for ext in exts]
            self.result = {
                "name": self.vars["name"].get().strip(),
                "source_folder": self.vars["source_folder"].get().strip(),
                "destination_folder": self.vars["destination_folder"].get().strip(),
                "extensions": exts,
                "move_mode": self.vars["move_mode"].get(),
                "delete_source_folder": bool(self.vars["delete_source_folder"].get()),
                "delete_delay_seconds": int(self.vars["delete_delay_seconds"].get()),
                "enabled": bool(self.vars["enabled"].get()),
            }
        except ValueError:
            messagebox.showerror("Invalid value", "Delete delay must be an integer")
            return
        self.destroy()


class SettingsWindow:
    def __init__(self, app_state):
        self.app_state = app_state
        self.root = tk.Tk()
        self.root.title("VCS AutoMover Settings")
        self.root.geometry("1100x420")

        self.startup_var = tk.BooleanVar(value=self.app_state.config.get("startup_enabled", False))
        self._build_ui()
        self._load_rules()

    def _build_ui(self) -> None:
        cols = ("name", "source", "destination", "extensions", "enabled")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("source", text="Source")
        self.tree.heading("destination", text="Destination")
        self.tree.heading("extensions", text="Extensions")
        self.tree.heading("enabled", text="Enabled")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill=tk.X, padx=10, pady=(0, 10))

        ttk.Button(ctrl, text="Add Rule", command=self._add_rule).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Edit Rule", command=self._edit_rule).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Delete Rule", command=self._delete_rule).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Save", command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Checkbutton(ctrl, text="Run at startup", variable=self.startup_var).pack(side=tk.RIGHT, padx=8)

    def _load_rules(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for idx, rule in enumerate(self.app_state.config.get("rules", [])):
            self.tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    rule.get("name", ""),
                    rule.get("source_folder", ""),
                    rule.get("destination_folder", ""),
                    ", ".join(rule.get("extensions", [])),
                    "Yes" if rule.get("enabled", True) else "No",
                ),
            )

    def _add_rule(self) -> None:
        dialog = RuleDialog(self.root, "Add Rule")
        self.root.wait_window(dialog)
        if dialog.result:
            self.app_state.config.setdefault("rules", []).append(dialog.result)
            self._load_rules()

    def _edit_rule(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        current = self.app_state.config["rules"][idx]
        dialog = RuleDialog(self.root, "Edit Rule", current)
        self.root.wait_window(dialog)
        if dialog.result:
            self.app_state.config["rules"][idx] = dialog.result
            self._load_rules()

    def _delete_rule(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        del self.app_state.config["rules"][idx]
        self._load_rules()

    def _save(self) -> None:
        self.app_state.config["startup_enabled"] = bool(self.startup_var.get())
        save_config(self.app_state.config)
        set_startup_enabled(self.app_state.config["startup_enabled"])
        rules = [WatcherRule.from_dict(rule) for rule in self.app_state.config.get("rules", [])]
        self.app_state.restart_watchers(rules)
        messagebox.showinfo("Saved", f"Configuration saved to {CONFIG_PATH}")

    def run(self) -> None:
        self.root.mainloop()


class LogViewerWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("VCS AutoMover Log Viewer")
        self.root.geometry("900x520")

        frame = ttk.Frame(self.root, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)

        self.text = tk.Text(frame, wrap="none")
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.config(state="disabled")

        ttk.Button(frame, text="Refresh", command=self.refresh).pack(pady=6)
        self.refresh()

    def refresh(self) -> None:
        from datetime import datetime, timezone

        log_path = LOG_DIR / f"log_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"
        content = ""
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")

        self.text.config(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert(tk.END, content)
        self.text.see(tk.END)
        self.text.config(state="disabled")

    def run(self) -> None:
        self.root.mainloop()
