#!/usr/bin/env python3
"""Assemble the CKI 1.0 Windows release package with a pinned toolchain.

  python tools/build_windows_package.py --archive <LLVM-18.1.3-win64.exe> [--out dist/]
  python tools/build_windows_package.py --toolchain-dir dist/CKI-18.1.3-win64/toolchain --verify

Why the toolchain goes inside the package: `inject_v10.py` compiles the payload on
the machine it runs on (the payload is built per host from ~20 `-DCK_*` defines, 12
of which are that host's function addresses), so a player cannot be asked to install
a compiler -- and a player who happens to have one is not safe either.  Every byte
in `qa/validation.json` came out of clang 18.1.3, so "any LLVM" is a different
claim from "the compiler that produced the screenshots we verified".  This script
ships that exact build, and `--verify` is what turns the claim from intent into a
measurement: it injects the flagship host with the *bundled* binaries and compares
the output against the ledger.

What it refuses to do:

  * Ship an unpinned compiler.  The archive name must carry the version, and the
    version must equal PINNED_CLANG, because a silent upgrade here invalidates the
    whole evidence chain without changing a single source line.
  * Produce a package whose payload bytes differ from the ledger's and call it done.
    Without --verify the script says so in its own output.

The archive is an NSIS installer, not a zip.  7z reads it, so no installer ever runs
and nothing is written to the system.  What goes into the package is four executables
(clang, ld.lld, llvm-objcopy, llvm-nm -- 232 MB unpacked, ~75 MB compressed) plus
clang's own freestanding headers, because clang is not self-contained: without
`lib/clang/18/include` it dies on the first `#include`.  Sizes measured on 18.1.3.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINNED_CLANG = '18.1.3'
# clang compiles and (via -fuse-ld=lld) links; llvm-objcopy extracts the flat blob;
# llvm-nm reads back symbol addresses.  ld.lld.exe must sit next to clang.exe or the
# driver cannot find it, which is why TOOLS is not just the three flags gui.py passes.
# lld.exe itself is the *same binary* under its multicall name and is never invoked by
# the driver, so it is not shipped (it would double the package for nothing).
TOOLS = ('bin/clang.exe', 'bin/ld.lld.exe',
         'bin/llvm-objcopy.exe', 'bin/llvm-nm.exe')
# clang is not self-contained: it reads its freestanding headers (stdint.h and friends)
# from <dir-of-clang>/../lib/clang/<major>/include.  Shipping only the exes compiles
# until the first #include and then dies with "'stdint.h' file not found" -- on the
# player's machine, at the compile step.  So the resource tree goes along, at exactly
# the relative path the driver expects.
HEADER_ROOT = 'lib/clang/'
# `docs/` ships because README.md is the package's only manual and every link in it
# points there; a player following one would otherwise hit a missing directory.
PRODUCT = ('cki.py', 'injector', 'payload', 'sdk', 'tools/export_source.py',
           'tools/build_windows_exe.py', 'tools/cki_version_info.txt',
           'requirements-build.txt', 'assets', 'docs',
           '打中文键盘.pyw', 'README.md', 'LICENSE', 'CREDITS.md', 'CITATION.cff',
           'LICENSE_NOTE.md')
PROJECT_VERSION = 'v1.0'
LEDGER = os.path.join('qa', 'validated_hosts.json')
FLAGSHIP = 'LightPlatinum_v012_mapheader_restore'


def sevenz():
    for cand in (shutil.which('7z'), shutil.which('7za'),
                 os.path.expanduser('~/scoop/shims/7z.exe'),
                 r'C:\Program Files\7-Zip\7z.exe'):
        if cand and os.path.isfile(cand):
            return cand
    sys.exit('need 7z to read the LLVM installer (scoop install 7zip, or install 7-Zip)')


def listing(z, archive):
    """Every path 7z can see inside the installer.

    `7z l -slt` prints `Path = <member>`; slicing by a fixed 5 characters leaves a
    leading `= ` on every name, which then matches nothing and looks like "this
    archive has the wrong layout".  Split on the first `=` instead.
    """
    r = subprocess.run([z, 'l', '-slt', '-ba', archive], capture_output=True,
                       text=True, errors='replace')
    if r.returncode != 0:
        sys.exit('7z could not read %s:\n%s' % (archive, (r.stdout + r.stderr)[-600:]))
    out = []
    for ln in r.stdout.splitlines():
        if ln.startswith('Path = '):
            out.append(ln.split('=', 1)[1].strip())
    return out


def extract(archive, out_dir, z):
    r"""Pull TOOLS plus clang's builtin headers out of the installer.

    The archive is an NSIS installer; 7z reads it without ever running it, so no
    registry key, PATH edit, or admin prompt is involved.  Member paths depend on how
    LLVM happened to be packaged (this one keeps its tools at top-level
    `bin/clang.exe`), so they are resolved from a live listing rather than hardcoded,
    and a missing member is a hard stop: a package that silently lacks ld.lld.exe
    fails only on the player's machine, at the compile step, with the message this
    whole route exists to avoid.  The headers must land at
    `<pkg>/toolchain/lib/clang/<major>/include`, because that is the one path the
    driver derives from its own location -- flattening them is not an option.
    """
    norm = [p.replace('\\', '/') for p in listing(z, archive)]
    want = {}
    for rel in TOOLS:
        name = os.path.basename(rel)
        hit = [p for p in norm if p.rsplit('/', 1)[-1] == name
               and len(p.split('/')) > 1
               and os.path.dirname(p).lower().rsplit('/', 1)[-1] == 'bin']
        if not hit:
            sys.exit('%s not found inside %s -- this archive is not the layout the '
                     'packager expects, refusing to ship a partial toolchain'
                     % (name, os.path.basename(archive)))
        want[name] = hit[0]
    major = PINNED_CLANG.split('.')[0]
    hdr_root = 'lib/clang/%s/include' % major
    headers = [p for p in norm if p.startswith(hdr_root + '/') and '/' in p[len(hdr_root):]]
    if not headers:
        sys.exit('%s (clang\'s freestanding headers: stdint.h and friends) is not in '
                 '%s -- clang cannot compile a single file without them, refusing to '
                 'ship a toolchain that only looks complete' % (hdr_root,
                                                                os.path.basename(archive)))
    bindir = os.path.join(out_dir, 'bin')
    os.makedirs(bindir, exist_ok=True)
    tmp = os.path.join(out_dir, '_x')
    r = subprocess.run([z, 'x', '-y', '-o' + tmp, archive]
                       + list(want.values()) + headers,
                       capture_output=True, text=True, errors='replace')
    if r.returncode != 0:
        sys.exit('7z extract failed:\n%s' % (r.stdout + r.stderr)[-600:])
    for name, member in want.items():
        src = os.path.join(tmp, member.replace('/', os.sep))
        if not os.path.isfile(src):                       # listing may be archive-rooted
            flat = os.path.join(tmp, name)
            src = flat if os.path.isfile(flat) else src
        if not os.path.isfile(src):
            sys.exit('7z reported %s but did not write it' % name)
        shutil.copy2(src, os.path.join(bindir, name))
    src_root = os.path.join(tmp, hdr_root.replace('/', os.sep))
    if not os.path.isdir(src_root):
        sys.exit('7z reported %d header(s) but wrote no %s directory'
                 % (len(headers), hdr_root))
    dst_root = os.path.join(out_dir, hdr_root.replace('/', os.sep))
    shutil.copytree(src_root, dst_root, dirs_exist_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    print('headers: %d member(s) -> %s' % (len(headers), hdr_root))
    return bindir


def verify(out_root):
    """Inject the flagship with the bundled toolchain and compare to the ledger.

    This is the whole point of the exercise: it is the only check that says
    "a player who double-clicks this package gets the ROM we actually verified".
    """
    import json
    bindir = os.path.join(out_root, 'toolchain', 'bin')
    tools = {'--clang': os.path.join(bindir, 'clang.exe'),
             '--llvm-objcopy': os.path.join(bindir, 'llvm-objcopy.exe'),
             '--nm': os.path.join(bindir, 'llvm-nm.exe')}
    src = None
    for d in ('test_roms/roms', 'test_roms/roms_noncjk'):
        p = os.path.join(ROOT, d, FLAGSHIP + '.gba')
        if os.path.isfile(p):
            src = p
            break
    if not src:
        return False, 'flagship input %s.gba not in the local corpus' % FLAGSHIP
    with open(os.path.join(ROOT, 'qa', 'validation.json'), encoding='utf-8') as f:
        led = json.load(f)
    row = next((h for h in led['hosts'] if h['host'] == FLAGSHIP and h['passed']), None)
    if row is None:
        return False, 'flagship has no fresh development validation record'
    work = os.path.join(ROOT, 'build', 'pkg_verify')
    os.makedirs(work, exist_ok=True)
    out = os.path.join(work, FLAGSHIP + '_cki_v10.gba')
    cmd = [sys.executable, os.path.join(ROOT, 'injector', 'inject_v10.py'), src,
           '-o', out, '--report', os.path.join(work, FLAGSHIP + '.json'),
           '--workdir', os.path.join(work, 'w'), '--toolchain', 'clang']
    for k, v in tools.items():
        cmd += [k, v]
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    if r.returncode != 0:
        return False, 'injection failed: %s' % (r.stdout + r.stderr)[-400:]
    import hashlib
    h = hashlib.sha256()
    with open(out, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    got = h.hexdigest()
    return got == row['output_sha256'], 'bundled-clang output %s v1.0 validation (%s…)' % (
        'MATCHES' if got == row['output_sha256'] else 'DIFFERS FROM',
        row['output_sha256'][:12])


def validate_toolchain(directory):
    from pathlib import Path
    directory = Path(directory).resolve()
    expected = list(TOOLS) + ['lib/clang/18/include/stdint.h']
    missing = [name for name in expected if not (directory / name).is_file()]
    if missing:
        raise ValueError('incomplete toolchain: ' + ', '.join(missing))
    version = subprocess.check_output([str(directory / 'bin/clang.exe'), '--version'], text=True)
    if not re.search(r'clang version ' + re.escape(PINNED_CLANG) + r'\b', version):
        raise ValueError('toolchain is not clang ' + PINNED_CLANG)
    return directory


def build(archive, out_dir, toolchain_dir=None, exe_dir=None):
    if archive:
        ver = re.findall(r'(\d+\.\d+\.\d+)', os.path.basename(archive))
        if not ver or ver[0] != PINNED_CLANG:
            sys.exit('archive must be LLVM %s' % PINNED_CLANG)
    elif toolchain_dir is not None:
        toolchain_dir = validate_toolchain(toolchain_dir)
    else:
        raise ValueError('archive or existing toolchain required')
    pkg = os.path.join(out_dir, 'CKI-%s-win64' % PROJECT_VERSION)
    os.makedirs(pkg, exist_ok=True)
    if toolchain_dir is not None:
        shutil.copytree(toolchain_dir, os.path.join(pkg, 'toolchain'), dirs_exist_ok=True)
        bindir = os.path.join(pkg, 'toolchain', 'bin')
    else:
        bindir = extract(archive, os.path.join(pkg, 'toolchain'), sevenz())
    moved = []
    for f in os.listdir(bindir):
        if f in {os.path.basename(t) for t in TOOLS}:
            moved.append('%s %.1f MB' % (f, os.path.getsize(os.path.join(bindir, f)) / 1048576))
    for name in PRODUCT:
        s = os.path.join(ROOT, name)
        if not os.path.exists(s):
            sys.exit('product file %s is missing from the repo' % name)
        d = os.path.join(pkg, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
    os.makedirs(os.path.join(pkg, 'qa'), exist_ok=True)
    shutil.copy2(os.path.join(ROOT, LEDGER), os.path.join(pkg, LEDGER))
    for name in ('validation.json', 'VALIDATION.md'):
        shutil.copy2(os.path.join(ROOT, 'qa', name), os.path.join(pkg, 'qa', name))
    if exe_dir is not None:
        exe_dir = os.path.abspath(exe_dir)
        required = ('CKI.exe', 'CKI-CLI.exe', 'internal', 'cli_internal')
        missing = [name for name in required if not os.path.exists(os.path.join(exe_dir, name))]
        if missing:
            raise ValueError('incomplete EXE build: ' + ', '.join(missing))
        for name in required:
            src = os.path.join(exe_dir, name)
            dst = os.path.join(pkg, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
    print('package: %s' % pkg)
    print('toolchain: %s' % ', '.join(sorted(moved)))
    zipname = os.path.join(out_dir, os.path.basename(pkg) + '.zip')
    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, _d, files in os.walk(pkg):
            for f in files:
                p = os.path.join(base, f)
                z.write(p, os.path.relpath(p, out_dir))
    print('archive: %s (%.1f MB)' % (zipname, os.path.getsize(zipname) / 1048576))
    return pkg


def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--archive', help='LLVM-%s-win64.exe on disk' % PINNED_CLANG)
    source.add_argument('--toolchain-dir', help='existing pinned toolchain directory')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    ap.add_argument('--exe-dir', help='directory produced by tools/build_windows_exe.py')
    ap.add_argument('--verify', action='store_true',
                    help='inject the flagship with the bundled compiler and compare '
                         'against qa/validation.json before calling it shippable')
    a = ap.parse_args()
    if a.archive and not os.path.isfile(a.archive):
        sys.exit('no archive at %s -- fetch it first (the release asset is ~357 MB)'
                 % a.archive)
    pkg = build(a.archive, a.out, a.toolchain_dir, a.exe_dir)
    if not a.verify:
        print('\nNOT VERIFIED: this package has not been shown to reproduce the '
              'ledger bytes. Re-run with --verify.')
        return 0
    ok, msg = verify(pkg)
    print(('VERIFIED: ' if ok else 'FAILED: ') + msg)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
