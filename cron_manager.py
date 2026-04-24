#!/usr/bin/env python3
"""
GUI do włączania/wyłączania codziennego scrapowania cen (zadanie cron).
Uruchom: python3 cron_manager.py
"""

import subprocess
import threading
from pathlib import Path
import tkinter as tk

PROJECT = Path("/Users/admin/Documents/Projekty N8N i Claude/Liofilizaty/liofilizaty-v2")
SCRIPT = PROJECT / "scraper_cron.sh"
LOG = Path.home() / "Library" / "Logs" / "liofilizaty_tracker.log"
MARKER = "# liofilizaty-tracker"
CRON_ENTRY = f'0 7 * * * /bin/bash "{SCRIPT}" >> "{LOG}" 2>&1  {MARKER}'


def _crontab_lines() -> list[str]:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def _write_crontab(lines: list[str]) -> None:
    content = "\n".join(lines) + "\n"
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def job_status() -> str:
    for line in _crontab_lines():
        if MARKER in line:
            return "enabled" if not line.strip().startswith("#") else "disabled"
    return "not_installed"


def enable() -> None:
    lines = _crontab_lines()
    updated, found = [], False
    for line in lines:
        if MARKER in line:
            updated.append(line.lstrip("# ").strip())
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(CRON_ENTRY)
    _write_crontab(updated)


def disable() -> None:
    lines = _crontab_lines()
    updated = []
    for line in lines:
        if MARKER in line and not line.strip().startswith("#"):
            updated.append("# " + line)
        else:
            updated.append(line)
    _write_crontab(updated)


class App(tk.Tk):
    COLOR_BG = "#1e1e2e"
    COLOR_PANEL = "#2a2a3e"
    COLOR_FG = "#cdd6f4"
    COLOR_FG_DIM = "#7f849c"
    COLOR_SEP = "#45475a"
    COLOR_ON = "#a6e3a1"
    COLOR_OFF = "#f38ba8"
    COLOR_WARN = "#fab387"

    def __init__(self):
        super().__init__()
        self.title("Liofilizaty Tracker — Harmonogram")
        self.resizable(False, False)
        self.configure(bg=self.COLOR_BG)
        self._build()
        self._refresh()

    def _build(self):
        pad = dict(padx=20, pady=8)

        # Nagłówek
        tk.Label(
            self, text="Liofilizaty Tracker", bg=self.COLOR_BG,
            fg=self.COLOR_FG, font=("Helvetica", 15, "bold"),
        ).pack(pady=(20, 4))
        tk.Label(
            self, text="44 produkty · 5 sklepów · Skalnik, WGL, Sportano, Sewel, 4camping",
            bg=self.COLOR_BG, fg=self.COLOR_FG_DIM, font=("Helvetica", 11),
        ).pack()

        tk.Frame(self, height=1, bg=self.COLOR_SEP).pack(fill="x", padx=20, pady=12)

        # Status
        sf = tk.Frame(self, bg=self.COLOR_BG)
        sf.pack(**pad)
        tk.Label(sf, text="Status:", bg=self.COLOR_BG, fg=self.COLOR_FG,
                 font=("Helvetica", 13)).pack(side="left")
        self.lbl_status = tk.Label(sf, text="...", bg=self.COLOR_BG,
                                   font=("Helvetica", 13, "bold"))
        self.lbl_status.pack(side="left", padx=10)

        self.lbl_info = tk.Label(self, text="", bg=self.COLOR_BG,
                                 fg=self.COLOR_FG_DIM, font=("Helvetica", 11))
        self.lbl_info.pack()

        tk.Frame(self, height=1, bg=self.COLOR_SEP).pack(fill="x", padx=20, pady=12)

        # Przyciski
        bf = tk.Frame(self, bg=self.COLOR_BG)
        bf.pack(**pad)
        self.btn_toggle = tk.Button(
            bf, text="...", width=14, font=("Helvetica", 12),
            bg=self.COLOR_PANEL, fg=self.COLOR_FG,
            activebackground=self.COLOR_SEP, activeforeground=self.COLOR_FG,
            relief="flat", command=self._toggle, cursor="hand2",
        )
        self.btn_toggle.pack(side="left", padx=6)
        self.btn_run = tk.Button(
            bf, text="Uruchom teraz", width=14, font=("Helvetica", 12),
            bg=self.COLOR_PANEL, fg=self.COLOR_FG,
            activebackground=self.COLOR_SEP, activeforeground=self.COLOR_FG,
            relief="flat", command=self._run_now, cursor="hand2",
        )
        self.btn_run.pack(side="left", padx=6)

        # Log
        tk.Frame(self, height=1, bg=self.COLOR_SEP).pack(fill="x", padx=20, pady=12)
        tk.Label(
            self, text="Ostatni log:", bg=self.COLOR_BG,
            fg=self.COLOR_FG_DIM, font=("Helvetica", 11), anchor="w",
        ).pack(fill="x", padx=20)
        self.txt_log = tk.Text(
            self, height=8, width=60, font=("Menlo", 10),
            state="disabled", bg=self.COLOR_PANEL, fg="#cdd6f4",
            relief="flat", padx=8, pady=6,
        )
        self.txt_log.pack(padx=20, pady=(4, 20))

    def _refresh(self):
        status = job_status()
        if status == "enabled":
            self.lbl_status.config(text="● WŁĄCZONE", fg=self.COLOR_ON)
            self.lbl_info.config(text="Uruchamiane codziennie o 07:00 → ~56 cen z 5 sklepów")
            self.btn_toggle.config(text="Wyłącz")
        elif status == "disabled":
            self.lbl_status.config(text="● WYŁĄCZONE", fg=self.COLOR_OFF)
            self.lbl_info.config(text="Zadanie jest wstrzymane")
            self.btn_toggle.config(text="Włącz")
        else:
            self.lbl_status.config(text="● NIEZAINSTALOWANE", fg=self.COLOR_WARN)
            self.lbl_info.config(text="Kliknij Włącz, aby dodać do harmonogramu")
            self.btn_toggle.config(text="Włącz")
        self._load_log()

    def _load_log(self):
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        if LOG.exists():
            lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            self.txt_log.insert("end", "\n".join(lines[-12:]))
        else:
            self.txt_log.insert("end", "(brak logów — uruchom raz żeby wygenerować)")
        self.txt_log.config(state="disabled")

    def _toggle(self):
        self.btn_toggle.config(state="disabled")
        if job_status() == "enabled":
            disable()
        else:
            enable()
        self._refresh()
        self.btn_toggle.config(state="normal")

    def _run_now(self):
        self.btn_run.config(text="Trwa...", state="disabled")
        threading.Thread(target=self._do_run, daemon=True).start()

    def _do_run(self):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            subprocess.run(["bash", str(SCRIPT)], stdout=f, stderr=f)
        self.after(0, self._run_done)

    def _run_done(self):
        self.btn_run.config(text="Uruchom teraz", state="normal")
        self._refresh()


if __name__ == "__main__":
    App().mainloop()
