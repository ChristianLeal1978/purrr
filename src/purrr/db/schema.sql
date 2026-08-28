PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
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
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    added_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_playlist_tracks_unique_pos
    ON playlist_tracks(playlist_id, position);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);

CREATE TABLE IF NOT EXISTS albums (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    artist      TEXT,
    art_path    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS album_tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id    INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(album_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_album_tracks_album ON album_tracks(album_id);
CREATE INDEX IF NOT EXISTS idx_album_tracks_track ON album_tracks(track_id);

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
