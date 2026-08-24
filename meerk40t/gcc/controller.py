"""Windows printer-queue transport for GCC LaserPro jobs."""

from threading import Lock

from .win32print import Win32PrintError, Win32RawPrinter


class GCCController:
    def __init__(self, service, printer=None):
        self.service = service
        self.printer = printer if printer is not None else Win32RawPrinter()
        self.state = "unavailable" if not self.printer.available else "idle"
        self.last_error = None
        self.last_job_id = None
        self.last_job_name = None
        self.events = service.channel("%s/events" % service.safe_label)
        self._submission_lock = Lock()

    @property
    def available(self):
        return self.printer.available

    @property
    def ready(self):
        return self.available and bool(
            str(getattr(self.service, "printer_queue", "")).strip()
        )

    @property
    def is_busy(self):
        return self.state == "submitting"

    @property
    def unavailable_reason(self):
        if not self.available:
            return self.service._("Windows RAW printing is unavailable")
        if not str(getattr(self.service, "printer_queue", "")).strip():
            return self.service._("Select a Windows printer queue in GCC Config")
        return None

    def enumerate_queues(self):
        return self.printer.enumerate_queues()

    def _set_state(self, state):
        self.state = state
        self.service.signal("gcc;state", state)

    def submit(self, data, document_name):
        queue_name = str(getattr(self.service, "printer_queue", "")).strip()
        if not self.available:
            raise Win32PrintError("Windows RAW printing is unavailable")
        if not queue_name:
            raise Win32PrintError("No Windows printer queue is configured")
        if not self._submission_lock.acquire(False):
            raise Win32PrintError("Another GCC print submission is in progress")

        try:
            self.last_error = None
            self.last_job_id = None
            self.last_job_name = document_name
            self.service.laser_status = "active"
            self._set_state("submitting")
            self.events(
                self.service._(
                    "Submitting '{name}' to Windows queue '{queue}'"
                ).format(name=document_name, queue=queue_name)
            )
            try:
                job_id = self.printer.submit(queue_name, data, document_name)
            except Exception as error:
                self.last_error = error
                self._set_state("error")
                self.service.signal("gcc;error", queue_name, str(error))
                self.events(
                    self.service._(
                        "Windows print submission failed: {error}"
                    ).format(error=error)
                )
                raise
            else:
                self.last_job_id = job_id
                self._set_state("idle")
                self.service.signal("gcc;job", queue_name, job_id, document_name)
                self.events(
                    self.service._(
                        "Windows accepted '{name}' as spool job {job_id}"
                    ).format(name=document_name, job_id=job_id)
                )
                return job_id
            finally:
                self.service.laser_status = "idle"
        finally:
            self._submission_lock.release()


__all__ = ("GCCController",)
