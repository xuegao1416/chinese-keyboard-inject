#!/usr/bin/env python3
"""Build and run a fresh matrix without changing CKI 1.0 ROMs or evidence."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_runtime import verify


def one(row, output, no_label):
    stem = Path(row["rom"]).stem
    directory = output / (stem + ("_no_label" if no_label else ""))
    directory.mkdir(parents=True)
    matches = list(ROOT.glob("test_roms/roms*/" + row["rom"]))
    if len(matches) != 1:
        return {"host": stem, "passed": False, "reason": "expected exactly one input ROM"}
    report = directory / "report.json"
    cmd = [sys.executable, str(ROOT / "cki.py"), "inject", str(matches[0]),
           "-o", str(directory / "patched.gba"), "--report", str(report),
           "--workdir", str(directory / "work")]
    if no_label:
        cmd.append("--no-cn-label")
    run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (directory / "build.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    if run.returncode:
        return {"host": stem, "passed": False, "exit_code": run.returncode,
                "reason": (run.stdout + run.stderr)[-1000:]}
    try:
        result = verify(report, directory / "capture", row["font_gate"])
        result.update(host=stem, no_label=no_label, output_sha256=result["rom_sha256"])
        return result
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        return {"host": stem, "passed": False, "reason": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--hosts", nargs="*")
    parser.add_argument("--no-label", action="store_true")
    parser.add_argument("--jobs", type=int, default=3, choices=range(1, 5))
    args = parser.parse_args()
    output = Path(args.out).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("output must be new or empty")
    ledger = json.loads((ROOT / "qa" / "validated_hosts.json").read_text(encoding="utf-8"))
    rows = [row for row in ledger["hosts"]
            if args.hosts is None or Path(row["rom"]).stem in args.hosts]
    if not rows:
        parser.error("no hosts selected")
    if args.hosts and {Path(row["rom"]).stem for row in rows} != set(args.hosts):
        parser.error("one or more requested hosts are absent from the input ledger")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        jobs = [executor.submit(one, row, output, args.no_label) for row in rows]
        for job in as_completed(jobs):
            try:
                result = job.result()
            except Exception as exc:
                result = {"host": "runner", "passed": False, "reason": str(exc)}
            results.append(result)
            print(("PASS " if result["passed"] else "FAIL ") + result["host"], flush=True)
    results.sort(key=lambda result: result["host"])
    summary = {"project_version": "1.0", "route": "text-switch",
               "hosts": results, "passed": sum(row["passed"] for row in results),
               "total": len(results)}
    (output / "matrix.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{summary['passed']}/{summary['total']} passed; {output / 'matrix.json'}")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
