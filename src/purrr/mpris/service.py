"""Servidor MPRIS2 (org.mpris.MediaPlayer2.purrr) para que GNOME Quick Settings, playerctl,
Powerzoid Music o cualquier otro cliente MPRIS estándar pueda ver y controlar a Purrr — el
mismo protocolo que ya usan Spotify y la mayoría de reproductores en Linux.
"""

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib

from purrr.config import APP_ID
from purrr.player.engine import PlayerEngine
from purrr.player.queue import PlayQueue, QueueItem
from purrr.ui.playback_bar import PlaybackBar

BUS_NAME = "org.mpris.MediaPlayer2.purrr"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
_PROPERTIES_IFACE = "org.freedesktop.DBus.Properties"

_STATE_TO_STATUS = {"playing": "Playing", "paused": "Paused"}

_INTROSPECTION_XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek">
      <arg direction="in" type="x" name="Offset"/>
    </method>
    <method name="SetPosition">
      <arg direction="in" type="o" name="TrackId"/>
      <arg direction="in" type="x" name="Position"/>
    </method>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""


class MprisService:
    def __init__(self, engine: PlayerEngine, queue: PlayQueue, playback_bar: PlaybackBar):
        self._engine = engine
        self._queue = queue
        self._playback_bar = playback_bar
        self._connection: Gio.DBusConnection | None = None
        self._registration_ids: list[int] = []
        self._current_item: QueueItem | None = None
        self._playback_status = "Stopped"

        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            None,
        )

        self._engine.connect("state-changed", self._on_state_changed)
        self._playback_bar.connect("now-playing-changed", self._on_now_playing_changed)

    def shutdown(self) -> None:
        if self._connection:
            for reg_id in self._registration_ids:
                self._connection.unregister_object(reg_id)
        Gio.bus_unown_name(self._owner_id)

    # --- Registro D-Bus ------------------------------------------------

    def _on_bus_acquired(self, connection: Gio.DBusConnection, _name: str) -> None:
        self._connection = connection
        node_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION_XML)
        for interface in node_info.interfaces:
            reg_id = connection.register_object(
                OBJECT_PATH,
                interface,
                self._handle_method_call,
                self._handle_get_property,
                self._handle_set_property,
            )
            self._registration_ids.append(reg_id)

    def _handle_method_call(
        self, _connection, _sender, _object_path, interface_name, method_name, parameters, invocation
    ) -> None:
        if interface_name == PLAYER_IFACE:
            if method_name == "Next":
                self._playback_bar.next()
            elif method_name == "Previous":
                self._playback_bar.previous()
            elif method_name == "Pause":
                if self._playback_bar.is_playing():
                    self._playback_bar.play_pause()
            elif method_name == "Play":
                if not self._playback_bar.is_playing():
                    self._playback_bar.play_pause()
            elif method_name == "PlayPause":
                self._playback_bar.play_pause()
            elif method_name == "Stop":
                self._engine.stop()
            elif method_name == "Seek":
                (offset_us,) = parameters.unpack()
                new_position = (self._engine.get_position() or 0.0) + offset_us / 1_000_000
                self._engine.seek(max(0.0, new_position))
            elif method_name == "SetPosition":
                _track_id, position_us = parameters.unpack()
                self._engine.seek(position_us / 1_000_000)
        # Raise/Quit (interfaz raíz) se ignoran: Purrr no cierra ni levanta ventana por D-Bus todavía.
        invocation.return_value(None)

    def _handle_get_property(
        self, _connection, _sender, _object_path, interface_name, property_name
    ) -> GLib.Variant | None:
        if interface_name == ROOT_IFACE:
            return self._root_property(property_name)
        if interface_name == PLAYER_IFACE:
            return self._player_property(property_name)
        return None

    def _handle_set_property(
        self, _connection, _sender, _object_path, interface_name, property_name, value
    ) -> bool:
        if interface_name == PLAYER_IFACE and property_name == "Volume":
            self._engine.set_volume(value.unpack())
        return True

    def _root_property(self, name: str) -> GLib.Variant | None:
        values = {
            "CanQuit": GLib.Variant("b", False),
            "CanRaise": GLib.Variant("b", False),
            "HasTrackList": GLib.Variant("b", False),
            "Identity": GLib.Variant("s", "Purrr"),
            "DesktopEntry": GLib.Variant("s", APP_ID),
            "SupportedUriSchemes": GLib.Variant("as", []),
            "SupportedMimeTypes": GLib.Variant("as", []),
        }
        return values.get(name)

    def _player_property(self, name: str) -> GLib.Variant | None:
        if name == "PlaybackStatus":
            return GLib.Variant("s", self._playback_status)
        if name == "Metadata":
            return GLib.Variant("a{sv}", self._metadata_dict())
        if name == "Position":
            return GLib.Variant("x", int((self._engine.get_position() or 0.0) * 1_000_000))
        if name == "Volume":
            return GLib.Variant("d", 1.0)
        if name == "CanGoNext":
            return GLib.Variant("b", self._queue.has_next())
        if name == "CanGoPrevious":
            return GLib.Variant("b", self._queue.has_previous())
        if name in ("CanPlay", "CanPause", "CanSeek", "CanControl"):
            return GLib.Variant("b", True)
        if name == "LoopStatus":
            return GLib.Variant("s", "Playlist" if self._queue.repeat else "None")
        if name == "Shuffle":
            return GLib.Variant("b", self._queue.shuffle)
        if name in ("Rate", "MinimumRate", "MaximumRate"):
            return GLib.Variant("d", 1.0)
        return None

    def _metadata_dict(self) -> dict[str, GLib.Variant]:
        item = self._current_item
        if item is None:
            return {}
        result = {
            "mpris:trackid": GLib.Variant("o", f"/org/purrr/track/{item.track_id}"),
            "xesam:title": GLib.Variant("s", item.title),
        }
        if item.artist:
            result["xesam:artist"] = GLib.Variant("as", [item.artist])
        if item.album:
            result["xesam:album"] = GLib.Variant("s", item.album)
        if item.duration_seconds:
            result["mpris:length"] = GLib.Variant("x", int(item.duration_seconds * 1_000_000))
        if item.art_path:
            result["mpris:artUrl"] = GLib.Variant("s", GLib.filename_to_uri(item.art_path))
        return result

    # --- Reaccionar a cambios en Purrr y avisarle a los clientes D-Bus -----

    def _on_state_changed(self, _engine, state: str) -> None:
        new_status = _STATE_TO_STATUS.get(state, "Stopped")
        if new_status == self._playback_status:
            return
        self._playback_status = new_status
        self._emit_properties_changed({"PlaybackStatus": GLib.Variant("s", new_status)})

    def _on_now_playing_changed(self, _bar, item: QueueItem) -> None:
        self._current_item = item
        self._emit_properties_changed({"Metadata": GLib.Variant("a{sv}", self._metadata_dict())})

    def _emit_properties_changed(self, changed: dict[str, GLib.Variant]) -> None:
        if self._connection is None:
            return
        self._connection.emit_signal(
            None,
            OBJECT_PATH,
            _PROPERTIES_IFACE,
            "PropertiesChanged",
            GLib.Variant("(sa{sv}as)", (PLAYER_IFACE, changed, [])),
        )
