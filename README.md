# Purrr 🐈

Reproductor de música para Fedora/GNOME que escanea carpetas de tu Google Drive,
lee los metadatos de tus archivos `.mp3`/`.flac`, arma una biblioteca local y te
deja crear playlists. También sintoniza radios en vivo (Rainwave, Radio Bío-Bío,
SmoothJazz.com/SmoothLounge.com y, con una cuenta Premium, los ~99 canales de
RadioTunes) desde la pantalla "Radios", controla Spotify Connect (Premium) para armar
playlists mixtas de Drive + Spotify, y arma colas de reproducción por ánimo
(contento/triste/relajado/agresivo) analizando el audio localmente.

Licenciado bajo [AGPL-3.0](LICENSE) — heredado de `essentia-tensorflow`, la
librería que usa el modo "Ánimo" para analizar canciones (ver esa sección más
abajo).

## Requisitos del sistema

Ya deberían estar instalados en Fedora Workstation, pero por si acaso:

```bash
sudo dnf install python3-gobject gtk4 libadwaita \
    gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-plugins-ugly-free
```

## Instalación

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
```

## Conectar Google Drive

El client ID de Google (tipo "Desktop app") ya viene incorporado en la app — no hace
falta crear ningún proyecto de Google Cloud propio. Basta con abrir Purrr → pantalla
"Fuentes" → **Conectar cuenta de Google** y aceptar el acceso de solo lectura a tu
Drive; se abre el navegador y vuelves autenticado solo.

La primera vez puede aparecer un aviso de "Google no verificó esta app" — es esperable
mientras el proyecto no pase la revisión de verificación de Google (pendiente), y no
afecta el acceso: hay que hacer clic en **Avanzado → Ir a Purrr (no seguro)** para
continuar.

## Sincronizar entre varios dispositivos (opcional)

Si usas Purrr en más de una computadora, puedes sincronizar tus playlists y álbumes
entre todas en tiempo real, y guardar tus credenciales (Drive, RadioTunes, Spotify)
en una bóveda centralizada para no tener que reconectarlas en cada equipo. El backend
(Supabase) ya viene incorporado en la app — no hay que crear ni configurar ningún
proyecto propio.

1. Abre Purrr → **Cuenta / Sync** en la barra lateral.
2. Crea tu cuenta (email + contraseña) o inicia sesión si ya la creaste en otro
   dispositivo.

En un equipo nuevo, con iniciar sesión alcanza: Drive queda conectado solo, sin
repetir el consentimiento de Google. Tu contraseña nunca viaja a Supabase en texto
plano ni se usa para cifrar nada ahí — se deriva localmente una clave de cifrado que
solo vive en tu dispositivo (ver `src/purrr/cloud/vault.py`). Si la olvidas y la
restableces por email, la bóveda vieja queda irrecuperable, igual que la contraseña
maestra de un gestor de contraseñas.

## Conectar Spotify (opcional)

Purrr controla Spotify Connect (necesitas **Spotify Premium**) — busca canciones,
las agrega a playlists mixtas junto con las de Drive, y le manda "reproducir" a un
dispositivo Spotify Connect que ya tengas activo (el celular, el cliente oficial en
otra computadora, etc.). Purrr nunca descarga ni decodifica el audio de Spotify.

1. Entra a [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
   y crea una app (gratis).
2. En **Settings** de esa app, agrega el Redirect URI
   `http://127.0.0.1:8888/callback` y guarda.
3. Copia el **Client ID** (no hace falta el Client Secret — el login usa PKCE, pensado
   justo para apps que no pueden guardar un secreto de forma segura).
4. Abre Purrr → **Spotify** en la barra lateral, pega el Client ID, y toca
   "Conectar con Spotify" — se abre tu navegador y vuelves autenticado solo.

Sin ningún dispositivo Spotify Connect activo en el momento de reproducir, Purrr
avisa y sigue con la siguiente canción de la cola — no hay forma de "despertar" un
dispositivo por control remoto, hay que abrir Spotify ahí primero.

## Escuchar radios en vivo

Desde **Radios** en la barra lateral: Rainwave, las 8 señales de Radio Bío-Bío y
SmoothJazz.com/SmoothLounge.com suenan directo, sin cuenta ni configuración — son
streams públicos.

RadioTunes es distinto: es parte de la red AudioAddict (la misma de DI.fm), y sin
una cuenta Premium el catálogo se ve pero ningún canal suena (probado con el stream
real sin key: devuelve `401 Authentication Required`). Para conectarla:

1. Entra a tu cuenta en [radiotunes.com](https://radiotunes.com) → **Player
   Settings → Hardware Player** y copia tu **Listen Key**.
2. Pégala en la sección "RadioTunes" de la pantalla Radios de Purrr.

Con la key guardada, los ~99 canales cargan solos (con buscador, son bastantes) y
quedan listos para reproducir.

## Reproducir por ánimo (opcional)

Desde **Ánimo** en la barra lateral, elige una o más canciones semilla y Purrr arma
una cola con las canciones de tu biblioteca (solo Drive — Spotify queda afuera, no
hay archivo local que analizar) más parecidas en ánimo, usando un clasificador
entrenado (no una regla hecha a mano) que estima cuánto de contenta, triste,
relajada o agresiva es cada canción.

La primera vez que se usa, Purrr baja ~20 MB de modelos a `~/.cache/purrr/models/`.
Elegir una semilla que nunca se analizó la analiza al instante (unos segundos);
también se puede tocar "Analizar biblioteca" para ir cubriendo todo de antemano en
segundo plano — en una biblioteca grande puede tardar horas, no bloquea nada mientras
tanto, y si se sincroniza entre varios dispositivos (ver arriba) ese análisis se
comparte: cada canción se analiza una sola vez entre todos los equipos, no en cada
uno.

## Ejecutar

```bash
.venv/bin/purrr
```

En el primer uso: conecta tu cuenta de Google desde la pantalla de "Fuentes",
luego agrega una carpeta de Drive (pegando su link o ID) y espera a que termine
la sincronización. Los archivos se descargan y cachean en `~/.cache/purrr/audio/`.

## Integrarlo al menú de GNOME (opcional)

```bash
cp io.github.christianlealreyes.Purrr.desktop ~/.local/share/applications/
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
cp data/icons/io.github.christianlealreyes.Purrr.svg ~/.local/share/icons/hicolor/scalable/apps/
# Si queda un icon-theme.cache viejo (de otra app) en ~/.local/share/icons/hicolor,
# GTK lo usa en vez de escanear la carpeta y el ícono nuevo queda invisible.
rm -f ~/.local/share/icons/hicolor/icon-theme.cache
```

## App Android

Alcance: Google Drive + playlists/álbumes sincronizados vía Supabase (mismo backend
que el escritorio), radios en vivo (Rainwave/Radio Bío-Bío/SmoothJazz.com/
RadioTunes), control remoto de Spotify Connect (playlists mixtas Drive+Spotify
incluidas) y modo por ánimo. A diferencia del escritorio, Android **no** analiza
audio para el modo por ánimo — solo sincroniza los vectores que ya calculó el
escritorio (essentia-tensorflow no tiene una conversión oficial a TensorFlow Lite
para los modelos que usa Purrr); una canción recién agregada tiene ánimo disponible
en el teléfono después de reproducirse al menos una vez en el escritorio.

Requisitos: JDK 17+, Android SDK (`compileSdk`/`targetSdk` 37, `minSdk` 26).

```bash
cd android
./gradlew assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

Antes de conectar Google Drive desde el teléfono hace falta un client ID nuevo en el
mismo proyecto de Google Cloud que ya se usa para el escritorio:

1. En [Google Cloud Console](https://console.cloud.google.com/) → *APIs & Services →
   Credentials* → *Create Credentials* → *OAuth client ID* → tipo **Android**.
2. Package name: `io.github.christianlealreyes.purrr`.
3. Huella SHA-1 del keystore de debug (para probar sin firmar la app todavía):
   ```bash
   keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android -keypass android | grep SHA1
   ```
4. Además, hace falta un client ID de tipo **Web application** (sin necesidad de
   configurar nada más en él) — es el que se pega en la pantalla "Fuentes" de la app
   como *Web client ID*: Credential Manager lo exige para el login de Google aunque
   la app en sí sea Android.

En la pantalla "Cuenta" de la app se inicia sesión con la misma cuenta Purrr que en
el escritorio — el backend Supabase es el mismo para ambas plataformas y ya viene
incorporado en la app, sin ningún dato que pegar a mano.

> **Nota:** al momento de este cambio, la pantalla "Cuenta" de la app Android
> todavía puede pedir Project URL/anon key como en la versión anterior del
> escritorio — ese flujo quedó desactualizado y conviene revisarlo para que también
> use el backend incorporado.

### Conectar Spotify

Igual que en el escritorio, Purrr Android nunca decodifica audio de Spotify — solo
lo controla de forma remota (Spotify Connect) y busca canciones vía la Web API.

1. Crea una app gratis en el
   [Dashboard de Spotify for Developers](https://developer.spotify.com/dashboard).
2. En su configuración, agrega como **Redirect URI**: `purrr://spotify-callback`.
3. Pega el **Client ID** de esa app en la pantalla "Spotify" de Purrr — no hace
   falta ningún Client Secret (el login es PKCE puro).
4. "Conectar con Spotify" abre el navegador para el login; hace falta Spotify
   Premium y algún dispositivo Connect activo (el celular con la app oficial de
   Spotify abierta, otra computadora, etc.) para poder reproducir.

### Conectar RadioTunes

Igual que en el escritorio: pega tu Listen Key (cuenta Premium AudioAddict → Player
Settings → Hardware Player) en la pantalla "Radios" — sin ella se puede ver el
catálogo pero no reproducir ningún canal.

## Estructura del proyecto

```
src/purrr/
├── auth/        # OAuth2 con Google (flujo "installed app")
├── drive/       # cliente y escáner recursivo de Google Drive
├── cache/       # descarga y caché local de audio
├── metadata/    # extracción de tags (mutagen)
├── db/          # esquema y acceso a SQLite
├── player/      # motor de reproducción (GStreamer), cola, estaciones de radio,
│                # y control remoto de Spotify Connect
├── spotify/     # cliente de la Web API de Spotify (búsqueda, caché de metadata)
├── sync/        # orquestación de escaneo/descarga en segundo plano
├── mood/        # análisis de ánimo (essentia-tensorflow) y armado de cola por ánimo
├── cloud/       # sync en tiempo real con Supabase + bóveda de credenciales
└── ui/          # ventana y widgets GTK4/libadwaita
```

## Datos locales

- Base de datos: `~/.local/share/purrr/purrr.db`
- Caché de audio: `~/.cache/purrr/audio/`
- Modelos de análisis de ánimo: `~/.cache/purrr/models/` (~20 MB, se bajan solos la
  primera vez que hace falta)
- Credenciales: `~/.config/purrr/client_secret.json`, `~/.config/purrr/token.json`,
  `~/.config/purrr/spotify_client.json`, `~/.config/purrr/spotify_token.json`,
  `~/.config/purrr/radiotunes_key.json`
