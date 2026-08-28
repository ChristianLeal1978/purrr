import sqlite3
import threading
from importlib import resources

from purrr.config import DB_PATH
from purrr.drive.scanner import DriveFile
from purrr.metadata.extractor import PartialMetadata, TrackMetadata

_local = threading.local()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_connection() -> sqlite3.Connection:
    """Devuelve una conexión propia del hilo actual (SQLite no es segura entre hilos)."""
    if not hasattr(_local, "conn"):
        _local.conn = _connect()
    return _local.conn


_TRACK_COLUMN_MIGRATIONS = {
    "art_path": "ALTER TABLE tracks ADD COLUMN art_path TEXT",
    "folder_cover_file_id": "ALTER TABLE tracks ADD COLUMN folder_cover_file_id TEXT",
    "folder_cover_ext": "ALTER TABLE tracks ADD COLUMN folder_cover_ext TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Agrega columnas nuevas a bases de datos ya existentes (CREATE TABLE IF NOT EXISTS no las toca)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(tracks)")}
    for column, statement in _TRACK_COLUMN_MIGRATIONS.items():
        if column not in existing:
            conn.execute(statement)
    conn.commit()


def init_db() -> None:
    schema = resources.files("purrr.db").joinpath("schema.sql").read_text()
    conn = get_connection()
    conn.executescript(schema)
    _migrate(conn)


# --- Sources -----------------------------------------------------------

def upsert_source(drive_folder_id: str, display_name: str) -> int:
    conn = get_connection()
    conn.execute(
        "INSERT INTO sources (drive_folder_id, display_name) VALUES (?, ?) "
        "ON CONFLICT(drive_folder_id) DO UPDATE SET display_name = excluded.display_name",
        (drive_folder_id, display_name),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM sources WHERE drive_folder_id = ?", (drive_folder_id,)
    ).fetchone()
    return row["id"]


def touch_source_scanned(source_id: int) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE sources SET last_scanned_at = datetime('now') WHERE id = ?", (source_id,)
    )
    conn.commit()


def list_sources() -> list[sqlite3.Row]:
    return get_connection().execute("SELECT * FROM sources ORDER BY display_name").fetchall()


def delete_source(source_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()


# --- Tracks --------------------------------------------------------------

def upsert_track_from_drive(source_id: int, drive_file: DriveFile) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO tracks (
            drive_file_id, source_id, drive_parent_id, drive_folder_path,
            file_name, mime_type, drive_md5, drive_modified_time, drive_size_bytes,
            cache_status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
        ON CONFLICT(drive_file_id) DO UPDATE SET
            drive_parent_id = excluded.drive_parent_id,
            drive_folder_path = excluded.drive_folder_path,
            file_name = excluded.file_name,
            mime_type = excluded.mime_type,
            drive_md5 = excluded.drive_md5,
            drive_modified_time = excluded.drive_modified_time,
            drive_size_bytes = excluded.drive_size_bytes,
            cache_status = CASE
                WHEN tracks.drive_md5 IS NOT excluded.drive_md5 THEN 'pending'
                ELSE tracks.cache_status
            END,
            updated_at = datetime('now')
        """,
        (
            drive_file.id,
            source_id,
            drive_file.parents[0] if drive_file.parents else None,
            drive_file.folder_path,
            drive_file.name,
            drive_file.mime_type,
            drive_file.md5_checksum,
            drive_file.modified_time,
            drive_file.size,
        ),
    )
    conn.commit()


def get_track_by_drive_id(drive_file_id: str) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM tracks WHERE drive_file_id = ?", (drive_file_id,)
    ).fetchone()


def list_pending_tracks(source_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        "SELECT * FROM tracks WHERE source_id = ? AND cache_status IN ('pending', 'error') "
        "ORDER BY file_name",
        (source_id,),
    ).fetchall()


def list_tracks_needing_metadata(source_id: int, folder_path: str | None = None) -> list[sqlite3.Row]:
    """Tracks sin descargar todavía y sin etiquetas leídas — candidatos para lectura parcial.

    Con `folder_path`, se limita a esa carpeta puntual (no recursivo) en vez de toda la fuente.
    """
    conn = get_connection()
    if folder_path is not None:
        return conn.execute(
            "SELECT * FROM tracks WHERE source_id = ? AND drive_folder_path = ? "
            "AND cache_status = 'pending' AND title IS NULL ORDER BY file_name",
            (source_id, folder_path),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM tracks WHERE source_id = ? AND cache_status = 'pending' AND title IS NULL "
        "ORDER BY file_name",
        (source_id,),
    ).fetchall()


def update_track_cache(
    drive_file_id: str,
    *,
    local_path: str | None = None,
    cache_status: str,
    cache_error: str | None = None,
) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE tracks SET local_path = ?, cache_status = ?, cache_error = ?, "
        "updated_at = datetime('now') WHERE drive_file_id = ?",
        (local_path, cache_status, cache_error, drive_file_id),
    )
    conn.commit()


def update_track_metadata(drive_file_id: str, metadata: TrackMetadata) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE tracks SET
            title = ?, artist = ?, album = ?, album_artist = ?,
            track_number = ?, disc_number = ?, year = ?, genre = ?,
            duration_seconds = ?, updated_at = datetime('now')
        WHERE drive_file_id = ?
        """,
        (
            metadata.title,
            metadata.artist,
            metadata.album,
            metadata.album_artist,
            metadata.track_number,
            metadata.disc_number,
            metadata.year,
            metadata.genre,
            metadata.duration_seconds,
            drive_file_id,
        ),
    )
    conn.commit()


def update_track_partial_metadata(drive_file_id: str, metadata: PartialMetadata) -> None:
    """Igual que update_track_metadata, pero solo pisa los campos que sí se pudieron leer
    (COALESCE) — para no perder datos ya conocidos con los None de una lectura parcial."""
    conn = get_connection()
    conn.execute(
        """
        UPDATE tracks SET
            title = COALESCE(?, title),
            artist = COALESCE(?, artist),
            album = COALESCE(?, album),
            album_artist = COALESCE(?, album_artist),
            track_number = COALESCE(?, track_number),
            disc_number = COALESCE(?, disc_number),
            year = COALESCE(?, year),
            genre = COALESCE(?, genre),
            duration_seconds = COALESCE(?, duration_seconds),
            updated_at = datetime('now')
        WHERE drive_file_id = ?
        """,
        (
            metadata.title,
            metadata.artist,
            metadata.album,
            metadata.album_artist,
            metadata.track_number,
            metadata.disc_number,
            metadata.year,
            metadata.genre,
            metadata.duration_seconds,
            drive_file_id,
        ),
    )
    conn.commit()


def update_track_art(drive_file_id: str, art_path: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE tracks SET art_path = ?, updated_at = datetime('now') WHERE drive_file_id = ?",
        (art_path, drive_file_id),
    )
    conn.commit()


def set_folder_covers(source_id: int, folder_covers: dict[str, tuple[str, str]]) -> None:
    """folder_covers: {drive_parent_id: (cover_drive_file_id, extensión_ej_'.jpg')}.

    Solo llena folder_cover_file_id en tracks que todavía no tenían uno asignado, para no
    pisar el de un escaneo previo si esta vez la carpeta no trajo covers (por una query parcial).
    """
    conn = get_connection()
    for parent_id, (cover_id, cover_ext) in folder_covers.items():
        conn.execute(
            "UPDATE tracks SET folder_cover_file_id = ?, folder_cover_ext = ? "
            "WHERE source_id = ? AND drive_parent_id = ? AND folder_cover_file_id IS NULL",
            (cover_id, cover_ext, source_id, parent_id),
        )
    conn.commit()


def force_set_folder_cover(source_id: int, parent_id: str, cover_id: str, cover_ext: str) -> None:
    """Como set_folder_covers, pero sin el resguardo de 'solo si estaba en NULL' — para cuando
    el usuario pide explícitamente re-buscar la carátula de una carpeta (botón 'Leer etiquetas'),
    donde si corresponde SÍ hay que pisar un folder_cover_file_id viejo o el sentinel '' de
    'ya se buscó antes y no había nada'."""
    conn = get_connection()
    conn.execute(
        "UPDATE tracks SET folder_cover_file_id = ?, folder_cover_ext = ? "
        "WHERE source_id = ? AND drive_parent_id = ?",
        (cover_id, cover_ext, source_id, parent_id),
    )
    conn.commit()


def mark_missing_tracks(source_id: int, seen_drive_file_ids: set[str]) -> None:
    conn = get_connection()
    placeholders = ",".join("?" * len(seen_drive_file_ids)) if seen_drive_file_ids else "''"
    conn.execute(
        f"UPDATE tracks SET cache_status = 'missing', updated_at = datetime('now') "
        f"WHERE source_id = ? AND drive_file_id NOT IN ({placeholders})",
        (source_id, *seen_drive_file_ids),
    )
    conn.commit()


def list_tracks(filter_text: str | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    if filter_text:
        like = f"%{filter_text}%"
        return conn.execute(
            "SELECT * FROM tracks WHERE cache_status != 'missing' AND "
            "(title LIKE ? OR artist LIKE ? OR album LIKE ?) "
            "ORDER BY artist, album, disc_number, track_number, title",
            (like, like, like),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM tracks WHERE cache_status != 'missing' "
        "ORDER BY artist, album, disc_number, track_number, title"
    ).fetchall()


def get_track(track_id: int) -> sqlite3.Row | None:
    return get_connection().execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()


def list_source_folder_paths(source_id: int) -> list[str]:
    """Rutas de carpeta distintas (relativas a la raíz de la fuente) que tienen canciones."""
    rows = get_connection().execute(
        "SELECT DISTINCT drive_folder_path FROM tracks "
        "WHERE source_id = ? AND drive_folder_path IS NOT NULL AND cache_status != 'missing'",
        (source_id,),
    ).fetchall()
    return [row["drive_folder_path"] for row in rows]


def list_tracks_in_folder(source_id: int, folder_path: str) -> list[sqlite3.Row]:
    """Canciones directamente dentro de esa carpeta (no recursivo), en orden de álbum.

    `file_name` como último criterio (en vez de `title`) porque suele traer el número de pista
    en el nombre — así el orden por defecto no queda arbitrario en canciones que aún no
    tienen etiquetas leídas (title/track_number en NULL).
    """
    return get_connection().execute(
        "SELECT * FROM tracks WHERE source_id = ? AND drive_folder_path = ? AND cache_status != 'missing' "
        "ORDER BY disc_number, track_number, file_name",
        (source_id, folder_path),
    ).fetchall()


def list_tracks_in_folder_recursive(source_id: int, folder_path: str) -> list[sqlite3.Row]:
    """Como list_tracks_in_folder, pero incluye también las subcarpetas — para "Agregar a
    álbumes" desde una carpeta que tiene discos/subcarpetas adentro."""
    conn = get_connection()
    if not folder_path or folder_path == "/":
        return conn.execute(
            "SELECT * FROM tracks WHERE source_id = ? AND cache_status != 'missing' "
            "ORDER BY drive_folder_path, disc_number, track_number, file_name",
            (source_id,),
        ).fetchall()
    prefix = folder_path.rstrip("/") + "/%"
    return conn.execute(
        "SELECT * FROM tracks WHERE source_id = ? AND cache_status != 'missing' "
        "AND (drive_folder_path = ? OR drive_folder_path LIKE ?) "
        "ORDER BY drive_folder_path, disc_number, track_number, file_name",
        (source_id, folder_path, prefix),
    ).fetchall()


# --- Álbumes -----------------------------------------------------------
# A diferencia de `tracks.album` (la etiqueta cruda del archivo, usada para mostrar/buscar en
# la biblioteca), un álbum acá es una entidad que el usuario arma a mano con "Agregar a
# álbumes" — solo así aparece en la vista Álbumes.

def get_or_create_album(name: str, artist: str | None = None) -> int:
    conn = get_connection()
    row = conn.execute("SELECT id FROM albums WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if row is not None:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO albums (name, artist) VALUES (?, ?)", (name, artist)
    )
    conn.commit()
    return cursor.lastrowid


def _backfill_album_art(conn: sqlite3.Connection, album_id: int) -> None:
    """Si el álbum todavía no tiene carátula, usa la primera que encuentre entre sus tracks
    (embebida o de carpeta) en vez de obligar a buscarla en internet de una."""
    row = conn.execute("SELECT art_path FROM albums WHERE id = ?", (album_id,)).fetchone()
    if row is None or row["art_path"]:
        return
    art_row = conn.execute(
        "SELECT t.art_path FROM album_tracks atk JOIN tracks t ON t.id = atk.track_id "
        "WHERE atk.album_id = ? AND t.art_path IS NOT NULL LIMIT 1",
        (album_id,),
    ).fetchone()
    if art_row is not None:
        conn.execute(
            "UPDATE albums SET art_path = ?, updated_at = datetime('now') WHERE id = ?",
            (art_row["art_path"], album_id),
        )
        conn.commit()


def add_tracks_to_album(album_id: int, track_ids: list[int]) -> int:
    """Agrega canciones a un álbum (ignora las que ya estaban). Devuelve cuántas se sumaron."""
    conn = get_connection()
    added = 0
    for track_id in track_ids:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO album_tracks (album_id, track_id) VALUES (?, ?)",
            (album_id, track_id),
        )
        added += cursor.rowcount
    conn.commit()
    _backfill_album_art(conn, album_id)
    return added


def update_album_art(album_id: int, art_path: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE albums SET art_path = ?, updated_at = datetime('now') WHERE id = ?",
        (art_path, album_id),
    )
    conn.commit()


def list_albums() -> list[sqlite3.Row]:
    """Un renglón por álbum armado a mano por el usuario, con año, cantidad de canciones
    (contando solo las que siguen presentes) y su carátula."""
    return get_connection().execute(
        """
        SELECT a.id AS id, a.name AS album, a.artist AS display_artist, a.art_path AS art_path,
               COUNT(t.id) AS track_count, MAX(t.year) AS year
        FROM albums a
        JOIN album_tracks atk ON atk.album_id = a.id
        JOIN tracks t ON t.id = atk.track_id AND t.cache_status != 'missing'
        GROUP BY a.id
        HAVING track_count > 0
        ORDER BY display_artist COLLATE NOCASE, year, album
        """
    ).fetchall()


def list_album_tracks(album_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        """
        SELECT t.* FROM tracks t
        JOIN album_tracks atk ON atk.track_id = t.id
        WHERE atk.album_id = ? AND t.cache_status != 'missing'
        ORDER BY t.disc_number, t.track_number, t.title
        """,
        (album_id,),
    ).fetchall()


# --- Playlists -------------------------------------------------------------

def create_playlist(name: str) -> int:
    conn = get_connection()
    cursor = conn.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
    conn.commit()
    return cursor.lastrowid


def rename_playlist(playlist_id: int, name: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE playlists SET name = ?, updated_at = datetime('now') WHERE id = ?",
        (name, playlist_id),
    )
    conn.commit()


def delete_playlist(playlist_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
    conn.commit()


def list_playlists() -> list[sqlite3.Row]:
    return get_connection().execute("SELECT * FROM playlists ORDER BY name").fetchall()


def list_playlist_tracks(playlist_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        """
        SELECT tracks.*, playlist_tracks.position AS playlist_position,
               playlist_tracks.id AS playlist_track_id
        FROM playlist_tracks
        JOIN tracks ON tracks.id = playlist_tracks.track_id
        WHERE playlist_tracks.playlist_id = ?
        ORDER BY playlist_tracks.position
        """,
        (playlist_id,),
    ).fetchall()


def add_track_to_playlist(playlist_id: int, track_id: int) -> None:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM playlist_tracks "
        "WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO playlist_tracks (playlist_id, track_id, position) VALUES (?, ?, ?)",
        (playlist_id, track_id, row["next_pos"]),
    )
    conn.commit()


def remove_playlist_track(playlist_track_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM playlist_tracks WHERE id = ?", (playlist_track_id,))
    conn.commit()


def reorder_playlist_tracks(playlist_id: int, playlist_track_ids_in_order: list[int]) -> None:
    conn = get_connection()
    # Desplazar a posiciones negativas temporales para esquivar el UNIQUE(playlist_id, position).
    for offset, playlist_track_id in enumerate(playlist_track_ids_in_order):
        conn.execute(
            "UPDATE playlist_tracks SET position = ? WHERE id = ? AND playlist_id = ?",
            (-(offset + 1), playlist_track_id, playlist_id),
        )
    for position, playlist_track_id in enumerate(playlist_track_ids_in_order):
        conn.execute(
            "UPDATE playlist_tracks SET position = ? WHERE id = ? AND playlist_id = ?",
            (position, playlist_track_id, playlist_id),
        )
    conn.commit()


# --- App state ---------------------------------------------------------

def get_state(key: str, default: str | None = None) -> str | None:
    row = get_connection().execute(
        "SELECT value FROM app_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO app_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
