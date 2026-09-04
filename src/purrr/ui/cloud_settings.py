import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.ui.markup import escape

_MAX_LOG_LINES = 30


class CloudSettingsView(Gtk.Box):
    """Pantalla 'Cuenta / Sync': login con la cuenta Purrr (email + contraseña,
    Supabase Auth, un único backend compartido — ver `purrr/config.py`) — esto es lo
    que trae Drive/RadioTunes/Spotify ya conectados desde la bóveda (`cloud/vault.py`),
    sin repetir ningún flujo de autorización.
    """

    __gsignals__ = {
        "sign-in-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "sign-up-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "sign-out-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        # `self` queda con un único hijo (el ScrolledWindow) para que esta pantalla no
        # fuerce una altura mayor a la disponible en pantallas chicas — mismo criterio
        # que stations_view.py.
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._content.set_margin_top(24)
        self._content.set_margin_bottom(24)
        self._content.set_margin_start(24)
        self._content.set_margin_end(24)

        self._build_login_step()
        self._build_connected_step()
        self._build_log()

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._content)
        self.append(scrolled)

        self.set_logged_in(False, None)

    # --- Login -----------------------------------------------------------

    def _build_login_step(self) -> None:
        self._login_page = Adw.StatusPage(
            icon_name="avatar-default-symbolic",
            title="Inicia sesión en tu cuenta Purrr",
            description="Con la misma cuenta en cada dispositivo, Drive/RadioTunes/"
            "Spotify quedan conectados solos — sin repetir ningún flujo de autorización.",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        box.set_size_request(320, -1)
        self._email_entry = Gtk.Entry(placeholder_text="email@ejemplo.com")
        self._password_entry = Gtk.Entry(placeholder_text="Contraseña", visibility=False)
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        sign_in_button = Gtk.Button(label="Iniciar sesión", css_classes=["suggested-action", "pill"])
        sign_in_button.connect("clicked", self._on_sign_in_clicked)
        sign_up_button = Gtk.Button(label="Crear cuenta", css_classes=["pill"])
        sign_up_button.connect("clicked", self._on_sign_up_clicked)
        button_box.append(sign_in_button)
        button_box.append(sign_up_button)
        box.append(self._email_entry)
        box.append(self._password_entry)
        box.append(button_box)
        self._login_page.set_child(box)
        self._content.append(self._login_page)

    def _credentials(self) -> tuple[str, str]:
        return self._email_entry.get_text().strip(), self._password_entry.get_text()

    def _on_sign_in_clicked(self, _button) -> None:
        email, password = self._credentials()
        if email and password:
            self.emit("sign-in-requested", email, password)

    def _on_sign_up_clicked(self, _button) -> None:
        email, password = self._credentials()
        if email and password:
            self.emit("sign-up-requested", email, password)

    # --- Estado conectado ----------------------------------------------------

    def _build_connected_step(self) -> None:
        self._connected_row = Adw.ActionRow(title="Conectado")
        self._status_label = Gtk.Label(label="", css_classes=["dim-label"])
        sign_out_button = Gtk.Button(label="Cerrar sesión", valign=Gtk.Align.CENTER)
        sign_out_button.connect("clicked", lambda _b: self.emit("sign-out-requested"))
        self._connected_row.add_suffix(self._status_label)
        self._connected_row.add_suffix(sign_out_button)
        self._connected_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["boxed-list"])
        self._connected_box.append(self._connected_row)
        self._content.append(self._connected_box)

    # --- Log de sync (debug) --------------------------------------------------

    def _build_log(self) -> None:
        header = Gtk.Label(label="Actividad reciente", halign=Gtk.Align.START, css_classes=["title-4"])
        self._log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=120)
        scrolled.set_child(self._log_box)
        self._log_header = header
        self._log_scrolled = scrolled
        self._content.append(header)
        self._content.append(scrolled)

    def log_event(self, message: str) -> None:
        label = Gtk.Label(label=message, halign=Gtk.Align.START, css_classes=["caption"], wrap=True)
        self._log_box.append(label)
        while len(list(self._iter_log_children())) > _MAX_LOG_LINES:
            first = self._log_box.get_first_child()
            if first is None:
                break
            self._log_box.remove(first)

    def _iter_log_children(self):
        child = self._log_box.get_first_child()
        while child is not None:
            yield child
            child = child.get_next_sibling()

    # --- Estado visible --------------------------------------------------------

    def set_logged_in(self, logged_in: bool, email: str | None) -> None:
        self._login_page.set_visible(not logged_in)
        self._connected_box.set_visible(logged_in)
        self._log_header.set_visible(logged_in)
        self._log_scrolled.set_visible(logged_in)
        if logged_in:
            self._connected_row.set_title(escape(email) if email else "Conectado")

    def set_status(self, text: str) -> None:
        self._status_label.set_label(text)
