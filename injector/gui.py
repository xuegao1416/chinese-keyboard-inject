#!/usr/bin/env python3
"""gui.py -- the player-facing window in front of inject_v10.py.

  python injector/gui.py [your_rom.gba]      # needs tkinter (ships with CPython)
  python injector/gui.py --self-test         # no display: checks the wording only

Design rules: the player must never see a stack trace, a command-line flag name, a
raw subprocess log, or an engineer's uncertainty.  Every string below is one a
Chinese GBA player reads and acts on; anything technical is either absent or
reachable behind an explicit "详情" button, which exists only so a bug report can be
written.

It adds no behaviour: it runs `inject_v10.py` as a subprocess and interprets what
comes back.  Two things it deliberately does not do:

  * It never enables the unsafe flag by default, and never names it.  The unchecked
    path is a second confirmation dialog in player words.
  * It does not claim to know whether the host has a Chinese font.  The static
    measure for that exists only in a local probe script and has a recorded false
    negative on the corpus (quetzal_alpha8v2_cn reads 20 KB yet really does render
    Chinese), so warning on it would cry wolf.  Instead the success card states the
    dependency in plain words, because the runtime gate in the payload is what
    silently declines to open Chinese mode on such a host.

In-game key wording comes from README.md (the PAGE tab, 4x8 grid, B deletes one
whole character, SELECT unlocks) rather than being invented here.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INJECTOR = os.path.join(HERE, 'inject_v10.py')
LEDGER = os.path.join(REPO, 'qa', 'validated_hosts.json')

# What the child process says -> what the player is told.  Matched on the raw
# output, but the raw output is never shown (except behind "详情").
CARDS = (
    ('ARM toolchain not found', 'missing_toolchain'),
    ('needs --allow-unvalidated', 'unknown_host'),
    ('not on the validated-host list', 'unknown_host'),
    ('input interface changed', 'redrawn'),
    ('no free space', 'no_room'),
    ('free-space resolver: no uniform', 'no_room'),
    ('not a pokeemerald', 'not_recognised'),
    ('unrecognised', 'not_recognised'),
    ('resolver rejected this ROM', 'not_recognised'),
)

TEXT = {
    'missing_toolchain': (
        '还差一个组件',
        '这台电脑上没有找到编译中文键盘需要的 ARM 编译器（clang 18）。\n'
        '它只影响最后一步：你的 ROM 没有被改动过。\n\n'
        '· 如果你拿到的是完整安装包，请用它——安装包自带这个组件；\n'
        '· 如果你在用源码版，装一个 LLVM 18 就能继续。',
    ),
    'unknown_host': (
        '这台我们没验过',
        '这台输入 ROM 没有独立验证记录，所以工具默认停止。\n'
        '你可以选择继续，但要清楚这一台是你在替我们试。',
    ),
    'redrawn': (
        '这台改过输入界面，工具不动它',
        '这个改版自己重写了选字界面（不是换了字体，是换了一整套）。\n'
        '工具认得出来，所以按设计拒绝修改。你的 ROM 一个字都没被改。',
    ),
    'no_room': (
        '这台装不下',
        '这个 ROM 里没有足够的空闲位置放下载荷（需要约 21 KB 的连续空闲块）。\n'
        '这是硬限制，绕不过去。你的 ROM 没有被改动。',
    ),
    'not_recognised': (
        '没认出这是哪种改版',
        '工具只认按口袋妖怪绿宝石（pokeemerald 系）做的改版，这一份的命名界面不是它认得的形状。\n'
        '你的 ROM 没有被改动。',
    ),
    'ok': ('装好了，可以进游戏了', ''),
    'source_ok': ('源码接入包已生成', ''),
    'pick_file': (
        '还没有选文件',
        '先在上面填一个 ROM 文件的位置，或者点"选择文件…"找到它。\n'
        '你的原文件不会被改动，工具只会另存一个新文件。',
    ),
    'stalled': (
        '这次没走完',
        '工具在半路停下了，这句我没法翻译成你能照着做的下一步。\n'
        '点下面的"详情"把那几行复制出来，发给我们就能查。\n'
        '你的 ROM 可能已经写出一半，别继续用那个输出文件。',
    ),
}

HOWTO = (
    '怎么玩：\n'
    '1. 进游戏，走到第一次起名字那一步；\n'
    '2. 用方向键把光标移到屏幕上的 PAGE 标签，按 A —— 出现 4×8 的中文选字格；\n'
    '3. 方向键选字，A 输入，B 一次删掉一个整字，SELECT 回到原版键盘。'
)

FONT_NOTE = (
    '说明：这个工具不自带汉字，它用的是你这款汉化版自己的字库。\n'
    '如果这款汉化版没有做中文字库，按 PAGE 后中文格不会出来，画面保持原样——\n'
    '不会出现乱码，这是刻意设计的行为。'
)


def sha256(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(block), b''):
            h.update(chunk)
    return h.hexdigest()


def ledger_row(sha):
    """The verified-host row for this exact output, or None.  Matched by sha only."""
    if not sha or not os.path.isfile(LEDGER):
        return None
    with open(LEDGER, encoding='utf-8') as f:
        led = json.load(f)
    for row in led.get('hosts', ()):
        if row.get('output_sha256') == sha:
            return row
    return None


def classify(rc, stdout, stderr, report=None):
    """('card_key', detail_text) -- the whole interpretation layer, display-free."""
    text = (stdout or '') + '\n' + (stderr or '')
    if rc == 0 and report:
        return 'ok', _ok_detail(report)
    for needle, key in CARDS:
        if needle in text:
            return key, TEXT[key][1]
    return 'stalled', TEXT['stalled'][1]


def _ok_detail(report):
    name = os.path.basename(report.get('output', '') or '')
    extra = ''
    row = ledger_row(report.get('output_sha256'))
    if row is not None:
        extra = '\n\n这一台我们在真机上看过截图：'
        extra += ('打完按 PAGE 就能出中文格。' if row.get('font_gate') == 'entered'
                  else '它属于"汉化版没带中文字库"那一类，按 PAGE 不会出中文格。')
    return ('新文件：%s\n它和你的原文件放在同一个文件夹里，原文件没有被改动。'
            '%s\n\n%s\n\n%s' % (name, extra, HOWTO, FONT_NOTE))


def bundled_tools():
    """The toolchain that ships inside the player package, or {} if not bundled.

    `tools/build_windows_package.py` unpacks the four binaries clang needs into
    <repo>/toolchain/bin.  A player must never be asked to install a compiler, so
    when that directory exists it wins over whatever happens to be on PATH -- and
    it is pinned to clang 18.1.3 on purpose: every byte in qa/validated_hosts.json
    came out of that version, so a different compiler is not a cosmetic swap.
    """
    out = {}
    package_root = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else REPO
    base = os.path.join(package_root, 'toolchain', 'bin')
    for flag, names in (('--clang', ('clang.exe', 'clang')),
                        ('--llvm-objcopy', ('llvm-objcopy.exe', 'llvm-objcopy')),
                        ('--nm', ('llvm-nm.exe', 'nm.exe', 'llvm-nm', 'nm'))):
        for n in names:
            p = os.path.join(base, n)
            if os.path.isfile(p):
                out[flag] = p
                break
    return out if len(out) == 3 else {}


def backend_command(script, args):
    if getattr(sys, 'frozen', False):
        cli = os.path.join(os.path.dirname(sys.executable), 'CKI-CLI.exe')
        relative = os.path.relpath(script, REPO)
        return [cli, '--_cki_backend', relative, *args]
    return [sys.executable, script, *args]


def run_injector(rom, out_path, report_path, allow_unvalidated, on_line):
    """Drive inject_v10.py.  Returns (rc, combined output, report path or None).

    `--workdir` is explicit and lives in the temp directory on purpose: the injector's
    default is `build/` next to *its own* tree, which would drop .elf/.ld junk into the
    player's package folder -- and fail outright when that folder is read-only
    (Program Files).  The report goes next to the ROM because that is the one artifact
    a bug report needs.
    """
    cmd = backend_command(INJECTOR, [rom, '-o', out_path, '--report', report_path])
    work = tempfile.mkdtemp(prefix='cki_gui_')
    if allow_unvalidated:
        cmd.append('--allow-unvalidated')
    for flag, path in sorted(bundled_tools().items()):
        cmd += [flag, path]
    try:
        flags = subprocess.CREATE_NO_WINDOW if getattr(sys, 'frozen', False) else 0
        p = subprocess.Popen(cmd + ['--workdir', work], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding='utf-8', errors='replace', bufsize=1,
                             creationflags=flags)
        buf = []
        for line in p.stdout:
            buf.append(line)
            on_line(line.rstrip())
        rc = p.wait()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return rc, ''.join(buf), (report_path if os.path.isfile(report_path) else None)


def run_source_export(output_dir, on_line):
    """Generate a standalone source bundle; no ROM or compiler is required."""
    cmd = backend_command(os.path.join(REPO, 'tools', 'export_source.py'), [output_dir])
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace',
                            creationflags=(subprocess.CREATE_NO_WINDOW
                                           if getattr(sys, 'frozen', False) else 0))
    for line in result.stdout.splitlines():
        on_line(line)
    return result.returncode, result.stdout


# --------------------------------------------------------------------- window
def _card(parent, key, detail, actions):
    """One result card: a headline, a paragraph, and buttons.  No raw output."""
    import tkinter as tk
    from tkinter import ttk
    for w in parent.winfo_children():
        w.destroy()
    head, _ = TEXT[key]
    ttk.Label(parent, text=head, style='CardTitle.TLabel').pack(anchor='w')
    body = detail or TEXT[key][1]
    tk.Label(parent, text=body, justify='left', anchor='w', wraplength=650,
             bg='#FFFFFF', fg='#3D4B5B', font=('Microsoft YaHei UI', 10)).pack(anchor='w', pady=(7, 14))
    bar = ttk.Frame(parent)
    bar.pack(anchor='w')
    for label, cmd in actions:
        ttk.Button(bar, text=label, command=cmd).pack(side='left', padx=(0, 8))


def main(argv):
    argv = [a for a in argv if not a.startswith('-')]
    if '--self-test' in sys.argv:
        return self_test()
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk
    except Exception as exc:                                  # noqa: BLE001
        # Under pythonw.exe (double-clicking 打中文键盘.pyw) there is no console at all,
        # so sys.stderr is None and writing the message would raise AttributeError --
        # the player would see nothing happen.
        msg = ('需要 tkinter（Python 自带）。命令行入口仍然可用：\n'
               '  python injector/inject_v10.py 你的ROM.gba\n（%s）' % exc)
        try:
            import tkinter.messagebox as mb
            mb.showerror('绿宝石汉化版 · 中文选字键盘工具', msg)
        except Exception:                                     # noqa: BLE001
            if sys.stderr:
                sys.stderr.write(msg + '\n')
        return 2

    root = tk.Tk()
    root.title('CKI v1.0 · 绿宝石中文键盘')
    root.geometry('760x620')
    root.minsize(650, 540)
    root.configure(bg='#F3F6FA')
    icon = os.path.join(REPO, 'assets', 'cki.ico')
    if os.path.isfile(icon):
        try:
            root.iconbitmap(icon)
        except Exception:                                 # noqa: BLE001
            pass
    style = ttk.Style(root)
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    style.configure('App.TFrame', background='#F3F6FA')
    style.configure('Panel.TFrame', background='#FFFFFF')
    style.configure('Panel.TLabel', background='#FFFFFF', foreground='#25364A')
    style.configure('CardTitle.TLabel', background='#FFFFFF', foreground='#123B5D',
                    font=('Microsoft YaHei UI', 16, 'bold'))
    style.configure('Mode.TRadiobutton', background='#FFFFFF', foreground='#24364A',
                    font=('Microsoft YaHei UI', 10, 'bold'), padding=(8, 7))
    style.map('Mode.TRadiobutton', foreground=[('selected', '#0F6CBD')],
              background=[('active', '#EEF6FC')])
    style.configure('Go.TButton', font=('Microsoft YaHei UI', 11, 'bold'),
                    padding=(12, 10), background='#0F6CBD', foreground='#FFFFFF')
    style.map('Go.TButton', background=[('active', '#0B5CAD'), ('disabled', '#AAB8C5')],
              foreground=[('disabled', '#F5F7FA')])
    style.configure('TEntry', padding=8, fieldbackground='#FFFFFF')
    style.configure('TButton', padding=(9, 6))

    state = {'rom': tk.StringVar(value=argv[0] if argv else ''),
             'mode': tk.StringVar(value='rom'),
             'busy': False, 'log': [], 'pending': None}

    outer = ttk.Frame(root, padding=(24, 20, 24, 14), style='App.TFrame')
    outer.pack(fill='both', expand=True)

    banner = tk.Frame(outer, bg='#123B5D', padx=20, pady=16)
    banner.pack(fill='x', pady=(0, 16))
    tk.Label(banner, text='CKI  /  绿宝石中文键盘', bg='#123B5D', fg='#FFFFFF',
             font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
    tk.Label(banner, text='给成品 ROM 打补丁，或为 C／Thumb 工程导出接入包  ·  by 脆皮穴糕',
             bg='#123B5D', fg='#D7E7F4', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(4, 0))

    top = ttk.Frame(outer, padding=(16, 13), style='Panel.TFrame')
    top.pack(fill='x', pady=(0, 12))
    ttk.Label(top, text='选择工作方式', style='Panel.TLabel',
              font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w', pady=(0, 5))
    mode_bar = ttk.Frame(top, style='Panel.TFrame')
    mode_bar.pack(fill='x', pady=(0, 5))
    mode_buttons = []
    for label, value in (('给 GBA 文件打补丁', 'rom'), ('导出 C／汇编接入包', 'source')):
        button = ttk.Radiobutton(mode_bar, text=label, value=value, variable=state['mode'],
                                 style='Mode.TRadiobutton', command=lambda: _mode_changed())
        button.pack(side='left', padx=(0, 12))
        mode_buttons.append(button)
    mode_hint = ttk.Label(top, text='使用现成 .gba 文件；原文件保持不变。', style='Panel.TLabel',
                          foreground='#5C6B7A', font=('Microsoft YaHei UI', 9))
    mode_hint.pack(anchor='w', pady=(0, 10))
    path_label = ttk.Label(top, text='要处理的 ROM 文件', style='Panel.TLabel',
                           font=('Microsoft YaHei UI', 9, 'bold'))
    path_label.pack(anchor='w')
    line = ttk.Frame(top, style='Panel.TFrame')
    line.pack(fill='x', pady=(5, 1))
    path_entry = ttk.Entry(line, textvariable=state['rom'])
    path_entry.pack(side='left', fill='x', expand=True)
    browse = ttk.Button(line, text='浏览…', width=12, command=lambda: _browse())
    browse.pack(side='right', padx=(8, 0))

    go = ttk.Button(outer, text='开始', default='active', style='Go.TButton')
    go.pack(fill='x', pady=(0, 12))

    steps = ttk.Frame(outer, padding=(14, 10), style='Panel.TFrame')
    steps.pack(fill='x', pady=(0, 10))
    step_lbl = ttk.Label(steps, text='选一个文件，然后点"开始"。',
                         style='Panel.TLabel', font=('Microsoft YaHei UI', 9))
    step_lbl.pack(anchor='w')
    card = ttk.Frame(outer, padding=(16, 14), style='Panel.TFrame')
    card.pack(fill='both', expand=True)
    ttk.Label(card, text='开始前看这里', style='CardTitle.TLabel').pack(anchor='w')
    tk.Label(card, text='选择 ROM 后，CKI 会检查键盘结构并把补丁另存为新文件。',
             bg='#FFFFFF', fg='#3D4B5B', font=('Microsoft YaHei UI', 10),
             justify='left', anchor='w').pack(anchor='w', pady=(8, 10))
    tk.Label(card, text='进游戏后：PAGE 上按 A 打开中文格  ·  A 输入  ·  B 整字删除\n'
                       'L／R 翻页  ·  SELECT 或 PAGE 返回原版键盘',
             bg='#F0F6FA', fg='#27465E', font=('Microsoft YaHei UI', 9),
             justify='left', anchor='w', padx=12, pady=10).pack(fill='x')
    tk.Label(card, text='当前是 4×8 分页选字，不提供拼音检索。汉字显示依赖 ROM 自带字库。',
             bg='#FFFFFF', fg='#5C6B7A', font=('Microsoft YaHei UI', 9),
             justify='left', anchor='w', wraplength=650).pack(anchor='w', pady=(12, 0))

    foot = ttk.Frame(outer, style='App.TFrame')
    foot.pack(fill='x', side='bottom')
    ttk.Button(foot, text='详情', width=7, command=lambda: _show_log(root, state['log'])).pack(side='right')
    ttk.Label(foot, text='仅支持可识别的绿宝石系改版  ·  原 ROM 不会被覆盖',
              style='App.TLabel', font=('Microsoft YaHei UI', 8), foreground='#526273').pack(side='left')

    def _log(line_):
        state['log'].append(line_)

    def _show_log(parent, lines):
        win = tk.Toplevel(parent)
        win.title('运行记录（给我们报障用）')
        win.geometry('640x360')
        t = tk.Text(win, bg='#111', fg='#ddd', font=('Consolas', 9))
        t.pack(fill='both', expand=True)
        t.insert('1.0', '\n'.join(lines) or '（这次运行还没有记录）')
        t.configure(state='disabled')

    def _browse():
        if state['mode'].get() == 'source':
            directory = filedialog.askdirectory(parent=root, title='选择接入包的保存位置')
            chosen = os.path.join(directory, 'cki_sdk') if directory else ''
        else:
            chosen = filedialog.askopenfilename(parent=root, title='选择你的 ROM',
                                               filetypes=[('GBA ROM', '*.gba *.agb *.bin'),
                                                          ('所有文件', '*.*')])
        if chosen:
            state['rom'].set(chosen)

    def _mode_changed():
        source_mode = state['mode'].get() == 'source'
        state['rom'].set('')
        path_label.configure(text='接入包输出目录（需要为空或尚不存在）' if source_mode else '要处理的 ROM 文件')
        browse.configure(text='选择位置…' if source_mode else '选择文件…')
        go.configure(text='生成接入包' if source_mode else '开始')
        mode_hint.configure(text=('导出独立源码组件；不需要 ROM 或编译器。' if source_mode
                                  else '使用现成 .gba 文件；原文件保持不变。'))
        for widget in card.winfo_children():
            widget.destroy()
        step_lbl.configure(text='生成 C 和 Thumb 汇编接入包；按包内说明连接游戏的字库和命名界面。'
                           if source_mode else '选一个文件，然后点“开始”。')
        step_lbl.pack(anchor='w')

    def _done(args):
        rc, out, report_path, mode = args
        state['busy'] = False
        go.configure(state='normal')
        browse.configure(state='normal')
        path_entry.configure(state='normal')
        for button in mode_buttons:
            button.configure(state='normal')
        step_lbl.configure(text='')
        if mode == 'source':
            detail = ('保存位置：%s\n\n包内含 C 输入核心、C／Thumb 示例与接入说明。\n'
                      '把绘制和按键回调接到你的工程，并确认宿主中文编码和姓名容量。' % state['rom'].get())
            if rc == 0:
                _card(card, 'source_ok', detail, [('打开所在文件夹', lambda: _open_dir(state['rom'].get())),
                                               ('再生成一个', _mode_changed)])
            else:
                _card(card, 'stalled', '接入包没有生成。输出目录必须为空；可以另选一个新目录。\n'
                      '已有文件不会被覆盖。点“详情”查看具体原因。', [('重新选择', _mode_changed)])
            return
        rep = None
        if rc == 0 and report_path:
            with open(report_path, encoding='utf-8') as f:
                rep = json.load(f)
        key, detail = classify(rc, out, '', rep)
        if key == 'unknown_host':
            step_lbl.configure(text='')
            _ask_risk(card, detail, lambda: _start(True))
            return
        actions = [('打开所在文件夹', lambda: _open_dir(state['rom'].get()))] if key == 'ok' else []
        actions.append(('再处理一个', lambda: _reset(card, step_lbl)))
        _card(card, key, detail, actions)

    def _start(allow_unvalidated=False):
        src = state['rom'].get().strip().strip('"')
        mode = state['mode'].get()
        if not src or (mode == 'rom' and not os.path.isfile(src)):
            _card(card, 'pick_file', TEXT['pick_file'][1], [])
            return
        state['busy'] = True
        state['log'] = []
        go.configure(state='disabled')
        browse.configure(state='disabled')
        path_entry.configure(state='disabled')
        for button in mode_buttons:
            button.configure(state='disabled')
        for w in card.winfo_children():
            w.destroy()
        step_lbl.pack(anchor='w')
        step_lbl.configure(text='正在生成接入包…' if mode == 'source' else '正在解析并编译补丁…')
        threading.Thread(target=_work, args=(src, allow_unvalidated, mode), daemon=True).start()

    def _work(src, allow_unvalidated, mode):
        if mode == 'source':
            try:
                rc, out = run_source_export(src, _log)
            except OSError as exc:
                rc, out = 1, str(exc)
                _log(out)
            root.after(0, _done, (rc, out, None, mode))
            return
        d = os.path.dirname(src)
        stem = os.path.splitext(os.path.basename(src))[0]
        try:
            rc, out, rp = run_injector(src, os.path.join(d, stem + '_cki.gba'),
                                      os.path.join(d, stem + '_cki.report.json'),
                                      allow_unvalidated, _log)
        except OSError as exc:
            rc, out, rp = 1, str(exc), None
            _log(out)
        root.after(0, _done, (rc, out, rp, mode))

    def _ask_risk(parent, detail, on_yes):
        import tkinter.messagebox as mb
        for w in parent.winfo_children():
            w.destroy()
        step_lbl.pack_forget()
        head, body = TEXT['unknown_host']
        tk.Label(parent, text=head, font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        tk.Label(parent, text=body, justify='left', anchor='w', wraplength=560,
                 font=('Microsoft YaHei UI', 10)).pack(anchor='w', pady=6)
        bar = ttk.Frame(parent)
        bar.pack(anchor='w', pady=(8, 0))
        ttk.Button(bar, text='算了', command=lambda: _reset(parent, step_lbl)).pack(side='left')

        def yes():
            if mb.askyesno('确认', '这台 ROM 我们从来没见过，打完可能出现：\n'
                                   '键盘没出来、字是乱码、或者存档不认。\n\n'
                                   '确定要继续吗？', parent=root):
                on_yes()
        ttk.Button(bar, text='我知道风险，继续打', command=yes).pack(side='left', padx=8)

    def _reset(parent, lbl):
        for w in parent.winfo_children():
            w.destroy()
        lbl.configure(text='选一个文件，然后点"开始"。')
        lbl.pack(anchor='w')

    def _open_dir(src):
        d = os.path.dirname(os.path.abspath(src.strip().strip('"'))) if src else REPO
        try:
            os.startfile(d)                            # noqa: S606 - Windows only
        except Exception:                              # noqa: BLE001
            pass

    go.configure(command=lambda: _start(False))
    root.mainloop()
    return 0


# ------------------------------------------------------------------- wording
def self_test():
    """The wording is the product surface; prove the mapping without a display."""
    cases = [
        ('缺编译器说人话', 1, 'input host status: validated\n',
         'ARM toolchain not found: clang, llvm-objcopy, nm\n', None, 'missing_toolchain'),
        ('未收录主机不甩术语', 1, 'host x is not validated; needs --allow-unvalidated\n', '',
         None, 'unknown_host'),
        ('换界面不当成故障', 3, 'input interface changed (layout at 0x6d2c7c)\n', '',
         None, 'redrawn'),
        ('装不下', 1, 'no free space within range\n', '', None, 'no_room'),
        ('看不懂的停止承认看不懂', 1, '', 'some crash\nline2\n', None, 'stalled'),
    ]
    bad = 0
    for name, rc, so, se, rep, want_key in cases:
        key, _ = classify(rc, so, se, rep)
        ok = key == want_key
        bad += 0 if ok else 1
        print('%s %s%s' % ('ok  ' if ok else 'FAIL', name, '' if ok else '  -> %s' % key))
    # no player-facing string may contain an internal flag name or a tool path
    leak = [k for k, v in TEXT.items() if '--allow-unvalidated' in str(v) or 'inject_v10' in str(v)]
    leak += [k for k in ('HOWTO', 'FONT_NOTE') if '--' in globals()[k]]
    print('%s 玩家可见文案里没有内部开关名/脚本名' % ('ok  ' if not leak else 'FAIL'))
    bad += 1 if leak else 0
    # every card key this module can hand to _card must have a headline: a missing one
    # is a KeyError dialog on the player's machine, which self_test cannot otherwise see.
    orphans = [k for _needle, k in CARDS if k not in TEXT]
    orphans += [k for k in ('ok', 'stalled', 'pick_file') if k not in TEXT]
    print('%s 每张卡都有标题，不会有卡打不开' % ('ok  ' if not orphans else 'FAIL %s' % orphans))
    bad += 1 if orphans else 0
    print('\n%d case(s), %d failure(s)' % (len(cases) + 2, bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main([a for a in sys.argv[1:] if not a.startswith('-')]))
