#!/usr/bin/env bash
# Headless acceptance for one host: patched run + unpatched control, same script,
# same default key timing. Written because the harness has three ways to fail
# quietly (out dir must pre-exist; run_capture.sh cd's to itself so every path
# must be absolute; the NS literal is per-host) and this sweep runs hosts in a row.
#
#   tools/qa_bench/qa_one.sh <stem> [<stem> ...]
#
# Reads the NS literal from test_roms/reports_full/<stem>.json, so a host with no
# report is refused rather than run against a borrowed address. That directory is
# the local corpus workbench and is not published with the repository: on a fresh
# clone every stem is refused with "no report", which is the correct outcome.
#
# QA_RD names the output prefix (default run1 -> run1_patched/run1_clean); set it
# when re-verifying so a fresh capture lands beside the archived one.
#
# Each run drops artifact.txt beside its frames. 13 hosts had been accepted on
# screenshots taken before their patched ROM was last rebuilt, and a capture that
# does not record which bytes it ran against cannot be audited later.
set -u
ROOT=${CKI_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}
QA="$ROOT/test_roms/qa_20260926"
HARNESS="$ROOT/qa/harness/cki-headless-qa-1.0"
[ -d "$QA" ] || echo "!! no corpus workbench at $QA - see README '仓库结构'; nothing to verify"

for stem in "$@"; do
  rep="$ROOT/test_roms/reports_full/$stem.json"
  inj="$ROOT/test_roms/injected/${stem}_cki_v10.gba"
  [ -f "$rep" ] || { echo "!! $stem: no report at $rep"; continue; }
  [ -f "$inj" ] || { echo "!! $stem: no patched ROM at $inj"; continue; }

  ns=$(python3 -c "
import json,sys
d=json.load(open('$rep',encoding='utf-8'))
v=(d.get('resolver') or {}).get('naming_screen_global')
print(v if v else '')")
  [ -n "$ns" ] || { echo "!! $stem: report has no naming_screen_global"; continue; }

  # Second per-host literal: the cursor-cell word at gSprites+0x2E (Spr.data[0/1]).
  # Only the boundary route uses it; hosts whose report lacks sprites_global, or a
  # route without the sentinel, skip it and stay on the 1-sentinel probe template.
  gs=$(python3 -c "
import json,sys
d=json.load(open('$rep',encoding='utf-8'))
v=(d.get('resolver') or {}).get('sprites_global')
print(('0x%x' % (int(v,0)+0x2E)) if v else '')")

  # the clean ROM lives under roms/ or roms_noncjk/; the report records which
  clean=$(python3 -c "
import json,os
d=json.load(open('$rep',encoding='utf-8'))
p=d.get('input') or ''
if p.startswith('/mnt/'): p='/'+p
print(os.path.basename(p))")
  src=""
  for dir in "$ROOT/test_roms/roms" "$ROOT/test_roms/roms_noncjk"; do
    [ -f "$dir/$clean" ] && src="$dir/$clean"
  done
  [ -n "$src" ] || { echo "!! $stem: cannot locate clean ROM for '$clean'"; continue; }

  hdir="$QA/$stem"
  mkdir -p "$hdir/scripts"
  # The template lives inside the harness package on purpose: when it was the base
  # case's own script, re-verifying the base case ran `sed tmpl > tmpl`, which
  # truncates the file first and left a 0-byte template behind.
  tmpl=${QA_TMPL:-$HARNESS/scripts/cki_probe_template.txt}
  sname=${QA_SCRIPT_NAME:-cki_probe.txt}
  grep -q '0x02035358' "$tmpl" || { echo "!! $stem: template lost its NS sentinel, refusing"; continue; }
  if [ -z "$gs" ] && grep -q '0x00FF00FF' "$tmpl"; then
    echo "!! $stem: route needs a cursor address but the report has no sprites_global, refusing"
    continue
  fi
  sed -e "s/0x02035358/$ns/g" -e "s/0x00FF00FF/$gs/g" "$tmpl" > "$hdir/scripts/$sname"
  grep -q "$ns" "$hdir/scripts/$sname" \
      || { echo "!! $stem: NS substitution did not land, refusing to run"; continue; }
  if grep -q '0x00FF00FF' "$hdir/scripts/$sname"; then
    echo "!! $stem: cursor sentinel did not land (report has sprites_global? got '$gs'), refusing"
    rm -f "$hdir/scripts/$sname"; continue
  fi

  for kind in patched clean; do
    rom="$inj"; [ "$kind" = clean ] && rom="$src"
    out="$hdir/${QA_RD:-run1}_$kind"
    mkdir -p "$out"
    ( cd "$HARNESS" && bash run_capture.sh "$rom" "$hdir/scripts/$sname" "$out" ) \
        > "$out/run.out" 2>&1
    { echo "rom=$rom"; echo "sha256=$(sha256sum "$rom" | cut -d' ' -f1)";
      echo "script=$hdir/scripts/$sname";
      echo "report=$rep";
      echo "harness=$(sha256sum "$HARNESS/build/gba_capture" | cut -d' ' -f1)"; } > "$out/artifact.txt"
    echo "== $stem / $kind  rc=$?  ns=$ns"
    [ -f "$out/capture.log" ] && sed 's/^/   /' "$out/capture.log"
  done
done
