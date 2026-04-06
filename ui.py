from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import AppConfig, WatcherRule


@dataclass
class UiCallbacks:
    load_config: Callable[[], AppConfig]
    save_config: Callable[[AppConfig], None]
    apply_startup: Callable[[bool], None]
    restart_watchers: Callable[[list[WatcherRule]], None]
    current_log_file: Callable[[], Path]


class SettingsWindow:
    def __init__(self, root: tk.Tk, logger: logging.Logger, cb: UiCallbacks) -> None:
        self._root = root
        self._log = logger
        self._cb = cb
        self._win: tk.Toplevel | None = None

    def show(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return

        cfg = self._cb.load_config()
        self._win = tk.Toplevel(self._root)
        self._win.title("VCS AutoMover — Settings")
        self._win.geometry("980x420")

        main = ttk.Frame(self._win, padding=10)
        main.pack(fill="both", expand=True)

        cols = ("name", "source", "dest", "exts", "enabled")
        tree = ttk.Treeview(main, columns=cols, show="headings", height=12)
        tree.heading("name", text="Name")
        tree.heading("source", text="Source")
        tree.heading("dest", text="Destination")
        tree.heading("exts", text="Extensions")
        tree.heading("enabled", text="Enabled")
        tree.column("name", width=120, stretch=False)
        tree.column("source", width=280)
        tree.column("dest", width=280)
        tree.column("exts", width=120, stretch=False)
        tree.column("enabled", width=80, stretch=False, anchor="center")
        tree.pack(fill="both", expand=True)

        rules: list[WatcherRule] = list(cfg.get("rules") or [])

        def refresh_tree() -> None:
            for i in tree.get_children():
                tree.delete(i)
            for idx, r in enumerate(rules):
                tree.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(
                        r.get("name", ""),
                        r.get("source_folder", ""),
                        r.get("destination_folder", ""),
                        ", ".join(r.get("extensions", [])),
                        "Yes" if r.get("enabled", True) else "No",
                    ),
                )

        refresh_tree()

        controls = ttk.Frame(main)
        controls.pack(fill="x", pady=(10, 0))

        startup_var = tk.BooleanVar(value=bool(cfg.get("startup_enabled", False)))
        startup_chk = ttk.Checkbutton(controls, text="Run at startup", variable=startup_var)
        startup_chk.pack(side="left")

        btns = ttk.Frame(controls)
        btns.pack(side="right")

        def selected_index() -> int | None:
            sel = tree.selection()
            if not sel:
                return None
            try:
                return int(sel[0])
            except ValueError:
                return None

        def add_rule() -> None:
            r = _RuleDialog(self._win, title="Add Rule").run()
            if r:
                rules.append(r)
                refresh_tree()

        def edit_rule() -> None:
            idx = selected_index()
            if idx is None or idx < 0 or idx >= len(rules):
                return
            r = _RuleDialog(self._win, title="Edit Rule", initial=rules[idx]).run()
            if r:
                rules[idx] = r
                refresh_tree()

        def delete_rule() -> None:
            idx = selected_index()
            if idx is None or idx < 0 or idx >= len(rules):
                return
            if not messagebox.askyesno("Delete Rule", f"Delete rule '{rules[idx].get('name','')}'?"):
                return
            rules.pop(idx)
            refresh_tree()

        def save_all() -> None:
            new_cfg: AppConfig = {"startup_enabled": bool(startup_var.get()), "rules": rules}
            try:
                self._cb.save_config(new_cfg)
                self._cb.apply_startup(bool(startup_var.get()))
                self._cb.restart_watchers(rules)
                messagebox.showinfo("Saved", "Configuration saved and watchers restarted.")
            except Exception as e:
                self._log.exception("save failed: %s", e)
                messagebox.showerror("Error", f"Failed to save configuration:\n{e}")

        ttk.Button(btns, text="Add Rule", command=add_rule).pack(side="left", padx=4)
        ttk.Button(btns, text="Edit Rule", command=edit_rule).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete Rule", command=delete_rule).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=save_all).pack(side="left", padx=4)


class LogViewerWindow:
    def __init__(self, root: tk.Tk, logger: logging.Logger, cb: UiCallbacks) -> None:
        self._root = root
        self._log = logger
        self._cb = cb
        self._win: tk.Toplevel | None = None
        self._text: tk.Text | None = None

    def show(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            self._reload()
            return

        self._win = tk.Toplevel(self._root)
        self._win.title("VCS AutoMover — Log")
        self._win.geometry("900x520")

        top = ttk.Frame(self._win, padding=10)
        top.pack(fill="both", expand=True)

        self._text = tk.Text(top, wrap="none")
        y = ttk.Scrollbar(top, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=y.set)
        self._text.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        controls = ttk.Frame(self._win, padding=10)
        controls.pack(fill="x")
        ttk.Button(controls, text="Refresh", command=self._reload).pack(side="right")

        self._reload()

    def _reload(self) -> None:
        if not self._text:
            return
        path = self._cb.current_log_file()
        try:
            content = path.read_text(encoding="utf-8") if path.exists() else ""
        except Exception as e:
            self._log.error("log read failed: %s", e)
            content = f"Failed to read log file:\n{e}\n\nPath: {path}"

        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", content)
        self._text.configure(state="disabled")
        self._text.see("end")


class _RuleDialog:
    def __init__(self, parent: tk.Toplevel, title: str, initial: WatcherRule | None = None) -> None:
        self._initial = initial or WatcherRule(
            name="",
            source_folder="",
            destination_folder="",
            extensions=[".mp4"],
            move_mode="wait_for_stable",
            delete_source_folder=True,
            delete_delay_seconds=60,
            enabled=True,
        )
        self._win = tk.Toplevel(parent)
        self._win.title(title)
        self._win.geometry("650x360")
        self._win.transient(parent)
        self._win.grab_set()

        frm = ttk.Frame(self._win, padding=10)
        frm.pack(fill="both", expand=True)

        self._vars: dict[str, tk.Variable] = {
            "name": tk.StringVar(value=self._initial.get("name", "")),
            "source_folder": tk.StringVar(value=self._initial.get("source_folder", "")),
            "destination_folder": tk.StringVar(value=self._initial.get("destination_folder", "")),
            "extensions": tk.StringVar(value=", ".join(self._initial.get("extensions", []))),
            "move_mode": tk.StringVar(value=self._initial.get("move_mode", "wait_for_stable")),
            "delete_source_folder": tk.BooleanVar(value=bool(self._initial.get("delete_source_folder", True))),
            "delete_delay_seconds": tk.StringVar(value=str(self._initial.get("delete_delay_seconds", 60))),
            "enabled": tk.BooleanVar(value=bool(self._initial.get("enabled", True))),
        }

        def row(label: str, key: str, browse: bool = False) -> None:
            r = ttk.Frame(frm)
            r.pack(fill="x", pady=4)
            ttk.Label(r, text=label, width=18).pack(side="left")
            ent = ttk.Entry(r, textvariable=self._vars[key])  # type: ignore[arg-type]
            ent.pack(side="left", fill="x", expand=True)
            if browse:
                ttk.Button(r, text="Browse", command=lambda: self._browse_dir(key)).pack(side="left", padx=6)

        row("Name", "name")
        row("Source folder", "source_folder", browse=True)
        row("Destination folder", "destination_folder", browse=True)
        row("Extensions", "extensions")

        r_mode = ttk.Frame(frm)
        r_mode.pack(fill="x", pady=4)
        ttk.Label(r_mode, text="Move mode", width=18).pack(side="left")
        ttk.Combobox(
            r_mode,
            textvariable=self._vars["move_mode"],  # type: ignore[arg-type]
            values=["wait_for_stable", "immediate"],
            state="readonly",
            width=18,
        ).pack(side="left")

        r_chk = ttk.Frame(frm)
        r_chk.pack(fill="x", pady=4)
        ttk.Checkbutton(r_chk, text="Enabled", variable=self._vars["enabled"]).pack(side="left")
        ttk.Checkbutton(r_chk, text="Delete source subfolder", variable=self._vars["delete_source_folder"]).pack(
            side="left", padx=10
        )

        r_delay = ttk.Frame(frm)
        r_delay.pack(fill="x", pady=4)
        ttk.Label(r_delay, text="Delete delay (sec)", width=18).pack(side="left")
        ttk.Entry(r_delay, textvariable=self._vars["delete_delay_seconds"], width=10).pack(side="left")

        bottom = ttk.Frame(frm)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="Cancel", command=self._cancel).pack(side="right", padx=6)
        ttk.Button(bottom, text="OK", command=self._ok).pack(side="right")

        self._result: WatcherRule | None = None

    def run(self) -> WatcherRule | None:
        self._win.wait_window()
        return self._result

    def _browse_dir(self, key: str) -> None:
        p = filedialog.askdirectory()
        if p:
            self._vars[key].set(p)

    def _cancel(self) -> None:
        self._result = None
        self._win.destroy()

    def _ok(self) -> None:
        try:
            delay = int(str(self._vars["delete_delay_seconds"].get()).strip() or "60")
        except ValueError:
            messagebox.showerror("Invalid value", "Delete delay must be an integer.")
            return

        exts_raw = str(self._vars["extensions"].get())
        exts = [e.strip() for e in exts_raw.split(",") if e.strip()]

        self._result = WatcherRule(
            name=str(self._vars["name"].get()).strip() or "Rule",
            source_folder=str(self._vars["source_folder"].get()).strip(),
            destination_folder=str(self._vars["destination_folder"].get()).strip(),
            extensions=exts,
            move_mode=str(self._vars["move_mode"].get()),  # type: ignore[typeddict-item]
            delete_source_folder=bool(self._vars["delete_source_folder"].get()),
            delete_delay_seconds=max(0, delay),
            enabled=bool(self._vars["enabled"].get()),
        )
        self._win.destroy()

