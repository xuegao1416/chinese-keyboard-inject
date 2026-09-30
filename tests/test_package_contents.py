import unittest
from pathlib import Path
from tools import build_windows_package


class PackageTests(unittest.TestCase):
    def test_both_backends_and_shared_core_are_in_product(self):
        product = set(build_windows_package.PRODUCT)
        self.assertTrue({'cki.py', 'sdk', 'tools/export_source.py', 'payload'} <= product)

    def test_existing_toolchain_must_contain_all_tools_and_headers(self):
        with self.assertRaises(ValueError):
            build_windows_package.validate_toolchain(Path(__file__).parent)


if __name__ == '__main__':
    unittest.main()
