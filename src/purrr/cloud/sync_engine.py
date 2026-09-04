"""Motor de sync en tiempo real con Supabase (Fase 1.3 del plan).

**Push**: cada mutación local de playlists/álbumes ya quedó encolada en
`pending_sync_ops` (ver `db/database.py`, `_enqueue_sync_op`) en el mismo commit que
la escribió. Un hilo "flusher" la drena contra Supabase con reintento simple: si falla
(sin red, por ejemplo), deja las filas en la cola y reintenta en el próximo ciclo.

**Pull**: el cliente realtime de `supabase-py` (paquete `realtime`) solo tiene
implementación *async* — la variante "sync" existe pero cada método lanza
`NotImplementedError` (confirmado leyendo `realtime/_sync/client.py`). Por eso este
motor corre un hilo dedicado con su propio event loop de asyncio, suscripto a los
cambios de Postgres en las 4 tablas sincronizadas; el resto de la app sigue sin usar
asyncio, igual que hoy. Cada evento recibido se aplica a la base local comparando
`updated_at` (last-write-wins) y **sin** volver a encolar un push — si no, un cambio
recibido por sync rebotaría de vuelta a Supabase en un eco infinito.

Todo el trabajo de red corre en hilos de fondo; el cruce hacia el hilo principal de
GTK es siempre vía `GLib.idle_add(...)`, igual que en `sync/controller.py`.
"""

import asyncio
import json
import mimetypes
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from purrr.cache import manager as cache_manager
from purrr.cloud import client as cloud_client
from purrr.cloud import identity
from purrr.config import SUPABASE_ANON_KEY, SUPABASE_URL
from purrr.db import database

_SYNCED_TABLES = ("playlists", "playlist_items", "albums", "album_items", "track_moods")
_FLUSH_INTERVAL_SECONDS = 3
_RECONNECT_DELAY_SECONDS = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_newer_or_equal(incoming: str | None, local: str | None) -> bool:
    """True si `incoming` no es más viejo que `local` — para last-write-wins.
    Sin dato local todavía, o sin timestamp entrante, gana igual (se aplica)."""
    incoming_ts, local_ts = _parse_ts(incoming), _parse_ts(local)
    if local_ts is None or incoming_ts is None:
        return True
    return incoming_ts >= local_ts


class CloudSyncEngine(GObject.Object):
    """Un solo `CloudSyncEngine` vive durante toda la sesión de la app (ver
    `ui/window.py`). `start()`/`stop()` son idempotentes y no hacen nada si Supabase
    no está configurado o no hay sesión — así se puede llamar siempre al iniciar,
    sin chequear antes."""

    __gsignals__ = {
        "playlists-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "albums-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "sync-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._flusher_thread: threading.Thread | None = None
        self._realtime_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # --- ciclo de vida -----------------------------------------------------

    def start(self) -> None:
        if not cloud_client.is_logged_in_locally():
            return
        self._stop_event.clear()
        if self._flusher_thread is None or not self._flusher_thread.is_alive():
            self._flusher_thread = threading.Thread(target=self._flush_loop, daemon=True)
            self._flusher_thread.start()
        if self._realtime_thread is None or not self._realtime_thread.is_alive():
            self._realtime_thread = threading.Thread(target=self._realtime_loop, daemon=True)
            self._realtime_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    # --- push: flusher de pending_sync_ops ----------------------------------

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._flush_once()
            except Exception as exc:  # sin red, Supabase caído, etc. — reintenta solo
                GLib.idle_add(self.emit, "sync-error", f"push: {exc}")
            self._stop_event.wait(_FLUSH_INTERVAL_SECONDS)

    def _flush_once(self) -> None:
        ops = database.list_pending_sync_ops()
        if not ops:
            return
        client = cloud_client.get_client()
        for op in ops:
            payload = json.loads(op["payload_json"])
            _PUSH_HANDLERS[op["table_name"]](client, payload)
            # Si el push de arriba lanza, esta fila (y las siguientes del batch) se
            # quedan en la cola para el próximo ciclo — no se llega a este delete.
            database.delete_pending_sync_op(op["id"])

    # --- pull: suscripción realtime -----------------------------------------

    def _realtime_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                asyncio.run(self._realtime_session())
            except Exception as exc:
                GLib.idle_add(self.emit, "sync-error", f"realtime: {exc}")
            if not self._stop_event.is_set():
                time.sleep(_RECONNECT_DELAY_SECONDS)

    async def _realtime_session(self) -> None:
        from supabase import acreate_client  # import perezoso: solo hace falta acá

        session = cloud_client.get_client().auth.get_session()
        if session is None:
            return
        async_client = await acreate_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        # Propaga el JWT de la sesión al cliente async para que Realtime aplique las
        # mismas políticas RLS que ya protegen la API REST (ver cloud/schema.sql).
        await async_client.auth.set_session(session.access_token, session.refresh_token)

        channel = async_client.channel("purrr-sync")
        for table in _SYNCED_TABLES:
            channel.on_postgres_changes(
                "*",
                schema="public",
                table=table,
                callback=lambda payload, table=table: self._on_remote_event(table, payload),
            )
        await channel.subscribe()
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(1)
        finally:
            await async_client.realtime.close()

    def _on_remote_event(self, table: str, payload: dict) -> None:
        data = payload.get("data", {})
        record = data.get("record") or data.get("old_record") or {}
        if not record:
            return
        GLib.idle_add(self._apply_remote_event, table, record)

    def _apply_remote_event(self, table: str, record: dict) -> bool:
        conn = database.get_connection()
        # El tercer parámetro (`self`) solo lo usa `_apply_album` (Fase 2), para
        # poder re-emitir "albums-changed" cuando termine de bajar una carátula
        # compartida en segundo plano — el resto de los handlers lo ignoran.
        changed_signal = _APPLY_HANDLERS[table](conn, record, self)
        if changed_signal:
            self.emit(changed_signal)
        return GLib.SOURCE_REMOVE


# --- Push: un handler por tabla, arma el payload remoto y lo manda -----------


def _push_playlist(client, payload: dict) -> None:
    if payload.get("deleted"):
        client.table("playlists").update({"deleted_at": _now_iso()}).eq(
            "uuid", payload["uuid"]
        ).execute()
        return
    client.table("playlists").upsert(
        {
            "uuid": payload["uuid"],
            "name": payload["name"],
            "updated_at": _now_iso(),
            "deleted_at": None,
        },
        on_conflict="uuid",
    ).execute()


def _push_playlist_item(client, payload: dict) -> None:
    if payload.get("deleted"):
        client.table("playlist_items").update({"deleted_at": _now_iso()}).eq(
            "playlist_uuid", payload["playlist_uuid"]
        ).eq("track_ref", payload["track_ref"]).execute()
        return
    client.table("playlist_items").upsert(
        {
            "playlist_uuid": payload["playlist_uuid"],
            "track_ref": payload["track_ref"],
            "position": payload["position"],
            "updated_at": _now_iso(),
            "deleted_at": None,
        },
        on_conflict="playlist_uuid,track_ref",
    ).execute()


_COVERS_BUCKET = "covers"


def _push_album(client, payload: dict) -> None:
    row = {
        "uuid": payload["uuid"],
        "name": payload["name"],
        "artist": payload.get("artist"),
        "updated_at": _now_iso(),
    }
    art_local_path = payload.get("art_local_path")
    if art_local_path and Path(art_local_path).exists():
        # Sin "art_local_path" en el payload (crear/renombrar un álbum sin tocar la
        # carátula), esta clave no va en el upsert — Postgrest solo pisa las
        # columnas presentes en el body, así que una carátula ya subida antes no
        # se pierde por un rename posterior.
        row["art_storage_path"] = _upload_album_art(client, payload["uuid"], art_local_path)
    client.table("albums").upsert(row, on_conflict="uuid").execute()


def _upload_album_art(client, album_uuid: str, local_path: str) -> str:
    path = Path(local_path)
    ext = path.suffix or ".jpg"
    storage_path = f"{album_uuid}{ext}"
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    client.storage.from_(_COVERS_BUCKET).upload(
        storage_path, path.read_bytes(), {"content-type": content_type, "upsert": "true"}
    )
    return storage_path


def _push_album_item(client, payload: dict) -> None:
    client.table("album_items").upsert(
        {
            "album_uuid": payload["album_uuid"],
            "track_ref": payload["track_ref"],
            "updated_at": _now_iso(),
            "deleted_at": None,
        },
        on_conflict="album_uuid,track_ref",
    ).execute()


def _push_track_mood(client, payload: dict) -> None:
    client.table("track_moods").upsert(
        {
            "track_ref": payload["track_ref"],
            "happy": payload["happy"],
            "sad": payload["sad"],
            "relaxed": payload["relaxed"],
            "aggressive": payload["aggressive"],
            "updated_at": _now_iso(),
        },
        on_conflict="track_ref,user_id",
    ).execute()


_PUSH_HANDLERS = {
    "playlists": _push_playlist,
    "playlist_items": _push_playlist_item,
    "albums": _push_album,
    "album_items": _push_album_item,
    "track_moods": _push_track_mood,
}


# --- Pull: un handler por tabla, aplica el registro remoto a SQLite local ----
# Nunca llaman a `_enqueue_sync_op` (evitan el eco push→pull→push) y respetan
# last-write-wins comparando `updated_at` antes de pisar una fila local.


def _apply_playlist(conn, record: dict, engine) -> str | None:
    playlist_uuid = record.get("uuid")
    if not playlist_uuid:
        return None
    local = conn.execute(
        "SELECT updated_at FROM playlists WHERE uuid = ?", (playlist_uuid,)
    ).fetchone()
    incoming_ts = record.get("updated_at") or record.get("deleted_at")
    if local is not None and not _is_newer_or_equal(incoming_ts, local["updated_at"]):
        return None
    if local is None:
        conn.execute(
            "INSERT INTO playlists (uuid, name, updated_at, deleted_at) VALUES (?, ?, ?, ?)",
            (playlist_uuid, record.get("name", ""), incoming_ts, record.get("deleted_at")),
        )
    else:
        conn.execute(
            "UPDATE playlists SET name = ?, updated_at = ?, deleted_at = ? WHERE uuid = ?",
            (record.get("name", ""), incoming_ts, record.get("deleted_at"), playlist_uuid),
        )
    conn.commit()
    return "playlists-changed"


def _apply_playlist_item(conn, record: dict, engine) -> str | None:
    """`track_ref` ya es la identidad de almacenamiento local (Fase 4: `playlist_items`,
    misma forma que este mismo registro remoto) — a diferencia de la Fase 1 original,
    acá no hace falta resolver Drive/Spotify para decidir si guardar el item; eso pasa
    recién al listar (`database.list_playlist_tracks`). El item siempre se guarda, solo
    puede no mostrarse todavía si este dispositivo no tiene ese track cacheado."""
    playlist_uuid, track_ref = record.get("playlist_uuid"), record.get("track_ref")
    if not playlist_uuid or not track_ref:
        return None
    playlist = conn.execute(
        "SELECT id FROM playlists WHERE uuid = ?", (playlist_uuid,)
    ).fetchone()
    if playlist is None:
        # La playlist todavía no llegó por sync a este dispositivo — se resuelve solo
        # cuando llegue (o en un resync completo, fuera de alcance de esta fase).
        return None
    incoming_ts = record.get("updated_at") or record.get("deleted_at")
    local = conn.execute(
        "SELECT updated_at FROM playlist_items WHERE playlist_id = ? AND track_ref = ?",
        (playlist["id"], track_ref),
    ).fetchone()
    if local is not None and not _is_newer_or_equal(incoming_ts, local["updated_at"]):
        return None
    if record.get("deleted_at"):
        conn.execute(
            "UPDATE playlist_items SET deleted_at = ?, updated_at = ? "
            "WHERE playlist_id = ? AND track_ref = ?",
            (record["deleted_at"], incoming_ts, playlist["id"], track_ref),
        )
    elif local is None:
        conn.execute(
            "INSERT INTO playlist_items (playlist_id, track_ref, position, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (playlist["id"], track_ref, record.get("position", 0), incoming_ts),
        )
    else:
        conn.execute(
            "UPDATE playlist_items SET position = ?, updated_at = ?, deleted_at = NULL "
            "WHERE playlist_id = ? AND track_ref = ?",
            (record.get("position", 0), incoming_ts, playlist["id"], track_ref),
        )
    conn.commit()
    return "playlists-changed"


def _apply_album(conn, record: dict, engine) -> str | None:
    album_uuid = record.get("uuid")
    if not album_uuid:
        return None
    local = conn.execute(
        "SELECT updated_at, art_path FROM albums WHERE uuid = ?", (album_uuid,)
    ).fetchone()
    incoming_ts = record.get("updated_at") or record.get("deleted_at")
    if local is not None and not _is_newer_or_equal(incoming_ts, local["updated_at"]):
        return None
    if local is None:
        conn.execute(
            "INSERT INTO albums (uuid, name, artist, updated_at, deleted_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                album_uuid,
                record.get("name", ""),
                record.get("artist"),
                incoming_ts,
                record.get("deleted_at"),
            ),
        )
    else:
        conn.execute(
            "UPDATE albums SET name = ?, artist = ?, updated_at = ?, deleted_at = ? "
            "WHERE uuid = ?",
            (
                record.get("name", ""),
                record.get("artist"),
                incoming_ts,
                record.get("deleted_at"),
                album_uuid,
            ),
        )
    conn.commit()

    # Fase 2: si el álbum ya tiene una carátula local (de cualquier origen) no se
    # vuelve a bajar aunque la remota haya cambiado — simplificación aceptada, ver
    # el plan. Cubre el caso principal (este dispositivo todavía no tiene ninguna)
    # sin la complejidad de detectar una carátula distinta más adelante.
    storage_path = record.get("art_storage_path")
    already_has_art = local is not None and local["art_path"]
    if storage_path and not already_has_art:
        album_row = conn.execute("SELECT id FROM albums WHERE uuid = ?", (album_uuid,)).fetchone()
        if album_row is not None:
            threading.Thread(
                target=_download_shared_album_art,
                args=(album_row["id"], storage_path, engine),
                daemon=True,
            ).start()
    return "albums-changed"


def _download_shared_album_art(album_id: int, storage_path: str, engine) -> None:
    """Corre en un hilo aparte — es red, y `_apply_remote_event` (quien llama a
    `_apply_album`) corre en el hilo principal de GTK."""
    try:
        data = cloud_client.get_client().storage.from_(_COVERS_BUCKET).download(storage_path)
    except Exception:
        return  # sin conexión o el archivo ya no está — no debe romper el resto del sync
    ext = Path(storage_path).suffix or ".jpg"
    path = cache_manager.save_album_art_bytes(data, album_id, ext)

    def apply_locally() -> bool:
        # SQL directo, no `database.update_album_art` — esa función encola un push
        # (Fase 2.2) y volver a subir lo que se acaba de bajar sería un eco.
        conn = database.get_connection()
        conn.execute("UPDATE albums SET art_path = ? WHERE id = ?", (str(path), album_id))
        conn.commit()
        engine.emit("albums-changed")
        return GLib.SOURCE_REMOVE

    GLib.idle_add(apply_locally)


def _apply_album_item(conn, record: dict, engine) -> str | None:
    album_uuid, track_ref = record.get("album_uuid"), record.get("track_ref")
    if not album_uuid or not track_ref:
        return None
    album = conn.execute("SELECT id FROM albums WHERE uuid = ?", (album_uuid,)).fetchone()
    if album is None:
        return None
    track_id = identity.resolve_local_track_id(track_ref)
    if track_id is None:
        return None
    incoming_ts = record.get("updated_at") or record.get("deleted_at")
    existing = conn.execute(
        "SELECT id, updated_at FROM album_tracks WHERE album_id = ? AND track_id = ?",
        (album["id"], track_id),
    ).fetchone()
    if existing is not None and not _is_newer_or_equal(incoming_ts, existing["updated_at"]):
        return None
    if record.get("deleted_at"):
        if existing is not None:
            conn.execute(
                "UPDATE album_tracks SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (record["deleted_at"], incoming_ts, existing["id"]),
            )
    elif existing is None:
        conn.execute(
            "INSERT INTO album_tracks (album_id, track_id, updated_at) VALUES (?, ?, ?)",
            (album["id"], track_id, incoming_ts),
        )
    else:
        conn.execute(
            "UPDATE album_tracks SET deleted_at = NULL, updated_at = ? WHERE id = ?",
            (incoming_ts, existing["id"]),
        )
    conn.commit()
    return "albums-changed"


def _apply_track_mood(conn, record: dict, engine) -> str | None:
    """A diferencia de playlists/álbumes, nada en la UI necesita refrescarse en vivo
    por esto todavía — por eso no emite señal (`None`), solo aplica el guardado."""
    track_ref = record.get("track_ref")
    if not track_ref:
        return None
    track_id = identity.resolve_local_track_id(track_ref)
    if track_id is None:
        # Este dispositivo todavía no escaneó ese archivo de Drive — se resuelve
        # solo cuando lo escanee (mismo caso conocido que el resto de la sync).
        return None
    incoming_ts = record.get("updated_at")
    existing = conn.execute(
        "SELECT updated_at FROM track_mood WHERE track_id = ?", (track_id,)
    ).fetchone()
    if existing is not None and not _is_newer_or_equal(incoming_ts, existing["updated_at"]):
        return None
    conn.execute(
        """
        INSERT INTO track_mood (track_id, happy, sad, relaxed, aggressive, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(track_id) DO UPDATE SET
            happy = excluded.happy, sad = excluded.sad, relaxed = excluded.relaxed,
            aggressive = excluded.aggressive, updated_at = excluded.updated_at
        """,
        (
            track_id, record.get("happy", 0.0), record.get("sad", 0.0),
            record.get("relaxed", 0.0), record.get("aggressive", 0.0), incoming_ts,
        ),
    )
    conn.commit()
    return None


_APPLY_HANDLERS = {
    "playlists": _apply_playlist,
    "playlist_items": _apply_playlist_item,
    "albums": _apply_album,
    "album_items": _apply_album_item,
    "track_moods": _apply_track_mood,
}
