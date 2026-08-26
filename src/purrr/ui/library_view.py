import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, GLib, GObject, Gtk, Pango


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return "--:--"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class TrackObject(GObject.Object):
    """Envoltorio GObject de una fila de `tracks` para usar en un Gio.ListStore."""

    def __init__(self, row: sqlite3.Row):
        super().__init__()
        self.track_id: int = row["id"]
        self.title: str = row["title"] or row["file_name"]
        self.artist: str = row["artist"] or ""
        self.album: str = row["album"] or ""
        self.duration_str: str = _format_duration(row["duration_seconds"])
        self.duration_seconds: float = row["duration_seconds"] or 0.0
        self.local_path: str | None = row["local_path"]
        self.cache_status: str = row["cache_status"]


def text_column(title: str, attr: str, expand: bool = False) -> Gtk.ColumnViewColumn:
    factory = Gtk.SignalListItemFactory()

    def on_setup(_factory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
        list_item.set_child(label)

    def on_bind(_factory, list_item: Gtk.ListItem) -> None:
        label = list_item.get_child()
        track: TrackObject = list_item.get_item()
        label.set_text(getattr(track, attr))

    factory.connect("setup", on_setup)
    factory.connect("bind", on_bind)
    column = Gtk.ColumnViewColumn(title=title, factory=factory)
    column.set_expand(expand)
    return column


class LibraryView(Gtk.Box):
    """Lista buscable de la biblioteca completa, respaldada por Gio.ListStore + Gtk.ColumnView."""

    __gsignals__ = {
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "search-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._tracks: list[TrackObject] = []

        self._search_entry = Gtk.SearchEntry(placeholder_text="Buscar por título, artista o álbum")
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_changed_source_id: int | None = None
        self.append(self._search_entry)

        self._store = Gio.ListStore(item_type=TrackObject)
        self._selection = Gtk.MultiSelection(model=self._store)

        self._column_view = Gtk.ColumnView(model=self._selection)
        self._column_view.append_column(text_column("Título", "title", expand=True))
        self._column_view.append_column(text_column("Artista", "artist", expand=True))
        self._column_view.append_column(text_column("Álbum", "album", expand=True))
        self._column_view.append_column(text_column("Duración", "duration_str"))
        self._column_view.connect("activate", self._on_row_activated)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._column_view)
        self.append(scrolled)

    def refresh(self, track_rows: list[sqlite3.Row]) -> None:
        self._tracks = [TrackObject(row) for row in track_rows]
        self._store.remove_all()
        for track in self._tracks:
            self._store.append(track)

    def get_visible_tracks(self) -> list[TrackObject]:
        return self._tracks

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        if self._search_changed_source_id is not None:
            GLib.source_remove(self._search_changed_source_id)

        def do_filter() -> bool:
            self._search_changed_source_id = None
            self.emit("search-changed", entry.get_text())
            return False

        self._search_changed_source_id = GLib.timeout_add(300, do_filter)

    def get_selected_track_ids(self) -> list[int]:
        bitset = self._selection.get_selection()
        ids = []
        # Gtk.Bitset no es iterable directo desde Python; recorremos el modelo y consultamos.
        for position in range(self._store.get_n_items()):
            if bitset.contains(position):
                ids.append(self._tracks[position].track_id)
        return ids

    def _on_row_activated(self, _view, position: int) -> None:
        track: TrackObject = self._store.get_item(position)
        self.emit("track-activated", track.track_id)
