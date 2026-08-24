"""
This file is used in builds to replace the dynamic plugins file. This file should not be included anywhere. It should
be swapped during a full build so that entry_points get switched for hard-linked references. This ensures that builds
can contain a list of useful desired plugins.

If you have written such a plugin, raise an issue to have it reviewed and included into the builds.
"""


def plugin(kernel, lifecycle):
    if lifecycle == "plugins":
        if kernel.args.no_plugins:
            # If no plugins was requested, we do not load these plugins.
            return

        plugins = list()

        """
        This loads Jpirnay's meerk40t-barcodes plugin.

        https://github.com/meerk40t/meerk40t-barcodes
        """

        try:
            from barcodes.main import plugin as barplugin
        except ImportError:
            # Optional build plugin. A frozen executable must still start when
            # the package was not installed in the build environment.
            pass
        else:
            plugins.append(barplugin)

        return plugins
