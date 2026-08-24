import os
import tempfile
import unittest

from meerk40t.core import core
from meerk40t.device import basedevice
from meerk40t.gcc import plugin as gcc_plugin
from meerk40t.gcc.device import GCCDevice
from meerk40t.kernel import Kernel


class TestDriverGCCIntegration(unittest.TestCase):
    def setUp(self):
        self.kernel = Kernel(
            "MeerK40t",
            "0.0.0-testing",
            "MeerK40t_TEST_gcc",
            ansi=False,
            ignore_settings=True,
        )
        self.kernel.add_plugin(basedevice.plugin)
        self.kernel.add_plugin(core.plugin)
        self.kernel.add_plugin(gcc_plugin.plugin)
        self.kernel(partial=True)

        provider = self.kernel.lookup("provider/device/gcc")
        info = self.kernel.lookup("dev_info/gcc-laserpro")
        self.device = provider(
            self.kernel,
            "gcc",
            choices=info["choices"],
        )
        self.kernel.add_service(
            "device", self.device, registered_path="provider/device/gcc"
        )
        self.kernel.activate("device", self.device, assigned=True)

    def tearDown(self):
        self.kernel()

    def test_mercury_profile_registration(self):
        self.assertIsInstance(self.device, GCCDevice)
        self.assertEqual(str(self.device.bedwidth), "635mm")
        self.assertEqual(str(self.device.bedheight), "458mm")
        self.assertEqual(self.device.extension, "prn")
        self.assertIsNone(self.device.spooler)
        self.assertEqual(self.device.location(), "File export only")

    def test_full_plan_vector_export(self):
        with tempfile.TemporaryDirectory() as directory:
            pathname = os.path.join(directory, "gcc vector export.prn")
            self.kernel.console("operation* remove\n")
            self.kernel.console(
                'rect 2cm 2cm 1cm 1cm engrave -s 50 '
                'plan copy-selected preprocess validate blob preopt optimize '
                'save_job "{}"\n'.format(pathname)
            )
            with open(pathname, "rb") as stream:
                data = stream.read()

        self.assertTrue(data.startswith(b"\x1b%-12345X\x1bE\x1b!r0A"))
        self.assertIn(b"\x1b%1B;PR;", data)
        self.assertIn(b"PD", data)
        self.assertTrue(data.endswith(b"\x1bE\x1b%-12345X"))


if __name__ == "__main__":
    unittest.main()
