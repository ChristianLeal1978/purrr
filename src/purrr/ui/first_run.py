import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.auth.oauth import is_authenticated


class SourcesView(Gtk.Box):
    """Pantalla de 'Fuentes': conectar cuenta de Google, agregar/escanear/eliminar carpetas de Drive."""

    __gsignals__ = {
        "connect-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "add-folder-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "rescan-requested": (GObject.SignalFlags.RUN_FIRST, None, (int, str, str)),
        "delete-source-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        self._connect_status_page = Adw.StatusPage(
            icon_name="folder-remote-symbolic",
            title="Conecta tu cuenta de Google",
            description="Purrr necesita acceso de solo lectura a tu Google Drive para "
            "encontrar tu música.",
        )
        connect_button = Gtk.Button(
            label="Conectar cuenta de Google", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"]
        )
        connect_button.connect("clicked", lambda _b: self.emit("connect-requested"))
        self._connect_status_page.set_child(connect_button)
        self.append(self._connect_status_page)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.append(Gtk.Label(label="Carpetas conectadas", halign=Gtk.Align.START, hexpand=True,
                                 css_classes=["title-2"]))
        self._add_folder_button = Gtk.Button(label="Agregar carpeta", icon_name="list-add-symbolic")
        self._add_folder_button.connect("clicked", lambda _b: self.emit("add-folder-requested"))
        header.append(self._add_folder_button)
        self.append(header)

        self._progress_label = Gtk.Label(label="", halign=Gtk.Align.START, visible=False)
        self._progress_bar = Gtk.ProgressBar(visible=False)
        self.append(self._progress_label)
        self.append(self._progress_bar)

        self._sources_list = Gtk.ListBox(css_classes=["boxed-list"])
        self.append(self._sources_list)

        self.set_authenticated(is_authenticated())

    def set_authenticated(self, authenticated: bool) -> None:
        self._connect_status_page.set_visible(not authenticated)
        self._add_folder_button.set_sensitive(authenticated)

    def show_progress(self, stage: str, actual: int, total: int) -> None:
        self._progress_label.set_visible(True)
        self._progress_bar.set_visible(True)
        self._progress_label.set_text(stage)
        if total > 0:
            self._progress_bar.set_fraction(actual / total)
        else:
            self._progress_bar.pulse()

    def hide_progress(self) -> None:
        self._progress_label.set_visible(False)
        self._progress_bar.set_visible(False)

    def refresh_sources(self, sources: list[sqlite3.Row]) -> None:
        while row := self._sources_list.get_row_at_index(0):
            self._sources_list.remove(row)

        for source in sources:
            row = Adw.ActionRow(
                title=source["display_name"],
                subtitle=f"Última sincronización: {source['last_scanned_at'] or 'nunca'}",
            )
            rescan_button = Gtk.Button(
                icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Escanear ahora"
            )
            rescan_button.connect(
                "clicked",
                lambda _b, s=source: self.emit(
                    "rescan-requested", s["id"], s["drive_folder_id"], s["display_name"]
                ),
            )
            delete_button = Gtk.Button(
                icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Eliminar fuente"
            )
            delete_button.connect(
                "clicked", lambda _b, s=source: self.emit("delete-source-requested", s["id"])
            )
            row.add_suffix(rescan_button)
            row.add_suffix(delete_button)
            self._sources_list.append(row)
