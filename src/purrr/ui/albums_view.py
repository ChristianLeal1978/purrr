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
        self.kind: str = row["kind"]  # "album" (armado a mano) o "group" (combinado, ver "Combinar")
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
        "album-activated": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),  # kind, id
        "album-art-search-requested": (GObject.SignalFlags.RUN_FIRST, None, (int, str, str)),
        # album_id, album name, display_artist (solo álbumes sueltos, no combinados)
        "album-rescan-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # album_id
        "album-art-upload-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),  # kind, id
        "album-delete-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, int, str)),  # kind, id, nombre
        "album-selected": (GObject.SignalFlags.RUN_FIRST, None, (str, int)),  # kind, id
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # track_id
        "albums-combine-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # list[int] album_ids
        "album-group-split-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),  # group_id
    }

    def __init__(self, tracks_panel_position: int = 560):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self._tracks_panel_position = tracks_panel_position
        self._sort_key = "artist"
        self._now_playing_track_id: int | None = None
        self._selected_key: tuple[str, int] | None = None
        # True cuando el usuario cerró el panel a mano con el botón de abajo mientras un
        # álbum seguía seleccionado — refresh() (llamado tras cada scan/sync) lo respeta
        # en vez de reabrirlo solo; ver refresh() y _on_grid_selection_changed().
        self._tracks_manually_hidden = False
        self._store = Gio.ListStore(item_type=AlbumObject)
        self._sorter = Gtk.CustomSorter.new(self._compare_albums)
        self._sort_model = Gtk.SortListModel(model=self._store, sorter=self._sorter)
        # MultiSelection (no SingleSelection): habilita Ctrl/Shift+clic gratis para elegir
        # varias tarjetas y combinarlas (mismo cambio que ya usan library_view.py/
        # playlist_view.py). El panel de canciones de abajo solo se actualiza cuando la
        # selección tiene exactamente una tarjeta — ver _on_grid_selection_changed.
        self._grid_selection = Gtk.MultiSelection(model=self._sort_model)
        self._grid_selection.connect("selection-changed", self._on_grid_selection_changed)

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
            margin_top=8, margin_bottom=4, margin_start=8, margin_end=8,
        )
        header.append(Gtk.Label(label="Ordenar por:"))
        self._sort_dropdown = Gtk.DropDown.new_from_strings([label for _key, label in _SORT_OPTIONS])
        self._sort_dropdown.connect("notify::selected", self._on_sort_changed)
        header.append(self._sort_dropdown)

        spacer = Gtk.Box(hexpand=True)
        header.append(spacer)

        self._tracks_toggle_button = Gtk.Button(icon_name="pan-down-symbolic", sensitive=False)
        self._tracks_toggle_button.add_css_class("flat")
        self._tracks_toggle_button.set_tooltip_text("Mostrar la lista de canciones")
        self._tracks_toggle_button.connect("clicked", self._on_tracks_toggle_clicked)
        header.append(self._tracks_toggle_button)

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
        self._paned.set_position(self._tracks_panel_position)
        self.append(self._paned)

    def get_tracks_panel_position(self) -> int:
        """Alto actual del divisor grilla/canciones, para que window.py lo persista
        (esta vista no importa `database` directamente, ver arriba)."""
        return self._paned.get_position()

    def refresh(self, album_rows) -> None:
        # Cada scan/sync en background llama a refresh() para traer datos frescos de la
        # base — antes esto colapsaba el panel de canciones incondicionalmente, cerrando
        # de golpe el álbum que el usuario tenía abierto. Ahora se reintenta reseleccionar
        # el mismo álbum (si sigue existiendo) para que el panel quede como estaba.
        # Se compara por (kind, id): un album_id y un group_id pueden coincidir en
        # número siendo autoincrementales de tablas distintas.
        previous_key = self._selected_key
        self._store.splice(0, self._store.get_n_items(), [AlbumObject(row) for row in album_rows])
        if previous_key is not None:
            for i in range(self._sort_model.get_n_items()):
                album = self._sort_model.get_item(i)
                if (album.kind, album.album_id) == previous_key:
                    self._grid_selection.select_item(i, True)
                    return
        self._grid_selection.unselect_all()
        self._selected_key = None
        self._tracks_manually_hidden = False
        self._collapse_tracks_panel()

    def _collapse_tracks_panel(self) -> None:
        self._track_store.remove_all()
        self._tracks_toggle_button.set_sensitive(False)
        self._set_tracks_visible(False)

    def _set_tracks_visible(self, visible: bool) -> None:
        self._tracks_box.set_visible(visible)
        self._tracks_toggle_button.set_icon_name("pan-up-symbolic" if visible else "pan-down-symbolic")
        self._tracks_toggle_button.set_tooltip_text(
            "Ocultar la lista de canciones" if visible else "Mostrar la lista de canciones"
        )

    def _on_tracks_toggle_clicked(self, _button: Gtk.Button) -> None:
        if self._selected_key is None:
            return
        visible = not self._tracks_box.get_visible()
        self._tracks_manually_hidden = not visible
        self._set_tracks_visible(visible)

    def show_tracks(self, track_rows) -> None:
        """Llamado por window.py en respuesta a "album-selected", con las canciones de
        ese álbum ya leídas de la base (esta vista no importa `database` directamente,
        mismo estilo que `ui/mood_view.py`)."""
        tracks = [TrackObject(row) for row in track_rows]
        self._track_store.splice(0, self._track_store.get_n_items(), tracks)
        apply_now_playing(self._track_store, self._now_playing_track_id)
        self._track_view.set_visible(bool(tracks))
        self._tracks_empty_label.set_visible(not tracks)
        self._tracks_toggle_button.set_sensitive(True)
        if not self._tracks_manually_hidden:
            self._set_tracks_visible(True)

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
        # halign/valign CENTER (en vez del FILL por defecto): sin esto, el Gtk.Box vertical
        # de la tarjeta estira la Picture al ancho completo de la columna del GridView
        # (que suele ser más ancha que _ART_SIZE), deformando la carátula a un rectángulo.
        picture.set_halign(Gtk.Align.CENTER)
        picture.set_valign(Gtk.Align.CENTER)
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

        overlay = Gtk.Overlay(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        overlay.set_child(picture)
        overlay.add_overlay(art_search_button)

        title = Gtk.Label(halign=Gtk.Align.CENTER, xalign=0.5, justify=Gtk.Justification.CENTER, ellipsize=Pango.EllipsizeMode.END)
        title.add_css_class("heading")
        artist = Gtk.Label(halign=Gtk.Align.CENTER, xalign=0.5, justify=Gtk.Justification.CENTER, ellipsize=Pango.EllipsizeMode.END)
        artist.add_css_class("dim-label")
        meta = Gtk.Label(halign=Gtk.Align.CENTER, xalign=0.5, justify=Gtk.Justification.CENTER)
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

        texture = (
            load_texture_at_size(album.art_path, _ART_SIZE, picture.get_scale_factor())
            if album.has_art() else None
        )
        picture.set_paintable(texture)
        # Buscar carátula en internet es una acción por álbum de verdad (guarda el
        # archivo con el album_id crudo como nombre) — se oculta en una tarjeta
        # combinada para no pisar por accidente la carátula de un álbum miembro.
        list_item.purrr_art_button.set_visible(not album.has_art() and album.kind == "album")
        if album.kind == "group":
            picture.add_css_class("purrr-album-art-combined")
        else:
            picture.remove_css_class("purrr-album-art-combined")

        title.set_text(album.album)
        artist.set_text(album.display_artist)
        meta.set_text(album.meta_label)

    def _on_art_search_clicked(self, list_item: Gtk.ListItem) -> None:
        album: AlbumObject = list_item.get_item()
        self.emit("album-art-search-requested", album.album_id, album.album, album.display_artist)

    def _on_album_context_menu(self, list_item: Gtk.ListItem, widget: Gtk.Widget, x: float, y: float) -> None:
        album: AlbumObject = list_item.get_item()
        position = list_item.get_position()
        bitset = self._grid_selection.get_selection()
        # Si el clic derecho cae en una tarjeta que ya forma parte de una selección
        # múltiple, la acción aplica a toda la selección; si no, solo a esa tarjeta
        # (mismo patrón que library_view.py:_on_track_context_menu).
        if bitset.get_size() > 1 and bitset.contains(position):
            selected = self.get_selected_albums()
        else:
            selected = [album]

        if len(selected) == 1:
            show_context_menu(widget, x, y, self._single_album_menu_items(selected[0]))
            return

        if all(a.kind == "album" for a in selected):
            # En orden de grilla (ya ordenada por artista/título/año): así "CD1" queda
            # antes que "CD2" sin lógica extra de disco.
            album_ids = [a.album_id for a in selected]
            show_context_menu(
                widget, x, y,
                [("Combinar", lambda: self.emit("albums-combine-requested", album_ids))],
            )
        # Selección mixta (incluye una tarjeta ya combinada) o 2+ grupos: sin acción
        # propia todavía — separar el/los grupo/s primero.

    def _single_album_menu_items(self, album: "AlbumObject") -> list[tuple[str, object]]:
        if album.kind == "group":
            return [
                ("Cargar imagen como carátula", lambda: self.emit("album-art-upload-requested", "group", album.album_id)),
                ("Separar", lambda: self.emit("album-group-split-requested", album.album_id)),
                ("Eliminar de la biblioteca", lambda: self.emit("album-delete-requested", "group", album.album_id, album.album)),
            ]
        return [
            ("Revisar carpeta por canciones nuevas", lambda: self.emit("album-rescan-requested", album.album_id)),
            ("Cargar imagen como carátula", lambda: self.emit("album-art-upload-requested", "album", album.album_id)),
            ("Eliminar de la biblioteca", lambda: self.emit("album-delete-requested", "album", album.album_id, album.album)),
        ]

    def _on_activate(self, _view, position: int) -> None:
        # `position` es un índice del modelo que ve el GridView (el ordenado), no del store crudo.
        album: AlbumObject = self._sort_model.get_item(position)
        self.emit("album-activated", album.kind, album.album_id)

    def get_selected_albums(self) -> list["AlbumObject"]:
        bitset = self._grid_selection.get_selection()
        return [
            self._sort_model.get_item(i)
            for i in range(self._sort_model.get_n_items())
            if bitset.contains(i)
        ]

    def _on_grid_selection_changed(self, _selection: Gtk.MultiSelection, _position: int, _n_items: int) -> None:
        selected = self.get_selected_albums()
        # El panel de canciones de abajo solo tiene sentido con una tarjeta elegida —
        # con 0 (deselección) o 2+ (el usuario está armando una combinación) se colapsa,
        # mismo criterio que ya usaba el estado "sin selección" de antes.
        if len(selected) != 1:
            self._selected_key = None
            self._tracks_manually_hidden = False
            self._collapse_tracks_panel()
            return
        album = selected[0]
        key = (album.kind, album.album_id)
        # Elegir un álbum nuevo siempre reabre el panel aunque el usuario lo haya cerrado a
        # mano antes; una reselección del MISMO álbum (la que hace refresh() tras un scan)
        # no toca ese estado — ver el comentario en refresh().
        if key != self._selected_key:
            self._tracks_manually_hidden = False
        self._selected_key = key
        self.emit("album-selected", album.kind, album.album_id)

    def _on_track_activated(self, _view, position: int) -> None:
        track: TrackObject = self._track_store.get_item(position)
        self.emit("track-activated", track.track_id)
