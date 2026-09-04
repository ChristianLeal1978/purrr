"""Bóveda de credenciales centralizada (Fase 1.5 del plan).

Objetivo: el token de Drive, el Listen Key de RadioTunes y (Fase 4) el token de
Spotify se guardan una sola vez, en cualquier dispositivo, y cualquier otro equipo
los recibe solo con iniciar sesión — sin repetir ningún flujo de autorización.

Cifrado "zero-knowledge", igual que un gestor de contraseñas: la misma contraseña de
la cuenta Purrr se pasa localmente por una KDF (`scrypt`) para derivar una clave
simétrica que nunca sale del dispositivo ni viaja a Supabase — solo se sube el blob ya
cifrado (`credential_vault.ciphertext`, columna `text`: un token Fernet ya es texto
base64 url-safe, así que no hace falta lidiar con `bytea` en la API REST de Postgrest).

La sal de la KDF es el email de la cuenta (normalizado), no un valor aleatorio
guardado aparte: así no hace falta sincronizar ni recordar nada además de la
contraseña, a costa de no ser tan fuerte como una sal aleatoria — aceptable para una
bóveda personal de pocos dispositivos, no para un vault multiusuario serio.

Limitación conocida (documentar en la UI de login): resetear la contraseña de la
cuenta Purrr deriva una clave distinta y deja la bóveda vieja irrecuperable, igual que
perder la contraseña maestra de un gestor de contraseñas.
"""

import base64
import hashlib
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from purrr.config import RADIOTUNES_CONFIG_PATH, SPOTIFY_TOKEN_PATH, TOKEN_PATH

# Dónde escribir cada credencial ya descifrada, para que el módulo dueño (auth/,
# etc.) la encuentre exactamente donde ya la busca hoy — sin enterarse de que llegó
# por sync en vez de por configuración manual.
_LOCAL_TARGETS = {
    "google_drive": TOKEN_PATH,
    "spotify": SPOTIFY_TOKEN_PATH,
    "radiotunes": RADIOTUNES_CONFIG_PATH,
}

_session_key: bytes | None = None


def derive_key(password: str, email: str) -> bytes:
    salt = hashlib.sha256(email.strip().lower().encode("utf-8")).digest()
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    raw = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def encrypt_credential(payload: dict, key: bytes) -> str:
    return Fernet(key).encrypt(json.dumps(payload).encode("utf-8")).decode("ascii")


def decrypt_credential(ciphertext: str, key: bytes) -> dict:
    return json.loads(Fernet(key).decrypt(ciphertext.encode("ascii")))


def unlock(password: str, email: str) -> None:
    """Deriva y guarda la clave de la bóveda en memoria para el resto de la sesión
    del proceso — nunca se persiste en disco. Se llama justo después de un login o
    registro exitoso (ver `cloud/client.py`)."""
    global _session_key
    _session_key = derive_key(password, email)


def lock() -> None:
    global _session_key
    _session_key = None


def is_unlocked() -> bool:
    return _session_key is not None


def push_credential(provider: str, payload: dict) -> None:
    """Sube la versión cifrada de una credencial recién guardada localmente (ej. al
    completar el flujo OAuth de Drive). Si la bóveda no está desbloqueada (no hay
    sesión Supabase activa todavía) no hace nada — el archivo local ya quedó guardado
    igual, simplemente no hay con qué cifrarlo/subirlo todavía; se sincroniza solo en
    el próximo login."""
    if _session_key is None:
        return
    from purrr.cloud import client as cloud_client

    user_id = cloud_client.current_user_id()
    if user_id is None:
        return
    ciphertext = encrypt_credential(payload, _session_key)
    cloud_client.get_client().table("credential_vault").upsert(
        {"user_id": user_id, "provider": provider, "ciphertext": ciphertext},
        on_conflict="user_id,provider",
    ).execute()


def pull_all_credentials() -> dict[str, dict]:
    if _session_key is None:
        return {}
    from purrr.cloud import client as cloud_client

    user_id = cloud_client.current_user_id()
    if user_id is None:
        return {}
    response = (
        cloud_client.get_client()
        .table("credential_vault")
        .select("provider, ciphertext")
        .eq("user_id", user_id)
        .execute()
    )
    credentials: dict[str, dict] = {}
    for row in response.data:
        try:
            credentials[row["provider"]] = decrypt_credential(row["ciphertext"], _session_key)
        except (InvalidToken, ValueError, KeyError):
            # Clave equivocada (ej. la contraseña de la cuenta cambió sin re-cifrar
            # la bóveda vieja) o fila corrupta — no debe romper el login por esto.
            continue
    return credentials


def apply_pulled_credentials(credentials: dict[str, dict]) -> None:
    for provider, payload in credentials.items():
        target = _LOCAL_TARGETS.get(provider)
        if target is None:
            continue
        target.write_text(json.dumps(payload))
        os.chmod(target, 0o600)


def sync_after_login(password: str, email: str) -> None:
    """Se llama justo después de un login/registro exitoso: desbloquea la bóveda con
    la contraseña recién ingresada y aplica localmente todo lo que ya estuviera
    guardado desde otro dispositivo (Drive conectado, etc.)."""
    unlock(password, email)
    apply_pulled_credentials(pull_all_credentials())
