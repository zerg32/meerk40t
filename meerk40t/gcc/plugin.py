"""GCC LaserPro PRN export and Windows printing plugin."""

from .device import GCCDevice


def plugin(kernel, lifecycle=None):
    if lifecycle == "plugins":
        from .gui import gui

        return [gui.plugin]
    if lifecycle == "register":
        _ = kernel.translation
        kernel.register("provider/device/gcc", GCCDevice)
        kernel.register(
            "provider/friendly/gcc", (_("GCC LaserPro (PRN / Windows RAW)"), 7)
        )
        kernel.register(
            "dev_info/gcc-laserpro",
            {
                "provider": "provider/device/gcc",
                "friendly_name": _(
                    "GCC LaserPro Mercury III (Old Motherboard)"
                ),
                "extended_info": _(
                    "Experimental GCC LaserPro PRN export and Windows RAW printer "
                    "queue submission. Physical machine status is not available."
                ),
                "priority": 0,
                "family": _("GCC LaserPro CO2-Laser"),
                "choices": [
                    {"attr": "label", "default": "GCC LaserPro Mercury III"},
                    {"attr": "bedwidth", "default": "635mm"},
                    {"attr": "bedheight", "default": "458mm"},
                ],
            },
        )
    elif lifecycle == "preboot":
        for section in kernel.section_startswith("gcc"):
            kernel.root(f"service device start -p {section} gcc\n")
