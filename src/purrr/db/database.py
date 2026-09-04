import json
import sqlite3
import threading
import uuid as uuid_lib
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


_COLUMN_MIGRATIONS: dict[str, dict[str, str]] = {
    "tracks": {
        "art_path": "ALTER TABLE tracks ADD COLUMN art_path TEXT",
        "folder_cover_file_id": "ALTER TABLE tracks ADD COLUMN folder_cover_file_id TEXT",
        "folder_cover_ext": "ALTER TABLE tracks ADD COLUMN folder_cover_ext TEXT",
    },
    "sources": {
        "provider": "ALTER TABLE sources ADD COLUMN provider TEXT NOT NULL DEFAULT 'drive'",
    },
    "playlists": {
        "uuid": "ALTER TABLE playlists ADD COLUMN uuid TEXT",
        "deleted_at": "ALTER TABLE playlists ADD COLUMN deleted_at TEXT",
    },
    "albums": {
        "uuid": "ALTER TABLE albums ADD COLUMN uuid TEXT",
        "deleted_at": "ALTER TABLE albums ADD COLUMN deleted_at TEXT",
    },
    "album_tracks": {
        "updated_at": (
            "ALTER TABLE album_tracks ADD COLUMN updated_at TEXT NOT NULL "
            "DEFAULT (datetime('now'))"
        ),
        "deleted_at": "ALTER TABLE album_tracks ADD COLUMN deleted_at TEXT",
    },
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Agrega columnas nuevas a bases de datos ya existentes (CREATE TABLE IF NOT EXISTS no las toca)."""
    for table, migrations in _COLUMN_MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, statement in migrations.items():
            if column not in existing:
                conn.execute(statement)
    conn.commit()
    _backfill_uuids(conn)
    _migrate_playlist_tracks_to_items(conn)


def _migrate_playlist_tracks_to_items(conn: sqlite3.Connection) -> None:
    """Fase 4: `playlist_tracks` (FK entero, solo Drive) se reemplaza por
    `playlist_items` (track_ref de texto, Drive o Spotify — misma forma que
    `cloud/schema.sql`). En una base de la Fase 0/1 que todavía tenga la tabla
    vieja, copia cada fila armando `track_ref = 'drive:<drive_file_id>'` y la
    borra — no queda como código muerto una vez migrada."""
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "playlist_tracks" not in tables:
        return
    rows = conn.execute(
        "SELECT pt.playlist_id, pt.position, pt.added_at, "
        "t.drive_file_id FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id"
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT OR IGNORE INTO playlist_items "
            "(playlist_id, track_ref, position, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                row["playlist_id"],
                f"drive:{row['drive_file_id']}",
                row["position"],
                row["added_at"],
                row["added_at"],
            ),
        )
    conn.execute("DROP TABLE playlist_tracks")
    conn.commit()


def _backfill_uuids(conn: sqlite3.Connection) -> None:
    """Las filas de playlists/albums creadas antes de que existiera la columna
    `uuid` (Fase 0, sync entre dispositivos) necesitan una identidad estable."""
    for table in ("playlists", "albums"):
        rows = conn.execute(f"SELECT id FROM {table} WHERE uuid IS NULL").fetchall()
        for row in rows:
            conn.execute(
                f"UPDATE {table} SET uuid = ? WHERE id = ?", (str(uuid_lib.uuid4()), row["id"])
            )
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uuid ON {table}(uuid)"
        )
    conn.commit()


def init_db() -> None:
    schema = resources.files("purrr.db").joinpath("schema.sql").read_text()
    conn = get_connection()
    conn.executescript(schema)
    _migrate(conn)


def _enqueue_sync_op(conn: sqlite3.Connection, table_name: str, payload: dict) -> None:
    """Encola una mutación para que `cloud.sync_engine.CloudSyncEngine` la empuje a
    Supabase. Se llama dentro de la misma transacción que la mutación local (mismo
    `conn`, sin commit propio acá) para que un cierre inesperado antes del commit
    no deje la cola desincronizada de lo que realmente se guardó (Fase 1.3)."""
    conn.execute(
        "INSERT INTO pending_sync_ops (table_name, payload_json) VALUES (?, ?)",
        (table_name, json.dumps(payload)),
    )


def _track_ref(track: sqlite3.Row) -> str:
    """Identidad estable de un track entre dispositivos: 'drive:<drive_file_id>'.
    Ver `cloud/identity.py` para el lado inverso (resolver esto a un id local)."""
    return f"drive:{track['drive_file_id']}"


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


def list_folder_siblings_by_album(track_id: int) -> list[sqlite3.Row]:
    """Canciones de la MISMA carpeta que comparten la etiqueta de álbum de esta canción — para
    que "Agregar a álbumes" desde una sola canción sume el álbum entero, no solo esa pista.
    Si la canción no tiene etiqueta de álbum, no hay con qué emparejarla: devuelve solo ella."""
    track = get_track(track_id)
    if track is None:
        return []
    if not track["album"]:
        return [track]
    return get_connection().execute(
        "SELECT * FROM tracks WHERE source_id = ? AND drive_folder_path = ? AND album = ? "
        "AND cache_status != 'missing' ORDER BY disc_number, track_number, file_name",
        (track["source_id"], track["drive_folder_path"], track["album"]),
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
    """Empareja por nombre + artista (no solo nombre) — el nombre ahora sale de la etiqueta de
    la canción sin que el usuario lo revise, y dos artistas distintos con un álbum del mismo
    nombre (p. ej. "Greatest Hits") son moneda corriente."""
    conn = get_connection()
    if artist:
        row = conn.execute(
            "SELECT id FROM albums WHERE name = ? COLLATE NOCASE AND artist = ? COLLATE NOCASE",
            (name, artist),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM albums WHERE name = ? COLLATE NOCASE AND artist IS NULL", (name,)
        ).fetchone()
    if row is not None:
        return row["id"]
    album_uuid = str(uuid_lib.uuid4())
    cursor = conn.execute(
        "INSERT INTO albums (uuid, name, artist) VALUES (?, ?, ?)", (album_uuid, name, artist)
    )
    _enqueue_sync_op(conn, "albums", {"uuid": album_uuid, "name": name, "artist": artist})
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
    added_track_ids = []
    for track_id in track_ids:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO album_tracks (album_id, track_id) VALUES (?, ?)",
            (album_id, track_id),
        )
        if cursor.rowcount:
            added += 1
            added_track_ids.append(track_id)
    if added_track_ids:
        album_row = conn.execute("SELECT uuid FROM albums WHERE id = ?", (album_id,)).fetchone()
        conn.execute("UPDATE albums SET updated_at = datetime('now') WHERE id = ?", (album_id,))
        if album_row is not None:
            for track_id in added_track_ids:
                track_row = get_track(track_id)
                if track_row is not None:
                    _enqueue_sync_op(
                        conn,
                        "album_items",
                        {"album_uuid": album_row["uuid"], "track_ref": _track_ref(track_row)},
                    )
    conn.commit()
    _backfill_album_art(conn, album_id)
    return added


def get_album(album_id: int) -> sqlite3.Row | None:
    return get_connection().execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()


def update_album_art(album_id: int, art_path: str) -> None:
    """Única mutación de `albums` que hasta la Fase 2 no encolaba sync — una
    carátula buscada en iTunes o subida a mano es la única que de verdad conviene
    compartir entre dispositivos (ver el plan): la embebida o de carpeta de Drive
    cualquier dispositivo la deriva sola de su propio escaneo."""
    conn = get_connection()
    conn.execute(
        "UPDATE albums SET art_path = ?, updated_at = datetime('now') WHERE id = ?",
        (art_path, album_id),
    )
    album_row = conn.execute(
        "SELECT uuid, name, artist FROM albums WHERE id = ?", (album_id,)
    ).fetchone()
    if album_row is not None:
        _enqueue_sync_op(
            conn,
            "albums",
            {
                "uuid": album_row["uuid"], "name": album_row["name"], "artist": album_row["artist"],
                "art_local_path": art_path,
            },
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
        JOIN album_tracks atk ON atk.album_id = a.id AND atk.deleted_at IS NULL
        JOIN tracks t ON t.id = atk.track_id AND t.cache_status != 'missing'
        WHERE a.deleted_at IS NULL
        GROUP BY a.id
        HAVING track_count > 0
        ORDER BY display_artist COLLATE NOCASE, year, album
        """
    ).fetchall()


def list_album_tracks(album_id: int) -> list[sqlite3.Row]:
    return get_connection().execute(
        """
        SELECT t.* FROM tracks t
        JOIN album_tracks atk ON atk.track_id = t.id AND atk.deleted_at IS NULL
        WHERE atk.album_id = ? AND t.cache_status != 'missing'
        ORDER BY t.disc_number, t.track_number, t.title
        """,
        (album_id,),
    ).fetchall()


# --- Playlists -------------------------------------------------------------

def create_playlist(name: str) -> int:
    conn = get_connection()
    playlist_uuid = str(uuid_lib.uuid4())
    cursor = conn.execute(
        "INSERT INTO playlists (uuid, name) VALUES (?, ?)", (playlist_uuid, name)
    )
    _enqueue_sync_op(conn, "playlists", {"uuid": playlist_uuid, "name": name})
    conn.commit()
    return cursor.lastrowid


def get_playlist(playlist_id: int) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM playlists WHERE id = ? AND deleted_at IS NULL", (playlist_id,)
    ).fetchone()


def rename_playlist(playlist_id: int, name: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE playlists SET name = ?, updated_at = datetime('now') WHERE id = ?",
        (name, playlist_id),
    )
    row = conn.execute("SELECT uuid FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
    if row is not None:
        _enqueue_sync_op(conn, "playlists", {"uuid": row["uuid"], "name": name})
    conn.commit()


def delete_playlist(playlist_id: int) -> None:
    """Soft-delete: la fila se conserva con `deleted_at` para poder propagar el
    borrado a los demás dispositivos por sync (Fase 1). La UI (`list_playlists`)
    ya filtra `deleted_at IS NULL`."""
    conn = get_connection()
    row = conn.execute("SELECT uuid FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
    conn.execute(
        "UPDATE playlists SET deleted_at = datetime('now'), updated_at = datetime('now') "
        "WHERE id = ?",
        (playlist_id,),
    )
    if row is not None:
        _enqueue_sync_op(conn, "playlists", {"uuid": row["uuid"], "deleted": True})
    conn.commit()


def list_playlists() -> list[sqlite3.Row]:
    return get_connection().execute(
        "SELECT * FROM playlists WHERE deleted_at IS NULL ORDER BY name"
    ).fetchall()


def _track_object_row_from_drive(track_row: sqlite3.Row, playlist_item_id: int, position: int) -> dict:
    row = dict(track_row)
    row["source"] = "drive"
    row["spotify_uri"] = None
    row["playlist_position"] = position
    row["playlist_track_id"] = playlist_item_id
    return row


def _track_object_row_from_spotify(spotify_row: sqlite3.Row, playlist_item_id: int, position: int) -> dict:
    return {
        "id": f"spotify:{spotify_row['id']}",
        "drive_file_id": None,
        "title": spotify_row["title"],
        "artist": spotify_row["artist"],
        "album": spotify_row["album"],
        "duration_seconds": spotify_row["duration_seconds"],
        "local_path": None,
        "cache_status": "spotify",
        "art_path": spotify_row["art_path"],
        "track_number": None,
        "source": "spotify",
        "spotify_uri": spotify_row["uri"],
        "playlist_position": position,
        "playlist_track_id": playlist_item_id,
    }


def list_playlist_tracks(playlist_id: int) -> list[dict]:
    """A diferencia de las demás `list_*`, no es un solo JOIN: `playlist_items.track_ref`
    puede apuntar a `tracks` (Drive) o `spotify_tracks`, así que cada fila se resuelve acá
    (ver `_track_object_row_from_drive`/`_track_object_row_from_spotify`). Un item cuyo
    track no está cacheado localmente todavía (llegó por sync desde otro dispositivo) se
    omite — limitación conocida, documentada en el plan de la Fase 4."""
    conn = get_connection()
    items = conn.execute(
        "SELECT id, track_ref, position FROM playlist_items "
        "WHERE playlist_id = ? AND deleted_at IS NULL ORDER BY position",
        (playlist_id,),
    ).fetchall()
    rows: list[dict] = []
    for item in items:
        provider, _, external_id = item["track_ref"].partition(":")
        if provider == "drive":
            track_row = get_track_by_drive_id(external_id)
            if track_row is not None:
                rows.append(_track_object_row_from_drive(track_row, item["id"], item["position"]))
        elif provider == "spotify":
            spotify_row = get_spotify_track(external_id)
            if spotify_row is not None:
                rows.append(_track_object_row_from_spotify(spotify_row, item["id"], item["position"]))
    return rows


def _add_ref_to_playlist(playlist_id: int, track_ref: str) -> None:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos FROM playlist_items "
        "WHERE playlist_id = ?",
        (playlist_id,),
    ).fetchone()
    next_pos = row["next_pos"]
    conn.execute(
        "INSERT INTO playlist_items (playlist_id, track_ref, position) VALUES (?, ?, ?)",
        (playlist_id, track_ref, next_pos),
    )
    playlist_row = conn.execute(
        "SELECT uuid FROM playlists WHERE id = ?", (playlist_id,)
    ).fetchone()
    if playlist_row is not None:
        conn.execute(
            "UPDATE playlists SET updated_at = datetime('now') WHERE id = ?", (playlist_id,)
        )
        _enqueue_sync_op(
            conn,
            "playlist_items",
            {"playlist_uuid": playlist_row["uuid"], "track_ref": track_ref, "position": next_pos},
        )
    conn.commit()


def add_track_to_playlist(playlist_id: int, track_id: int) -> None:
    track_row = get_track(track_id)
    if track_row is not None:
        _add_ref_to_playlist(playlist_id, _track_ref(track_row))


def add_spotify_track_to_playlist(playlist_id: int, spotify_track_id: str) -> None:
    _add_ref_to_playlist(playlist_id, f"spotify:{spotify_track_id}")


def remove_playlist_item(playlist_item_id: int) -> None:
    """Soft-delete: igual que `delete_playlist`, para poder propagar la quita a
    los demás dispositivos (Fase 1). El índice único de posición es parcial
    (`WHERE deleted_at IS NULL`, ver schema.sql) así que esto no bloquea que un
    reorder posterior reutilice esa misma posición numérica."""
    conn = get_connection()
    row = conn.execute(
        "SELECT pi.playlist_id AS playlist_id, p.uuid AS playlist_uuid, pi.track_ref AS track_ref "
        "FROM playlist_items pi JOIN playlists p ON p.id = pi.playlist_id WHERE pi.id = ?",
        (playlist_item_id,),
    ).fetchone()
    conn.execute(
        "UPDATE playlist_items SET deleted_at = datetime('now'), updated_at = datetime('now') "
        "WHERE id = ?",
        (playlist_item_id,),
    )
    if row is not None:
        conn.execute(
            "UPDATE playlists SET updated_at = datetime('now') WHERE id = ?",
            (row["playlist_id"],),
        )
        _enqueue_sync_op(
            conn,
            "playlist_items",
            {
                "playlist_uuid": row["playlist_uuid"],
                "track_ref": row["track_ref"],
                "deleted": True,
            },
        )
    conn.commit()


def reorder_playlist_items(playlist_id: int, playlist_item_ids_in_order: list[int]) -> None:
    conn = get_connection()
    # Desplazar a posiciones negativas temporales para esquivar el UNIQUE(playlist_id, position).
    for offset, playlist_item_id in enumerate(playlist_item_ids_in_order):
        conn.execute(
            "UPDATE playlist_items SET position = ? WHERE id = ? AND playlist_id = ?",
            (-(offset + 1), playlist_item_id, playlist_id),
        )
    for position, playlist_item_id in enumerate(playlist_item_ids_in_order):
        conn.execute(
            "UPDATE playlist_items SET position = ?, updated_at = datetime('now') "
            "WHERE id = ? AND playlist_id = ?",
            (position, playlist_item_id, playlist_id),
        )
    playlist_row = conn.execute(
        "SELECT uuid FROM playlists WHERE id = ?", (playlist_id,)
    ).fetchone()
    if playlist_row is not None:
        conn.execute(
            "UPDATE playlists SET updated_at = datetime('now') WHERE id = ?", (playlist_id,)
        )
        rows = conn.execute(
            "SELECT position, track_ref FROM playlist_items "
            "WHERE playlist_id = ? AND deleted_at IS NULL",
            (playlist_id,),
        ).fetchall()
        for item in rows:
            _enqueue_sync_op(
                conn,
                "playlist_items",
                {
                    "playlist_uuid": playlist_row["uuid"],
                    "track_ref": item["track_ref"],
                    "position": item["position"],
                },
            )
    conn.commit()


# --- Spotify (cache local de metadata — Purrr no decodifica su audio) --------

def cache_spotify_track(
    spotify_id: str,
    title: str,
    artist: str | None,
    album: str | None,
    duration_seconds: float | None,
    art_url: str | None,
    art_path: str | None,
    uri: str,
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO spotify_tracks (id, title, artist, album, duration_seconds, art_url, art_path, uri)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, artist = excluded.artist, album = excluded.album,
            duration_seconds = excluded.duration_seconds, art_url = excluded.art_url,
            art_path = COALESCE(excluded.art_path, spotify_tracks.art_path)
        """,
        (spotify_id, title, artist, album, duration_seconds, art_url, art_path, uri),
    )
    conn.commit()


def get_spotify_track(spotify_id: str) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM spotify_tracks WHERE id = ?", (spotify_id,)
    ).fetchone()


# --- Ánimo (Fase 5 — solo tracks de Drive, ver mood/) ------------------------

def save_track_mood(
    track_id: int, happy: float, sad: float, relaxed: float, aggressive: float
) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO track_mood (track_id, happy, sad, relaxed, aggressive)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(track_id) DO UPDATE SET
            happy = excluded.happy, sad = excluded.sad, relaxed = excluded.relaxed,
            aggressive = excluded.aggressive, updated_at = datetime('now')
        """,
        (track_id, happy, sad, relaxed, aggressive),
    )
    track_row = get_track(track_id)
    if track_row is not None:
        _enqueue_sync_op(
            conn,
            "track_moods",
            {
                "track_ref": _track_ref(track_row),
                "happy": happy, "sad": sad, "relaxed": relaxed, "aggressive": aggressive,
            },
        )
    conn.commit()


def get_track_mood(track_id: int) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM track_mood WHERE track_id = ?", (track_id,)
    ).fetchone()


def list_tracks_needing_mood_analysis() -> list[sqlite3.Row]:
    """Tracks de Drive ya cacheados (hay archivo local para analizar) que todavía no
    tienen un vector de ánimo — candidatos para `mood.controller.analyze_library`."""
    return get_connection().execute(
        """
        SELECT t.* FROM tracks t
        LEFT JOIN track_mood tm ON tm.track_id = t.id
        WHERE t.cache_status = 'cached' AND t.local_path IS NOT NULL AND tm.track_id IS NULL
        ORDER BY t.artist, t.album, t.track_number
        """
    ).fetchall()


def list_track_moods() -> list[sqlite3.Row]:
    """Todos los vectores de ánimo ya calculados, con los datos de su track — para
    rankear candidatos en `mood.queue_builder.build_mood_queue`."""
    return get_connection().execute(
        """
        SELECT t.*, tm.happy, tm.sad, tm.relaxed, tm.aggressive
        FROM track_mood tm
        JOIN tracks t ON t.id = tm.track_id
        WHERE t.cache_status != 'missing'
        """
    ).fetchall()


# --- Cola de sync (cloud/sync_engine.py) --------------------------------

def list_pending_sync_ops(limit: int = 100) -> list[sqlite3.Row]:
    return get_connection().execute(
        "SELECT * FROM pending_sync_ops ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def delete_pending_sync_op(op_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM pending_sync_ops WHERE id = ?", (op_id,))
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
