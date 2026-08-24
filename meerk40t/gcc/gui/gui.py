def plugin(service, lifecycle):
    if lifecycle == "invalidate":
        return not service.has_feature("wx")
    if lifecycle == "service":
        return "provider/device/gcc"
    if lifecycle == "added":
        from meerk40t.gcc.gui.gccconfig import GCCConfiguration
        from meerk40t.gui.icons import icons8_computer_support

        _ = service._
        service.register("window/Configuration", GCCConfiguration)
        service.register("winpath/Configuration", service)
        kernel = service.kernel
        if not (
            hasattr(kernel.args, "lock_device_config")
            and kernel.args.lock_device_config
        ):
            service.register(
                "button/device/Configuration",
                {
                    "label": _("Config"),
                    "icon": icons8_computer_support,
                    "tip": _("Open GCC export configuration"),
                    "action": lambda event: service(
                        "window toggle Configuration\n"
                    ),
                },
            )
