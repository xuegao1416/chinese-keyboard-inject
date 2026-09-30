#!/usr/bin/env python3
"""Capture a fresh CKI text-switch regression; never overwrite legacy evidence."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "qa" / "harness" / "cki-headless-qa-1.0"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def guest_path(path):
    path = Path(path).resolve()
    if os.name != "nt":
        return str(path)
    return subprocess.check_output(
        ["wsl", "-d", "Ubuntu-24.04", "--", "wslpath", "-a", path.as_posix()],
        text=True).strip()


def capture(rom, script, output):
    output.mkdir(parents=True)
    command = ["bash", guest_path(HARNESS / "run_capture.sh"), guest_path(rom),
               guest_path(script), guest_path(output)]
    if os.name == "nt":
        command = ["wsl", "-d", "Ubuntu-24.04", "--", *command]
    run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (output / "run.out").write_text(run.stdout + run.stderr, encoding="utf-8")
    if run.returncode:
        raise RuntimeError(f"capture failed ({run.returncode}); see {output / 'run.out'}")
    (output / "artifact.json").write_text(json.dumps({
        "rom": str(rom), "rom_sha256": digest(rom), "script_sha256": digest(script),
        "harness_sha256": digest(HARNESS / "build" / "gba_capture"),
    }, indent=2), encoding="utf-8")
    return (output / "capture.log").read_text(encoding="utf-8")


def verify(report_path, output, font):
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rom = Path(report["output"])
    if not rom.is_absolute():
        rom = ROOT / rom
    if digest(rom) != report["output_sha256"]:
        raise ValueError("report does not bind to the requested ROM")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    template = (ROOT / "tools" / "qa_bench" / "text_switch_template.txt").read_text()
    # Some mods have configuration menus before the intro. Reuse the recorded
    # per-host navigation, not a fixed number of A presses on every game.
    stem = Path(report["input"]).stem
    routes = ROOT / "test_roms" / "qa_20260926" / stem / "scripts"
    for name in ("cki_probe_nav.txt", "cki_probe.txt"):
        route = routes / name
        if route.exists():
            prefix, separator, _ = route.read_text(encoding="utf-8").partition('text "naming_reached')
            if separator:
                template = ("ptr C 0x00FF00FF\n" + prefix + template[template.index('shot naming'):])
                break
    # Empty/unreached screens must fail even on a host expected to refuse CJK.
    template = template.replace('shot naming', 'text "naming ptr="\npeek 0x02035358 4 be\ntext " cid="\npeek NS+0x1e23 1\ntext "\\n"\nshot naming', 1)
    if font == "refused":
        template = template.replace('shot entered\n', 'shot entered\nkey LEFT\nframes 60\n', 1)
    script = output / "switch.txt"
    script.write_text(template.replace("0x02035358", report["resolver"]["naming_screen_global"])
                      .replace("0x00FF00FF", hex(int(report["resolver"]["sprites_global"], 0) + 0x2E)),
                      encoding="utf-8")
    log = capture(rom, script, output / "patched")
    alive = re.search(r"^naming ptr=([0-9A-Fa-f]{8}) cid=([0-9A-Fa-f]{2})$", log, re.M)
    if not alive or not (0x02000000 <= int(alive[1], 16) < 0x02040000) or int(alive[2], 16) != 0:
        raise RuntimeError("naming screen not reached, or cursor-id assumption not satisfied")
    if font == "entered":
        expected = ("entered lock=C000", "chinese name=0100FFFFFFFFFFFF",
                    "exited lock=0000 name=0100FFFFFFFFFFFF",
                    "deleted name=FFFFFFFFFFFFFFFF",
                    "latin name=D5FFFFFFFFFFFFFF")
        missing = [line for line in expected if line not in log.splitlines()]
        if missing:
            raise RuntimeError("text-switch regression: " + repr(missing))
    else:
        original = Path(report["input"])
        if not original.is_absolute():
            original = ROOT / original
        if digest(original) != report["input_sha256"]:
            raise ValueError("report does not bind to the clean control")
        clean = capture(original, script, output / "clean")
        if log != clean:
            raise RuntimeError("refused host behavior differs from clean control")
        pixel_exact = True
        for image in (output / "clean" / "png").glob("*.png"):
            if digest(image) != digest(output / "patched" / "png" / image.name):
                pixel_exact = False
        # Gate latency changes animation phase. Use the previously calibrated
        # novelty audit (radius 2, which still catches the known delete ghost).
        sys.path.insert(0, str(ROOT / "tools"))
        from check_refusal_pixels import audit_dirs
        audit = audit_dirs(str(output / "patched"), str(output / "clean"), radius=2)
        if audit is None or audit[0]:
            raise RuntimeError("refused host has novel pixels: " + repr(audit))
    result = {"rom_sha256": digest(rom), "input_sha256": report["input_sha256"],
              "font": font, "passed": True, "capture": str(output),
              "report_sha256": digest(report_path), "script_sha256": digest(script),
              "harness_sha256": digest(HARNESS / "build" / "gba_capture")}
    if font == "refused":
        result.update(pixel_exact=pixel_exact, novel_pixels=0, phase_pixels=audit[1],
                      differing_pixels=audit[2], novelty_radius=2)
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--out", required=True)
    parser.add_argument("--font", choices=("entered", "refused"), required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.report, args.out, args.font), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"QA FAILED: {exc}\n")


if __name__ == "__main__":
    main()
