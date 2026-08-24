"""Pure byte encoder for the captured GCC LaserPro PCL/HP-GL dialect."""

ESC = b"\x1b"
UEL = ESC + b"%-12345X"
PCL = ESC + b"%1A"
HPGL = ESC + b"%1B"


def _ascii(value):
    if isinstance(value, bytes):
        value.decode("ascii")
        return value
    return str(value).encode("ascii")


def esc_command(command):
    """Prefix an ASCII-only byte command with ESC."""
    command = _ascii(command)
    return ESC + command


def _parameter(prefix, value, suffix, sign=False):
    value = int(value)
    if sign:
        encoded = (b"+" if value >= 0 else b"-") + _ascii(abs(value))
    else:
        encoded = _ascii(value)
    return esc_command(_ascii(prefix) + encoded + _ascii(suffix))


def d4(value):
    """Encode a GCC table value as four zero-padded ASCII digits."""
    value = int(value)
    if not 0 <= value <= 1000:
        raise ValueError("D4 value must be between 0 and 1000")
    return ("%04d" % value).encode("ascii")


def d4_table(values):
    """Encode exactly sixteen D4 values as a 64-byte payload."""
    values = list(values)
    if len(values) != 16:
        raise ValueError("a pen table requires exactly 16 values")
    return b"".join(d4(value) for value in values)


def encode_job_name(name, maximum=32):
    """Return a UTF-8 name, truncating safely and adding an ASCII ellipsis."""
    if isinstance(name, bytes):
        encoded = name
        encoded.decode("utf-8")
    else:
        encoded = str(name).encode("utf-8")
    maximum = int(maximum)
    if maximum < 0:
        raise ValueError("maximum must not be negative")
    if len(encoded) <= maximum:
        return encoded
    ellipsis = b"..."
    if maximum < len(ellipsis):
        return ellipsis[:maximum]
    prefix = encoded[: maximum - len(ellipsis)]
    prefix = prefix.decode("utf-8", "ignore").encode("utf-8")
    return prefix + ellipsis


def transfer_width(width):
    """Return the raster transfer width padded to a 64-pixel boundary."""
    width = int(width)
    if width < 0:
        raise ValueError("width must not be negative")
    return ((width + 63) // 64) * 64


def pack_monochrome_row(pixels, width=None):
    """Pack off/on pixels MSB-first and zero-pad to a 64-pixel boundary."""
    pixels = list(pixels)
    if width is None:
        width = len(pixels)
    width = int(width)
    if width < 0 or len(pixels) != width:
        raise ValueError("pixel count must equal width")
    packed = bytearray(transfer_width(width) // 8)
    for index, pixel in enumerate(pixels):
        if pixel not in (0, 1, False, True):
            raise ValueError("monochrome pixels must be 0 (off) or 1 (on)")
        if pixel:
            packed[index // 8] |= 0x80 >> (index & 7)
    return bytes(packed)


def gcc_rle_encode(row):
    """Encode packed raster bytes as GCC count/value pairs plus 00 00."""
    if not isinstance(row, (bytes, bytearray)):
        raise TypeError("row must be bytes")
    row = bytes(row)
    encoded = bytearray()
    index = 0
    while index < len(row):
        value = row[index]
        count = 1
        while (
            index + count < len(row)
            and row[index + count] == value
            and count < 128
        ):
            count += 1
        encoded.extend((count, value))
        index += count
    encoded.extend((0, 0))
    return bytes(encoded)


def _setting_values(settings, key, default):
    value = settings.get(key, default)
    if isinstance(value, (list, tuple)):
        if len(value) != 16:
            raise ValueError("%s requires exactly 16 values" % key)
        return list(value)
    return [value] * 16


def _pen_columns(settings):
    if isinstance(settings, (list, tuple)):
        if len(settings) != 16:
            raise ValueError("settings require exactly 16 pens")
        pens = list(settings)
        return {
            key: [pen.get(key, default) for pen in pens]
            for key, default in (
                ("ppi_enabled", True),
                ("ppi", 400),
                ("speed", 500),
                ("power", 500),
                ("air", False),
            )
        }
    if not isinstance(settings, dict):
        raise TypeError("settings must be a dict or a 16-pen list")
    if "pens" in settings:
        return _pen_columns(settings["pens"])
    return {
        key: _setting_values(settings, key, default)
        for key, default in (
            ("ppi_enabled", True),
            ("ppi", 400),
            ("speed", 500),
            ("power", 500),
            ("air", False),
        )
    }


class GCCJob:
    """Build one GCC job without device, service, or transport dependencies."""

    def __init__(self):
        self._data = bytearray()
        self._mode = None
        self._raster_active = False
        self._job_start_written = False
        self._vector_x = 0
        self._vector_y = 0
        self._raster_width = None
        self._immediate_start = False

    def _write(self, data):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("protocol data must be bytes")
        self._data.extend(data)

    def getvalue(self):
        return bytes(self._data)

    def begin_job(
        self,
        name=b"",
        immediate=False,
        settings=None,
        dpi=508,
        legacy_header_value=152500,
    ):
        """Write the captured original-driver envelope and optional pen tables."""
        name = encode_job_name(name)
        self._immediate_start = bool(immediate)
        self._write(UEL)
        self._write(esc_command(b"E"))
        self._write(esc_command(b"!r0A"))
        self._write(esc_command(b"!m" + _ascii(len(name)) + b"N") + name)
        if settings is not None:
            self.write_settings(settings)
        self._write(_parameter(b"!h", legacy_header_value, b"T"))
        self.write_resolution(dpi)
        self._write(esc_command(b"!r0N"))
        self._write(esc_command(b"!r0E"))
        self.select_pcl()

    def write_settings(self, settings):
        """Write the captured 16-pen PPI, speed, power, and air table order."""
        columns = _pen_columns(settings)
        enabled = bytes(49 if value else 48 for value in columns["ppi_enabled"])
        air = bytes(2 if value else 0 for value in columns["air"])
        self._write(esc_command(b"!v16R") + enabled)
        self._write(esc_command(b"!v64I") + d4_table(columns["ppi"]))
        self._write(esc_command(b"!v64V") + d4_table(columns["speed"]))
        self._write(esc_command(b"!v64P") + d4_table(columns["power"]))
        self._write(esc_command(b"!v16D") + air)

    def write_resolution(self, dpi):
        dpi = int(dpi)
        if dpi <= 0:
            raise ValueError("dpi must be positive")
        self._write(_parameter(b"*t", dpi, b"R"))
        self._write(_parameter(b"&u", dpi, b"D"))

    def write_raster_settings(self, speed, power):
        self._write(_parameter(b"!r", speed, b"I"))
        self._write(_parameter(b"!r", speed, b"K"))
        self._write(_parameter(b"!r", power, b"P"))

    def reset_raster(self):
        self._write(esc_command(b"*r1A"))
        self._write(esc_command(b"*rC"))

    def select_pcl(self):
        if self._raster_active:
            self.end_raster()
        self._write(PCL)
        self._mode = "pcl"

    def write_job_start(self, immediate=None):
        if not self._job_start_written:
            if immediate is None:
                immediate = self._immediate_start
            self._write(esc_command(b"!m1S" if immediate else b"!m0S"))
            self._write(esc_command(b"!s0S"))
            self._job_start_written = True

    def begin_vector(self, pen=None):
        if self._raster_active:
            self.end_raster()
        self.write_job_start()
        self._write(HPGL + b";PR;")
        self._mode = "hpgl"
        if pen is not None:
            self.select_pen(pen)

    def select_pen(self, pen):
        pen = int(pen)
        if not 1 <= pen <= 16:
            raise ValueError("pen must be between 1 and 16")
        self._write(b"SP" + _ascii(pen) + b";")

    def set_vector_position(self, x, y):
        """Set the known source-coordinate position without emitting movement."""
        self._vector_x = int(round(x))
        self._vector_y = int(round(y))

    def _vector_to(self, command, x, y):
        x = int(round(x))
        y = int(round(y))
        dx = x - self._vector_x
        dy = -(y - self._vector_y)
        self._write(command + _ascii(dx) + b"," + _ascii(dy) + b";")
        self._vector_x = x
        self._vector_y = y

    def vector_move(self, x, y):
        self._vector_to(b"PU", x, y)

    def vector_cut(self, x, y):
        self._vector_to(b"PD", x, y)

    def vector_move_relative(self, dx, dy):
        self.vector_move(self._vector_x + dx, self._vector_y + dy)

    def vector_cut_relative(self, dx, dy):
        self.vector_cut(self._vector_x + dx, self._vector_y + dy)

    def pen_up(self):
        self._write(b"PU;")

    def write_raster_frame(
        self, width, height, x, y, raster_offset_x=0, raster_offset_y=0
    ):
        """Write captured A-F/X/Y frame fields; offsets are artwork offsets."""
        self._write(_parameter(b"*p", width, b"A"))
        self._write(_parameter(b"*p", height, b"B"))
        self._write(esc_command(b"*p-" + _ascii(abs(int(raster_offset_x))) + b"C"))
        self._write(esc_command(b"*p-" + _ascii(abs(int(raster_offset_y))) + b"D"))
        self._write(_parameter(b"*p", x, b"E"))
        self._write(_parameter(b"*p", y, b"F"))
        self._write(_parameter(b"*p", x, b"X"))
        self._write(_parameter(b"*p", y, b"Y"))

    def move_raster_cursor(self, dx, dy):
        """Move between bands using the captured explicitly signed PCL form."""
        if self._raster_active:
            self.end_raster()
        self.select_pcl()
        self._write(_parameter(b"*p", dx, b"X", sign=True))
        self._write(_parameter(b"*p", dy, b"Y", sign=True))

    def begin_raster(
        self,
        rows,
        columns,
        speed,
        power,
        dpi=508,
        top_down=True,
        immediate=None,
    ):
        """Start an original-driver monochrome raster band."""
        if self._raster_active:
            raise ValueError("a raster band is already active")
        rows = int(rows)
        columns = int(columns)
        if rows < 0 or columns < 0:
            raise ValueError("raster dimensions must not be negative")
        self._write(esc_command(b"*t1Y"))
        self._write(esc_command(b"!r0B" if top_down else b"!r1B"))
        self._write(esc_command(b"!r1M"))
        self.write_raster_settings(speed, power)
        self.write_resolution(dpi)
        self.write_job_start(immediate=immediate)
        self._raster_width = columns
        self._write(_parameter(b"*r", rows, b"T"))
        self._write(_parameter(b"*r", transfer_width(columns), b"S"))
        self._write(esc_command(b"*b1M"))
        self._write(esc_command(b"*r1A"))
        self._raster_active = True
        self._mode = "raster"

    def write_packed_raster_row(self, row):
        if not self._raster_active:
            raise ValueError("no raster band is active")
        if not isinstance(row, (bytes, bytearray)):
            raise TypeError("packed row must be bytes")
        expected = transfer_width(self._raster_width) // 8
        if len(row) != expected:
            raise ValueError("packed row must contain %d bytes" % expected)
        encoded = gcc_rle_encode(row)
        self._write(_parameter(b"*b", len(encoded), b"W") + encoded)

    def write_raster_row(self, pixels):
        self.write_packed_raster_row(pack_monochrome_row(pixels, self._raster_width))

    def end_raster(self):
        if self._raster_active:
            self._write(esc_command(b"*rC"))
            self._raster_active = False
            self._mode = "pcl"

    def finish_job(self, park=None):
        """Close the job; optional machine-specific park data is caller-owned."""
        if self._raster_active:
            self.end_raster()
        if self._mode == "hpgl":
            self._write(b"PU;ZS0;RS0;")
        self._write(PCL)
        if park is not None:
            if not isinstance(park, (bytes, bytearray)):
                raise TypeError("park must be raw bytes")
            self._write(park)
        self._write(esc_command(b"*r1A"))
        self._write(esc_command(b"*rC"))
        self._write(esc_command(b"E"))
        self._write(UEL)
        self._mode = None
