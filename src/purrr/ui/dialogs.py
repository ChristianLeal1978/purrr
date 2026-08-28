import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


def prompt_text(parent: Gtk.Window, title: str, on_confirm, initial_text: str = "") -> None:
    """Diálogo chico de "escribí un texto y confirmá" (nombre de playlist, término de
    búsqueda de carátula, etc.)."""
    dialog = Gtk.Dialog(title=title, modal=True, transient_for=parent)
    entry = Gtk.Entry(
        text=initial_text, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12
    )
    dialog.get_content_area().append(entry)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button("Aceptar", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    def on_response(dlg, response):
        text = entry.get_text().strip()
        if response == Gtk.ResponseType.OK and text:
            on_confirm(text)
        dlg.destroy()

    dialog.connect("response", on_response)
    dialog.present()
