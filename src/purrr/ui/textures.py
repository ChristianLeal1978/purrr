import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib


def load_texture_at_size(path: str, size: int) -> Gdk.Texture | None:
    """Escala la imagen ANTES de dársela a Gtk.Picture — si le pasamos el archivo completo
    (a veces 500px+ de carátula embebida), Picture usa esas dimensiones como tamaño natural
    sin importar `set_size_request`, y termina empujando el layout de todo lo que la rodea."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
        return Gdk.Texture.new_for_pixbuf(pixbuf)
    except Exception:
        return None


def load_texture_from_bytes(data: bytes, size: int) -> Gdk.Texture | None:
    """Como load_texture_at_size, pero para bytes todavía no guardados en disco — se usa para
    previsualizar una carátula candidata de internet antes de que el usuario la apruebe."""
    try:
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
        pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, size, size, True, None)
        return Gdk.Texture.new_for_pixbuf(pixbuf)
    except Exception:
        return None
