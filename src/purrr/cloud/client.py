"""Cliente Supabase compartido (sync) — login/registro (Fase 1.5) y push del outbox
(Fase 1.3). El cliente *realtime* es aparte (async, en `sync_engine.py`) porque
necesita su propio hilo con event loop; ver el plan.

La sesión (access/refresh token de Supabase Auth) se guarda localmente para no tener
que loguearse de nuevo en cada arranque de la app.
"""

import json
import os

from supabase import Client as SupabaseClient
from supabase import create_client
from supabase_auth.types import AuthResponse

from purrr.config import SUPABASE_ANON_KEY, SUPABASE_SESSION_PATH, SUPABASE_URL

_client: SupabaseClient | None = None


def get_client() -> SupabaseClient:
    """Cliente sync, creado una sola vez por proceso. Restaura la sesión guardada
    (si hay) la primera vez que se pide, para no exigir login en cada arranque."""
    global _client
    if _client is not None:
        return _client
    _client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    _restore_session(_client)
    return _client


def reset_client() -> None:
    """Fuerza recrear el cliente en la próxima llamada a get_client() — usar tras cerrar sesión."""
    global _client
    _client = None


def _restore_session(client: SupabaseClient) -> None:
    if not SUPABASE_SESSION_PATH.exists():
        return
    try:
        data = json.loads(SUPABASE_SESSION_PATH.read_text())
        client.auth.set_session(data["access_token"], data["refresh_token"])
    except Exception:
        # Sesión guardada corrupta o expirada sin refresh_token válido: seguimos
        # sin sesión, el usuario tendrá que loguearse de nuevo desde la UI.
        SUPABASE_SESSION_PATH.unlink(missing_ok=True)


def _persist_session(response: AuthResponse) -> None:
    if response.session is None:
        return
    SUPABASE_SESSION_PATH.write_text(
        json.dumps(
            {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }
        )
    )
    os.chmod(SUPABASE_SESSION_PATH, 0o600)


def sign_up(email: str, password: str) -> AuthResponse:
    response = get_client().auth.sign_up({"email": email, "password": password})
    _persist_session(response)
    return response


def sign_in(email: str, password: str) -> AuthResponse:
    response = get_client().auth.sign_in_with_password({"email": email, "password": password})
    _persist_session(response)
    return response


def sign_out() -> None:
    try:
        get_client().auth.sign_out()
    finally:
        SUPABASE_SESSION_PATH.unlink(missing_ok=True)
        reset_client()


def is_logged_in_locally() -> bool:
    """Chequeo rápido sin red: ¿hay una sesión guardada en este dispositivo?"""
    return SUPABASE_SESSION_PATH.exists()


def current_user_id() -> str | None:
    if not is_logged_in_locally():
        return None
    session = get_client().auth.get_session()
    return session.user.id if session else None
