import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from purrr.ui.markup import escape

_MAX_LOG_LINES = 30

# Puntaje de fortaleza de contraseña (heurística simple, sin dependencias externas):
# un punto por cada criterio cumplido, sobre un máximo de 5 — ver _password_strength.
_STRENGTH_LABELS = ("Muy débil", "Débil", "Media", "Fuerte", "Muy fuerte", "Muy fuerte")


def _password_strength(password: str) -> tuple[int, str]:
    score = 0
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if re.search(r"[a-z]", password) and re.search(r"[A-Z]", password):
        score += 1
    if re.search(r"[0-9]", password):
        score += 1
    if re.search(r"[^A-Za-z0-9]", password):
        score += 1
    return score, _STRENGTH_LABELS[score]


class CloudSettingsView(Gtk.Box):
    """Pantalla 'Cuenta / Sync': login con la cuenta Purrr (email + contraseña,
    Supabase Auth, un único backend compartido — ver `purrr/config.py`) — esto es lo
    que trae Drive/RadioTunes/Spotify ya conectados desde la bóveda (`cloud/vault.py`),
    sin repetir ningún flujo de autorización.
    """

    __gsignals__ = {
        "sign-in-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        # avatar_path va vacío ("") cuando no se eligió foto — Adw.Avatar ya resuelve
        # las iniciales solo, así que el backend no recibe None por un tipo de señal
        # que no admite Optional[str].
        "sign-up-requested": (GObject.SignalFlags.RUN_FIRST, None, (str, str, str, str)),
        "sign-out-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "avatar-upload-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
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
        # Dos pantallas dentro de la misma tarjeta: "form" (login/registro de siempre)
        # y "pending" (justo después de crear la cuenta, mientras falta confirmar el
        # correo) — self._pending_email guarda el email para precargarlo al volver.
        self._login_stack = Gtk.Stack(halign=Gtk.Align.CENTER)
        self._pending_email: str | None = None
        self._login_stack.add_named(self._build_login_form(), "form")
        self._login_stack.add_named(self._build_pending_confirmation(), "pending")
        self._login_page.set_child(self._login_stack)
        self._content.append(self._login_page)

    def _build_login_form(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        box.set_size_request(320, -1)

        # Foto opcional (solo para "Crear cuenta"): sin ella, Adw.Avatar cae solo a
        # las iniciales del texto que le demos (ver _on_name_changed), no hace falta
        # calcularlas a mano.
        self._avatar_path: str | None = None
        self._avatar_widget = Adw.Avatar(size=64, show_initials=True, halign=Gtk.Align.CENTER)
        avatar_button = Gtk.Button(
            label="Elegir foto…", halign=Gtk.Align.CENTER, css_classes=["flat"]
        )
        avatar_button.connect("clicked", lambda _b: self.emit("avatar-upload-requested"))
        self._avatar_remove_button = Gtk.Button(
            label="Quitar foto", halign=Gtk.Align.CENTER, css_classes=["flat"], visible=False
        )
        self._avatar_remove_button.connect("clicked", lambda _b: self.set_avatar_photo(None))
        avatar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, halign=Gtk.Align.CENTER)
        avatar_box.append(self._avatar_widget)
        avatar_box.append(avatar_button)
        avatar_box.append(self._avatar_remove_button)

        # El nombre, la repetición de contraseña y el medidor de fortaleza solo los
        # pide "Crear cuenta"; "Iniciar sesión" los ignora.
        self._name_entry = Gtk.Entry(placeholder_text="Nombre (solo para crear cuenta)")
        self._name_entry.connect("changed", self._on_name_changed)
        self._email_entry = Gtk.Entry(placeholder_text="email@ejemplo.com")
        self._password_entry = Gtk.Entry(placeholder_text="Contraseña", visibility=False)
        self._password_entry.connect("changed", self._on_password_changed)
        self._password_confirm_entry = Gtk.Entry(
            placeholder_text="Repetir contraseña (solo para crear cuenta)", visibility=False
        )

        self._strength_bar = Gtk.LevelBar(min_value=0, max_value=5, visible=False)
        self._strength_bar.add_offset_value("low", 2)
        self._strength_bar.add_offset_value("high", 4)
        self._strength_bar.add_offset_value("full", 5)
        self._strength_label = Gtk.Label(
            label="", halign=Gtk.Align.START, css_classes=["caption", "dim-label"], visible=False
        )

        self._error_label = Gtk.Label(
            label="", halign=Gtk.Align.START, css_classes=["error"], wrap=True, visible=False
        )
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.CENTER)
        sign_in_button = Gtk.Button(label="Iniciar sesión", css_classes=["suggested-action", "pill"])
        sign_in_button.connect("clicked", self._on_sign_in_clicked)
        sign_up_button = Gtk.Button(label="Crear cuenta", css_classes=["pill"])
        sign_up_button.connect("clicked", self._on_sign_up_clicked)
        button_box.append(sign_in_button)
        button_box.append(sign_up_button)
        box.append(avatar_box)
        box.append(self._name_entry)
        box.append(self._email_entry)
        box.append(self._password_entry)
        box.append(self._strength_bar)
        box.append(self._strength_label)
        box.append(self._password_confirm_entry)
        box.append(self._error_label)
        box.append(button_box)
        return box

    def _build_pending_confirmation(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        box.set_size_request(320, -1)
        self._pending_label = Gtk.Label(label="", wrap=True, justify=Gtk.Justification.CENTER)
        continue_button = Gtk.Button(
            label="Iniciar sesión", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"]
        )
        continue_button.connect("clicked", self._on_pending_continue_clicked)
        box.append(self._pending_label)
        box.append(continue_button)
        return box

    def show_signup_pending(self, email: str) -> None:
        """Reemplaza el formulario por el aviso de "revisa tu correo" — se llama tras
        crear la cuenta cuando el proyecto Supabase exige confirmar el email antes de
        dar sesión (ver window.py:_on_cloud_signup_pending)."""
        self._pending_email = email
        self._pending_label.set_label(
            "¡Tu cuenta ya fue creada!\n\nAntes de iniciar sesión, por favor revisa tu correo "
            f"({email}) y confirma tu registro."
        )
        self._login_stack.set_visible_child_name("pending")

    def _on_pending_continue_clicked(self, _button) -> None:
        self.reset_login_form()
        if self._pending_email:
            self._email_entry.set_text(self._pending_email)
        self._password_entry.grab_focus()

    def _credentials(self) -> tuple[str, str]:
        return self._email_entry.get_text().strip(), self._password_entry.get_text()

    def _show_error(self, text: str) -> None:
        self._error_label.set_label(text)
        self._error_label.set_visible(True)

    def _on_name_changed(self, _entry) -> None:
        # Solo actualiza las iniciales cuando no hay foto elegida — con foto, el
        # nombre no debe pisar la vista previa de la imagen.
        if self._avatar_path is None:
            self._avatar_widget.set_text(self._name_entry.get_text().strip())

    def _on_password_changed(self, _entry) -> None:
        password = self._password_entry.get_text()
        if not password:
            self._strength_bar.set_visible(False)
            self._strength_label.set_visible(False)
            return
        score, label = _password_strength(password)
        self._strength_bar.set_value(score)
        self._strength_bar.set_visible(True)
        self._strength_label.set_label(f"Fortaleza: {label}")
        self._strength_label.set_visible(True)

    def set_avatar_photo(self, path: str | None) -> None:
        """Fija (o quita, con path=None) la foto elegida para la cuenta nueva. Si falla
        la carga de la imagen, cae a las iniciales — nunca bloquea crear la cuenta."""
        if path is None:
            self._avatar_path = None
            self._avatar_widget.set_custom_image(None)
            self._avatar_remove_button.set_visible(False)
            self._avatar_widget.set_text(self._name_entry.get_text().strip())
            return
        try:
            texture = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            self._show_error("No se pudo cargar esa imagen — se usarán las iniciales.")
            return
        self._avatar_path = path
        self._avatar_widget.set_custom_image(texture)
        self._avatar_remove_button.set_visible(True)

    def _on_sign_in_clicked(self, _button) -> None:
        email, password = self._credentials()
        if not email or not password:
            self._show_error("Ingresa tu email y contraseña.")
            return
        self._error_label.set_visible(False)
        self.emit("sign-in-requested", email, password)

    def _on_sign_up_clicked(self, _button) -> None:
        name = self._name_entry.get_text().strip()
        email, password = self._credentials()
        password_confirm = self._password_confirm_entry.get_text()
        if not name or not email or not password:
            self._show_error("Completa nombre, email y contraseña para crear la cuenta.")
            return
        if password != password_confirm:
            self._show_error("Las contraseñas no coinciden.")
            return
        if _password_strength(password)[0] < 2:
            self._show_error("Elige una contraseña más segura (al menos 8 caracteres).")
            return
        self._error_label.set_visible(False)
        self.emit("sign-up-requested", name, email, password, self._avatar_path or "")

    # --- Estado conectado ----------------------------------------------------

    def _build_connected_step(self) -> None:
        self._connected_row = Adw.ActionRow(title="Conectado")
        self._connected_avatar = Adw.Avatar(size=40, show_initials=True)
        self._status_label = Gtk.Label(label="", css_classes=["dim-label"])
        sign_out_button = Gtk.Button(label="Cerrar sesión", valign=Gtk.Align.CENTER)
        sign_out_button.connect("clicked", lambda _b: self.emit("sign-out-requested"))
        self._connected_row.add_prefix(self._connected_avatar)
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

    def set_logged_in(
        self,
        logged_in: bool,
        email: str | None,
        name: str | None = None,
        avatar_bytes: bytes | None = None,
    ) -> None:
        self._login_page.set_visible(not logged_in)
        self._connected_box.set_visible(logged_in)
        self._log_header.set_visible(logged_in)
        self._log_scrolled.set_visible(logged_in)
        if logged_in:
            self._connected_row.set_title(escape(email) if email else "Conectado")
            self._connected_avatar.set_text(name or email or "")
            self.set_connected_avatar(avatar_bytes)
        else:
            self.reset_login_form()

    def set_connected_avatar(self, avatar_bytes: bytes | None) -> None:
        """La foto de perfil se baja aparte (red) — ver window.py:_refresh_cloud_settings_view
        — así que llega después de que `set_logged_in` ya mostró las iniciales."""
        texture = None
        if avatar_bytes:
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(avatar_bytes))
            except GLib.Error:
                texture = None
        self._connected_avatar.set_custom_image(texture)

    def reset_login_form(self) -> None:
        """Limpia el formulario de login/registro — se llama tras autenticar y al
        cerrar sesión, para que la próxima vez no arrastre datos de la cuenta anterior."""
        self._name_entry.set_text("")
        self._email_entry.set_text("")
        self._password_entry.set_text("")
        self._password_confirm_entry.set_text("")
        self._error_label.set_visible(False)
        self._login_stack.set_visible_child_name("form")
        self.set_avatar_photo(None)

    def set_status(self, text: str) -> None:
        self._status_label.set_label(text)
