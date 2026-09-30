#!/usr/bin/env python3
"""Reconstruct a "pre-injection equivalent" ROM from an injected output.

Test ROMs are usually only available as already-patched output, so this script
undoes the injection: it restores the recorded original bytes at every patch site
and returns the payload region to its original fill byte. The result is
byte-equivalent to the pre-injection ROM for every region the injector touched,
which is enough to re-run the whole resolver / free-space / pre-check pipeline.

  python tools/reconstruct_preinject.py patched.gba scratch/preinject.gba \
      --report qa/report_v10_clang_route.json

Everything is read out of the report - the patch sites and their original bytes,
the payload offset and size, and the pre-injection SHA256 used to verify the
result. Nothing about any particular ROM is hardcoded here, so reports from either
compile route (`report_v10_clang_route.json`, `report_v10_gnu_route.json`) work.

ROMs are never copied into the repository - point the output at a scratch path.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def sites_from_report(rep):
    """(label, file offset, original bytes) for every site the injector wrote."""
    sites = []
    if "handler_table" in rep:
        h = rep["handler_table"]
        sites.append(("key-handler table", int(h["offset"], 16), bytes.fromhex(h["old"])))
    if "delete_hook" in rep:
        h = rep["delete_hook"]
        sites.append(("delete hook", int(h["offset"], 16), bytes.fromhex(h["old"])))
    if "frame_hook" in rep:
        h = rep["frame_hook"]
        sites.append(("frame hook", int(h["offset"], 16), bytes.fromhex(h["old"])))
    for name, h in (rep.get("hooks") or {}).items():
        sites.append((f"{name} hook", int(h["offset"], 16), bytes.fromhex(h["old"])))
    return sites


def payload_region(rep):
    p = rep.get("payload") or {}
    off = p.get("offset") or rep.get("payload_offset")
    size = p.get("size") or rep.get("payload_size")
    if off is None or size is None:
        raise SystemExit("report has no payload offset/size - is this an injector report?")
    return int(off, 16), int(size)


def infer_fill(rom, free, size):
    """The injector's fill byte, read from a region it did not overwrite.

    Only [free, free+size) was written. The injector requires a uniform run that
    is larger than the payload, so the bytes just past the payload are still the
    original fill. Fall back to scanning backwards if that ever is not the case.
    """
    for off in range(free + size, min(len(rom), free + size + 0x1000)):
        if rom[off] in (0, 0xFF):
            return rom[off]
    for off in range(free - 1, max(-1, free - 0x1000), -1):
        if rom[off] in (0, 0xFF):
            return rom[off]
    return 0xFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patched")
    ap.add_argument("out")
    ap.add_argument("--report", required=True,
                    help="the report the injector wrote (its patch sites, payload "
                         "region, and input SHA256 drive everything)")
    ap.add_argument("--fill", help="fill byte for the payload region (default: inferred)")
    a = ap.parse_args()

    rom = bytearray(Path(a.patched).read_bytes())
    rep = json.loads(Path(a.report).read_text())
    print(f"report {a.report}")
    print(f"  format {rep.get('format')}  project version {rep.get('project_version', '?')}")
    if rep.get("output_sha256") and hashlib.sha256(bytes(rom)).hexdigest() != rep["output_sha256"]:
        raise SystemExit("this ROM is not the output that report describes "
                         "(sha256 mismatch) - refusing to reconstruct")

    sites = sites_from_report(rep)
    if not sites:
        raise SystemExit("report lists no patch sites")
    free, size = payload_region(rep)

    fill = int(a.fill, 16) if a.fill else infer_fill(rom, free, size)
    if fill not in (0, 0xFF):
        print(f"warning: inferred fill byte {fill:#04x}, expected 0x00/0xFF", file=sys.stderr)
    rom[free:free + size] = bytes([fill]) * size
    print(f"payload region {free:#x}..{free + size:#x} ({size} bytes) -> {fill:#04x}")

    for name, off, exp in sites:
        n = len(exp)
        print(f"{name:20s} {off:#x}: {rom[off:off + n].hex()} -> {exp.hex()}")
        rom[off:off + n] = exp

    Path(a.out).write_bytes(rom)
    print(f"wrote {a.out}")

    want = rep.get("input_sha256")
    if want:
        got = hashlib.sha256(bytes(rom)).hexdigest()
        print(f"reconstructed sha256 {got}")
        print(f"report input_sha256  {want}")
        if got == want:
            print("reconstruction VERIFIED")
        else:
            print("reconstruction MISMATCH", file=sys.stderr)
            raise SystemExit(1)


if __name__ == "__main__":
    main()
