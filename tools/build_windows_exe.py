#!/usr/bin/env python3
"""Build the double-click Windows GUI and its quiet command-line worker."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = [
    (ROOT / "injector", "injector"),
    (ROOT / "payload", "payload"),
    (ROOT / "sdk", "sdk"),
    (ROOT / "tools" / "export_source.py", "tools"),
    (ROOT / "qa" / "validated_hosts.json", "qa"),
    (ROOT / "assets" / "cki.ico", "assets"),
]
HIDDEN_IMPORTS = [path.stem for path in (ROOT / "injector").glob("*.py")]
HIDDEN_IMPORTS += ["export_source", "tkinter", "tkinter.ttk", "tkinter.filedialog",
                   "tkinter.messagebox"]


def build(out_dir):
    out_dir = Path(out_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"EXE output directory must be empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    work = ROOT / "build" / "windows_exe"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cli_work = work / "cli"
    gui_dist, cli_dist = work / "gui_dist", work / "cli_dist"
    common = ["--noconfirm", "--clean", "--onedir", "--contents-directory"]
    hidden = [arg for name in HIDDEN_IMPORTS for arg in ("--hidden-import", name)]
    add_data = []
    for source, destination in DATA:
        add_data += ["--add-data", f"{source};{destination}"]
    common_data = ["--distpath", str(gui_dist), "--workpath", str(work / "gui_work"),
                   "--specpath", str(work / "gui_spec"), *add_data]
    gui = subprocess.run([sys.executable, "-m", "PyInstaller", *common, "internal",
                          "--noconsole", "--name", "CKI", "--icon", str(ROOT / "assets" / "cki.ico"),
                          "--version-file", str(ROOT / "tools" / "cki_version_info.txt"),
                          "--paths", str(ROOT / "injector"), "--paths", str(ROOT / "tools"),
                          *hidden, *common_data, str(ROOT / "cki.py")], cwd=ROOT)
    if gui.returncode:
        raise RuntimeError("PyInstaller GUI build failed")
    cli_data = ["--distpath", str(cli_dist), "--workpath", str(cli_work),
                "--specpath", str(work / "cli_spec"), *add_data]
    cli = subprocess.run([sys.executable, "-m", "PyInstaller", *common, "cli_internal",
                          "--console", "--name", "CKI-CLI", "--icon", str(ROOT / "assets" / "cki.ico"),
                          "--version-file", str(ROOT / "tools" / "cki_version_info.txt"),
                          "--paths", str(ROOT / "injector"), "--paths", str(ROOT / "tools"),
                          *hidden, *cli_data, str(ROOT / "cki.py")], cwd=ROOT)
    if cli.returncode:
        raise RuntimeError("PyInstaller CLI build failed")
    gui_dir = gui_dist / "CKI"
    cli_dir = cli_dist / "CKI-CLI"
    shutil.copy2(gui_dir / "CKI.exe", out_dir / "CKI.exe")
    shutil.copytree(gui_dir / "internal", out_dir / "internal", dirs_exist_ok=True)
    shutil.copy2(cli_dir / "CKI-CLI.exe", out_dir / "CKI-CLI.exe")
    shutil.copytree(cli_dir / "cli_internal", out_dir / "cli_internal", dirs_exist_ok=True)
    print(f"GUI: {out_dir / 'CKI.exe'}")
    print(f"CLI worker: {out_dir / 'CKI-CLI.exe'}")
    return out_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        build(args.out)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"EXE build failed: {exc}\n")


if __name__ == "__main__":
    main()
