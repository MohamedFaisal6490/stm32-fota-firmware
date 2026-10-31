#!/usr/bin/env python3
"""Firmware Manifest Tool (Tkinter) - creates manifest.json for the STM32 FOTA project.

1. Browse the app.bin   2. Check the version (next number is suggested)   3. Generate
Optional: commit, tag and push to GitHub in one click (needs git installed and a cloned repo).
"""
import json
import pathlib
import re
import subprocess
import tkinter as tk
import zlib
from tkinter import filedialog, messagebox, scrolledtext, ttk

MAX_APP_SIZE = 0x78000          # 480 KB, same limit as the ESP32 / bootloader
APP_ADDR = 0x08008000


def build_manifest(bin_path: pathlib.Path, version: str) -> dict:
    data = bin_path.read_bytes()
    return {
        "version": version.lstrip("vV"),
        "file": bin_path.name,
        "size": len(data),
        "crc32": "%08X" % (zlib.crc32(data) & 0xFFFFFFFF),
    }


def check_image(data: bytes) -> list:
    """Return a list of warnings about the image (empty = looks fine)."""
    w = []
    if len(data) < 64:
        w.append("File is smaller than 64 bytes.")
    if len(data) > MAX_APP_SIZE:
        w.append(f"File is {len(data)} bytes; the maximum is {MAX_APP_SIZE} bytes (480 KB).")
    if len(data) >= 8:
        msp = int.from_bytes(data[0:4], "little")
        rst = int.from_bytes(data[4:8], "little")
        if (msp & 0x2FFE0000) != 0x20000000:
            w.append(f"Stack pointer 0x{msp:08X} is not in SRAM - is this a raw .bin?")
        if not (rst & 1) or not (APP_ADDR <= rst < APP_ADDR + MAX_APP_SIZE):
            w.append(f"Reset vector 0x{rst:08X} is outside 0x08008000 - check the linker script / VECT_TAB_OFFSET.")
    return w


def next_version(manifest_path: pathlib.Path) -> str:
    try:
        old = json.loads(manifest_path.read_text())["version"]
        a, b, c = (int(x) for x in old.lstrip("vV").split("."))
        return f"{a}.{b}.{c + 1}"
    except Exception:
        return "1.0.0"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STM32 FOTA - Manifest Tool")
        self.geometry("720x600")
        self.minsize(640, 520)
        self.bin_var = tk.StringVar()
        self.ver_var = tk.StringVar(value="1.0.0")
        self.manifest = None
        self.manifest_path = None
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        f = ttk.LabelFrame(self, text="1. Firmware file")
        f.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Entry(f, textvariable=self.bin_var).pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(f, text="Browse...", command=self.browse).pack(side="left", padx=(0, 8))

        v = ttk.LabelFrame(self, text="2. Version (x.y.z) - must be higher than the previous release")
        v.pack(fill="x", **pad)
        ttk.Entry(v, textvariable=self.ver_var, width=14).pack(side="left", padx=8, pady=8)
        ttk.Button(v, text="+ Patch", command=lambda: self.bump(2)).pack(side="left", padx=2)
        ttk.Button(v, text="+ Minor", command=lambda: self.bump(1)).pack(side="left", padx=2)
        ttk.Button(v, text="+ Major", command=lambda: self.bump(0)).pack(side="left", padx=2)

        g = ttk.LabelFrame(self, text="3. Generate")
        g.pack(fill="x", **pad)
        ttk.Button(g, text="Generate manifest.json", command=self.generate).pack(side="left", padx=8, pady=8)
        self.copy_btn = ttk.Button(g, text="Copy JSON", command=self.copy, state="disabled")
        self.copy_btn.pack(side="left", padx=2)
        self.open_btn = ttk.Button(g, text="Open folder", command=self.open_folder, state="disabled")
        self.open_btn.pack(side="left", padx=2)

        self.out = scrolledtext.ScrolledText(self, height=8, font=("Consolas", 10), state="disabled")
        self.out.pack(fill="x", padx=10, pady=4)

        r = ttk.LabelFrame(self, text="4. Publish to GitHub (optional): git add, commit, tag vX.Y.Z, push")
        r.pack(fill="x", **pad)
        self.rel_btn = ttk.Button(r, text="Commit, tag and push", command=self.release, state="disabled")
        self.rel_btn.pack(side="left", padx=8, pady=8)
        ttk.Label(r, text="The GitHub Action then publishes the release automatically.").pack(side="left")

        self.log = scrolledtext.ScrolledText(self, height=9, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True, padx=10, pady=(4, 10))

    # ------------------------------------------------------------------ helpers
    def _write(self, widget, text, clear=False):
        widget.config(state="normal")
        if clear:
            widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.see("end")
        widget.config(state="disabled")

    def browse(self):
        p = filedialog.askopenfilename(title="Select app.bin", filetypes=[("Binary", "*.bin"), ("All files", "*.*")])
        if p:
            self.bin_var.set(p)
            self.ver_var.set(next_version(pathlib.Path(p).with_name("manifest.json")))

    def bump(self, idx):
        try:
            parts = [int(x) for x in self.ver_var.get().lstrip("vV").split(".")]
            parts[idx] += 1
            for i in range(idx + 1, 3):
                parts[i] = 0
            self.ver_var.set(".".join(str(x) for x in parts))
        except Exception:
            messagebox.showerror("Version", "Version must look like 1.0.3")

    # ------------------------------------------------------------------ actions
    def generate(self):
        p = pathlib.Path(self.bin_var.get().strip())
        ver = self.ver_var.get().strip().lstrip("vV")
        if not p.is_file():
            messagebox.showerror("File", "Select the firmware .bin file first.")
            return
        if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
            messagebox.showerror("Version", "Version must look like 1.0.3")
            return
        data = p.read_bytes()
        warnings = check_image(data)
        if warnings and not messagebox.askyesno("Image warning", "\n\n".join(warnings) + "\n\nContinue anyway?"):
            return
        try:
            self.manifest = build_manifest(p, ver)
            self.manifest_path = p.with_name("manifest.json")
            self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + "\n")
        except OSError as e:
            messagebox.showerror("Write error", str(e))
            return
        self._write(self.out, f"Saved: {self.manifest_path}\n\n{json.dumps(self.manifest, indent=2)}\n", clear=True)
        for b in (self.copy_btn, self.open_btn, self.rel_btn):
            b.config(state="normal")
        self._write(self.log, f"Manifest created for version {ver} ({self.manifest['size']} bytes, CRC32 {self.manifest['crc32']}).\n", clear=True)

    def copy(self):
        if self.manifest:
            self.clipboard_clear()
            self.clipboard_append(json.dumps(self.manifest, indent=2))
            self._write(self.log, "JSON copied to clipboard.\n")

    def open_folder(self):
        import os
        import sys
        folder = str(self.manifest_path.parent)
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def _git(self, args, cwd):
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
        self._write(self.log, f"$ git {' '.join(args)}\n{r.stdout}{r.stderr}")
        self.update_idletasks()
        return r.returncode == 0

    def release(self):
        if not self.manifest:
            return
        ver = self.manifest["version"]
        folder = self.manifest_path.parent
        if not messagebox.askyesno("Publish", f"Commit and push firmware v{ver}, and create tag v{ver}?"):
            return
        try:
            top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=folder, capture_output=True, text=True)
        except FileNotFoundError:
            messagebox.showerror("Git", "git is not installed or not in PATH.")
            return
        if top.returncode != 0:
            messagebox.showerror("Git", "The firmware folder is not inside a git repository (clone your repo first).")
            return
        root = top.stdout.strip()
        bin_file = str(pathlib.Path(self.bin_var.get()).resolve())
        steps = [["add", bin_file, str(self.manifest_path.resolve())],
                 ["commit", "-m", f"Firmware {ver}"],
                 ["tag", f"v{ver}"],
                 ["push"],
                 ["push", "--tags"]]
        for s in steps:
            if not self._git(s, root):
                messagebox.showerror("Git", f"'git {' '.join(s[:2])}' failed - see the log below.")
                return
        self._write(self.log, f"\nDone. GitHub will publish release v{ver} shortly.\n")
        messagebox.showinfo("Published", f"Version v{ver} pushed.")


if __name__ == "__main__":
    App().mainloop()
