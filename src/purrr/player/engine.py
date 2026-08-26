from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, GObject, Gst

_gst_initialized = False


def ensure_gst_init() -> None:
    global _gst_initialized
    if not _gst_initialized:
        Gst.init(None)
        _gst_initialized = True


class PlayerEngine(GObject.Object):
    """Envuelve un playbin de GStreamer para reproducir archivos locales cacheados."""

    __gsignals__ = {
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "position-updated": (GObject.SignalFlags.RUN_FIRST, None, (float, float)),
        "eos": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        ensure_gst_init()
        self._playbin = Gst.ElementFactory.make("playbin", "player")
        if self._playbin is None:
            raise RuntimeError("No se pudo crear el elemento playbin de GStreamer")

        bus = self._playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        self._position_source_id: int | None = None

    def load(self, local_path: Path) -> None:
        self.stop()
        uri = GLib.filename_to_uri(str(local_path))
        self._playbin.set_property("uri", uri)

    def play(self) -> None:
        self._playbin.set_state(Gst.State.PLAYING)
        self._start_position_polling()

    def pause(self) -> None:
        self._playbin.set_state(Gst.State.PAUSED)
        self._stop_position_polling()

    def stop(self) -> None:
        self._playbin.set_state(Gst.State.NULL)
        self._stop_position_polling()

    def seek(self, position_seconds: float) -> None:
        self._playbin.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(position_seconds * Gst.SECOND),
        )

    def set_volume(self, volume: float) -> None:
        self._playbin.set_property("volume", max(0.0, min(1.0, volume)))

    def get_position(self) -> float | None:
        ok, position = self._playbin.query_position(Gst.Format.TIME)
        return position / Gst.SECOND if ok else None

    def get_duration(self) -> float | None:
        ok, duration = self._playbin.query_duration(Gst.Format.TIME)
        return duration / Gst.SECOND if ok else None

    def _start_position_polling(self) -> None:
        if self._position_source_id is not None:
            return
        self._position_source_id = GLib.timeout_add(250, self._poll_position)

    def _stop_position_polling(self) -> None:
        if self._position_source_id is not None:
            GLib.source_remove(self._position_source_id)
            self._position_source_id = None

    def _poll_position(self) -> bool:
        position = self.get_position()
        duration = self.get_duration()
        if position is not None and duration is not None:
            self.emit("position-updated", position, duration)
        return True

    def _on_bus_message(self, _bus, message: Gst.Message) -> None:
        if message.type == Gst.MessageType.EOS:
            self._stop_position_polling()
            self.emit("eos")
        elif message.type == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self._stop_position_polling()
            self.emit("error", error.message)
        elif message.type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._playbin:
                _old, new, _pending = message.parse_state_changed()
                self.emit("state-changed", new.value_nick)
