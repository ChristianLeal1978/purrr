-- Purrr — schema remoto Supabase (Fase 1 del plan de sync).
--
-- Este es el proyecto Supabase compartido que usa Purrr (URL + anon key incrustados
-- en `purrr/config.py`, ver ese archivo) — un único backend para todos los usuarios,
-- no uno por persona. Correr esto una vez en el SQL editor de ESE proyecto
-- (https://supabase.com/dashboard/project/_/sql/new) al aprovisionarlo.
--
-- Requiere Supabase Auth (email + contraseña) habilitado, que es el default de un
-- proyecto nuevo. Todas las tablas usan Row Level Security con `auth.uid()`, así que
-- el anon key por sí solo no alcanza para leer ni escribir nada: cada usuario solo ve
-- sus propias filas, autenticado con su propia cuenta Purrr.

create extension if not exists "pgcrypto";

-- --- Playlists -------------------------------------------------------------

create table if not exists playlists (
    uuid        uuid primary key,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    name        text not null,
    updated_at  timestamptz not null default now(),
    deleted_at  timestamptz
);

alter table playlists enable row level security;

create policy "playlists_owner_all" on playlists
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table if not exists playlist_items (
    playlist_uuid uuid not null references playlists(uuid) on delete cascade,
    user_id       uuid not null references auth.users(id) on delete cascade default auth.uid(),
    track_ref     text not null,        -- ej. 'drive:abc123' o 'spotify:<id>' (Fase 4)
    position      integer not null,
    updated_at    timestamptz not null default now(),
    deleted_at    timestamptz,
    primary key (playlist_uuid, track_ref)
);

alter table playlist_items enable row level security;

create policy "playlist_items_owner_all" on playlist_items
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- --- Álbumes -----------------------------------------------------------

create table if not exists albums (
    uuid              uuid primary key,
    user_id           uuid not null references auth.users(id) on delete cascade default auth.uid(),
    name              text not null,
    artist            text,
    art_storage_path  text,  -- Fase 2: ruta dentro del bucket 'covers', ver más abajo
    updated_at        timestamptz not null default now(),
    deleted_at        timestamptz
);

-- Por si esta tabla ya existía de una Fase 1 previa (ALTER TABLE es idempotente).
alter table albums add column if not exists art_storage_path text;

alter table albums enable row level security;

create policy "albums_owner_all" on albums
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table if not exists album_items (
    album_uuid  uuid not null references albums(uuid) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    track_ref   text not null,
    updated_at  timestamptz not null default now(),
    deleted_at  timestamptz,
    primary key (album_uuid, track_ref)
);

alter table album_items enable row level security;

create policy "album_items_owner_all" on album_items
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- --- Bóveda de credenciales (Fase 1.5) -----------------------------------
-- `ciphertext` es un token Fernet (AES + HMAC autenticado) generado en el cliente
-- con `cloud/vault.py` — Supabase nunca ve la credencial en texto plano, ni la
-- contraseña con la que se cifró. Es texto (no bytea) porque un token Fernet ya es
-- base64 url-safe, lo que evita el encoding de bytea sobre la API REST de Postgrest.

create table if not exists credential_vault (
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    provider    text not null,        -- 'google_drive' | 'radiotunes' | 'smoothjazz' | 'spotify'
    ciphertext  text not null,
    updated_at  timestamptz not null default now(),
    primary key (user_id, provider)
);

alter table credential_vault enable row level security;

create policy "credential_vault_owner_all" on credential_vault
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- --- Ánimo (Fase 5) -----------------------------------------------------
-- Vector de ánimo de un track (calculado una sola vez, en cualquier dispositivo, con
-- essentia-tensorflow — ver mood/analyzer.py). Sin deleted_at: un vector no se
-- borra, se recalcula si hiciera falta.

create table if not exists track_moods (
    track_ref   text not null,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    happy       real not null,
    sad         real not null,
    relaxed     real not null,
    aggressive  real not null,
    updated_at  timestamptz not null default now(),
    primary key (track_ref, user_id)
);

alter table track_moods enable row level security;

create policy "track_moods_owner_all" on track_moods
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- --- Estadísticas: historial de reproducciones ----------------------------
-- Un evento por reproducción (no un contador acumulado): así dos dispositivos que
-- suman plays offline nunca pisan el contador del otro al sincronizar — cada
-- reproducción es su propia fila, "cuántas veces" es un COUNT(*) al leer (ver
-- db/database.py:list_most_played_tracks/list_most_played_artists). `uuid` lo genera
-- el cliente al registrar la reproducción, así el push es un upsert idempotente que
-- puede reintentarse sin duplicar el evento.

create table if not exists track_plays (
    uuid        uuid primary key,
    user_id     uuid not null references auth.users(id) on delete cascade default auth.uid(),
    track_ref   text not null,
    played_at   timestamptz not null default now()
);

alter table track_plays enable row level security;

create policy "track_plays_owner_all" on track_plays
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- --- Carátulas compartidas (Fase 2) ---------------------------------------
-- Bucket privado para las carátulas de álbumes armados a mano (búsqueda iTunes o
-- subida manual, ver cloud/sync_engine.py:_push_album/_apply_album) — las
-- carátulas embebidas o de carpeta de Drive NO pasan por acá porque cualquier
-- dispositivo las deriva solo de su propio escaneo, no hace falta compartirlas.
-- Privado (no público): se lee con el cliente ya logueado
-- (storage.from_("covers").download(...)), igual que el resto del proyecto no usa
-- URLs públicas sueltas.

insert into storage.buckets (id, name, public) values ('covers', 'covers', false)
    on conflict (id) do nothing;

create policy "covers_authenticated_all" on storage.objects
    for all using (bucket_id = 'covers' and auth.role() = 'authenticated')
    with check (bucket_id = 'covers' and auth.role() = 'authenticated');

-- --- Foto de perfil (opcional, Fase 1.5) ----------------------------------
-- Bucket privado para la foto que el usuario puede elegir al crear la cuenta
-- (cloud/client.py:upload_avatar/download_avatar). Sin foto, la UI usa las
-- iniciales del nombre (Adw.Avatar en ui/cloud_settings.py) — nunca se bloquea
-- la creación de cuenta por esto.
--
-- A diferencia de 'covers' (compartido entre todos los autenticados a propósito:
-- carátulas de álbum no son datos privados), acá cada archivo se llama
-- "<uuid-del-usuario>.<ext>" (ver upload_avatar) y la política solo deja tocar el
-- que coincide con el propio auth.uid() — nadie ve ni pisa la foto de otro.

insert into storage.buckets (id, name, public) values ('avatars', 'avatars', false)
    on conflict (id) do nothing;

create policy "avatars_owner_all" on storage.objects
    for all using (bucket_id = 'avatars' and auth.uid()::text = split_part(name, '.', 1))
    with check (bucket_id = 'avatars' and auth.uid()::text = split_part(name, '.', 1));

-- --- Realtime ------------------------------------------------------------
-- Habilita que INSERT/UPDATE/DELETE en estas tablas se transmitan por WebSocket a
-- los clientes suscriptos (cloud/sync_engine.py) — no incluye credential_vault, que
-- se trae solo al loguearse (pull), no en tiempo real.

alter publication supabase_realtime add table playlists;
alter publication supabase_realtime add table playlist_items;
alter publication supabase_realtime add table albums;
alter publication supabase_realtime add table album_items;
alter publication supabase_realtime add table track_moods;
alter publication supabase_realtime add table track_plays;
