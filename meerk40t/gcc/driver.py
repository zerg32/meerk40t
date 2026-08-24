"""CutCode-to-PRN driver for captured GCC LaserPro jobs."""

import os

from meerk40t.core.cutcode.cubiccut import CubicCut
from meerk40t.core.cutcode.linecut import LineCut
from meerk40t.core.cutcode.plotcut import PlotCut
from meerk40t.core.cutcode.quadcut import QuadCut
from meerk40t.core.cutcode.rastercut import RasterCut
from meerk40t.core.geomstr import Geomstr
from meerk40t.core.units import Length
from meerk40t.svgelements import Color

from .gccjob import GCCJob, esc_command


SUPPORTED_DPI = (127, 254, 381, 508, 762, 1016, 1524)
DISPLAY_DPI = {
    125: 127,
    250: 254,
    380: 381,
    500: 508,
    760: 762,
    1000: 1016,
    1500: 1524,
}
NATIVE_DPI = 1016.0

# Original-driver pen slots observed for the standard GCC color palette.
PALETTE_SLOTS = {
    (0, 0, 0): 1,
    (255, 0, 0): 2,
    (0, 255, 0): 3,
    (255, 255, 0): 4,
    (0, 0, 255): 5,
    (255, 0, 255): 6,
    (0, 255, 255): 7,
    (255, 255, 255): 8,
}


def _clamp(value, minimum=0, maximum=1000):
    return max(minimum, min(maximum, int(round(value))))


def _color_rgb(value):
    if value is None:
        return 0, 0, 0
    try:
        color = value if isinstance(value, Color) else Color(value)
        return color.red, color.green, color.blue
    except (AttributeError, TypeError, ValueError):
        return 0, 0, 0


class GCCDriver:
    """Build a complete export synchronously when queued CutCode is flushed."""

    def __init__(self, service, output=None, transport=None):
        self.service = service
        self.output = output
        self.transport = transport
        self.queue = []
        self.paused = False
        self.hold = False
        self.native_x = 0
        self.native_y = 0
        self._job = None
        self._settings = {}

    def hold_work(self, priority):
        return self.hold or self.paused

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        self._settings[key] = value

    def status(self):
        state = "hold" if self.hold or self.paused else "idle"
        return (self.native_x, self.native_y), state, "export-only"

    def job_start(self, job):
        self._job = job
        self.queue = []

    def job_finish(self, job):
        try:
            data = self._build_job()
            if self.output is not None:
                self.output(data)
            if self.transport is not None:
                self.transport.submit(data, self._document_name(job))
        finally:
            self.queue = []
            self._job = None

    @staticmethod
    def _document_name(job):
        label = str(getattr(job, "label", "") or "")
        label = os.path.basename(label)
        label = "".join(character for character in label if ord(character) >= 32)
        return label[:255] or "MeerK40t GCC Job"

    def plot(self, cut):
        self.queue.append(cut)

    def plot_start(self):
        # A LaserJob can contain multiple CutCode generators. Keep collecting
        # until job_finish so one plan produces one GCC envelope.
        return False

    def _speed(self, settings, raster=False):
        speed = float(settings.get("speed", 0))
        attr = "max_raster_speed" if raster else "max_vector_speed"
        maximum = float(getattr(self.service, attr, 1000.0))
        if maximum <= 0:
            raise ValueError("%s must be greater than zero" % attr)
        return _clamp(speed * 1000.0 / maximum)

    def _pen_settings(self, cut, raster=False):
        settings = cut.settings
        coolant = int(settings.get("coolant", 0) or 0)
        if coolant == 1:
            air = True
        elif coolant == 2:
            air = False
        else:
            air = bool(getattr(self.service, "air_assist", False))
        return {
            "speed": self._speed(settings, raster=raster),
            "power": _clamp(settings.get("power", 1000)),
            "ppi_enabled": bool(
                settings.get(
                    "ppi_enabled", getattr(self.service, "ppi_enabled", True)
                )
            ),
            "ppi": _clamp(
                settings.get("gcc_ppi", getattr(self.service, "ppi", 400))
            ),
            "air": air,
        }

    def _assign_pens(self, rasters, vectors):
        default = {
            "speed": 500,
            "power": 500,
            "ppi_enabled": bool(getattr(self.service, "ppi_enabled", True)),
            "ppi": _clamp(getattr(self.service, "ppi", 400)),
            "air": False,
        }
        pens = [dict(default) for _ in range(16)]
        assignments = {}
        used = set()

        def assign(cut, raster=False):
            key = id(cut.settings)
            if key in assignments:
                return assignments[key]
            desired = 1 if raster else PALETTE_SLOTS.get(_color_rgb(cut.color))
            setting = self._pen_settings(cut, raster=raster)
            if desired is not None and (
                desired not in used or pens[desired - 1] == setting
            ):
                slot = desired
            else:
                slot = next(
                    (index for index in range(1, 17) if index not in used), None
                )
                if slot is None:
                    raise ValueError(
                        "GCC jobs support at most 16 distinct pen settings"
                    )
            pens[slot - 1] = setting
            used.add(slot)
            assignments[key] = slot
            return slot

        for cut in rasters:
            assign(cut, raster=True)
        for cut in vectors:
            assign(cut, raster=False)
        return pens, assignments

    @staticmethod
    def _raster_bounds(cut):
        return (
            cut.offset_x,
            cut.offset_y,
            cut.offset_x + cut.width * cut.step_x,
            cut.offset_y + cut.height * cut.step_y,
        )

    def _bounds(self, cuts):
        if self._job is not None:
            bounds = self._job.bounds()
            if bounds is not None:
                return bounds
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")
        for cut in cuts:
            if isinstance(cut, RasterCut):
                left, top, right, bottom = self._raster_bounds(cut)
            else:
                points = [cut.start, cut.end]
                left = min(point[0] for point in points)
                top = min(point[1] for point in points)
                right = max(point[0] for point in points)
                bottom = max(point[1] for point in points)
            min_x = min(min_x, left)
            min_y = min(min_y, top)
            max_x = max(max_x, right)
            max_y = max(max_y, bottom)
        if min_x == float("inf"):
            return 0, 0, 0, 0
        return min_x, min_y, max_x, max_y

    @staticmethod
    def _pcl(value, dpi):
        return int(round(float(value) * float(dpi) / NATIVE_DPI))

    @staticmethod
    def _native_from_pcl(value, dpi):
        return int(round(float(value) * NATIVE_DPI / float(dpi)))

    def _raster_dpi(self, cut):
        if not cut.horizontal:
            raise ValueError("GCC export currently supports horizontal raster only")
        if not cut.bidirectional:
            raise ValueError("GCC export currently supports bidirectional raster only")
        if cut.step_x == 0:
            raise ValueError("GCC raster pixel width must not be zero")
        dpi = int(round(NATIVE_DPI / abs(float(cut.step_x))))
        dpi = DISPLAY_DPI.get(dpi, dpi)
        if dpi not in SUPPORTED_DPI:
            raise ValueError("Unsupported GCC raster resolution: %s DPI" % dpi)
        return dpi

    def _write_raster(self, encoder, cut, first, cursor):
        dpi = self._raster_dpi(cut)
        x = self._pcl(cut.offset_x, dpi)
        y = self._pcl(cut.offset_y, dpi)
        if not cut.start_minimum_y:
            y += cut.height - 1
        if not first:
            encoder.move_raster_cursor(x - cursor[0], y - cursor[1])
        setting = self._pen_settings(cut, raster=True)
        encoder.begin_raster(
            cut.height,
            cut.width,
            setting["speed"],
            setting["power"],
            dpi=dpi,
            top_down=cut.start_minimum_y,
        )
        rows = range(cut.height)
        if not cut.start_minimum_y:
            rows = range(cut.height - 1, -1, -1)
        for row in rows:
            pixels = [
                1 if cut.plot.px(column, row) >= 0.5 else 0
                for column in range(cut.width)
            ]
            encoder.write_raster_row(pixels)
        encoder.end_raster()
        end_y = y + (cut.height - 1 if cut.start_minimum_y else -(cut.height - 1))
        return [x, end_y], dpi

    def _write_vector_cut(self, encoder, cut):
        if isinstance(cut, LineCut):
            encoder.vector_cut(*cut.end)
            return
        if isinstance(cut, (QuadCut, CubicCut)):
            geometry = Geomstr()
            if isinstance(cut, CubicCut):
                geometry.cubic(
                    complex(*cut.start),
                    complex(*cut.c1()),
                    complex(*cut.c2()),
                    complex(*cut.end),
                )
            else:
                geometry.quad(
                    complex(*cut.start), complex(*cut.c()), complex(*cut.end)
                )
            for point in list(geometry.as_equal_interpolated_points(distance=4))[1:]:
                encoder.vector_cut(point.real, point.imag)
            return
        if isinstance(cut, PlotCut):
            for unused_x, unused_y, on, x, y in cut.plot:
                if on:
                    encoder.vector_cut(x, y)
                else:
                    encoder.vector_move(x, y)
            return
        raise ValueError("Unsupported GCC vector cut: %s" % type(cut).__name__)

    def _park_bytes(self, pcl_x, pcl_y, dpi):
        park_x = int(round(Length(self.service.park_x).mm * dpi / 25.4))
        park_y = int(round(Length(self.service.park_y).mm * dpi / 25.4))
        return (
            esc_command(b"*p%+dX" % (park_x - pcl_x))
            + esc_command(b"*p%+dY" % (park_y - pcl_y))
        )

    def _build_job(self):
        rasters = [cut for cut in self.queue if isinstance(cut, RasterCut)]
        vectors = [
            cut
            for cut in self.queue
            if isinstance(cut, (LineCut, QuadCut, CubicCut, PlotCut))
        ]
        unsupported = [
            cut for cut in self.queue if cut not in rasters and cut not in vectors
        ]
        if unsupported:
            raise ValueError(
                "Unsupported GCC cut type: %s" % type(unsupported[0]).__name__
            )

        dpi = self._raster_dpi(rasters[0]) if rasters else int(self.service.raster_dpi)
        if any(self._raster_dpi(cut) != dpi for cut in rasters):
            raise ValueError("All GCC raster bands in a job must use the same DPI")

        pens, assignments = self._assign_pens(rasters, vectors)
        encoder = GCCJob()
        label = os.path.basename(getattr(self._job, "label", "") or "")
        encoder.begin_job(
            label,
            immediate=bool(self.service.immediate_start),
            settings=pens,
            dpi=dpi,
            legacy_header_value=self.service.legacy_header_value,
        )

        all_cuts = rasters + vectors
        min_x, min_y, max_x, max_y = self._bounds(all_cuts)
        frame_left = self._pcl(min_x, dpi)
        frame_top = self._pcl(min_y, dpi)
        frame_width = max(1, self._pcl(max_x, dpi) - frame_left)
        frame_height = max(1, self._pcl(max_y, dpi) - frame_top)

        if rasters:
            first_x = self._pcl(rasters[0].offset_x, dpi)
            first_y = self._pcl(rasters[0].offset_y, dpi)
        elif vectors:
            first_x = self._pcl(vectors[0].start[0], dpi)
            first_y = self._pcl(vectors[0].start[1], dpi)
        else:
            first_x = frame_left
            first_y = frame_top
        if vectors and not rasters:
            setting = self._pen_settings(vectors[0], raster=False)
            encoder.write_raster_settings(setting["speed"], setting["power"])
            encoder.write_resolution(dpi)
        encoder.write_raster_frame(
            frame_width,
            frame_height,
            first_x,
            first_y,
            raster_offset_x=first_x - frame_left,
            raster_offset_y=first_y - frame_top,
        )

        cursor = [first_x, first_y]
        for index, cut in enumerate(rasters):
            cursor, unused_dpi = self._write_raster(
                encoder, cut, first=index == 0, cursor=cursor
            )

        if vectors:
            if not rasters:
                encoder.write_job_start()
                encoder.reset_raster()
            encoder.begin_vector()
            encoder.set_vector_position(
                self._native_from_pcl(cursor[0], dpi),
                self._native_from_pcl(cursor[1], dpi),
            )
            current_pen = None
            for cut in vectors:
                if tuple(cut.start) != (encoder._vector_x, encoder._vector_y):
                    encoder.vector_move(*cut.start)
                pen = assignments[id(cut.settings)]
                if pen != current_pen:
                    encoder.select_pen(pen)
                    current_pen = pen
                self._write_vector_cut(encoder, cut)
            cursor = [
                self._pcl(encoder._vector_x, dpi),
                self._pcl(encoder._vector_y, dpi),
            ]

        self.native_x = self._native_from_pcl(cursor[0], dpi)
        self.native_y = self._native_from_pcl(cursor[1], dpi)
        encoder.finish_job(park=self._park_bytes(cursor[0], cursor[1], dpi))
        return encoder.getvalue()
