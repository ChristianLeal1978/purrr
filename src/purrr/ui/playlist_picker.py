from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from purrr.db import database
from purrr.ui.dialogs import prompt_text


def open_playlist_picker(parent: Gtk.Window, on_chosen: Callable[[int], None]) -> None:
    """Diálogo chico para elegir a qué playlist agregar un track — reutilizado tanto
    para canciones de Drive (`ui/library_view.py`) como resultados de Spotify
    (`ui/spotify_view.py`). `on_chosen` recibe el id de la playlist elegida."""
    dialog = Gtk.Dialog(title="Agregar a playlist", modal=True, transient_for=parent)
    dialog.set_default_size(300, 300)

    box = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL, spacing=6,
        margin_top=12, margin_bottom=12, margin_start=12, margin_end=12,
    )
    list_box = Gtk.ListBox(css_classes=["boxed-list"])
    scrolled = Gtk.ScrolledWindow(vexpand=True)
    scrolled.set_child(list_box)
    box.append(scrolled)

    new_playlist_button = Gtk.Button(label="Nueva playlist…")
    box.append(new_playlist_button)
    dialog.get_content_area().append(box)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)

    def choose(playlist_id: int) -> None:
        dialog.destroy()
        on_chosen(playlist_id)

    for playlist in database.list_playlists():
        row = Gtk.ListBoxRow()
        row.set_child(Gtk.Label(label=playlist["name"], halign=Gtk.Align.START, margin_top=8, margin_bottom=8))
        row.playlist_id = playlist["id"]
        list_box.append(row)
    list_box.connect("row-activated", lambda _lb, row: choose(row.playlist_id))

    def on_new_playlist_clicked(_button) -> None:
        def on_confirm(name: str) -> None:
            playlist_id = database.create_playlist(name)
            choose(playlist_id)

        prompt_text(dialog, "Nombre de la nueva playlist", on_confirm)

    new_playlist_button.connect("clicked", on_new_playlist_clicked)

    dialog.connect("response", lambda dlg, _response: dlg.destroy())
    dialog.present()
