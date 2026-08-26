# Purrr 🐈

Reproductor de música para Fedora/GNOME que escanea carpetas de tu Google Drive,
lee los metadatos de tus archivos `.mp3`/`.flac`, arma una biblioteca local y te
deja crear playlists.

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

## Configurar el acceso a Google Drive

Purrr usa tu propio proyecto de Google Cloud (gratis) para conectarse a tu Drive.
No hay credenciales compartidas embebidas en la app — cada usuario crea las suyas:

1. Entra a la [Google Cloud Console](https://console.cloud.google.com/) y crea un
   proyecto nuevo (o reutiliza uno).
2. Habilita la **Google Drive API** para ese proyecto.
3. Ve a **APIs & Services → OAuth consent screen**:
   - Tipo de usuario: **External**.
   - Nombre de la app: `Purrr`.
   - Agrega el scope `https://www.googleapis.com/auth/drive.readonly`.
   - Publica la app en estado **"In production"** (sin enviarla a verificación de
     Google). La primera vez que conectes tu cuenta verás un aviso de "app no
     verificada" — hay que hacer clic en **Avanzado → Ir a Purrr (no seguro)**.
     Esto es normal para una app personal de un solo usuario; a cambio, el token
     de acceso no expira cada 7 días como pasaría en modo "Testing".
4. Ve a **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Tipo de aplicación: **Desktop app**.
   - Descarga el JSON generado.
5. Guarda ese archivo como `~/.config/purrr/client_secret.json`.

Nunca compartas ni subas a git ese archivo (ya está en `.gitignore`).

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
gtk4-update-icon-cache ~/.local/share/icons/hicolor 2>/dev/null || true
```

## Estructura del proyecto

```
src/purrr/
├── auth/        # OAuth2 con Google (flujo "installed app")
├── drive/       # cliente y escáner recursivo de Google Drive
├── cache/       # descarga y caché local de audio
├── metadata/    # extracción de tags (mutagen)
├── db/          # esquema y acceso a SQLite
├── player/      # motor de reproducción (GStreamer) y cola de reproducción
├── sync/        # orquestación de escaneo/descarga en segundo plano
└── ui/          # ventana y widgets GTK4/libadwaita
```

## Datos locales

- Base de datos: `~/.local/share/purrr/purrr.db`
- Caché de audio: `~/.cache/purrr/audio/`
- Credenciales: `~/.config/purrr/client_secret.json`, `~/.config/purrr/token.json`
