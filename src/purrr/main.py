import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from purrr.config import APP_ID, ensure_dirs
from purrr.db import database
from purrr.ui.window import PurrrWindow


class PurrrApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

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
