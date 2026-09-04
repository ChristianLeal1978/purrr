"""Control remoto de Spotify Connect (Fase 4): Purrr nunca decodifica el audio de
Spotify, solo le manda comandos a un dispositivo Connect ya activo (el celular, el
cliente oficial en otra compu, etc.) y consulta su estado por polling — mismo estilo
que `sync/controller.py`: trabajo de red en un hilo, cruce a la UI vía GLib.idle_add.
"""

import threading

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib, GObject

from purrr.auth.spotify_oauth import get_client, is_authenticated
from purrr.spotify.track import SpotifyTrack

_POLL_INTERVAL_SECONDS = 3


class SpotifyConnectController(GObject.Object):
    __gsignals__ = {
        # position_seconds, duration_seconds, is_playing
        "position-updated": (GObject.SignalFlags.RUN_FIRST, None, (float, float, bool)),
        "ended": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "no-device": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._device_id: str | None = None

    def play(self, track: SpotifyTrack) -> None:
        self.stop()
        if not is_authenticated():
            GLib.idle_add(self.emit, "error", "No hay una sesión de Spotify activa.")
            return
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._start_and_poll, args=(track,), daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        """Para el polling — no manda pausa a Spotify: el usuario puede querer seguir
        escuchando ahí mismo aunque Purrr pase a otra cosa."""
        self._stop_event.set()
        self._poll_thread = None
        self._device_id = None

    def pause(self) -> None:
        self._run_player_command(lambda client: client.pause_playback(device_id=self._device_id))

    def resume(self) -> None:
        self._run_player_command(lambda client: client.start_playback(device_id=self._device_id))

    def _run_player_command(self, command) -> None:
        if self._device_id is None or not is_authenticated():
            return

        def worker() -> None:
            try:
                command(get_client())
            except Exception as exc:
                GLib.idle_add(self.emit, "error", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def list_devices(self) -> list[dict]:
        """Lectura de solo consulta para la UI ("Dispositivos disponibles"). Pega a la
        red — llamar desde un hilo."""
        if not is_authenticated():
            return []
        try:
            return get_client().devices().get("devices", [])
        except Exception:
            return []

    def _start_and_poll(self, track: SpotifyTrack) -> None:
        try:
            client = get_client()
            devices = client.devices().get("devices", [])
        except Exception as exc:
            GLib.idle_add(self.emit, "error", str(exc))
            return
        if not devices:
            GLib.idle_add(self.emit, "no-device")
            return
        device = next((d for d in devices if d.get("is_active")), devices[0])
        self._device_id = device["id"]
        try:
            client.start_playback(device_id=device["id"], uris=[track.uri])
        except Exception as exc:
            GLib.idle_add(self.emit, "error", str(exc))
            return
        self._poll_loop(client, track)

    def _poll_loop(self, client, track: SpotifyTrack) -> None:
        while not self._stop_event.wait(_POLL_INTERVAL_SECONDS):
            try:
                state = client.current_playback()
            except Exception as exc:
                GLib.idle_add(self.emit, "error", str(exc))
                return
            if self._stop_event.is_set():
                return
            if state is None:
                GLib.idle_add(self.emit, "ended")
                return
            item = state.get("item") or {}
            position_s = (state.get("progress_ms") or 0) / 1000
            duration_s = (item.get("duration_ms") or 0) / 1000 or (track.duration_seconds or 0)
            is_playing = bool(state.get("is_playing"))
            same_track = item.get("uri") == track.uri
            finished = not same_track or (
                not is_playing and duration_s > 0 and position_s >= duration_s - 1
            )
            if finished:
                GLib.idle_add(self.emit, "ended")
                return
            GLib.idle_add(self.emit, "position-updated", position_s, duration_s, is_playing)
