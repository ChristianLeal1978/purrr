import sqlite3

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

_LIBRARY_ROW = "library"
_FOLDERS_ROW = "folders"
_ALBUMS_ROW = "albums"
_SOURCES_ROW = "sources"
_RADIOS_ROW = "radios"
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
        "radios-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
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

        menu_header = Gtk.Label(label="Menú", halign=Gtk.Align.START)
        menu_header.add_css_class("purrr-sidebar-section-label")
        self.append(menu_header)

        self._list_box = Gtk.ListBox(css_classes=["navigation-sidebar", "purrr-sidebar-list"])
        self._list_box.connect("row-activated", self._on_row_activated)

        self._library_row = self._make_row("Biblioteca", "audio-x-generic-symbolic")
        self._list_box.append(self._library_row)

        self._folders_row = self._make_row("Carpetas", "folder-symbolic")
        self._list_box.append(self._folders_row)

        self._albums_row = self._make_row("Álbumes", "media-optical-symbolic")
        self._list_box.append(self._albums_row)

        self._sources_row = self._make_row("Fuentes de Google Drive", "folder-remote-symbolic")
        self._list_box.append(self._sources_row)

        self._radios_row = self._make_row("Radios", "network-wireless-signal-excellent-symbolic")
        self._list_box.append(self._radios_row)

        self._spotify_row = self._make_row("Spotify", "audio-headphones-symbolic")
        self._list_box.append(self._spotify_row)

        self._mood_row = self._make_row("Ánimo", "face-smile-symbolic")
        self._list_box.append(self._mood_row)

        self._cloud_row = self._make_row("Cuenta / Sync", "network-server-symbolic")
        self._list_box.append(self._cloud_row)

        header = Gtk.ListBoxRow(selectable=False, activatable=False)
        header_label = Gtk.Label(label="Playlists", halign=Gtk.Align.START, margin_top=12)
        header_label.add_css_class("purrr-sidebar-section-label")
        header.set_child(header_label)
        self._list_box.append(header)

        self._new_playlist_row = self._make_row("Nueva playlist…", "list-add-symbolic")
        self._list_box.append(self._new_playlist_row)

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

    def select_radios_row(self) -> None:
        self._list_box.select_row(self._radios_row)

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
        elif row is self._radios_row:
            self.emit("radios-selected")
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
