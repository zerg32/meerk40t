import wx

from meerk40t.gui.choicepropertypanel import ChoicePropertyPanel
from meerk40t.gui.icons import icons8_administrative_tools
from meerk40t.gui.mwindow import MWindow

_ = wx.GetTranslation


class GCCConfiguration(MWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(480, 620, *args, **kwargs)
        self.context = self.context.device
        self.SetHelpText("gccconfig")
        icon = wx.NullIcon
        icon.CopyFromBitmap(icons8_administrative_tools.GetBitmap())
        self.SetIcon(icon)
        self.SetTitle(_("GCC LaserPro Output Configuration"))

        notebook = wx.aui.AuiNotebook(
            self,
            -1,
            style=wx.aui.AUI_NB_TAB_EXTERNAL_MOVE
            | wx.aui.AUI_NB_SCROLL_BUTTONS
            | wx.aui.AUI_NB_TAB_MOVE,
        )
        self.window_context.themes.set_window_colors(notebook)
        self.sizer.Add(notebook, 1, wx.EXPAND, 0)

        self.panels = []
        for choices, title in (
            ("gcc-bed", _("Device")),
            ("gcc-export", _("Output")),
            ("gcc-defaults", _("Operation Defaults")),
            ("gcc-effects", _("Effects")),
        ):
            panel = ChoicePropertyPanel(
                notebook, wx.ID_ANY, context=self.context, choices=choices
            )
            self.panels.append(panel)
            notebook.AddPage(panel, title)

        self.Layout()
        self.restore_aspect()
        for panel in self.panels:
            self.add_module_delegate(panel)

    def window_close(self):
        for panel in self.panels:
            panel.pane_hide()

    def window_open(self):
        for panel in self.panels:
            panel.pane_show()

    def window_preserve(self):
        return False

    @staticmethod
    def submenu():
        return "Device-Settings", "Configuration"
