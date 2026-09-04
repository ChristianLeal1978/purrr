PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    provider          TEXT NOT NULL DEFAULT 'drive',
    drive_folder_id   TEXT NOT NULL UNIQUE,
    display_name      TEXT NOT NULL,
    added_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_scanned_at   TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_file_id       TEXT NOT NULL UNIQUE,
    source_id           INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    drive_parent_id     TEXT,
    drive_folder_path   TEXT,
    file_name           TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    drive_md5           TEXT,
    drive_modified_time TEXT,
    drive_size_bytes    INTEGER,
    local_path          TEXT,
    cache_status        TEXT NOT NULL DEFAULT 'pending'
                         CHECK (cache_status IN ('pending','downloading','cached','error','missing')),
    cache_error          TEXT,
    title                TEXT,
    artist               TEXT,
    album                TEXT,
    album_artist         TEXT,
    track_number         INTEGER,
    disc_number          INTEGER,
    year                 INTEGER,
    genre                TEXT,
    duration_seconds     REAL,
    art_path             TEXT,
    folder_cover_file_id TEXT,
    folder_cover_ext     TEXT,
    added_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_source       ON tracks(source_id);
CREATE INDEX IF NOT EXISTS idx_tracks_artist       ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album        ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_tracks_cache_status ON tracks(cache_status);

CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at  TEXT
);

-- Cache local de metadata de tracks de Spotify (buscados/agregados a una playlist
-- mixta) — Purrr nunca descarga ni decodifica el audio de Spotify (solo control
-- remoto vía Spotify Connect, ver player/spotify_connect.py), así que acá no hay
-- local_path/cache_status: solo lo necesario para mostrar la fila y mandar el URI.
CREATE TABLE IF NOT EXISTS spotify_tracks (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    artist            TEXT,
    album             TEXT,
    duration_seconds  REAL,
    art_url           TEXT,
    art_path          TEXT,
    uri               TEXT NOT NULL,
    cached_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Un item de playlist es una referencia estable ('drive:<id>' | 'spotify:<id>'), no
-- un FK entero a una sola tabla — misma forma que cloud/schema.sql para que local y
-- remoto queden simétricos, y para que una playlist pueda mezclar tracks de Drive y
-- de Spotify sin un JOIN polimórfico incómodo.
CREATE TABLE IF NOT EXISTS playlist_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_ref   TEXT NOT NULL,
    position    INTEGER NOT NULL,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at  TEXT
);

-- Índices parciales (solo filas activas): una fila soft-deleted no debe bloquear
-- que otra fila activa ocupe su misma posición numérica tras un reorder, ni su
-- mismo track_ref si el usuario vuelve a agregar la misma canción.
CREATE UNIQUE INDEX IF NOT EXISTS idx_playlist_items_unique_pos
    ON playlist_items(playlist_id, position) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_playlist_items_unique_ref
    ON playlist_items(playlist_id, track_ref) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist ON playlist_items(playlist_id);

CREATE TABLE IF NOT EXISTS albums (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    artist      TEXT,
    art_path    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS album_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id    INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at  TEXT,
    UNIQUE(album_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_album_tracks_album ON album_tracks(album_id);
CREATE INDEX IF NOT EXISTS idx_album_tracks_track ON album_tracks(track_id);

-- Vector de ánimo de un track de Drive (Fase 5), calculado una vez localmente con
-- essentia-tensorflow (ver mood/analyzer.py) y sincronizado entre dispositivos (no
-- hace falta `deleted_at`: un vector no se borra, se recalcula si hiciera falta).
CREATE TABLE IF NOT EXISTS track_mood (
    track_id    INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    happy       REAL NOT NULL,
    sad         REAL NOT NULL,
    relaxed     REAL NOT NULL,
    aggressive  REAL NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Cola de salida hacia Supabase (cloud/sync_engine.py): cada mutación de
-- playlist/álbum encola aquí, en la misma transacción, el payload a empujar.
-- Un hilo "flusher" la drena contra Supabase y borra las filas ya enviadas —
-- así una mutación hecha offline no se pierde.
CREATE TABLE IF NOT EXISTS pending_sync_ops (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
