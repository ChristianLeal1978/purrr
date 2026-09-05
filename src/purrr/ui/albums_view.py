from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GObject, Gtk, Pango

from purrr.ui.context_menu import show_context_menu
from purrr.ui.library_view import TrackObject, apply_now_playing, text_column
from purrr.ui.textures import load_texture_at_size

_ART_SIZE = 160

_SORT_OPTIONS = [
    ("artist", "Artista"),
    ("title", "Título"),
    ("year", "Año"),
]


class AlbumObject(GObject.Object):
    def __init__(self, row):
        super().__init__()
        self.album_id: int = row["id"]
        self.album: str = row["album"]
        self.display_artist: str = row["display_artist"] or "Artista desconocido"
        self.year: int | None = row["year"]
        self.track_count: int = row["track_count"]
        self.art_path: str | None = row["art_path"]

        year_str = str(self.year) if self.year else "—"
        cancion_palabra = "canción" if self.track_count == 1 else "canciones"
        self.meta_label: str = f"{year_str} · {self.track_count} {cancion_palabra}"

    def has_art(self) -> bool:
        return bool(self.art_path and Path(self.art_path).exists())


class AlbumsView(Gtk.Box):
    """Grilla de álbumes armados a mano por el usuario (clic derecho > "Agregar a álbumes" en
    una carpeta o canción): carátula, nombre, artista, año y cantidad de canciones. Un clic
    selecciona el álbum y muestra sus canciones en el panel de abajo (mismo patrón de
    tree/tracks que `ui/folder_view.py`); activarlo (doble clic / Enter) lo pone a reproducir
    completo desde la primera pista, igual que antes. Si un álbum no tiene carátula, la
    tarjeta muestra un botón para buscarla en internet."""

    __gsignals__ = {
        "album-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # album_id
        "album-art-search-requested": (GObject.SignalFlags.RUN_FIRST, None, (int, str, str)),
        # album_id, album name, display_artist
        "album-rescan-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # album_id
        "album-art-upload-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # album_id
        "album-selected": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # album_id
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # track_id
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self._sort_key = "artist"
        self._now_playing_track_id: int | None = None
        self._store = Gio.ListStore(item_type=AlbumObject)
        self._sorter = Gtk.CustomSorter.new(self._compare_albums)
        self._sort_model = Gtk.SortListModel(model=self._store, sorter=self._sorter)
        # autoselect=False: si no, apenas se llena la grilla (cada refresh()) quedaría
        # seleccionado el primer álbum solo, mostrando sus canciones sin que el usuario
        # haya tocado nada — mismo motivo que ya documenta folder_view.py para su árbol.
        self._grid_selection = Gtk.SingleSelection(model=self._sort_model, autoselect=False)
        self._grid_selection.connect("notify::selected-item", self._on_grid_selection_changed)

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
            margin_top=8, margin_bottom=4, margin_start=8, margin_end=8,
        )
        header.append(Gtk.Label(label="Ordenar por:"))
        self._sort_dropdown = Gtk.DropDown.new_from_strings([label for _key, label in _SORT_OPTIONS])
        self._sort_dropdown.connect("notify::selected", self._on_sort_changed)
        header.append(self._sort_dropdown)
        self.append(header)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)

        self._grid_view = Gtk.GridView(model=self._grid_selection, factory=factory, vexpand=True)
        self._grid_view.set_min_columns(2)
        self._grid_view.set_max_columns(10)
        self._grid_view.add_css_class("navigation-sidebar")  # sin fondo de selección de fila
        self._grid_view.connect("activate", self._on_activate)

        grid_scrolled = Gtk.ScrolledWindow(vexpand=True)
        grid_scrolled.set_child(self._grid_view)

        self._tracks_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, vexpand=True, visible=False,
            margin_start=12, margin_top=12, margin_end=12, margin_bottom=12,
        )
        self._tracks_empty_label = Gtk.Label(
            label="Este álbum no tiene canciones.",
            halign=Gtk.Align.START, css_classes=["dim-label"], visible=False,
        )
        self._tracks_box.append(self._tracks_empty_label)

        self._track_store = Gio.ListStore(item_type=TrackObject)
        track_selection = Gtk.NoSelection(model=self._track_store)
        self._track_view = Gtk.ColumnView(model=track_selection)
        self._track_view.append_column(text_column("Pista", "track_label"))
        self._track_view.append_column(text_column("Título", "title", expand=True))
        self._track_view.append_column(text_column("Artista", "artist", expand=True))
        self._track_view.append_column(text_column("Duración", "duration_str"))
        self._track_view.connect("activate", self._on_track_activated)
        tracks_scrolled = Gtk.ScrolledWindow(vexpand=True)
        tracks_scrolled.set_child(self._track_view)
        self._tracks_box.append(tracks_scrolled)

        # El panel de canciones (`_tracks_box`) arranca oculto: al entrar a Álbumes solo se
        # ven las portadas, ocupando toda la pantalla. Un Gtk.Paned con un hijo `visible=False`
        # le da el 100% del espacio al otro hijo y no dibuja el separador — recién al elegir
        # un álbum (`show_tracks`) se lo hace visible y ahí aparece la división horizontal.
        self._paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True, wide_handle=True)
        self._paned.set_start_child(grid_scrolled)
        self._paned.set_resize_start_child(True)
        self._paned.set_shrink_start_child(True)
        self._paned.set_end_child(self._tracks_box)
        self._paned.set_resize_end_child(True)
        self._paned.set_shrink_end_child(True)
        self._paned.set_position(320)
        self.append(self._paned)

    def refresh(self, album_rows) -> None:
        self._store.splice(0, self._store.get_n_items(), [AlbumObject(row) for row in album_rows])
        self._collapse_tracks_panel()

    def _collapse_tracks_panel(self) -> None:
        self._track_store.remove_all()
        self._tracks_box.set_visible(False)

    def show_tracks(self, track_rows) -> None:
        """Llamado por window.py en respuesta a "album-selected", con las canciones de
        ese álbum ya leídas de la base (esta vista no importa `database` directamente,
        mismo estilo que `ui/mood_view.py`)."""
        tracks = [TrackObject(row) for row in track_rows]
        self._track_store.splice(0, self._track_store.get_n_items(), tracks)
        apply_now_playing(self._track_store, self._now_playing_track_id)
        self._track_view.set_visible(bool(tracks))
        self._tracks_empty_label.set_visible(not tracks)
        self._tracks_box.set_visible(True)

    def get_visible_tracks(self) -> list[TrackObject]:
        return [self._track_store.get_item(i) for i in range(self._track_store.get_n_items())]

    def set_now_playing(self, track_id: int | None) -> None:
        self._now_playing_track_id = track_id
        apply_now_playing(self._track_store, track_id)

    def _on_sort_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        self._sort_key = _SORT_OPTIONS[dropdown.get_selected()][0]
        self._sorter.changed(Gtk.SorterChange.DIFFERENT)

    def _compare_albums(self, a: "AlbumObject", b: "AlbumObject", _data=None) -> int:
        if self._sort_key == "title":
            va, vb = a.album.lower(), b.album.lower()
        elif self._sort_key == "year":
            va, vb = (a.year or 0), (b.year or 0)
        else:
            va, vb = a.display_artist.lower(), b.display_artist.lower()
        return -1 if va < vb else (1 if va > vb else 0)

    def _on_setup(self, _factory, list_item: Gtk.ListItem) -> None:
        card = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=_ART_SIZE,
            margin_top=8, margin_bottom=8, margin_start=8, margin_end=8,
        )
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        picture.set_size_request(_ART_SIZE, _ART_SIZE)
        picture.add_css_class("card")
        picture.set_overflow(Gtk.Overflow.HIDDEN)

        art_search_button = Gtk.Button(
            icon_name="edit-find-symbolic",
            tooltip_text="Buscar carátula en internet",
            valign=Gtk.Align.END, halign=Gtk.Align.END,
            margin_bottom=6, margin_end=6,
        )
        art_search_button.add_css_class("circular")
        art_search_button.add_css_class("osd")
        # captura `list_item` (no el álbum) porque GTK recicla este mismo Gtk.ListItem entre
        # tarjetas al hacer scroll — list_item.get_item() da el álbum actual de la tarjeta.
        art_search_button.connect("clicked", lambda _b, li=list_item: self._on_art_search_clicked(li))

        overlay = Gtk.Overlay()
        overlay.set_child(picture)
        overlay.add_overlay(art_search_button)

        title = Gtk.Label(halign=Gtk.Align.START, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("heading")
        artist = Gtk.Label(halign=Gtk.Align.START, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        artist.add_css_class("dim-label")
        meta = Gtk.Label(halign=Gtk.Align.START, xalign=0)
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")

        card.append(overlay)
        card.append(title)
        card.append(artist)
        card.append(meta)
        list_item.set_child(card)
        list_item.purrr_art_button = art_search_button

        context_gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        context_gesture.connect(
            "pressed", lambda _g, _n, x, y, li=list_item, w=card: self._on_album_context_menu(li, w, x, y)
        )
        card.add_controller(context_gesture)

    def _on_bind(self, _factory, list_item: Gtk.ListItem) -> None:
        card = list_item.get_child()
        album: AlbumObject = list_item.get_item()
        overlay, title, artist, meta = (
            card.get_first_child(),
            card.get_first_child().get_next_sibling(),
            card.get_first_child().get_next_sibling().get_next_sibling(),
            card.get_last_child(),
        )
        picture = overlay.get_child()

        texture = load_texture_at_size(album.art_path, _ART_SIZE) if album.has_art() else None
        picture.set_paintable(texture)
        list_item.purrr_art_button.set_visible(not album.has_art())

        title.set_text(album.album)
        artist.set_text(album.display_artist)
        meta.set_text(album.meta_label)

    def _on_art_search_clicked(self, list_item: Gtk.ListItem) -> None:
        album: AlbumObject = list_item.get_item()
        self.emit("album-art-search-requested", album.album_id, album.album, album.display_artist)

    def _on_album_context_menu(self, list_item: Gtk.ListItem, widget: Gtk.Widget, x: float, y: float) -> None:
        album: AlbumObject = list_item.get_item()
        show_context_menu(
            widget, x, y,
            [
                (
                    "Revisar carpeta por canciones nuevas",
                    lambda: self.emit("album-rescan-requested", album.album_id),
                ),
                (
                    "Cargar imagen como carátula",
                    lambda: self.emit("album-art-upload-requested", album.album_id),
                ),
            ],
        )

    def _on_activate(self, _view, position: int) -> None:
        # `position` es un índice del modelo que ve el GridView (el ordenado), no del store crudo.
        album: AlbumObject = self._sort_model.get_item(position)
        self.emit("album-activated", album.album_id)

    def _on_grid_selection_changed(self, selection: Gtk.SingleSelection, _pspec) -> None:
        album: AlbumObject | None = selection.get_selected_item()
        if album is not None:
            self.emit("album-selected", album.album_id)

    def _on_track_activated(self, _view, position: int) -> None:
        track: TrackObject = self._track_store.get_item(position)
        self.emit("track-activated", track.track_id)
