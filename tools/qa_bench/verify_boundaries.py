#!/usr/bin/env python3
"""Re-record the existing 27-step naming boundary route against a fresh matrix."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_runtime import capture, digest
sys.path.insert(0, str(ROOT / "tools"))
from check_boundary_route import host_verdict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("matrix_directory")
    args = parser.parse_args()
    matrix = Path(args.matrix_directory).resolve()
    results = []
    for directory in sorted(matrix.iterdir()):
        report_path = directory / "report.json"
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text())
        stem = Path(report["input"]).stem
        old = ROOT / "test_roms" / "qa_20260926" / stem / "scripts"
        route = old / "cki_boundary_nav.txt"
        if not route.exists():
            route = old / "cki_boundary.txt"
        if not route.exists():
            raise RuntimeError("missing recorded route for " + stem)
        script = directory / "boundary.txt"
        script.write_text(route.read_text(encoding="utf-8"), encoding="utf-8")
        if digest(report["output"]) != report["output_sha256"]:
            raise RuntimeError("unbound report for " + stem)
        capture(Path(report["output"]), script, directory / "boundary_final_patched")
        capture(Path(report["input"]), script, directory / "boundary_final_clean")
        ok, fails, notes = host_verdict(str(directory))
        result = {"host": stem, "passed": ok, "failures": fails, "notes": notes,
                  "input_sha256": report["input_sha256"], "output_sha256": report["output_sha256"],
                  "script_sha256": digest(script)}
        results.append(result)
        print(("PASS " if ok else "FAIL ") + stem + (" " + repr(fails) if fails else ""), flush=True)
    if not results:
        raise RuntimeError("no boundary reports tested")
    (matrix / "boundaries.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
