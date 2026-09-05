import sqlite3
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from purrr.db import database
from purrr.ui.context_menu import show_context_menu
from purrr.ui.playlist_picker import open_playlist_picker
from purrr.ui.textures import load_texture_at_size

_DASHBOARD_ART_SIZE = 140
_AVATAR_SIZE = 64
_RECENT_THUMB_SIZE = 40
_TOP_ARTISTS_LIMIT = 8
_GENRES_LIMIT = 6
_RECENT_LIMIT = 5


def _format_duration(seconds: float | None) -> str:
    if not seconds:
        return "--:--"
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


class TrackObject(GObject.Object):
    """Envoltorio GObject de una fila de `tracks` (o, desde una playlist mixta, de un
    dict ya normalizado por `database.list_playlist_tracks` — mismas claves, mapping
    con `row["clave"]` en ambos casos) para usar en un Gio.ListStore."""

    playing = GObject.Property(type=bool, default=False)

    def __init__(self, row: sqlite3.Row | dict):
        super().__init__()
        self.track_id: int | str = row["id"]
        self.drive_file_id: str | None = row["drive_file_id"]
        self.title: str = row["title"] or (row["file_name"] if "file_name" in row.keys() else "")
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
        # Fase 4 — playlists mixtas: 'drive' (default, biblioteca/carpetas/álbumes,
        # siempre) o 'spotify' (solo posible viniendo de una playlist). Ver
        # ui/playback_bar.py:play_queue_item para el despacho por proveedor.
        self.source: str = row["source"] if "source" in row.keys() else "drive"
        self.spotify_uri: str | None = row["spotify_uri"] if "spotify_uri" in row.keys() else None


def _clear_box(box: Gtk.Widget) -> None:
    child = box.get_first_child()
    while child is not None:
        next_child = child.get_next_sibling()
        box.remove(child)
        child = next_child


def apply_now_playing(store: Gio.ListStore, track_id: int | None) -> None:
    """Marca (con notificación GObject, para que las filas ya dibujadas se repinten solas) cuál
    TrackObject de este store es el que está sonando ahora."""
    for i in range(store.get_n_items()):
        track: TrackObject = store.get_item(i)
        track.playing = track.track_id == track_id


def _sync_playing_style(label: Gtk.Label, track: TrackObject) -> None:
    if track.playing:
        label.add_css_class("purrr-now-playing")
    else:
        label.remove_css_class("purrr-now-playing")


def text_column(
    title: str,
    attr: str,
    expand: bool = False,
    sortable: bool = False,
    sort_attr: str | None = None,
    on_context_menu: Callable[[Gtk.ListItem, Gtk.Widget, float, float], None] | None = None,
) -> Gtk.ColumnViewColumn:
    factory = Gtk.SignalListItemFactory()

    def on_setup(_factory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(halign=Gtk.Align.START, ellipsize=Pango.EllipsizeMode.END)
        list_item.set_child(label)
        if on_context_menu is not None:
            # Se captura `list_item` (no el track) porque GTK recicla este mismo Gtk.ListItem
            # entre filas al hacer scroll — list_item.get_item() siempre da el track ACTUAL
            # de la fila, aun si el clic ocurre mucho después de este setup().
            gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
            gesture.connect(
                "pressed", lambda _g, _n, x, y, li=list_item, lbl=label: on_context_menu(li, lbl, x, y)
            )
            label.add_controller(gesture)

    def on_bind(_factory, list_item: Gtk.ListItem) -> None:
        label = list_item.get_child()
        track: TrackObject = list_item.get_item()
        label.set_text(getattr(track, attr))
        _sync_playing_style(label, track)
        # El item se recicla entre filas al hacer scroll — sin desconectar en on_unbind, cada
        # rebind agregaría OTRA conexión, y una fila terminaría reaccionando a canciones ajenas.
        handler_id = track.connect("notify::playing", lambda t, _p, lbl=label: _sync_playing_style(lbl, t))
        list_item.purrr_playing_binding = (track, handler_id)

    def on_unbind(_factory, list_item: Gtk.ListItem) -> None:
        binding = getattr(list_item, "purrr_playing_binding", None)
        if binding is not None:
            track, handler_id = binding
            track.disconnect(handler_id)
            list_item.purrr_playing_binding = None

    factory.connect("setup", on_setup)
    factory.connect("bind", on_bind)
    factory.connect("unbind", on_unbind)
    column = Gtk.ColumnViewColumn(title=title, factory=factory)
    column.set_expand(expand)
    column.set_resizable(True)

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
        "add-to-album-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # list[int]
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._now_playing_track_id: int | None = None

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
        self._column_view.append_column(
            text_column(
                "Título", "title", expand=True, sortable=True, on_context_menu=self._on_track_context_menu
            )
        )
        self._column_view.append_column(
            text_column(
                "Artista", "artist", expand=True, sortable=True, on_context_menu=self._on_track_context_menu
            )
        )
        self._column_view.append_column(
            text_column(
                "Álbum", "album", expand=True, sortable=True, on_context_menu=self._on_track_context_menu
            )
        )
        self._column_view.append_column(
            text_column(
                "Duración",
                "duration_str",
                sortable=True,
                sort_attr="duration_seconds",
                on_context_menu=self._on_track_context_menu,
            )
        )
        self._column_view.connect("activate", self._on_row_activated)
        self._sort_model.set_sorter(self._column_view.get_sorter())

        # --- Dashboard (hero / top artists / géneros / agregado recientemente) ------
        # Se arma con Python puro sobre los mismos `track_rows` que ya llegan a refresh() —
        # sin consultas SQL nuevas. Solo se muestra cuando no hay una búsqueda activa (con
        # texto en el buscador se prioriza la tabla completa filtrada, sin distraer con
        # secciones que no reflejan el filtro).
        self._dashboard_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=20,
            margin_top=8, margin_bottom=16, margin_start=8, margin_end=8,
        )
        self._hero_slot = Gtk.Box()
        self._dashboard_box.append(self._hero_slot)

        top_artists_label = Gtk.Label(label="Top Artistas", halign=Gtk.Align.START)
        top_artists_label.add_css_class("heading")
        self._top_artists_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        top_artists_scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER,
        )
        top_artists_scrolled.set_child(self._top_artists_box)
        self._top_artists_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._top_artists_section.append(top_artists_label)
        self._top_artists_section.append(top_artists_scrolled)
        self._dashboard_box.append(self._top_artists_section)

        genres_label = Gtk.Label(label="Géneros", halign=Gtk.Align.START)
        genres_label.add_css_class("heading")
        self._genres_flowbox = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, row_spacing=8, column_spacing=8,
            homogeneous=False, max_children_per_line=6,
        )
        self._genres_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._genres_section.append(genres_label)
        self._genres_section.append(self._genres_flowbox)
        self._dashboard_box.append(self._genres_section)

        recent_label = Gtk.Label(label="Agregado recientemente", halign=Gtk.Align.START)
        recent_label.add_css_class("heading")
        self._recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._dashboard_box.append(recent_label)
        self._dashboard_box.append(self._recent_box)

        # El dashboard NO va dentro del mismo ScrolledWindow que el ColumnView: este último
        # necesita ser hijo DIRECTO de su propio Gtk.ScrolledWindow para virtualizar filas (solo
        # renderiza las visibles) — meterlo dentro de un Box intermedio le haría perder eso y
        # renderizar la biblioteca completa de una, el mismo problema de rendimiento que ya se
        # evitó en refresh() con splice(). El dashboard, en cambio, es contenido acotado (unas
        # pocas decenas de widgets como mucho) y no necesita su propio scroll.
        self.append(self._dashboard_box)

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
        apply_now_playing(self._store, self._now_playing_track_id)

        search_active = bool(self._search_entry.get_text().strip())
        self._dashboard_box.set_visible(not search_active)
        if not search_active:
            self._update_dashboard(track_rows)

    # --- Dashboard (estilo "hero + top artistas + géneros + charts") -----------

    def _update_dashboard(self, track_rows: list[sqlite3.Row]) -> None:
        _clear_box(self._hero_slot)
        _clear_box(self._top_artists_box)
        _clear_box(self._genres_flowbox)
        _clear_box(self._recent_box)

        if not track_rows:
            self._top_artists_section.set_visible(False)
            self._genres_section.set_visible(False)
            return

        by_recent = sorted(track_rows, key=lambda r: r["added_at"] or "", reverse=True)

        self._hero_slot.append(self._build_hero(by_recent[0]))

        artist_counts = Counter(r["artist"] for r in track_rows if r["artist"])
        self._top_artists_section.set_visible(bool(artist_counts))
        for artist, count in artist_counts.most_common(_TOP_ARTISTS_LIMIT):
            art_row = next((r for r in track_rows if r["artist"] == artist and r["art_path"]), None)
            self._top_artists_box.append(self._build_artist_tile(artist, count, art_row))

        genre_counts = Counter(r["genre"] for r in track_rows if r["genre"])
        self._genres_section.set_visible(bool(genre_counts))
        for i, (genre, count) in enumerate(genre_counts.most_common(_GENRES_LIMIT)):
            self._genres_flowbox.insert(self._build_genre_chip(genre, count, i), -1)

        for i, row in enumerate(by_recent[:_RECENT_LIMIT]):
            self._recent_box.append(self._build_recent_row(i + 1, row))

    def _build_hero(self, row: sqlite3.Row) -> Gtk.Widget:
        hero = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        hero.add_css_class("purrr-hero")

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER, hexpand=True)
        eyebrow = Gtk.Label(label="Agregado hace poco", halign=Gtk.Align.START)
        eyebrow.add_css_class("caption")
        eyebrow.add_css_class("dim-label")
        title = Gtk.Label(label=row["title"] or row["file_name"], halign=Gtk.Align.START, xalign=0)
        title.add_css_class("title-1")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        subtitle_text = row["artist"] or "Artista desconocido"
        if row["album"]:
            subtitle_text += f" · {row['album']}"
        subtitle = Gtk.Label(label=subtitle_text, halign=Gtk.Align.START, xalign=0)
        subtitle.add_css_class("dim-label")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)

        play_button = Gtk.Button(label="▶  Reproducir", halign=Gtk.Align.START, margin_top=8)
        play_button.add_css_class("pill")
        play_button.add_css_class("purrr-accent-button")
        track_id = row["id"]
        play_button.connect("clicked", lambda _b: self.emit("track-activated", track_id))

        text_box.append(eyebrow)
        text_box.append(title)
        text_box.append(subtitle)
        text_box.append(play_button)
        hero.append(text_box)

        art_path = row["art_path"]
        texture = load_texture_at_size(art_path, _DASHBOARD_ART_SIZE) if art_path and Path(art_path).exists() else None
        if texture:
            picture = Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.COVER, can_shrink=True)
            picture.set_size_request(_DASHBOARD_ART_SIZE, _DASHBOARD_ART_SIZE)
            picture.add_css_class("purrr-art-rounded")
            picture.set_overflow(Gtk.Overflow.HIDDEN)
            hero.append(picture)

        return hero

    def _build_artist_tile(self, artist: str, count: int, art_row: sqlite3.Row | None) -> Gtk.Widget:
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=_AVATAR_SIZE + 16)

        art_path = art_row["art_path"] if art_row else None
        texture = load_texture_at_size(art_path, _AVATAR_SIZE) if art_path and Path(art_path).exists() else None
        if texture:
            avatar = Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.COVER, can_shrink=True)
            avatar.set_size_request(_AVATAR_SIZE, _AVATAR_SIZE)
            avatar.add_css_class("purrr-avatar-circle")
            avatar.set_overflow(Gtk.Overflow.HIDDEN)
        else:
            avatar = Gtk.Label(label=(artist[:1] or "?").upper())
            avatar.add_css_class("purrr-avatar-fallback")
            avatar.set_size_request(_AVATAR_SIZE, _AVATAR_SIZE)

        cancion_palabra = "canción" if count == 1 else "canciones"
        name = Gtk.Label(label=artist, halign=Gtk.Align.CENTER, justify=Gtk.Justification.CENTER)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(12)
        meta = Gtk.Label(label=f"{count} {cancion_palabra}", halign=Gtk.Align.CENTER)
        meta.add_css_class("caption")
        meta.add_css_class("dim-label")

        button = Gtk.Button(has_frame=False, valign=Gtk.Align.START)
        button.add_css_class("flat")
        button.set_child(avatar)
        button.connect("clicked", lambda _b, a=artist: self._search_entry.set_text(a))

        tile.append(button)
        tile.append(name)
        tile.append(meta)
        return tile

    def _build_genre_chip(self, genre: str, count: int, index: int) -> Gtk.Widget:
        chip = Gtk.Button(label=f"{genre} · {count}")
        chip.add_css_class("purrr-chip")
        chip.add_css_class(f"purrr-chip-{(index % 6) + 1}")
        chip.connect("clicked", lambda _b, g=genre: self._search_entry.set_text(g))
        return chip

    def _build_recent_row(self, rank: int, row: sqlite3.Row) -> Gtk.Widget:
        art_path = row["art_path"]
        texture = load_texture_at_size(art_path, _RECENT_THUMB_SIZE) if art_path and Path(art_path).exists() else None
        if texture:
            thumb = Gtk.Picture(paintable=texture, content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        else:
            thumb = Gtk.Image(icon_name="audio-x-generic-symbolic")
        thumb.set_size_request(_RECENT_THUMB_SIZE, _RECENT_THUMB_SIZE)
        thumb.add_css_class("purrr-art-rounded")
        thumb.set_overflow(Gtk.Overflow.HIDDEN)

        rank_label = Gtk.Label(label=str(rank))
        rank_label.add_css_class("purrr-rank-badge")
        rank_label.set_size_request(22, 22)

        title = Gtk.Label(
            label=row["title"] or row["file_name"], halign=Gtk.Align.START, xalign=0, hexpand=True,
        )
        title.set_ellipsize(Pango.EllipsizeMode.END)
        artist = Gtk.Label(label=row["artist"] or "", halign=Gtk.Align.START, xalign=0, hexpand=True)
        artist.add_css_class("dim-label")
        artist.add_css_class("caption")
        artist.set_ellipsize(Pango.EllipsizeMode.END)
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        text_box.append(title)
        text_box.append(artist)

        duration = Gtk.Label(label=_format_duration(row["duration_seconds"]))
        duration.add_css_class("dim-label")

        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=4, margin_bottom=4,
                           margin_start=6, margin_end=6)
        row_box.append(rank_label)
        row_box.append(thumb)
        row_box.append(text_box)
        row_box.append(duration)
        row_box.add_css_class("purrr-dashboard-row")

        button = Gtk.Button(has_frame=False)
        button.add_css_class("flat")
        button.set_child(row_box)
        track_id = row["id"]
        button.connect("clicked", lambda _b: self.emit("track-activated", track_id))
        return button

    def get_visible_tracks(self) -> list[TrackObject]:
        """Tracks tal como se ven actualmente (respetando el orden/columna elegidos por el usuario)."""
        return [self._selection.get_item(i) for i in range(self._selection.get_n_items())]

    def set_now_playing(self, track_id: int | None) -> None:
        self._now_playing_track_id = track_id
        apply_now_playing(self._store, track_id)

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

    def _on_track_context_menu(self, list_item: Gtk.ListItem, widget: Gtk.Widget, x: float, y: float) -> None:
        track: TrackObject = list_item.get_item()
        position = list_item.get_position()
        bitset = self._selection.get_selection()
        # Si el clic derecho cae sobre una fila que ya formaba parte de una selección múltiple,
        # la acción aplica a toda la selección; si no, solo a esa fila.
        if bitset.get_size() > 1 and bitset.contains(position):
            track_ids = self.get_selected_track_ids()
        else:
            track_ids = [track.track_id]

        show_context_menu(
            widget,
            x,
            y,
            [
                ("Agregar a álbumes", lambda: self.emit("add-to-album-requested", track_ids)),
                ("Agregar a playlist…", lambda: self._add_to_playlist(track_ids)),
            ],
        )

    def _add_to_playlist(self, track_ids: list[int]) -> None:
        def on_chosen(playlist_id: int) -> None:
            for track_id in track_ids:
                database.add_track_to_playlist(playlist_id, track_id)

        open_playlist_picker(self.get_root(), on_chosen)
