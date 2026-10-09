import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from tools.build_pinyin_dictionary import generate
from tools.export_source import export_source

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PinyinTests(unittest.TestCase):
    def test_dictionary_mapping_order_and_validation(self):
        text = generate({'爱': '8001', '矮': '8002'}, {'ai': ['矮', '爱', '爱']}, {'爱': 20, '矮': 1})
        self.assertIn('0x8001,0x8002', text)
        self.assertIn('{"ai",0u,2u}', text)
        self.assertIn('0x8002,0x8001', generate({'爱': '8001', '矮': '8002'}, {'ai': ['矮', '爱']}))
        for charset, readings, frequency in [
            ({'爱': '80ff'}, {'ai': ['爱']}, None),
            ({'爱': '8001'}, {'ai': ['矮']}, None),
            ({'爱': '8001'}, {'ai': []}, None),
            ({'爱': '8001'}, {'AI': ['爱']}, None),
            ({'爱': '8001'}, {'ai': ['爱']}, {'爱': -1}),
            ({'爱': '8001', '矮': '8001'}, {'ai': ['爱']}, None),
        ]:
            with self.subTest(charset=charset, readings=readings, frequency=frequency):
                with self.assertRaises(ValueError):
                    generate(charset, readings, frequency)

    def test_exported_pinyin_runtime(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            out = pathlib.Path(directory) / 'bundle'
            result = export_source(out)
            for name in ('cki_pinyin.h', 'cki_pinyin.c', 'cki_pinyin_ui.h', 'cki_pinyin_ui.c'):
                self.assertIn(name, result['files'])
            if shutil.which('gcc'):
                prefix, base = [], str(ROOT)
                location = str(out)
            else:
                prefix = ['wsl', '-d', 'Ubuntu-24.04', '--']
                base = subprocess.check_output(prefix + ['wslpath', '-a', ROOT.as_posix()], text=True, encoding='utf-8').strip()
                location = base + '/' + out.relative_to(ROOT).as_posix()
            target = location + '/pinyin-cases'
            subprocess.run(prefix + ['gcc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                           '-I', location, location + '/cki_pinyin.c', location + '/cki_pinyin_ui.c',
                           base + '/tests/pinyin_cases.c', '-o', target], check=True)
            subprocess.run(prefix + [target], check=True)

    def test_arm_freestanding(self):
        zig = os.environ.get('CKI_ZIG')
        clang = shutil.which('clang')
        if zig:
            compiler = [zig, 'cc', '-target', 'thumb-freestanding-eabi', '-mcpu=arm7tdmi']
        elif clang:
            compiler = [clang, '--target=arm-none-eabi', '-march=armv4t', '-mthumb']
        else:
            self.skipTest('ARM compilation requires Clang or CKI_ZIG pointing to Zig')
        with tempfile.TemporaryDirectory() as directory:
            for name in ('cki_pinyin.c', 'cki_pinyin_ui.c', 'example_pinyin.c'):
                subprocess.run(compiler + ['-std=c99', '-Wall', '-Wextra', '-Werror',
                               '-ffreestanding', '-fno-builtin', '-I', str(ROOT / 'sdk'),
                               '-I', str(ROOT / 'payload'), '-c', str(ROOT / 'sdk' / name),
                               '-o', str(pathlib.Path(directory) / (name + '.o'))], check=True)
