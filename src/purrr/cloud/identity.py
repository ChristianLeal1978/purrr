"""Identidad estable de un track entre dispositivos, para el sync de playlists/álbumes.

Dos de tus Fedora escanean la misma cuenta de Drive, así que `drive_file_id` ya es un
identificador global compartido entre dispositivos — no hace falta sincronizar la tabla
`tracks` completa (título/artista/etc.), cada dispositivo la deriva de su propio escaneo.
Lo que sí viaja a Supabase es una referencia liviana con forma `"<provider>:<external_id>"`
(ej. `drive:abc123`), que este módulo sabe traducir de vuelta a un id local de SQLite.

El prefijo de proveedor es lo que permite, más adelante (Fase 5), que un mismo
`playlist_items.track_ref` sea indistintamente `drive:abc123` o `spotify:<id>` — para
tracks de Spotify no hay fila local que resolver (no hay cache de audio), se resuelven
contra metadata de la Web API en el módulo de Spotify, no acá.
"""

from purrr.db import database

DRIVE_PROVIDER = "drive"


def track_external_ref(track_row) -> str:
    """`track_row` es una `sqlite3.Row` de la tabla `tracks` (o cualquier mapping con
    `drive_file_id`). Hoy siempre es un track de Drive; el prefijo ya deja lugar para
    otros proveedores de tracks on-demand."""
    return f"{DRIVE_PROVIDER}:{track_row['drive_file_id']}"


def parse_track_ref(track_ref: str) -> tuple[str, str]:
    """Separa 'drive:abc123' en ('drive', 'abc123'). Lanza ValueError si no tiene el
    formato esperado — un track_ref mal formado no debería llegar nunca desde Supabase
    (solo lo escribe este mismo código), así que fallar fuerte acá ayuda a detectar bugs."""
    provider, _, external_id = track_ref.partition(":")
    if not provider or not external_id:
        raise ValueError(f"track_ref con formato inválido: {track_ref!r}")
    return provider, external_id


def resolve_local_track_id(track_ref: str) -> int | None:
    """Busca en la base local el track que corresponde a esta referencia estable.

    Devuelve `None` si el proveedor no es 'drive' (ver docstring del módulo — otros
    proveedores no tienen fila local) o si este dispositivo todavía no escaneó ese
    archivo de Drive (p. ej. el otro dispositivo agregó a una playlist un track de una
    carpeta que acá no está agregada como fuente). Este es un caso borde conocido y sin
    resolver en la Fase 1: el item de playlist llega por sync pero no se puede mostrar
    hasta que el track aparezca en un escaneo local — no debe romper nada mientras tanto.
    """
    provider, external_id = parse_track_ref(track_ref)
    if provider != DRIVE_PROVIDER:
        return None
    track = database.get_track_by_drive_id(external_id)
    return track["id"] if track is not None else None
