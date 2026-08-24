import threading
import time
import unittest

from meerk40t.core.spoolers import Spooler


class LoggingStub:
    def __init__(self, events):
        self.events = events
        self.index = 0

    def uid(self, kind):
        self.index += 1
        return self.index

    def event(self, entry):
        self.events.append(("log", entry["status"], entry["label"]))


class ContextStub:
    label = "Test Device"

    def __init__(self, events):
        self.events = events
        self.kernel = self
        self.is_shutdown = False
        self.logging = LoggingStub(events)

    def _(self, message):
        return message

    def signal(self, *args):
        self.events.append(("signal",) + args)

    def channel(self, name):
        return lambda message: self.events.append(("channel", name, message))


class JobStub:
    priority = 0
    enabled = True
    helper = False
    status = "Waiting"
    loops_executed = 1
    loops = 1
    time_started = None
    runtime = 0
    steps_done = 1
    steps_total = 1

    def __init__(self, label):
        self.label = label
        self.stopped = False

    def execute(self, driver):
        return True

    def stop(self):
        self.stopped = True

    def is_running(self):
        return False

    def estimate_time(self):
        return 0


class DriverStub:
    def __init__(self, events, fail_label=None):
        self.events = events
        self.fail_label = fail_label

    @staticmethod
    def hold_work(priority):
        return False

    def job_start(self, job):
        self.events.append(("start", job.label))

    def job_finish(self, job):
        self.events.append(("finish", job.label))
        if job.label == self.fail_label:
            raise OSError("finish failed")


class TestSpoolerFinalization(unittest.TestCase):
    def test_finalize_before_completion_and_continue_after_failure(self):
        events = []
        context = ContextStub(events)
        driver = DriverStub(events, fail_label="first")
        spooler = Spooler(context, driver=driver)
        first = JobStub("first")
        second = JobStub("second")
        spooler.send(first)
        spooler.send(second)

        thread = threading.Thread(target=spooler.run, daemon=True)
        thread.start()
        timeout = time.time() + 2.0
        while spooler.queue and time.time() < timeout:
            time.sleep(0.01)
        context.is_shutdown = True
        with spooler._lock:
            spooler._lock.notify_all()
        thread.join(1.0)

        self.assertEqual(len(spooler.queue), 0)
        self.assertLess(
            events.index(("finish", "first")),
            events.index(("log", "failed", "first")),
        )
        self.assertLess(
            events.index(("finish", "second")),
            events.index(("log", "completed", "second")),
        )
        self.assertIn(("start", "second"), events)
        self.assertTrue(first.stopped)
        self.assertTrue(second.stopped)


if __name__ == "__main__":
    unittest.main()
