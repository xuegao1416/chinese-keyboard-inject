import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class UnifiedCliTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("cki", ROOT / "cki.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_inspect_forces_read_only_pipeline(self):
        with patch.object(self.module, "run_backend", return_value=2) as run:
            result = self.module.main(["inspect", "game.gba", "--oracle-map", "game.map"])
        self.assertEqual(result, 2)
        self.assertEqual(run.call_args.args[1], ["game.gba", "--oracle-map", "game.map", "--dry-run"])

    def test_inject_preserves_backend_arguments_and_exit_code(self):
        with patch.object(self.module, "run_backend", return_value=3) as run:
            result = self.module.main(["inject", "game.gba", "-o", "patched.gba", "--no-cn-label"])
        self.assertEqual(result, 3)
        self.assertEqual(run.call_args.args[1], ["game.gba", "-o", "patched.gba", "--no-cn-label"])

    def test_source_dispatches_exporter(self):
        with patch.object(self.module, "run_backend", return_value=0) as run:
            result = self.module.main(["source", "sdk-output", "--charset", "codes.json"])
        self.assertEqual(result, 0)
        self.assertEqual(Path(run.call_args.args[0]).name, "export_source.py")
        self.assertEqual(run.call_args.args[1], ["sdk-output", "--charset", "codes.json"])

    def test_no_arguments_opens_existing_gui(self):
        with patch.object(self.module, "run_backend", return_value=0) as run:
            self.module.main([])
        self.assertEqual(Path(run.call_args.args[0]).name, "gui.py")


if __name__ == "__main__":
    unittest.main()
