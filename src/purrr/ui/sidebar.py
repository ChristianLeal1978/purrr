import sqlite3

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk

_LIBRARY_ROW = "library"
_FOLDERS_ROW = "folders"
_SOURCES_ROW = "sources"
_NEW_PLAYLIST_ROW = "new-playlist"


class Sidebar(Gtk.Box):
    __gsignals__ = {
        "library-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "folders-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "sources-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "playlist-selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "new-playlist-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._playlist_row_ids: dict[Gtk.ListBoxRow, int] = {}

        self._list_box = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self._list_box.connect("row-activated", self._on_row_activated)

        self._library_row = self._make_row("Biblioteca", "audio-x-generic-symbolic")
        self._list_box.append(self._library_row)

        self._folders_row = self._make_row("Carpetas", "folder-symbolic")
        self._list_box.append(self._folders_row)

        self._sources_row = self._make_row("Fuentes de Google Drive", "folder-remote-symbolic")
        self._list_box.append(self._sources_row)

        header = Gtk.ListBoxRow(selectable=False, activatable=False)
        header_label = Gtk.Label(label="Playlists", halign=Gtk.Align.START, margin_top=12)
        header_label.add_css_class("heading")
        header.set_child(header_label)
        self._list_box.append(header)

        self._new_playlist_row = self._make_row("Nueva playlist…", "list-add-symbolic")
        self._list_box.append(self._new_playlist_row)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._list_box)
        self.append(scrolled)

        self._list_box.select_row(self._library_row)

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
        elif row is self._sources_row:
            self.emit("sources-selected")
        elif row is self._new_playlist_row:
            self.emit("new-playlist-requested")
        elif row in self._playlist_row_ids:
            self.emit("playlist-selected", self._playlist_row_ids[row])
