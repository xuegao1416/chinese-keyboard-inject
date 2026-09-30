import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'injector'))
from stock_keyboard_resolver import resolve_stock_keyboard
from resolve_modern import calls
from trampoline import thumb_bl


class StockKeyboardResolverTests(unittest.TestCase):
    def test_three_compiler_variants(self):
        for name, expected in [('bubble128_cn', 0x08165D8D),
                               ('LightPlatinum_v012_mapheader_restore', 0x0818E20D),
                               ('rogue_zh', 0x08128269)]:
            with self.subTest(name=name):
                report = json.loads((ROOT / 'test_roms/reports_full' / (name+'.json')).read_text())
                rom = (ROOT / 'test_roms/roms' / (name+'.gba')).read_bytes()
                self.assertEqual(resolve_stock_keyboard(rom, report['resolver'], report['externals']), expected)
                bad = dict(report['externals'], PutWindowTilemap='0x08000001')
                with self.assertRaises(RuntimeError):
                    resolve_stock_keyboard(rom, report['resolver'], bad)

    def test_corrupted_returns_and_saved_registers_are_refused(self):
        report = json.loads((ROOT / 'test_roms/reports_full/rogue_zh.json').read_text())
        original = (ROOT / 'test_roms/roms/rogue_zh.gba').read_bytes()
        for offset, replacement in [(0x1282BC, b'\x10\xBC'),
                                    (0x1282BA, b'\x30\xBC'),
                                    (0x1282B8, b'\x02\xB0')]:
            with self.subTest(offset=hex(offset)):
                rom = bytearray(original)
                rom[offset:offset+2] = replacement
                with self.assertRaises(RuntimeError):
                    resolve_stock_keyboard(rom, report['resolver'], report['externals'])

    def test_corrupted_high_register_restore_is_refused(self):
        report = json.loads((ROOT / 'test_roms/reports_full/bubble128_cn.json').read_text())
        rom = bytearray((ROOT / 'test_roms/roms/bubble128_cn.gba').read_bytes())
        rom[0x165DDA:0x165DDC] = b'\xB0\x46'  # MOV r8,r6 instead of r8,r7
        with self.assertRaises(RuntimeError):
            resolve_stock_keyboard(rom, report['resolver'], report['externals'])

    def test_duplicate_printer_is_refused(self):
        report = json.loads((ROOT / 'test_roms/reports_full/rogue_zh.json').read_text())
        rom = bytearray((ROOT / 'test_roms/roms/rogue_zh.gba').read_bytes())
        source, dest = 0x128268, 0x128A00
        # Preserve the function and its relative literal pool, but relocate BLs.
        rom[dest:dest+0x64] = rom[source:source+0x64]
        for q, target in calls(rom, source, 0x58):
            site = dest + q-source
            rom[site:site+4] = thumb_bl(0x08000000+site, target)
        with self.assertRaisesRegex(RuntimeError, 'candidates=.*0x8128269.*0x8128a01'):
            resolve_stock_keyboard(rom, report['resolver'], report['externals'])


if __name__ == '__main__':
    unittest.main()

