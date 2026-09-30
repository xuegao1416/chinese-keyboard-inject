#!/usr/bin/env python3
"""Unified CKI entry point: ROM inspection/injection and C/Thumb source export."""
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
VERSION = "1.0"

HELP = """CKI 1.0 — 绿宝石中文键盘工具

用法:
  CKI.exe                               打开桌面工具
  CKI-CLI.exe inspect ROM [选项]        解析和预检，不写 ROM
  CKI-CLI.exe inject ROM [选项]         给 GBA 文件注入补丁
  CKI-CLI.exe source 目录 [选项]        导出 C / Thumb 汇编接入包

示例:
  CKI-CLI.exe inject game.gba -o game_cki.gba
  CKI-CLI.exe source my-project/cki

inspect / inject 使用注入器的选项；source 支持 --charset JSON。
在子命令后加 --help 可查看详细参数。
宿主必须支持接入包所用的中文编码与字库；补丁不扩容存档姓名字段。
"""


def run_backend(script, args):
    if getattr(sys, "frozen", False):
        script = Path(script).resolve()
        sys.path.insert(0, str(script.parent))
        sys.argv = [str(script), *args]
        runpy.run_path(str(script), run_name="__main__")
        return 0
    try:
        return subprocess.call([sys.executable, str(script), *args])
    except OSError as exc:
        print(f"无法运行 CKI：{exc}", file=sys.stderr)
        return 1


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--_cki_backend"]:
        if len(args) < 2:
            print("Missing internal backend", file=sys.stderr)
            return 2
        return run_backend(ROOT / args[1], args[2:])
    if not args:
        return run_backend(ROOT / "injector" / "gui.py", [])
    command, *rest = args
    if command in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if command == "--version":
        print(f"CKI {VERSION}")
        return 0
    if command in ("inspect", "inject"):
        if command == "inspect" and "--dry-run" not in rest:
            rest.append("--dry-run")
        return run_backend(ROOT / "injector" / "inject_v10.py", rest)
    if command == "source":
        return run_backend(ROOT / "tools" / "export_source.py", rest)
    print(f"未知操作：{command}\n{HELP}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
