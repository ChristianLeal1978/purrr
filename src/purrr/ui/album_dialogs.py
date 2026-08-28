import sqlite3
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from purrr.metadata.cover_search import CoverCandidate
from purrr.ui.textures import load_texture_from_bytes

_THUMB_SIZE = 120


def open_add_to_album_dialog(
    parent: Gtk.Window,
    albums: list[sqlite3.Row],
    on_confirm: Callable[[int | None, str | None], None],
) -> None:
    """Diálogo de "Agregar a álbumes": elegir uno ya armado o escribir el nombre de uno nuevo.

    `on_confirm(album_id, new_name)` se llama con exactamente uno de los dos en no-None.
    """
    dialog = Gtk.Dialog(title="Agregar a álbumes", modal=True, transient_for=parent)
    dialog.set_default_size(340, 420)
    content = dialog.get_content_area()
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    content.append(box)

    list_box = None
    if albums:
        existing_label = Gtk.Label(label="Álbum existente", halign=Gtk.Align.START)
        existing_label.add_css_class("heading")
        box.append(existing_label)

        list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        list_box.add_css_class("boxed-list")
        for album in albums:
            row = Gtk.ListBoxRow()
            row.purrr_album_id = album["id"]
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                margin_top=6, margin_bottom=6, margin_start=8, margin_end=8,
            )
            title_label = Gtk.Label(label=album["album"], halign=Gtk.Align.START)
            artist_label = Gtk.Label(
                label=album["display_artist"] or "Artista desconocido", halign=Gtk.Align.START
            )
            artist_label.add_css_class("dim-label")
            row_box.append(title_label)
            row_box.append(artist_label)
            row.set_child(row_box)
            list_box.append(row)

        scrolled = Gtk.ScrolledWindow(min_content_height=160, vexpand=True)
        scrolled.set_child(list_box)
        box.append(scrolled)

    new_label = Gtk.Label(label="O crear álbum nuevo", halign=Gtk.Align.START)
    new_label.add_css_class("heading")
    box.append(new_label)
    entry = Gtk.Entry(placeholder_text="Nombre del álbum nuevo")
    box.append(entry)

    if list_box is not None:
        # Elegir una de las dos opciones limpia la otra, para que quede claro cuál se va a usar.
        list_box.connect(
            "row-selected", lambda _lb, row: entry.set_text("") if row is not None else None
        )
        entry.connect(
            "changed", lambda e: list_box.unselect_all() if e.get_text() else None
        )

    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button("Agregar", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)

    def on_response(dlg, response):
        if response == Gtk.ResponseType.OK:
            selected_row = list_box.get_selected_row() if list_box is not None else None
            name = entry.get_text().strip()
            if selected_row is not None:
                on_confirm(selected_row.purrr_album_id, None)
            elif name:
                on_confirm(None, name)
        dlg.destroy()

    dialog.connect("response", on_response)
    dialog.present()


def open_cover_approval_dialog(
    parent: Gtk.Window,
    album_label: str,
    candidates: list[tuple[CoverCandidate, bytes | None]],
    on_approve: Callable[[CoverCandidate], None],
) -> None:
    """Muestra las carátulas candidatas encontradas en internet para que el usuario elija (o
    cancele). Solo al hacer clic sobre una se descarga en resolución completa y se guarda."""
    dialog = Gtk.Dialog(title=f"Carátula para «{album_label}»", modal=True, transient_for=parent)
    dialog.set_default_size(420, 380)
    content = dialog.get_content_area()
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)

    if not candidates:
        content.append(Gtk.Label(label="No se encontraron carátulas para este álbum.", wrap=True))
        dialog.add_button("Cerrar", Gtk.ResponseType.CANCEL)
        dialog.connect("response", lambda dlg, _r: dlg.destroy())
        dialog.present()
        return

    content.append(
        Gtk.Label(label="Elegí la carátula correcta para guardarla localmente:", wrap=True, halign=Gtk.Align.START)
    )

    flow = Gtk.FlowBox(
        selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, homogeneous=True,
        column_spacing=8, row_spacing=8,
    )
    for candidate, thumb_bytes in candidates:
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
        picture.set_size_request(_THUMB_SIZE, _THUMB_SIZE)
        texture = load_texture_from_bytes(thumb_bytes, _THUMB_SIZE) if thumb_bytes else None
        picture.set_paintable(texture)

        button = Gtk.Button(child=picture, has_frame=False, tooltip_text=candidate.label)

        def on_click(_button, c=candidate):
            on_approve(c)
            dialog.destroy()

        button.connect("clicked", on_click)
        flow.append(button)

    scrolled = Gtk.ScrolledWindow(vexpand=True)
    scrolled.set_child(flow)
    content.append(scrolled)

    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.connect("response", lambda dlg, _r: dlg.destroy())
    dialog.present()
