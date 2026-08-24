import os
import unittest

from meerk40t.gcc.win32print import Win32PrintError, Win32RawPrinter


class FakePrintAPI:
    def __init__(self, fail=None, writes=None, queues=None):
        self.available = True
        self.fail = fail
        self.write_results = list(writes or [])
        self.queues = list(queues or [])
        self.events = []
        self.received = bytearray()

    def _event(self, name, *values):
        self.events.append((name,) + values)
        if self.fail == name:
            raise Win32PrintError("%s failed" % name)

    def open_printer(self, queue_name):
        self._event("open", queue_name)
        return "handle"

    def start_doc(self, handle, document_name):
        self._event("start_doc", handle, document_name)
        return 73

    def start_page(self, handle):
        self._event("start_page", handle)

    def write(self, handle, data):
        self._event("write", handle, data)
        result = self.write_results.pop(0) if self.write_results else len(data)
        if result > 0:
            self.received.extend(data[:result])
        return result

    def end_page(self, handle):
        self._event("end_page", handle)

    def end_doc(self, handle):
        self._event("end_doc", handle)

    def abort(self, handle):
        self._event("abort", handle)

    def close(self, handle):
        self._event("close", handle)

    def enumerate_queues(self):
        self._event("enumerate")
        return list(self.queues)


class TestWin32RawPrinter(unittest.TestCase):
    def test_default_backend_is_unavailable_off_windows(self):
        if os.name == "nt":
            self.skipTest("non-Windows behavior")
        printer = Win32RawPrinter()
        self.assertFalse(printer.available)
        with self.assertRaises(Win32PrintError):
            printer.enumerate_queues()

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_real_windows_queue_enumeration(self):
        printer = Win32RawPrinter()
        self.assertTrue(printer.available)
        queues = printer.enumerate_queues()
        self.assertTrue(all(isinstance(queue, str) for queue in queues))

    def test_success_preserves_binary_and_unicode_names(self):
        api = FakePrintAPI()
        printer = Win32RawPrinter(api=api)
        data = b"\x00\x1b%-12345X\xff\x00"
        job_id = printer.submit("GCC \u96f7\u5c04", data, "Job \u03a9")
        self.assertEqual(job_id, 73)
        self.assertEqual(bytes(api.received), data)
        self.assertEqual(api.events[0], ("open", "GCC \u96f7\u5c04"))
        self.assertEqual(api.events[1], ("start_doc", "handle", "Job \u03a9"))
        self.assertEqual(
            [event[0] for event in api.events],
            [
                "open",
                "start_doc",
                "start_page",
                "write",
                "end_page",
                "end_doc",
                "close",
            ],
        )

    def test_chunks_and_retries_only_unwritten_partial_data(self):
        api = FakePrintAPI(writes=[2, 2, 1, 3, 1])
        printer = Win32RawPrinter(api=api, chunk_size=4)
        data = b"abcdefghi"
        printer.submit("queue", data, "chunks")
        requests = [event[2] for event in api.events if event[0] == "write"]
        self.assertEqual(requests, [b"abcd", b"cd", b"efgh", b"fgh", b"i"])
        self.assertEqual(bytes(api.received), data)

    def test_empty_job_still_starts_and_ends_page(self):
        api = FakePrintAPI()
        Win32RawPrinter(api=api).submit("queue", b"", "empty")
        self.assertNotIn("write", [event[0] for event in api.events])
        self.assertIn(("end_page", "handle"), api.events)

    def test_open_failure_does_not_cleanup_invalid_handle(self):
        api = FakePrintAPI(fail="open")
        with self.assertRaisesRegex(Win32PrintError, "open failed"):
            Win32RawPrinter(api=api).submit("queue", b"x", "job")
        self.assertEqual(api.events, [("open", "queue")])

    def test_start_doc_failure_only_closes(self):
        api = FakePrintAPI(fail="start_doc")
        with self.assertRaisesRegex(Win32PrintError, "start_doc failed"):
            Win32RawPrinter(api=api).submit("queue", b"x", "job")
        self.assertEqual(
            [event[0] for event in api.events], ["open", "start_doc", "close"]
        )

    def test_started_job_failures_abort_then_close(self):
        for failure in ("start_page", "write", "end_page", "end_doc"):
            with self.subTest(failure=failure):
                api = FakePrintAPI(fail=failure)
                with self.assertRaisesRegex(Win32PrintError, failure + " failed"):
                    Win32RawPrinter(api=api).submit("queue", b"x", "job")
                self.assertEqual(
                    [event[0] for event in api.events[-2:]], ["abort", "close"]
                )

    def test_zero_write_aborts_without_retry(self):
        api = FakePrintAPI(writes=[0, 1])
        with self.assertRaisesRegex(Win32PrintError, "zero bytes"):
            Win32RawPrinter(api=api).submit("queue", b"abc", "job")
        self.assertEqual(
            [event[0] for event in api.events].count("write"), 1
        )
        self.assertEqual(
            [event[0] for event in api.events[-2:]], ["abort", "close"]
        )

    def test_cleanup_errors_do_not_replace_primary_error(self):
        class CleanupFailureAPI(FakePrintAPI):
            def abort(self, handle):
                self.events.append(("abort", handle))
                raise Win32PrintError("abort cleanup failed")

            def close(self, handle):
                self.events.append(("close", handle))
                raise Win32PrintError("close cleanup failed")

        api = CleanupFailureAPI(fail="write")
        with self.assertRaisesRegex(Win32PrintError, "write failed"):
            Win32RawPrinter(api=api).submit("queue", b"abc", "job")
        self.assertEqual(
            [event[0] for event in api.events[-2:]], ["abort", "close"]
        )

    def test_close_failure_after_end_doc_does_not_report_job_failed(self):
        api = FakePrintAPI(fail="close")
        job_id = Win32RawPrinter(api=api).submit("queue", b"data", "job")
        self.assertEqual(job_id, 73)
        self.assertIn(("end_doc", "handle"), api.events)

    def test_enumeration_sorts_deduplicates_and_returns_copy(self):
        source = ["Zulu", "Alpha", "alpha", "Alpha", "\u6253\u5370\u673a"]
        api = FakePrintAPI(queues=source)
        queues = Win32RawPrinter(api=api).enumerate_queues()
        self.assertEqual(queues, ["Alpha", "Zulu", "\u6253\u5370\u673a"])
        queues.append("changed")
        self.assertEqual(api.queues, source)

    def test_validation_happens_before_api_calls(self):
        api = FakePrintAPI()
        printer = Win32RawPrinter(api=api)
        for queue in (None, b"queue"):
            with self.subTest(queue=queue):
                with self.assertRaises(TypeError):
                    printer.submit(queue, b"data", "job")
        with self.assertRaises(ValueError):
            printer.submit("", b"data", "job")
        for data in (bytearray(b"data"), memoryview(b"data"), "data"):
            with self.subTest(data=type(data).__name__):
                with self.assertRaises(TypeError):
                    printer.submit("queue", data, "job")
        with self.assertRaises(TypeError):
            printer.submit("queue", b"data", b"job")
        self.assertEqual(api.events, [])

    def test_chunk_size_validation(self):
        for value in (0, -1):
            with self.assertRaises(ValueError):
                Win32RawPrinter(api=FakePrintAPI(), chunk_size=value)
        for value in (True, 1.5, "1024"):
            with self.assertRaises(TypeError):
                Win32RawPrinter(api=FakePrintAPI(), chunk_size=value)

    def test_injected_api_can_report_unavailable(self):
        api = FakePrintAPI()
        api.available = False
        printer = Win32RawPrinter(api=api)
        self.assertFalse(printer.available)
        with self.assertRaises(Win32PrintError):
            printer.submit("queue", b"data", "job")


if __name__ == "__main__":
    unittest.main()
