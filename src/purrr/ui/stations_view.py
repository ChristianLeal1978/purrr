import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.player.sources import list_all_stations
from purrr.player.station import Station
from purrr.ui.markup import escape

_GROUPS = [
    ("rainwave", "Rainwave"),
    ("biobio", "Radio Bío-Bío"),
    ("smoothjazz", "SmoothJazz.com"),
]


class StationsView(Gtk.Box):
    """Pantalla 'Radios'. Rainwave/Bío-Bío/SmoothJazz son un catálogo fijo (se
    listan solas, sin refresh — igual que antes). RadioTunes es aparte: necesita
    una Listen Key configurada y su catálogo (~99 canales) se pide a `ui/window.py`
    en un hilo — ver `set_radiotunes_configured`/`show_radiotunes_channels`."""

    __gsignals__ = {
        "station-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # Station
        "radiotunes-key-save-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        # `self` queda con un único hijo (el ScrolledWindow) para que esta pantalla no
        # fuerce una altura mayor a la disponible: entre Rainwave/Bío-Bío/SmoothJazz y
        # el catálogo de RadioTunes (~99 canales) el contenido sin acotar superaba
        # fácil los 1000px, más que muchas pantallas físicas.
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._radiotunes_all_stations: list[Station] = []

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        self._content = content

        stations = list_all_stations()
        for provider, group_title in _GROUPS:
            group_stations = [s for s in stations if s.provider == provider]
            if not group_stations:
                continue
            content.append(Gtk.Label(label=group_title, halign=Gtk.Align.START, css_classes=["title-2"]))
            list_box = Gtk.ListBox(css_classes=["boxed-list"])
            for station in group_stations:
                list_box.append(self._make_row(station))
            content.append(list_box)

        self._build_radiotunes_section(content)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(content)
        self.append(scrolled)

    def _make_row(self, station: Station) -> Adw.ActionRow:
        row = Adw.ActionRow(title=escape(station.display_name), subtitle=escape(station.subtitle or ""))
        play_button = Gtk.Button(
            icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Reproducir"
        )
        play_button.connect("clicked", lambda _b, s=station: self.emit("station-activated", s))
        row.add_suffix(play_button)
        row.set_activatable_widget(play_button)
        return row

    # --- RadioTunes: Listen Key + catálogo dinámico + buscador ----------------

    def _build_radiotunes_section(self, content: Gtk.Box) -> None:
        content.append(Gtk.Label(label="RadioTunes", halign=Gtk.Align.START, css_classes=["title-2"]))

        self._radiotunes_key_page = Adw.StatusPage(
            icon_name="network-wireless-signal-excellent-symbolic",
            title="Conecta tu cuenta de RadioTunes",
            description="Con una cuenta Premium, obtén tu Listen Key desde "
            "radiotunes.com → Player Settings → Hardware Player, y pégalo aquí. "
            "Sin él no hay audio — el catálogo de canales se ve igual, pero "
            "ninguno suena.",
        )
        key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        key_box.set_size_request(360, -1)
        self._radiotunes_key_entry = Gtk.Entry(placeholder_text="Listen Key", visibility=False)
        save_button = Gtk.Button(
            label="Guardar", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"]
        )
        save_button.connect("clicked", self._on_save_radiotunes_key_clicked)
        key_box.append(self._radiotunes_key_entry)
        key_box.append(save_button)
        self._radiotunes_key_page.set_child(key_box)
        content.append(self._radiotunes_key_page)

        self._radiotunes_loading_label = Gtk.Label(
            label="Cargando canales…", halign=Gtk.Align.START, visible=False, css_classes=["dim-label"]
        )
        content.append(self._radiotunes_loading_label)

        self._radiotunes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, visible=False)
        self._radiotunes_search = Gtk.SearchEntry(placeholder_text="Buscar canal (~99 disponibles)")
        self._radiotunes_search.connect(
            "search-changed", lambda entry: self._render_radiotunes_rows(self._filtered(entry.get_text()))
        )
        self._radiotunes_box.append(self._radiotunes_search)
        self._radiotunes_list = Gtk.ListBox(css_classes=["boxed-list"])
        scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=320)
        scrolled.set_child(self._radiotunes_list)
        self._radiotunes_box.append(scrolled)
        content.append(self._radiotunes_box)

        self.set_radiotunes_configured(False)

    def _on_save_radiotunes_key_clicked(self, _button) -> None:
        key = self._radiotunes_key_entry.get_text().strip()
        if key:
            self.emit("radiotunes-key-save-requested", key)

    def _filtered(self, query: str) -> list[Station]:
        query = query.strip().lower()
        if not query:
            return self._radiotunes_all_stations
        return [s for s in self._radiotunes_all_stations if query in s.display_name.lower()]

    def set_radiotunes_configured(self, configured: bool) -> None:
        self._radiotunes_key_page.set_visible(not configured)
        self._radiotunes_box.set_visible(configured)

    def show_radiotunes_loading(self) -> None:
        self._radiotunes_loading_label.set_visible(True)
        self._radiotunes_box.set_visible(False)

    def show_radiotunes_channels(self, stations: list[Station]) -> None:
        self._radiotunes_loading_label.set_visible(False)
        self._radiotunes_box.set_visible(True)
        self._radiotunes_all_stations = stations
        self._render_radiotunes_rows(self._filtered(self._radiotunes_search.get_text()))

    def _render_radiotunes_rows(self, stations: list[Station]) -> None:
        while row := self._radiotunes_list.get_row_at_index(0):
            self._radiotunes_list.remove(row)
        for station in stations:
            self._radiotunes_list.append(self._make_row(station))
