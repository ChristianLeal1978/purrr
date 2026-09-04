import json
import os

from google.oauth2.credentials import Credentials

from purrr.config import DRIVE_SCOPES, TOKEN_PATH


def save_token(creds: Credentials) -> None:
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)
    # Fase 1.5: si hay una bóveda Supabase desbloqueada, este mismo punto de guardado
    # empuja la versión cifrada — así el resto de tus dispositivos recibe la conexión
    # a Drive con solo iniciar sesión, sin repetir el consentimiento OAuth. Si todavía
    # no hay sesión (o falla la red), push_credential no hace nada y el archivo local
    # ya quedó guardado igual — no es una dependencia dura.
    from purrr.cloud import vault

    try:
        vault.push_credential("google_drive", json.loads(creds.to_json()))
    except Exception:
        pass


def load_token() -> Credentials | None:
    if not TOKEN_PATH.exists():
        return None
    return Credentials.from_authorized_user_file(str(TOKEN_PATH), DRIVE_SCOPES)


def delete_token() -> None:
    TOKEN_PATH.unlink(missing_ok=True)
