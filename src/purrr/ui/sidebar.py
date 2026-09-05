import sqlite3

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

_LIBRARY_ROW = "library"
_FOLDERS_ROW = "folders"
_ALBUMS_ROW = "albums"
_SOURCES_ROW = "sources"
_RAINWAVE_ROW = "rainwave"
_RADIOTUNES_ROW = "radiotunes"
_BIOBIO_ROW = "biobio"
_SMOOTHJAZZ_ROW = "smoothjazz"
_SPOTIFY_ROW = "spotify"
_MOOD_ROW = "mood"
_CLOUD_ROW = "cloud"
_NEW_PLAYLIST_ROW = "new-playlist"


class Sidebar(Gtk.Box):
    __gsignals__ = {
        "library-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "folders-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "albums-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "sources-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Antes era una sola sección "Radios" con las 4 fuentes agrupadas adentro
        # (ver ui/stations_view.py); ahora cada una es su propia fila del menú.
        "rainwave-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "radiotunes-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "biobio-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "smoothjazz-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "spotify-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "mood-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "cloud-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "playlist-selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "new-playlist-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["purrr-sidebar"])
        self._playlist_row_ids: dict[Gtk.ListBoxRow, int] = {}

        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                             margin_top=14, margin_bottom=6, margin_start=8, margin_end=8)
        brand_box.append(Gtk.Label(label="🐾"))
        brand_label = Gtk.Label(label="Purrr", halign=Gtk.Align.START)
        brand_label.add_css_class("purrr-sidebar-brand")
        brand_box.append(brand_label)
        self.append(brand_box)

        self._list_box = Gtk.ListBox(css_classes=["navigation-sidebar", "purrr-sidebar-list"])
        self._list_box.connect("row-activated", self._on_row_activated)

        self._library_row = self._make_row("Biblioteca", "audio-x-generic-symbolic")
        self._list_box.append(self._library_row)

        self._folders_row = self._make_row("Carpetas", "folder-symbolic")
        self._list_box.append(self._folders_row)

        self._albums_row = self._make_row("Álbumes", "media-optical-symbolic")
        self._list_box.append(self._albums_row)

        self._rainwave_row = self._make_row("Rainwave", "applications-games-symbolic")
        self._list_box.append(self._rainwave_row)

        self._radiotunes_row = self._make_row("RadioTunes", "radio-symbolic")
        self._list_box.append(self._radiotunes_row)

        self._biobio_row = self._make_row("Radio Bío-Bío", "network-transmit-symbolic")
        self._list_box.append(self._biobio_row)

        self._smoothjazz_row = self._make_row("SmoothJazz.com", "audio-speakers-symbolic")
        self._list_box.append(self._smoothjazz_row)

        self._spotify_row = self._make_row("Spotify", "audio-headphones-symbolic")
        self._list_box.append(self._spotify_row)

        self._mood_row = self._make_row("Ánimo", "face-smile-symbolic")
        self._list_box.append(self._mood_row)

        self._list_box.append(self._make_section_header("Playlists"))

        self._new_playlist_row = self._make_row("Nueva playlist…", "list-add-symbolic")
        self._list_box.append(self._new_playlist_row)

        self._list_box.append(self._make_section_header("Administrar"))

        self._sources_row = self._make_row("Fuentes de Google Drive", "folder-remote-symbolic")
        self._list_box.append(self._sources_row)

        self._cloud_row = self._make_row("Cuenta / Sync", "network-server-symbolic")
        self._list_box.append(self._cloud_row)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._list_box)
        self.append(scrolled)

        self._list_box.select_row(self._library_row)

    def select_library_row(self) -> None:
        self._list_box.select_row(self._library_row)

    def select_folders_row(self) -> None:
        self._list_box.select_row(self._folders_row)

    def select_albums_row(self) -> None:
        self._list_box.select_row(self._albums_row)

    def select_sources_row(self) -> None:
        self._list_box.select_row(self._sources_row)

    def select_rainwave_row(self) -> None:
        self._list_box.select_row(self._rainwave_row)

    def select_radiotunes_row(self) -> None:
        self._list_box.select_row(self._radiotunes_row)

    def select_biobio_row(self) -> None:
        self._list_box.select_row(self._biobio_row)

    def select_smoothjazz_row(self) -> None:
        self._list_box.select_row(self._smoothjazz_row)

    def select_spotify_row(self) -> None:
        self._list_box.select_row(self._spotify_row)

    def select_mood_row(self) -> None:
        self._list_box.select_row(self._mood_row)

    def select_cloud_row(self) -> None:
        self._list_box.select_row(self._cloud_row)

    def select_playlist_row(self, playlist_id: int) -> None:
        for row, pid in self._playlist_row_ids.items():
            if pid == playlist_id:
                self._list_box.select_row(row)
                return

    def _make_section_header(self, label: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        header_label = Gtk.Label(label=label, halign=Gtk.Align.START, margin_top=12)
        header_label.add_css_class("purrr-sidebar-section-label")
        row.set_child(header_label)
        return row

    def _make_row(self, label: str, icon_name: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=6, margin_bottom=6,
                       margin_start=8, margin_end=8)
        box.append(Gtk.Image(icon_name=icon_name))
        box.append(Gtk.Label(label=label, halign=Gtk.Align.START))
        row.set_child(box)
        return row

    def refresh_playlists(self, playlists: list[sqlite3.Row]) -> None:
        for row in list(self._playlist_row_ids):
            self._list_box.remove(row)
        self._playlist_row_ids.clear()

        for playlist in playlists:
            row = self._make_row(playlist["name"], "view-list-symbolic")
            self._list_box.insert(row, self._index_of(self._new_playlist_row))
            self._playlist_row_ids[row] = playlist["id"]

    def _index_of(self, row: Gtk.ListBoxRow) -> int:
        index = 0
        child = self._list_box.get_first_child()
        while child is not None and child is not row:
            index += 1
            child = child.get_next_sibling()
        return index

    def _on_row_activated(self, _list_box, row: Gtk.ListBoxRow) -> None:
        if row is self._library_row:
            self.emit("library-selected")
        elif row is self._folders_row:
            self.emit("folders-selected")
        elif row is self._albums_row:
            self.emit("albums-selected")
        elif row is self._sources_row:
            self.emit("sources-selected")
        elif row is self._rainwave_row:
            self.emit("rainwave-selected")
        elif row is self._radiotunes_row:
            self.emit("radiotunes-selected")
        elif row is self._biobio_row:
            self.emit("biobio-selected")
        elif row is self._smoothjazz_row:
            self.emit("smoothjazz-selected")
        elif row is self._spotify_row:
            self.emit("spotify-selected")
        elif row is self._mood_row:
            self.emit("mood-selected")
        elif row is self._cloud_row:
            self.emit("cloud-selected")
        elif row is self._new_playlist_row:
            self.emit("new-playlist-requested")
        elif row in self._playlist_row_ids:
            self.emit("playlist-selected", self._playlist_row_ids[row])
