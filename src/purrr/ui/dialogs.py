import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


def prompt_text(parent: Gtk.Window, title: str, on_confirm, initial_text: str = "") -> None:
    """Diálogo chico de "escribí un texto y confirmá" (nombre de playlist, término de
    búsqueda de carátula, etc.)."""
    dialog = Gtk.Dialog(title=title, modal=True, transient_for=parent)
    entry = Gtk.Entry(
        text=initial_text, activates_default=True,
        margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
    )
    dialog.get_content_area().append(entry)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button("Aceptar", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    # Todo seleccionado de entrada: si el texto viene precargado (p. ej. el término de una
    # búsqueda de carátula que no encontró nada), escribir de una lo reemplaza en vez de
    # insertarse en el medio — si no, es fácil terminar reenviando el mismo término sin querer.
    entry.select_region(0, -1)
    entry.grab_focus()

    def on_response(dlg, response):
        text = entry.get_text().strip()
        if response == Gtk.ResponseType.OK and text:
            on_confirm(text)
        dlg.destroy()

    dialog.connect("response", on_response)
    dialog.present()


def confirm_action(
    parent: Gtk.Window, heading: str, body: str, confirm_label: str, on_confirm, destructive: bool = True
) -> None:
    """Diálogo chico de "¿confirmás?" (borrar álbum, etc.) — a diferencia de `prompt_text`,
    no hay entrada de texto, solo Cancelar/confirmar."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancelar")
    dialog.add_response("confirm", confirm_label)
    dialog.set_response_appearance(
        "confirm", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
    )
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def on_response(_dlg, response):
        if response == "confirm":
            on_confirm()

    dialog.connect("response", on_response)
    dialog.present(parent)
