from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Pango

from purrr.metadata.cover_search import CoverCandidate
from purrr.ui.dialogs import prompt_text
from purrr.ui.textures import load_texture_from_bytes

_THUMB_SIZE = 120
_RESPONSE_SEARCH_AGAIN = 1


def open_cover_approval_dialog(
    parent: Gtk.Window,
    album_label: str,
    search_term: str,
    candidates: list[tuple[CoverCandidate, bytes | None]],
    on_approve: Callable[[CoverCandidate], None],
    on_search_again: Callable[[str], None],
) -> None:
    """Muestra las carátulas candidatas encontradas en internet para que el usuario elija (o
    cancele, o pida otra búsqueda si ninguna coincide). Solo al hacer clic sobre una se
    descarga en resolución completa y se guarda."""
    dialog = Gtk.Dialog(title=f"Carátula para «{album_label}»", modal=True, transient_for=parent)
    dialog.set_default_size(420, 380)
    content = dialog.get_content_area()
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)

    def on_response(dlg, response):
        dlg.destroy()
        if response == _RESPONSE_SEARCH_AGAIN:
            prompt_text(parent, "Buscar carátula", on_search_again, initial_text=search_term)

    if not candidates:
        content.append(Gtk.Label(label="No se encontraron carátulas para este álbum.", wrap=True))
        dialog.add_button("Nueva búsqueda", _RESPONSE_SEARCH_AGAIN)
        dialog.add_button("Cerrar", Gtk.ResponseType.CANCEL)
        dialog.connect("response", on_response)
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

        # Etiqueta VISIBLE (no solo tooltip al pasar el mouse) — para que se note a simple
        # vista que una nueva búsqueda trajo resultados distintos, y no solo carátulas
        # abstractas que a ojo pueden parecer "las mismas de antes".
        caption = Gtk.Label(
            label=candidate.label, wrap=True, justify=Gtk.Justification.CENTER,
            lines=2, ellipsize=Pango.EllipsizeMode.END, max_width_chars=16,
        )
        caption.add_css_class("caption")

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, width_request=_THUMB_SIZE)
        button = Gtk.Button(child=picture, has_frame=False, tooltip_text=candidate.label)

        def on_click(_button, c=candidate):
            on_approve(c)
            dialog.destroy()

        button.connect("clicked", on_click)
        card.append(button)
        card.append(caption)
        flow.append(card)

    scrolled = Gtk.ScrolledWindow(vexpand=True)
    scrolled.set_child(flow)
    content.append(scrolled)

    dialog.add_button("Nueva búsqueda", _RESPONSE_SEARCH_AGAIN)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    dialog.connect("response", on_response)
    dialog.present()
