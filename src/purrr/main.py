import sys
from importlib import resources

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, Gtk

from purrr.config import APP_ID, ensure_dirs
from purrr.db import database
from purrr.ui.window import PurrrWindow


class PurrrApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        css = resources.files("purrr.ui").joinpath("style.css").read_text()
        provider = Gtk.CssProvider()
        provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = PurrrWindow(application=self)
        window.present()


def main() -> int:
    ensure_dirs()
    database.init_db()
    app = PurrrApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
