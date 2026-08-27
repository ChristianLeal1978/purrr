import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf


def load_texture_at_size(path: str, size: int) -> Gdk.Texture | None:
    """Escala la imagen ANTES de dársela a Gtk.Picture — si le pasamos el archivo completo
    (a veces 500px+ de carátula embebida), Picture usa esas dimensiones como tamaño natural
    sin importar `set_size_request`, y termina empujando el layout de todo lo que la rodea."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
        return Gdk.Texture.new_for_pixbuf(pixbuf)
    except Exception:
        return None
