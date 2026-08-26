from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from purrr.drive.client import parse_folder_id_or_link


def show_add_folder_dialog(parent: Gtk.Window, on_confirm: Callable[[str, str], None]) -> None:
    """on_confirm recibe (folder_id, texto_original_como_nombre_para_mostrar)."""
    dialog = Gtk.Dialog(title="Agregar carpeta de Google Drive", modal=True, transient_for=parent)

    content = dialog.get_content_area()
    content.set_spacing(6)
    label = Gtk.Label(
        label="Pega el link o el ID de la carpeta de Google Drive a escanear:",
        halign=Gtk.Align.START,
        margin_top=12,
        margin_start=12,
        margin_end=12,
    )
    entry = Gtk.Entry(
        placeholder_text="https://drive.google.com/drive/folders/…",
        margin_start=12,
        margin_end=12,
        margin_bottom=12,
    )
    content.append(label)
    content.append(entry)

    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button("Agregar", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    def on_response(dlg, response):
        text = entry.get_text().strip()
        if response == Gtk.ResponseType.OK and text:
            on_confirm(parse_folder_id_or_link(text), text)
        dlg.destroy()

    dialog.connect("response", on_response)
    dialog.present()
