import threading
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import GLib, Gtk, Pango

from purrr.drive.client import parse_folder_id_or_link

_ROOT_ID = "root"
_ROOT_NAME = "Mi unidad"


class DriveFolderPickerDialog(Gtk.Dialog):
    """Explorador de carpetas de Drive: navega subcarpetas o pega un link/ID manualmente."""

    def __init__(self, parent: Gtk.Window, service, on_confirm: Callable[[str, str], None]):
        super().__init__(title="Elegir carpeta de Google Drive", modal=True, transient_for=parent)
        self.set_default_size(480, 480)
        self._service = service
        self._on_confirm = on_confirm
        self._path_stack: list[tuple[str, str]] = [(_ROOT_ID, _ROOT_NAME)]

        content = self.get_content_area()
        content.set_spacing(6)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        nav_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._up_button = Gtk.Button(icon_name="go-up-symbolic", tooltip_text="Subir un nivel")
        self._up_button.connect("clicked", self._on_up_clicked)
        self._path_label = Gtk.Label(halign=Gtk.Align.START, hexpand=True,
                                      ellipsize=Pango.EllipsizeMode.START)
        nav_row.append(self._up_button)
        nav_row.append(self._path_label)
        content.append(nav_row)

        self._list_box = Gtk.ListBox(css_classes=["boxed-list"])
        self._list_box.connect("row-activated", self._on_row_activated)
        scrolled = Gtk.ScrolledWindow(vexpand=True)
        scrolled.set_child(self._list_box)
        content.append(scrolled)

        self._spinner = Gtk.Spinner()
        content.append(self._spinner)

        self._error_label = Gtk.Label(visible=False, wrap=True, css_classes=["error"])
        content.append(self._error_label)

        manual_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._manual_entry = Gtk.Entry(
            placeholder_text="…o pega un link/ID de carpeta aquí", hexpand=True
        )
        manual_add_button = Gtk.Button(label="Usar este link")
        manual_add_button.connect("clicked", self._on_manual_confirm)
        manual_row.append(self._manual_entry)
        manual_row.append(manual_add_button)
        content.append(manual_row)

        self.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        self.add_button("Usar esta carpeta", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.connect("response", self._on_response)

        self._refresh()

    def _current(self) -> tuple[str, str]:
        return self._path_stack[-1]

    def _refresh(self) -> None:
        folder_id, _name = self._current()
        self._path_label.set_text(" / ".join(name for _id, name in self._path_stack))
        self._up_button.set_sensitive(len(self._path_stack) > 1)
        self._error_label.set_visible(False)
        self._spinner.start()
        while row := self._list_box.get_row_at_index(0):
            self._list_box.remove(row)

        def worker() -> None:
            try:
                response = (
                    self._service.files()
                    .list(
                        q=(
                            f"'{folder_id}' in parents and "
                            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                        ),
                        fields="files(id, name)",
                        orderBy="name",
                        pageSize=200,
                    )
                    .execute(num_retries=3)
                )
                folders = response.get("files", [])
                GLib.idle_add(self._populate, folders)
            except Exception as exc:  # noqa: BLE001 — se muestra en el diálogo
                GLib.idle_add(self._show_error, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _populate(self, folders: list[dict]) -> bool:
        self._spinner.stop()
        if not folders:
            row = Gtk.ListBoxRow(selectable=False, activatable=False)
            row.set_child(Gtk.Label(label="(sin subcarpetas)", margin_top=6, margin_bottom=6))
            self._list_box.append(row)
            return False

        for folder in folders:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                margin_top=6, margin_bottom=6, margin_start=6, margin_end=6,
            )
            box.append(Gtk.Image(icon_name="folder-symbolic"))
            box.append(Gtk.Label(label=folder["name"], halign=Gtk.Align.START, hexpand=True))
            row.set_child(box)
            row.folder_id = folder["id"]
            row.folder_name = folder["name"]
            self._list_box.append(row)
        return False

    def _show_error(self, message: str) -> bool:
        self._spinner.stop()
        self._error_label.set_text(f"No se pudo cargar: {message}")
        self._error_label.set_visible(True)
        return False

    def _on_row_activated(self, _list_box, row: Gtk.ListBoxRow) -> None:
        if not hasattr(row, "folder_id"):
            return
        self._path_stack.append((row.folder_id, row.folder_name))
        self._refresh()

    def _on_up_clicked(self, _button) -> None:
        if len(self._path_stack) > 1:
            self._path_stack.pop()
            self._refresh()

    def _on_manual_confirm(self, _button) -> None:
        text = self._manual_entry.get_text().strip()
        if text:
            self._on_confirm(parse_folder_id_or_link(text), text)
            self.destroy()

    def _on_response(self, _dialog, response: int) -> None:
        if response == Gtk.ResponseType.OK:
            folder_id, folder_name = self._current()
            self._on_confirm(folder_id, folder_name)
        self.destroy()
