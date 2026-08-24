import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from meerk40t import external_plugins_build


class TestBuildExternalPlugins(unittest.TestCase):
    def test_missing_optional_barcode_plugin(self):
        kernel = SimpleNamespace(args=SimpleNamespace(no_plugins=False))
        with patch.dict(
            sys.modules,
            {
                "barcodes": None,
                "barcodes.main": None,
            },
        ):
            plugins = external_plugins_build.plugin(kernel, "plugins")
        self.assertEqual(plugins, [])


if __name__ == "__main__":
    unittest.main()
