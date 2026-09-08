import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk


class SpotifyView(Gtk.ScrolledWindow):
    """Pantalla 'Spotify': conectar la cuenta (PKCE, sin contraseña que pasar por acá)
    para controlar Spotify Connect desde Purrr. Mismo estilo que
    `ui/first_run.py`/`ui/cloud_settings.py`.

    La búsqueda de canciones se sacó (ver commit) porque `/v1/search` no funciona para
    apps personales en modo Development desde el cambio de política de Spotify de
    noviembre 2024 — solo apps con Extended Quota Mode tienen acceso al catálogo, y
    Spotify no lo otorga para apps de uso individual.

    Envuelta en un ScrolledWindow (a diferencia de esas otras dos): sin conexión Spotify
    Connect, la lista de dispositivos queda vacía y el contenido es corto, pero con la
    ventana achicada el bloque entero (client ID + login + dispositivos) puede superar
    el alto disponible — antes quedaba cortado abajo sin ninguna forma de bajar a ver
    el resto."""

    __gsignals__ = {
        "client-id-save-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "connect-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(vexpand=True)
        self._box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12,
            margin_top=24, margin_bottom=24, margin_start=24, margin_end=24,
        )
        self.set_child(self._box)

        self._build_client_id_step()
        self._build_connect_step()
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
        self._box.append(self._client_id_page)

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
        self._box.append(self._connect_page)

    # --- Dispositivos Spotify Connect (solo lectura) --------------------------

    def _build_devices_section(self) -> None:
        header = Gtk.Label(
            label="Dispositivos Spotify Connect disponibles",
            halign=Gtk.Align.START, css_classes=["title-4"],
        )
        self._devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._devices_header = header
        self._box.append(header)
        self._box.append(self._devices_box)

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
        self._devices_header.set_visible(authenticated)
        self._devices_box.set_visible(authenticated)
