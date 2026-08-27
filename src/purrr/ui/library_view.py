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
        self.drive_file_id: str = row["drive_file_id"]
        self.title: str = row["title"] or row["file_name"]
        self.artist: str = row["artist"] or ""
        self.album: str = row["album"] or ""
        self.duration_str: str = _format_duration(row["duration_seconds"])
        self.duration_seconds: float = row["duration_seconds"] or 0.0
        self.local_path: str | None = row["local_path"]
        self.cache_status: str = row["cache_status"]
        self.art_path: str | None = row["art_path"]
        self.track_label: str = str(row["track_number"]) if row["track_number"] is not None else ""
        # Sentinel grande para que las pistas sin número de pista queden al final al ordenar,
        # en vez de mezclarse con la pista "0"/"1" real por culpa del None.
        self.track_number_sort: int = (
            row["track_number"] if row["track_number"] is not None else 1_000_000
        )


def text_column(
    title: str, attr: str, expand: bool = False, sortable: bool = False, sort_attr: str | None = None
) -> Gtk.ColumnViewColumn:
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

    if sortable:
        key = sort_attr or attr

        def compare(a: TrackObject, b: TrackObject, _data=None) -> int:
            va, vb = getattr(a, key), getattr(b, key)
            return -1 if va < vb else (1 if va > vb else 0)

        column.set_sorter(Gtk.CustomSorter.new(compare))

    return column


class LibraryView(Gtk.Box):
    """Lista buscable y ordenable de la biblioteca, respaldada por Gio.ListStore + Gtk.ColumnView."""

    __gsignals__ = {
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "search-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self._search_entry = Gtk.SearchEntry(placeholder_text="Buscar por título, artista o álbum")
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._search_changed_source_id: int | None = None
        self.append(self._search_entry)

        self._store = Gio.ListStore(item_type=TrackObject)
        # El SortListModel deja que el usuario reordene haciendo clic en los encabezados de columna,
        # sin tocar el orden de inserción original (que ya viene agrupado por artista/álbum desde SQL).
        self._sort_model = Gtk.SortListModel(model=self._store)
        self._selection = Gtk.MultiSelection(model=self._sort_model)

        self._column_view = Gtk.ColumnView(model=self._selection)
        self._column_view.append_column(text_column("Título", "title", expand=True, sortable=True))
        self._column_view.append_column(text_column("Artista", "artist", expand=True, sortable=True))
        self._column_view.append_column(text_column("Álbum", "album", expand=True, sortable=True))
        self._column_view.append_column(
            text_column("Duración", "duration_str", sortable=True, sort_attr="duration_seconds")
        )
        self._column_view.connect("activate", self._on_row_activated)
        self._sort_model.set_sorter(self._column_view.get_sorter())

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._column_view)
        self.append(scrolled)

    def refresh(self, track_rows: list[sqlite3.Row]) -> None:
        # splice() en vez de remove_all() + append() en loop: reemplaza todo en una sola señal
        # "items-changed" en lugar de miles. Con bibliotecas grandes, el loop de appends uno por
        # uno no solo es mucho más lento (~10x) sino que además se degrada en llamadas sucesivas
        # (cada refresh() quedaba más lento que el anterior) — vimos una biblioteca de 8900
        # canciones pasar de ~1s a >10s tras solo un puñado de refrescos seguidos, suficiente para
        # que la ventana pareciera colgada durante un escaneo de metadatos.
        items = [TrackObject(row) for row in track_rows]
        self._store.splice(0, self._store.get_n_items(), items)

    def get_visible_tracks(self) -> list[TrackObject]:
        """Tracks tal como se ven actualmente (respetando el orden/columna elegidos por el usuario)."""
        return [self._selection.get_item(i) for i in range(self._selection.get_n_items())]

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
        # Gtk.Bitset no es iterable directo desde Python; recorremos el modelo (ya ordenado) y consultamos.
        for position in range(self._selection.get_n_items()):
            if bitset.contains(position):
                ids.append(self._selection.get_item(position).track_id)
        return ids

    def _on_row_activated(self, _view, position: int) -> None:
        track: TrackObject = self._selection.get_item(position)
        self.emit("track-activated", track.track_id)
