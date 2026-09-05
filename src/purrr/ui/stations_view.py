import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.player.station import Station
from purrr.ui.markup import escape


def _make_station_row(station: Station, emitter: GObject.Object) -> Adw.ActionRow:
    row = Adw.ActionRow(title=escape(station.display_name), subtitle=escape(station.subtitle or ""))
    play_button = Gtk.Button(
        icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Reproducir"
    )
    play_button.connect("clicked", lambda _b, s=station: emitter.emit("station-activated", s))
    row.add_suffix(play_button)
    row.set_activatable_widget(play_button)
    return row


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
        self._rows_by_slug: dict[str, Adw.ActionRow] = {}

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
            "search-changed", lambda entry: self._render_rows(self._filtered(entry.get_text()))
        )
        self._box.append(self._search)
        self._list = Gtk.ListBox(css_classes=["boxed-list"])
        list_scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=320)
        list_scrolled.set_child(self._list)
        self._box.append(list_scrolled)
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
        self._render_rows(self._filtered(self._search.get_text()))

    def _render_rows(self, stations: list[Station]) -> None:
        while row := self._list.get_row_at_index(0):
            self._list.remove(row)
        self._rows_by_slug = {}
        for station in stations:
            row = _make_station_row(station, self)
            if station.slug == self._now_playing_slug:
                row.add_css_class("purrr-now-playing")
            self._rows_by_slug[station.slug] = row
            self._list.append(row)

    def set_now_playing(self, slug: str | None) -> None:
        """Ver SimpleStationsView.set_now_playing — acá además hay que recordar el
        slug aparte, porque el buscador reconstruye las filas (`_render_rows`) y
        perdería el resalte si solo tocáramos las filas ya dibujadas."""
        self._now_playing_slug = slug
        for row_slug, row in self._rows_by_slug.items():
            if row_slug == slug:
                row.add_css_class("purrr-now-playing")
            else:
                row.remove_css_class("purrr-now-playing")
