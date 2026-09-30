"""Decorative labels must not control the font-check geometry."""
import sys
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "injector"))
import inject_v10


class KeyboardOptionsTests(unittest.TestCase):
    def test_flash_alias_to_name_renderer_is_disabled(self):
        self.assertEqual(inject_v10.safe_flash_target({"flash": 0x166040}, 0x08166041), 0)
        self.assertEqual(inject_v10.safe_flash_target({"flash": 0x166080}, 0x08166041), 0x08166081)

    def test_bundled_toolchain_is_found_without_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "toolchain" / "bin" / "clang.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            with patch.object(inject_v10, "REPO", root), patch.object(inject_v10.os, "name", "nt"), patch.object(inject_v10.shutil, "which", return_value=None):
                self.assertEqual(inject_v10.find_tool(inject_v10.CLANG_NAMES), str(binary))

    def test_rom_output_and_report_must_be_distinct(self):
        with self.assertRaises(ValueError):
            inject_v10.validate_output_paths(Path("game.gba"), Path("game.gba"), Path("report.json"))
        with self.assertRaises(ValueError):
            inject_v10.validate_output_paths(Path("game.gba"), Path("patch.gba"), Path("patch.gba"))
        with self.assertRaises(ValueError):
            inject_v10.validate_output_paths(Path("game.gba"), Path("patch.gba"), Path("game.gba"))

    def test_disabling_label_preserves_font_gate_geometry(self):
        windows = {
            "win1": {"base_block": 0x30, "width": 19, "bg": 1},
            "win2": {"base_block": 0xC8, "width": 19, "bg": 2},
        }
        on = inject_v10.keyboard_defines(windows, True)
        off = inject_v10.keyboard_defines(windows, False)
        self.assertEqual(off["CK_ENABLE_LABEL"], 0)
        self.assertEqual(on["CK_ENABLE_LABEL"], 1)
        for key in ("CK_KB_TILEBASE", "CK_KB_TILEBASE2", "CK_KB_WINW",
                    "CK_KB_BG1", "CK_KB_BG2"):
            self.assertEqual(off[key], on[key])
        self.assertEqual(off["CK_KB_WINW"], 19)

    def test_unknown_windows_disable_probe_and_label(self):
        settings = inject_v10.keyboard_defines(None, True)
        self.assertEqual(settings["CK_KB_TILEBASE"], 0)
        self.assertEqual(settings["CK_ENABLE_LABEL"], 0)


if __name__ == "__main__":
    unittest.main()
