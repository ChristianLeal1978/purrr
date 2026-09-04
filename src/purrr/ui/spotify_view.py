import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.spotify.track import SpotifyTrack
from purrr.ui.markup import escape

_MAX_LOG_LINES = 20


class SpotifyView(Gtk.Box):
    """Pantalla 'Spotify': conectar la cuenta (PKCE, sin contraseña que pasar por acá)
    y buscar canciones para reproducir por Spotify Connect o agregar a una playlist
    mixta. Mismo estilo que `ui/first_run.py`/`ui/cloud_settings.py`."""

    __gsignals__ = {
        "client-id-save-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "connect-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "search-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "play-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # SpotifyTrack
        "add-to-playlist-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # SpotifyTrack
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        self._build_client_id_step()
        self._build_connect_step()
        self._build_search_step()
        self._build_devices_section()

        self.set_client_configured(False)
        self.set_authenticated(False)

    # --- Paso 1: Client ID de la app de Spotify del usuario -------------------

    def _build_client_id_step(self) -> None:
        self._client_id_page = Adw.StatusPage(
            icon_name="audio-headphones-symbolic",
            title="Conecta tu app de Spotify",
            description="Crea una app gratis en developer.spotify.com/dashboard, "
            "agrega el Redirect URI 'http://127.0.0.1:8888/callback' y pega aquí el "
            "Client ID (no hace falta client secret).",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        box.set_size_request(360, -1)
        self._client_id_entry = Gtk.Entry(placeholder_text="Client ID")
        save_button = Gtk.Button(
            label="Guardar", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"]
        )
        save_button.connect(
            "clicked",
            lambda _b: self._client_id_entry.get_text().strip()
            and self.emit("client-id-save-requested", self._client_id_entry.get_text().strip()),
        )
        box.append(self._client_id_entry)
        box.append(save_button)
        self._client_id_page.set_child(box)
        self.append(self._client_id_page)

    # --- Paso 2: login PKCE -----------------------------------------------

    def _build_connect_step(self) -> None:
        self._connect_page = Adw.StatusPage(
            icon_name="audio-headphones-symbolic",
            title="Conecta tu cuenta de Spotify",
            description="Se abre tu navegador — Purrr nunca ve tu usuario ni contraseña "
            "de Spotify (ver auth/spotify_oauth.py).",
        )
        connect_button = Gtk.Button(
            label="Conectar con Spotify", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"]
        )
        connect_button.connect("clicked", lambda _b: self.emit("connect-requested"))
        self._connect_page.set_child(connect_button)
        self.append(self._connect_page)

    # --- Paso 3: búsqueda -----------------------------------------------------

    def _build_search_step(self) -> None:
        self._search_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._search_entry = Gtk.SearchEntry(placeholder_text="Buscar canciones en Spotify")
        self._search_entry.connect("activate", lambda entry: self.emit("search-requested", entry.get_text()))
        self._search_box.append(self._search_entry)

        self._results_list = Gtk.ListBox(css_classes=["boxed-list"])
        scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=240)
        scrolled.set_child(self._results_list)
        self._search_box.append(scrolled)
        self.append(self._search_box)

    def show_results(self, tracks: list[SpotifyTrack]) -> None:
        while row := self._results_list.get_row_at_index(0):
            self._results_list.remove(row)
        for track in tracks:
            subtitle = f"{track.artist or ''} — {track.album or ''}".strip(" —")
            row = Adw.ActionRow(title=escape(track.title), subtitle=escape(subtitle))
            play_button = Gtk.Button(
                icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Reproducir"
            )
            play_button.connect("clicked", lambda _b, t=track: self.emit("play-requested", t))
            add_button = Gtk.Button(
                icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Agregar a playlist"
            )
            add_button.connect("clicked", lambda _b, t=track: self.emit("add-to-playlist-requested", t))
            row.add_suffix(play_button)
            row.add_suffix(add_button)
            self._results_list.append(row)

    # --- Dispositivos Spotify Connect (solo lectura) --------------------------

    def _build_devices_section(self) -> None:
        header = Gtk.Label(
            label="Dispositivos Spotify Connect disponibles",
            halign=Gtk.Align.START, css_classes=["title-4"],
        )
        self._devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._devices_header = header
        self.append(header)
        self.append(self._devices_box)

    def show_devices(self, devices: list[dict]) -> None:
        while child := self._devices_box.get_first_child():
            self._devices_box.remove(child)
        if not devices:
            self._devices_box.append(
                Gtk.Label(
                    label="Ninguno — abre Spotify en tu celular u otra computadora para poder reproducir aquí.",
                    halign=Gtk.Align.START, css_classes=["dim-label"], wrap=True,
                )
            )
            return
        for device in devices:
            state = "activo" if device.get("is_active") else "en espera"
            self._devices_box.append(
                Gtk.Label(
                    label=f"• {device.get('name', '?')} ({device.get('type', '?')}) — {state}",
                    halign=Gtk.Align.START,
                )
            )

    # --- Estado visible --------------------------------------------------------

    def set_client_configured(self, configured: bool) -> None:
        self._client_id_page.set_visible(not configured)
        self._connect_page.set_sensitive(configured)

    def set_authenticated(self, authenticated: bool) -> None:
        self._connect_page.set_visible(not authenticated)
        self._search_box.set_visible(authenticated)
        self._devices_header.set_visible(authenticated)
        self._devices_box.set_visible(authenticated)
