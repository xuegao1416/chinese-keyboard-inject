"""Execute the freestanding C core, then check its GBA target compilation."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TextCoreTests(unittest.TestCase):
    def test_executable_regressions(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            target = pathlib.Path(directory) / "cases"
            if shutil.which("gcc"):
                subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "payload"), str(ROOT / "tests/text_core_cases.c"), "-o", str(target)], check=True)
                subprocess.run([str(target)], check=True)
            else:
                # The supported Windows development environment supplies Ubuntu WSL.
                source = subprocess.check_output(["wsl", "-d", "Ubuntu-24.04", "--", "wslpath", "-a", ROOT.as_posix()], text=True).strip()
                out = source + "/" + target.relative_to(ROOT).as_posix()
                subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", "gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", source + "/payload", source + "/tests/text_core_cases.c", "-o", out], check=True)
                subprocess.run(["wsl", "-d", "Ubuntu-24.04", "--", out], check=True)

    def test_armv4t_freestanding(self):
        bundled = ROOT / "dist/CKI-18.1.3-win64/toolchain/bin/clang.exe"
        compiler = str(bundled) if bundled.exists() else shutil.which("clang")
        self.assertIsNotNone(compiler, "Clang is required for ARMv4T validation")
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([compiler, "--target=arm-none-eabi", "-march=armv4t", "-mthumb", "-ffreestanding", "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "payload"), "-c", str(ROOT / "tests/text_core_cases.c"), "-o", str(pathlib.Path(directory) / "cases.o")], check=True)


if __name__ == "__main__":
    unittest.main()
