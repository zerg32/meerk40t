"""Dependency-free Windows RAW printer submission.

The module is safe to import on non-Windows systems.  The Win32 DLL is loaded
only when a default :class:`Win32RawPrinter` backend is first used.
"""

import ctypes
import errno
import os
from ctypes import wintypes


class Win32PrintError(OSError):
    """An error raised while accessing the Windows print spooler."""


class _DocInfo1W(ctypes.Structure):
    _fields_ = (
        ("pDocName", ctypes.c_wchar_p),
        ("pOutputFile", ctypes.c_wchar_p),
        ("pDatatype", ctypes.c_wchar_p),
    )


class _PrinterInfo4W(ctypes.Structure):
    _fields_ = (
        ("pPrinterName", ctypes.c_wchar_p),
        ("pServerName", ctypes.c_wchar_p),
        ("Attributes", wintypes.DWORD),
    )


class _WinspoolAPI:
    """Thin, exception-based adapter around winspool.drv."""

    PRINTER_ENUM_LOCAL = 0x00000002
    PRINTER_ENUM_CONNECTIONS = 0x00000004
    ERROR_INSUFFICIENT_BUFFER = 122

    def __init__(self):
        # WinDLL is intentionally resolved here rather than at module import.
        self.dll = ctypes.WinDLL("winspool.drv", use_last_error=True)
        self._configure_functions()

    def _configure_functions(self):
        handle_pointer = ctypes.POINTER(wintypes.HANDLE)
        dword_pointer = ctypes.POINTER(wintypes.DWORD)

        self.dll.OpenPrinterW.argtypes = (
            wintypes.LPWSTR,
            handle_pointer,
            ctypes.c_void_p,
        )
        self.dll.OpenPrinterW.restype = wintypes.BOOL
        self.dll.StartDocPrinterW.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(_DocInfo1W),
        )
        self.dll.StartDocPrinterW.restype = wintypes.DWORD
        for name in (
            "StartPagePrinter",
            "EndPagePrinter",
            "EndDocPrinter",
            "AbortPrinter",
            "ClosePrinter",
        ):
            function = getattr(self.dll, name)
            function.argtypes = (wintypes.HANDLE,)
            function.restype = wintypes.BOOL
        self.dll.WritePrinter.argtypes = (
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            dword_pointer,
        )
        self.dll.WritePrinter.restype = wintypes.BOOL
        self.dll.EnumPrintersW.argtypes = (
            wintypes.DWORD,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            dword_pointer,
            dword_pointer,
        )
        self.dll.EnumPrintersW.restype = wintypes.BOOL

    @staticmethod
    def _error(operation):
        code = ctypes.get_last_error()
        try:
            message = ctypes.FormatError(code).strip()
        except (AttributeError, OSError):
            message = "Windows error %d" % code
        return Win32PrintError(code, "%s failed: %s" % (operation, message))

    def open_printer(self, queue_name):
        handle = wintypes.HANDLE()
        if not self.dll.OpenPrinterW(queue_name, ctypes.byref(handle), None):
            raise self._error("OpenPrinterW")
        return handle

    def start_doc(self, handle, document_name):
        info = _DocInfo1W(document_name, None, "RAW")
        job_id = self.dll.StartDocPrinterW(handle, 1, ctypes.byref(info))
        if not job_id:
            raise self._error("StartDocPrinterW")
        return int(job_id)

    def start_page(self, handle):
        if not self.dll.StartPagePrinter(handle):
            raise self._error("StartPagePrinter")

    def write(self, handle, data):
        written = wintypes.DWORD()
        buffer = ctypes.create_string_buffer(data, len(data))
        if not self.dll.WritePrinter(
            handle, buffer, len(data), ctypes.byref(written)
        ):
            raise self._error("WritePrinter")
        return int(written.value)

    def end_page(self, handle):
        if not self.dll.EndPagePrinter(handle):
            raise self._error("EndPagePrinter")

    def end_doc(self, handle):
        if not self.dll.EndDocPrinter(handle):
            raise self._error("EndDocPrinter")

    def abort(self, handle):
        if not self.dll.AbortPrinter(handle):
            raise self._error("AbortPrinter")

    def close(self, handle):
        if not self.dll.ClosePrinter(handle):
            raise self._error("ClosePrinter")

    def enumerate_queues(self):
        flags = self.PRINTER_ENUM_LOCAL | self.PRINTER_ENUM_CONNECTIONS
        needed = wintypes.DWORD()
        returned = wintypes.DWORD()
        ctypes.set_last_error(0)
        result = self.dll.EnumPrintersW(
            flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned)
        )
        if result:
            return []
        error = ctypes.get_last_error()
        if error != self.ERROR_INSUFFICIENT_BUFFER:
            raise self._error("EnumPrintersW")
        if not needed.value:
            return []

        buffer = ctypes.create_string_buffer(needed.value)
        if not self.dll.EnumPrintersW(
            flags,
            None,
            4,
            buffer,
            needed.value,
            ctypes.byref(needed),
            ctypes.byref(returned),
        ):
            raise self._error("EnumPrintersW")
        records = ctypes.cast(buffer, ctypes.POINTER(_PrinterInfo4W))
        return [
            str(records[index].pPrinterName)
            for index in range(returned.value)
            if records[index].pPrinterName
        ]


class Win32RawPrinter:
    """Submit byte-exact RAW jobs to Windows printer queues.

    ``api`` may be an object implementing the high-level methods used by this
    class, which permits spooler behavior to be tested without Windows.
    """

    DEFAULT_CHUNK_SIZE = 1024 * 1024

    def __init__(self, api=None, chunk_size=DEFAULT_CHUNK_SIZE):
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise TypeError("chunk_size must be an integer")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self.chunk_size = chunk_size
        self._api = api
        self._api_loaded = api is not None
        self._load_error = None

    def _load_api(self):
        if self._api_loaded:
            return self._api
        self._api_loaded = True
        if os.name != "nt":
            return None
        try:
            self._api = _WinspoolAPI()
        except (AttributeError, OSError) as error:
            self._load_error = error
        return self._api

    @property
    def available(self):
        api = self._load_api()
        if api is None:
            return False
        try:
            return bool(getattr(api, "available", True))
        except OSError:
            return False

    def _require_api(self):
        api = self._load_api()
        if api is None or not self.available:
            if self._load_error is not None:
                raise self._convert_error(self._load_error)
            raise Win32PrintError(
                errno.ENOSYS, "Windows RAW printing is not available"
            )
        return api

    @staticmethod
    def _convert_error(error):
        if isinstance(error, Win32PrintError):
            return error
        if isinstance(error, OSError):
            return Win32PrintError(*error.args)
        return error

    @staticmethod
    def _validate_queue(queue_name):
        if not isinstance(queue_name, str):
            raise TypeError("queue_name must be a string")
        if not queue_name:
            raise ValueError("queue_name must not be empty")

    def enumerate_queues(self):
        api = self._require_api()
        try:
            names = api.enumerate_queues()
        except OSError as error:
            raise self._convert_error(error)
        copied = []
        for name in names:
            if not isinstance(name, str):
                raise Win32PrintError("printer API returned a non-string name")
            copied.append(str(name))
        unique = {}
        for name in copied:
            unique.setdefault(name.casefold(), name)
        return sorted(unique.values(), key=str.casefold)

    def submit(self, queue_name, data, document_name):
        self._validate_queue(queue_name)
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        if not isinstance(document_name, str):
            raise TypeError("document_name must be a string")

        api = self._require_api()
        handle = None
        document_started = False
        try:
            handle = api.open_printer(queue_name)
            job_id = api.start_doc(handle, document_name)
            document_started = True
            api.start_page(handle)

            offset = 0
            data_length = len(data)
            while offset < data_length:
                chunk_end = min(offset + self.chunk_size, data_length)
                while offset < chunk_end:
                    written = api.write(handle, data[offset:chunk_end])
                    if not isinstance(written, int) or isinstance(written, bool):
                        raise Win32PrintError(
                            "WritePrinter returned an invalid byte count"
                        )
                    if written <= 0:
                        raise Win32PrintError("WritePrinter wrote zero bytes")
                    if written > chunk_end - offset:
                        raise Win32PrintError(
                            "WritePrinter returned an invalid byte count"
                        )
                    offset += written

            api.end_page(handle)
            api.end_doc(handle)
            document_started = False
        except BaseException as error:
            if document_started:
                try:
                    api.abort(handle)
                except BaseException:
                    pass
            if handle is not None:
                try:
                    api.close(handle)
                except BaseException:
                    pass
            converted = self._convert_error(error)
            if converted is error:
                raise
            raise converted

        try:
            api.close(handle)
        except OSError:
            # EndDocPrinter already transferred ownership to Windows. Reporting
            # failure here could prompt a dangerous duplicate laser job.
            pass
        return job_id


__all__ = ("Win32PrintError", "Win32RawPrinter")
