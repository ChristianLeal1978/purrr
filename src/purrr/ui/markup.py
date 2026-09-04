import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib


def escape(text: str) -> str:
    """`Adw.ActionRow` interpreta `title`/`subtitle` como marcado Pango, no texto
    plano — un nombre con `&` (ej. "Dave Koz & Friends", un canal real de
    RadioTunes) rompe el parseo si no se escapa primero. Confirmado con un warning
    real de GTK al mostrar el catálogo de RadioTunes."""
    return GLib.markup_escape_text(text)
