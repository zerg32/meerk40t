import os
import tempfile
import time
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
        self.assertIsNotNone(self.device.spooler)
        self.assertFalse(self.device.can_spool)
        self.assertEqual(
            self.device.location(), "Windows printer queue not configured"
        )

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

    def test_full_plan_windows_queue_submission(self):
        class Printer:
            available = True

            def __init__(self):
                self.calls = []

            @staticmethod
            def enumerate_queues():
                return ["GCC Mercury RAW"]

            def submit(self, queue, data, name):
                self.calls.append((queue, data, name))
                return 91

        printer = Printer()
        self.device.controller.printer = printer
        self.device.printer_queue = "GCC Mercury RAW"
        self.kernel.console("operation* remove\n")
        self.kernel.console(
            "rect 2cm 2cm 1cm 1cm engrave -s 50 "
            "plan copy-selected preprocess validate blob preopt optimize spool\n"
        )
        timeout = time.time() + 2.0
        while not printer.calls and time.time() < timeout:
            time.sleep(0.01)

        self.assertEqual(len(printer.calls), 1)
        queue, data, name = printer.calls[0]
        self.assertEqual(queue, "GCC Mercury RAW")
        self.assertTrue(data.startswith(b"\x1b%-12345X"))
        self.assertEqual(self.device.controller.last_job_id, 91)

    def test_unconfigured_queue_rejects_spool_without_crash(self):
        self.kernel.console("operation* remove\n")
        self.kernel.console(
            "rect 2cm 2cm 1cm 1cm engrave -s 50 "
            "plan copy-selected preprocess validate blob preopt optimize spool\n"
        )
        self.assertEqual(len(self.device.spooler.queue), 0)

    def test_failed_submission_does_not_stop_spooler(self):
        class Printer:
            available = True

            def __init__(self):
                self.calls = 0

            @staticmethod
            def enumerate_queues():
                return ["GCC Mercury RAW"]

            def submit(self, queue, data, name):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("offline")
                return 92

        printer = Printer()
        self.device.controller.printer = printer
        self.device.printer_queue = "GCC Mercury RAW"

        for expected_calls in (1, 2):
            self.kernel.console("operation* remove\n")
            self.kernel.console(
                "rect 2cm 2cm 1cm 1cm engrave -s 50 "
                "plan copy-selected preprocess validate blob preopt optimize spool\n"
            )
            timeout = time.time() + 2.0
            while printer.calls < expected_calls and time.time() < timeout:
                time.sleep(0.01)
            while self.device.spooler.queue and time.time() < timeout:
                time.sleep(0.01)

        self.assertEqual(printer.calls, 2)
        self.assertEqual(self.device.controller.last_job_id, 92)
        self.assertEqual(self.device.controller.state, "idle")


if __name__ == "__main__":
    unittest.main()
