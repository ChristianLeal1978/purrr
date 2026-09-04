from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from purrr.config import DRIVE_SCOPES, GOOGLE_OAUTH_CLIENT_CONFIG
from purrr.auth.token_store import delete_token, load_token, save_token


def run_oauth_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_config(GOOGLE_OAUTH_CLIENT_CONFIG, DRIVE_SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(creds)
    return creds


def get_credentials() -> Credentials:
    creds = load_token()
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(creds)
        return creds
    return run_oauth_flow()


def is_authenticated() -> bool:
    creds = load_token()
    return bool(creds and (creds.valid or (creds.expired and creds.refresh_token)))


def revoke() -> None:
    delete_token()
