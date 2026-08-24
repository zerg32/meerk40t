"""Export-only GCC LaserPro device service."""

from meerk40t.core.laserjob import LaserJob
from meerk40t.core.units import Length
from meerk40t.core.view import View
from meerk40t.device.devicechoices import get_effect_choices, get_operation_choices
from meerk40t.device.mixins import Status
from meerk40t.kernel import CommandSyntaxError, Service, signal_listener

from .driver import GCCDriver


class GCCDevice(Service, Status):
    """Device settings and PRN export for GCC LaserPro machines."""

    def __init__(self, kernel, path, *args, choices=None, **kwargs):
        Service.__init__(self, kernel, path)
        Status.__init__(self)
        self.name = "GCCDevice"
        self.extension = "prn"

        if choices is not None:
            for choice in choices:
                attr = choice.get("attr")
                default = choice.get("default")
                if attr is not None and default is not None:
                    setattr(self, attr, default)

        self.setting(bool, "use_percent_for_power_display", False)
        self.setting(bool, "use_mm_min_for_speed_display", False)

        _ = self._
        self._laser_status = "idle"
        configuration = "_10_" + _("Configuration")
        dimensions = "_10_" + _("Dimensions")
        axis_corrections = "_20_" + _("Axis corrections")
        output = "_20_" + _("GCC Export")

        choices = [
            {
                "attr": "label",
                "object": self,
                "default": path,
                "type": str,
                "label": _("Label"),
                "tip": _("What is this device called."),
                "section": "_00_" + _("General"),
                "signals": "device;renamed",
            },
            {
                "attr": "bedwidth",
                "object": self,
                "default": "635mm",
                "type": Length,
                "label": _("Width"),
                "tip": _(
                    "Configured width of the laser bed for this device profile."
                ),
                "section": configuration,
                "subsection": dimensions,
                "nonzero": True,
            },
            {
                "attr": "bedheight",
                "object": self,
                "default": "458mm",
                "type": Length,
                "label": _("Height"),
                "tip": _(
                    "Configured height of the laser bed for this device profile."
                ),
                "section": configuration,
                "subsection": dimensions,
                "nonzero": True,
            },
            {
                "attr": "scale_x",
                "object": self,
                "default": 1.0,
                "type": float,
                "label": _("X Scale Factor"),
                "tip": _("Scale factor for the X axis."),
                "section": configuration,
                "subsection": axis_corrections,
            },
            {
                "attr": "scale_y",
                "object": self,
                "default": 1.0,
                "type": float,
                "label": _("Y Scale Factor"),
                "tip": _("Scale factor for the Y axis."),
                "section": configuration,
                "subsection": axis_corrections,
            },
            {
                "attr": "flip_x",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Flip X"),
                "tip": _("Flip the X axis for the exported job."),
                "section": configuration,
                "subsection": axis_corrections,
            },
            {
                "attr": "flip_y",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Flip Y"),
                "tip": _("Flip the Y axis for the exported job."),
                "section": configuration,
                "subsection": axis_corrections,
            },
            {
                "attr": "swap_xy",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Swap X and Y"),
                "tip": _("Swap the X and Y axes before applying axis flips."),
                "section": configuration,
                "subsection": axis_corrections,
            },
            {
                "attr": "home_corner",
                "object": self,
                "default": "auto",
                "type": str,
                "style": "combo",
                "choices": [
                    "auto",
                    "top-left",
                    "top-right",
                    "bottom-left",
                    "bottom-right",
                    "center",
                ],
                "label": _("Force Declared Home"),
                "tip": _("Override the native home location."),
                "section": configuration,
                "subsection": "_30_" + _("Home position"),
            },
            {
                "attr": "user_margin_x",
                "object": self,
                "default": "0",
                "type": str,
                "label": _("X-Margin"),
                "tip": _("Unused space at the left side of the X axis."),
                "section": configuration,
                "subsection": "_40_" + _("User Offset"),
            },
            {
                "attr": "user_margin_y",
                "object": self,
                "default": "0",
                "type": str,
                "label": _("Y-Margin"),
                "tip": _("Unused space at the top of the Y axis."),
                "section": configuration,
                "subsection": "_40_" + _("User Offset"),
            },
        ]
        self.register_choices("gcc-bed", choices)

        choices = [
            {
                "attr": "max_vector_speed",
                "object": self,
                "default": 1000.0,
                "type": float,
                "style": "speed",
                "label": _("Maximum vector speed"),
                "tip": _(
                    "Generic configurable speed ceiling used to scale vector "
                    "speed into GCC's 0-1000 range."
                ),
                "section": output,
            },
            {
                "attr": "max_raster_speed",
                "object": self,
                "default": 1000.0,
                "type": float,
                "style": "speed",
                "label": _("Maximum raster speed"),
                "tip": _(
                    "Generic configurable speed ceiling used to scale raster "
                    "speed into GCC's 0-1000 range."
                ),
                "section": output,
            },
            {
                "attr": "raster_dpi",
                "object": self,
                "default": 508,
                "type": int,
                "style": "combo",
                "choices": [127, 254, 381, 508, 762, 1016, 1524],
                "label": _("Raster DPI"),
                "tip": _("Default GCC raster resolution."),
                "section": output,
            },
            {
                "attr": "ppi_enabled",
                "object": self,
                "default": True,
                "type": bool,
                "label": _("Enable PPI"),
                "tip": _("Enable pulses-per-inch control in exported jobs."),
                "section": output,
            },
            {
                "attr": "ppi",
                "object": self,
                "default": 400,
                "type": int,
                "min": 0,
                "max": 1000,
                "label": _("PPI"),
                "tip": _("Default pulses per inch, from 0 through 1000."),
                "conditional": (self, "ppi_enabled"),
                "section": output,
            },
            {
                "attr": "immediate_start",
                "object": self,
                "default": False,
                "type": bool,
                "label": _("Start immediately"),
                "tip": _(
                    "Start the job immediately after download. Disable for "
                    "manual start at the laser."
                ),
                "section": output,
            },
            {
                "attr": "park_x",
                "object": self,
                "default": "617.3mm",
                "type": Length,
                "label": _("Park X"),
                "tip": _("X coordinate used when parking after export."),
                "section": output,
            },
            {
                "attr": "park_y",
                "object": self,
                "default": "5mm",
                "type": Length,
                "label": _("Park Y"),
                "tip": _("Y coordinate used when parking after export."),
                "section": output,
            },
            {
                "attr": "legacy_header_value",
                "object": self,
                "default": 152500,
                "type": int,
                "label": _("Legacy header value"),
                "tip": _(
                    "Value emitted by the legacy GCC driver in the job header."
                ),
                "section": output,
            },
        ]
        self.register_choices("gcc-export", choices)
        self.register_choices("gcc-effects", get_effect_choices(self))
        self.register_choices(
            "gcc-defaults",
            get_operation_choices(
                self,
                default_cut_speed=20,
                default_engrave_speed=100,
                default_raster_speed=300,
            ),
        )

        self.view = View(self.bedwidth, self.bedheight, dpi=1016.0)
        self.realize()
        self.driver = GCCDriver(self)
        self.spooler = None

        @self.console_argument("filename", type=str)
        @self.console_command(
            "save_job", help=_("Save GCC job export"), input_type="plan"
        )
        def gcc_save(channel, _, filename, data=None, **kwgs):
            if filename is None:
                raise CommandSyntaxError
            try:
                with open(filename, "wb") as output_file:
                    driver = GCCDriver(self, output_file.write)
                    job = LaserJob(
                        filename,
                        list(data.plan),
                        driver=driver,
                        outline=getattr(data, "outline", None),
                    )
                    driver.job_start(job)
                    job.execute()
                    driver.job_finish(job)
            except (PermissionError, OSError) as error:
                channel(
                    _("Could not save {filename}: {error}").format(
                        filename=filename, error=error
                    )
                )
            except Exception as error:
                channel(
                    _("Could not export {filename}: {error}").format(
                        filename=filename, error=error
                    )
                )

    @property
    def safe_label(self):
        label = getattr(self, "label", self.name).replace(" ", "-")
        return label.replace("/", "-")

    def service_attach(self, *args, **kwargs):
        self.realize()

    def location(self):
        return self._("File export only")

    @property
    def connected(self):
        return False

    @property
    def is_busy(self):
        return False

    @property
    def current(self):
        return self.view.iposition(self.driver.native_x, self.driver.native_y)

    @property
    def native(self):
        return self.driver.native_x, self.driver.native_y

    @signal_listener("bedwidth")
    @signal_listener("bedheight")
    @signal_listener("scale_x")
    @signal_listener("scale_y")
    @signal_listener("flip_x")
    @signal_listener("flip_y")
    @signal_listener("swap_xy")
    @signal_listener("home_corner")
    @signal_listener("user_margin_x")
    @signal_listener("user_margin_y")
    def realize(self, origin=None, *args):
        if origin is not None and origin != self.path:
            return
        corner = self.setting(str, "home_corner")
        home_dx = 0
        home_dy = 0
        if corner == "top-left":
            home_dx = 1 if self.flip_x else 0
            home_dy = 1 if self.flip_y else 0
        elif corner == "top-right":
            home_dx = 0 if self.flip_x else 1
            home_dy = 1 if self.flip_y else 0
        elif corner == "bottom-left":
            home_dx = 1 if self.flip_x else 0
            home_dy = 0 if self.flip_y else 1
        elif corner == "bottom-right":
            home_dx = 0 if self.flip_x else 1
            home_dy = 0 if self.flip_y else 1
        elif corner == "center":
            home_dx = 0.5
            home_dy = 0.5
        self.view.set_dims(self.bedwidth, self.bedheight)
        self.view.set_margins(self.user_margin_x, self.user_margin_y)
        self.view.transform(
            user_scale_x=self.scale_x,
            user_scale_y=self.scale_y,
            flip_x=self.flip_x,
            flip_y=self.flip_y,
            swap_xy=self.swap_xy,
            origin_x=home_dx,
            origin_y=home_dy,
        )
        self.view.realize()
        self.signal("view;realized")

    def get_operation_defaults(self, operation_type):
        return self.get_operation_power_speed_defaults(operation_type)
