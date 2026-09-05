import threading
import urllib.parse
import urllib.request
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, GLib, GObject, Gtk, Pango

from purrr.cache import manager as cache_manager
from purrr.player.station import Station
from purrr.ui.markup import escape
from purrr.ui.textures import load_texture_at_size

_TILE_SIZE = 130
_USER_AGENT = "Purrr/0.1 (+https://github.com/christianlealreyes/purrr)"


def _make_station_row(station: Station, emitter: GObject.Object) -> Adw.ActionRow:
    row = Adw.ActionRow(title=escape(station.display_name), subtitle=escape(station.subtitle or ""))
    play_button = Gtk.Button(
        icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Reproducir"
    )
    play_button.connect("clicked", lambda _b, s=station: emitter.emit("station-activated", s))
    row.add_suffix(play_button)
    row.set_activatable_widget(play_button)
    return row


class _StationTile(Gtk.Button):
    """Cuadrado con la carátula de un canal de RadioTunes (por ahora el único
    proveedor que trae `station.art_url`, ver player/sources/radiotunes.py) —
    clickeable entero, con borde de acento y un ícono de play superpuesto
    mientras es el canal sonando (ver `set_playing`). Sin carátula (todavía
    cargando, o si nunca llega), cae a un ícono genérico — nunca deja el
    cuadro vacío."""

    def __init__(self, station: Station, emitter: GObject.Object):
        super().__init__(has_frame=False, css_classes=["flat"], tooltip_text=station.display_name)
        self.slug = station.slug
        self.connect("clicked", lambda _b, s=station: emitter.emit("station-activated", s))

        self._art = Gtk.Overlay(css_classes=["purrr-station-tile-art"])
        self._art.set_overflow(Gtk.Overflow.HIDDEN)
        self._art.set_size_request(_TILE_SIZE, _TILE_SIZE)

        self._picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        self._art.set_child(self._picture)

        self._fallback_icon = Gtk.Image(
            icon_name="radio-symbolic", pixel_size=40, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER
        )
        self._art.add_overlay(self._fallback_icon)

        self._scrim = Gtk.Box(css_classes=["purrr-station-tile-scrim"], visible=False)
        self._scrim.append(
            Gtk.Image(icon_name="media-playback-start-symbolic", pixel_size=36,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        )
        self._art.add_overlay(self._scrim)

        label = Gtk.Label(
            label=escape(station.display_name), wrap=True, justify=Gtk.Justification.CENTER,
            lines=2, ellipsize=Pango.EllipsizeMode.END, max_width_chars=14,
            halign=Gtk.Align.CENTER, use_markup=True,
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._art)
        box.append(label)
        self.set_child(box)

    def set_art_texture(self, texture) -> None:
        self._picture.set_paintable(texture)
        self._fallback_icon.set_visible(texture is None)

    def set_playing(self, playing: bool) -> None:
        if playing:
            self._art.add_css_class("purrr-station-tile-playing")
        else:
            self._art.remove_css_class("purrr-station-tile-playing")
        self._scrim.set_visible(playing)


def _load_tile_art(tile: _StationTile, station: Station, on_ready) -> None:
    """Carga la carátula del canal en el cuadro: si ya está cacheada en disco de una
    sesión anterior la aplica al toque (sin red); si no, la baja en un hilo aparte y
    recién ahí llama a `on_ready` (agendado con GLib.idle_add — thread-safe para
    tocar widgets)."""
    if not station.art_url:
        return
    ext = Path(urllib.parse.urlparse(station.art_url).path).suffix or ".jpg"
    cache_path = cache_manager.art_cache_path(f"radiotunes-{station.slug}", ext)
    if cache_path.exists():
        texture = load_texture_at_size(str(cache_path), _TILE_SIZE)
        if texture:
            tile.set_art_texture(texture)
        return

    def worker() -> None:
        try:
            request = urllib.request.Request(station.art_url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(request, timeout=10) as response:
                data = response.read()
        except Exception:  # noqa: BLE001 — sin carátula, se queda con el ícono genérico
            return
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
        texture = load_texture_at_size(str(cache_path), _TILE_SIZE)
        if texture:
            GLib.idle_add(on_ready, texture)

    threading.Thread(target=worker, daemon=True).start()


class SimpleStationsView(Gtk.Box):
    """Catálogo fijo de un solo proveedor de radio (Rainwave, Radio Bío-Bío o
    SmoothJazz.com) — cada uno es su propia entrada del menú lateral (ver
    ui/sidebar.py y ui/window.py), a diferencia de RadioTunesView que necesita
    Listen Key y buscador por su catálogo mucho más grande."""

    __gsignals__ = {
        "station-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # Station
    }

    def __init__(self, title: str, stations: list[Station]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._rows_by_slug: dict[str, Adw.ActionRow] = {}

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.append(Gtk.Label(label=title, halign=Gtk.Align.START, css_classes=["title-2"]))
        list_box = Gtk.ListBox(css_classes=["boxed-list"])
        for station in stations:
            row = _make_station_row(station, self)
            self._rows_by_slug[station.slug] = row
            list_box.append(row)
        content.append(list_box)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(content)
        self.append(scrolled)

    def set_now_playing(self, slug: str | None) -> None:
        """Resalta (con la misma clase `purrr-now-playing` que biblioteca/carpetas/
        playlists) la fila de la estación que está sonando; None apaga el resalte."""
        for row_slug, row in self._rows_by_slug.items():
            if row_slug == slug:
                row.add_css_class("purrr-now-playing")
            else:
                row.remove_css_class("purrr-now-playing")


class RadioTunesView(Gtk.Box):
    """Pantalla 'RadioTunes': necesita una Listen Key configurada y su catálogo
    (~99 canales) se pide a `ui/window.py` en un hilo — ver
    `set_configured`/`show_channels`."""

    __gsignals__ = {
        "station-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # Station
        "radiotunes-key-save-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        # `self` queda con un único hijo (el ScrolledWindow) para que esta pantalla no
        # fuerce una altura mayor a la disponible — el catálogo (~99 canales) sin
        # acotar superaba fácil los 1000px, más que muchas pantallas físicas.
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._all_stations: list[Station] = []
        self._now_playing_slug: str | None = None
        self._tiles_by_slug: dict[str, _StationTile] = {}

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        self._key_page = Adw.StatusPage(
            icon_name="radio-symbolic",
            title="Conecta tu cuenta de RadioTunes",
            description="Con una cuenta Premium, obtén tu Listen Key desde "
            "radiotunes.com → Player Settings → Hardware Player, y pégalo aquí. "
            "Sin él no hay audio — el catálogo de canales se ve igual, pero "
            "ninguno suena.",
        )
        key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        key_box.set_size_request(360, -1)
        self._key_entry = Gtk.Entry(placeholder_text="Listen Key", visibility=False)
        save_button = Gtk.Button(
            label="Guardar", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"]
        )
        save_button.connect("clicked", self._on_save_key_clicked)
        key_box.append(self._key_entry)
        key_box.append(save_button)
        self._key_page.set_child(key_box)
        content.append(self._key_page)

        self._loading_label = Gtk.Label(
            label="Cargando canales…", halign=Gtk.Align.START, visible=False, css_classes=["dim-label"]
        )
        content.append(self._loading_label)

        self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
        self._search = Gtk.SearchEntry(placeholder_text="Buscar canal (~99 disponibles)")
        self._search.connect(
            "search-changed", lambda entry: self._render_tiles(self._filtered(entry.get_text()))
        )
        self._box.append(self._search)
        # Cuadrícula (no lista): cada canal es un cuadrado con su carátula — ver
        # _StationTile más arriba.
        self._grid = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            column_spacing=16,
            row_spacing=16,
            min_children_per_line=2,
            max_children_per_line=8,
        )
        grid_scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=320)
        grid_scrolled.set_child(self._grid)
        self._box.append(grid_scrolled)
        content.append(self._box)

        self.set_configured(False)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(content)
        self.append(scrolled)

    def _on_save_key_clicked(self, _button) -> None:
        key = self._key_entry.get_text().strip()
        if key:
            self.emit("radiotunes-key-save-requested", key)

    def _filtered(self, query: str) -> list[Station]:
        query = query.strip().lower()
        if not query:
            return self._all_stations
        return [s for s in self._all_stations if query in s.display_name.lower()]

    def set_configured(self, configured: bool) -> None:
        self._key_page.set_visible(not configured)
        self._box.set_visible(configured)

    def show_loading(self) -> None:
        self._loading_label.set_visible(True)
        self._box.set_visible(False)

    def show_channels(self, stations: list[Station]) -> None:
        self._loading_label.set_visible(False)
        self._box.set_visible(True)
        self._all_stations = stations
        self._render_tiles(self._filtered(self._search.get_text()))

    def _render_tiles(self, stations: list[Station]) -> None:
        child = self._grid.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._grid.remove(child)
            child = next_child
        self._tiles_by_slug = {}
        for station in stations:
            tile = _StationTile(station, self)
            if station.slug == self._now_playing_slug:
                tile.set_playing(True)
            self._tiles_by_slug[station.slug] = tile
            self._grid.append(tile)
            _load_tile_art(tile, station, tile.set_art_texture)

    def set_now_playing(self, slug: str | None) -> None:
        """Ver SimpleStationsView.set_now_playing — acá además hay que recordar el
        slug aparte, porque el buscador reconstruye los cuadros (`_render_tiles`) y
        perdería el resalte si solo tocáramos los que están dibujados ahora."""
        self._now_playing_slug = slug
        for tile_slug, tile in self._tiles_by_slug.items():
            tile.set_playing(tile_slug == slug)
