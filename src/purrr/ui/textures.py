import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib


def load_texture_at_size(path: str, size: int, scale: int = 1) -> Gdk.Texture | None:
    """Escala la imagen ANTES de dársela a Gtk.Picture — si le pasamos el archivo completo
    (a veces 500px+ de carátula embebida), Picture usa esas dimensiones como tamaño natural
    sin importar `set_size_request`, y termina empujando el layout de todo lo que la rodea.

    `scale` debe ser el `Gtk.Widget.get_scale_factor()` del widget donde se va a mostrar
    (2 en pantallas HiDPI): `size` son píxeles lógicos, pero Picture renderiza en píxeles
    físicos (`size * scale`), así que pedir la textura solo a `size` la deja corta de
    resolución ahí y GTK la agranda — se ve borrosa. Con `scale=1` (default) no cambia nada."""
    try:
        pixel_size = round(size * scale)
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, pixel_size, pixel_size)
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
