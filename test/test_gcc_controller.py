import unittest

from meerk40t.gcc.controller import GCCController
from meerk40t.gcc.win32print import Win32PrintError


class ServiceStub:
    safe_label = "gcc-test"

    def __init__(self, queue=""):
        self.printer_queue = queue
        self.signals = []
        self.messages = []
        self._laser_status = "idle"

    def _(self, message):
        return message

    def signal(self, *args):
        self.signals.append(args)

    def channel(self, name):
        return self.messages.append

    @property
    def laser_status(self):
        return self._laser_status

    @laser_status.setter
    def laser_status(self, value):
        self._laser_status = value
        self.signal("pipe;running", value == "active")


class PrinterStub:
    def __init__(self, available=True, error=None):
        self.available = available
        self.error = error
        self.calls = []

    def enumerate_queues(self):
        return ["GCC Mercury RAW"]

    def submit(self, queue, data, name):
        self.calls.append((queue, data, name))
        if self.error is not None:
            raise self.error
        return 73


class TestGCCController(unittest.TestCase):
    def test_unavailable_and_unconfigured(self):
        unavailable = GCCController(ServiceStub(), PrinterStub(available=False))
        self.assertFalse(unavailable.available)
        self.assertFalse(unavailable.ready)
        self.assertEqual(unavailable.state, "unavailable")

        controller = GCCController(ServiceStub(), PrinterStub())
        self.assertTrue(controller.available)
        self.assertFalse(controller.ready)
        with self.assertRaisesRegex(Win32PrintError, "No Windows printer"):
            controller.submit(b"data", "job")

    def test_successful_submission(self):
        service = ServiceStub("GCC Mercury RAW")
        printer = PrinterStub()
        controller = GCCController(service, printer)
        job_id = controller.submit(b"\x00\x1bPRN", "GCC Job")

        self.assertEqual(job_id, 73)
        self.assertEqual(
            printer.calls, [("GCC Mercury RAW", b"\x00\x1bPRN", "GCC Job")]
        )
        self.assertEqual(controller.state, "idle")
        self.assertEqual(controller.last_job_id, 73)
        self.assertIsNone(controller.last_error)
        self.assertEqual(service.laser_status, "idle")
        self.assertIn(("gcc;state", "submitting"), service.signals)
        self.assertIn(("gcc;job", "GCC Mercury RAW", 73, "GCC Job"), service.signals)

    def test_failure_and_recovery(self):
        service = ServiceStub("GCC Mercury RAW")
        printer = PrinterStub(error=Win32PrintError("offline"))
        controller = GCCController(service, printer)

        with self.assertRaisesRegex(Win32PrintError, "offline"):
            controller.submit(b"data", "failed")
        self.assertEqual(controller.state, "error")
        self.assertIsNotNone(controller.last_error)
        self.assertEqual(service.laser_status, "idle")

        printer.error = None
        self.assertEqual(controller.submit(b"data", "recovered"), 73)
        self.assertEqual(controller.state, "idle")
        self.assertIsNone(controller.last_error)

    def test_rejects_concurrent_submission(self):
        service = ServiceStub("GCC Mercury RAW")
        controller = GCCController(service, PrinterStub())
        controller._submission_lock.acquire()
        try:
            with self.assertRaisesRegex(Win32PrintError, "in progress"):
                controller.submit(b"data", "job")
        finally:
            controller._submission_lock.release()


if __name__ == "__main__":
    unittest.main()
