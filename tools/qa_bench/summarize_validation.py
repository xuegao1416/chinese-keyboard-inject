#!/usr/bin/env python3
"""Publish hashes and verdicts from fresh local captures, without distributing ROMs."""
import json
from pathlib import Path

from verify_runtime import digest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "build/v2_matrix_verified"
NO_LABEL = ROOT / "build/v2_no_label_verified"
EXPECTED_ENTERED = ("entered lock=C000", "chinese name=0100FFFFFFFFFFFF",
                    "exited lock=0000 name=0100FFFFFFFFFFFF",
                    "deleted name=FFFFFFFFFFFFFFFF",
                    "latin name=D5FFFFFFFFFFFFFF")


def rows(directory):
    matrix = json.loads((directory / "matrix.json").read_text(encoding="utf-8"))
    result = []
    for row in matrix["hosts"]:
        item = {key: row[key] for key in ("host", "passed")}
        if not row["passed"]:
            item["outcome"] = "resolver_refused"
            item["reason"] = row["reason"].splitlines()[0]
            result.append(item)
            continue
        capture = Path(row["capture"])
        report = json.loads((capture.parent / "report.json").read_text(encoding="utf-8"))
        log = (capture / "patched/capture.log").read_text(encoding="utf-8")
        if row["font"] == "entered" and not all(line in log.splitlines() for line in EXPECTED_ENTERED):
            raise ValueError("incomplete entered-host route: " + row["host"])
        if digest(report["output"]) != row["output_sha256"]:
            raise ValueError("ROM hash mismatch: " + row["host"])
        if digest(capture / "switch.txt") != row["script_sha256"]:
            raise ValueError("route hash mismatch: " + row["host"])
        verdict = json.loads((capture / "result.json").read_text(encoding="utf-8"))
        if not verdict["passed"] or verdict["rom_sha256"] != row["output_sha256"]:
            raise ValueError("unbound runtime result: " + row["host"])
        item.update(input_sha256=row["input_sha256"], output_sha256=row["output_sha256"],
                    font_gate=row["font"], no_label=row["no_label"],
                    script_sha256=row["script_sha256"], harness_sha256=row["harness_sha256"])
        if row["font"] == "refused":
            item.update(novel_pixels=row["novel_pixels"], novelty_radius=row["novelty_radius"])
        result.append(item)
    return result


def main():
    main_rows = rows(MAIN)
    boundaries = json.loads((MAIN / "boundaries.json").read_text(encoding="utf-8"))
    if len(boundaries) != 24 or not all(row["passed"] for row in boundaries):
        raise ValueError("boundary routes incomplete")
    for row in boundaries:
        item = next((x for x in main_rows if x["host"] == row["host"]), None)
        if not item or item.get("output_sha256") != row["output_sha256"]:
            raise ValueError("unbound boundary route: " + row["host"])
    no_label = rows(NO_LABEL)
    if len(no_label) != 3 or not all(row["passed"] for row in no_label):
        raise ValueError("no-label routes incomplete")
    manifest = {"format": "CKI-1.0-QA1", "project_version": "1.0",
                "note": "Release validation on the local ROM corpus. No ROMs are included. One input is safely refused.",
                "hosts": main_rows, "boundary_27_step_passed": len(boundaries),
                "no_label_hosts": no_label, "unit_tests_passed": 23}
    target = ROOT / "qa/validation.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{sum(x['passed'] for x in main_rows)}/{len(main_rows)} hosts; "
          f"{len(boundaries)} boundaries; {len(no_label)} no-label: {target}")


if __name__ == "__main__":
    main()
