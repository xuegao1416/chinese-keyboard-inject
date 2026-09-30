import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "injector"))
import gui


class GuiSourceTests(unittest.TestCase):
    def test_real_unknown_host_message_offers_supported_retry(self):
        key, _ = gui.classify(2, '', 'input abc is not on the validated-host list (ledger) and no --oracle-map confirmed it.')
        self.assertEqual(key, 'unknown_host')

    def test_source_export_works_without_a_rom_or_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "cki"
            lines = []
            rc, output = gui.run_source_export(str(target), lines.append)
            self.assertEqual(rc, 0, output)
            self.assertTrue((target / "cki_keyboard.c").exists())
            self.assertTrue(lines)
            rc, output = gui.run_source_export(str(target), lines.append)
            self.assertNotEqual(rc, 0)
            self.assertIn("refusing overwrite", output)


if __name__ == "__main__":
    unittest.main()
