import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk

from purrr.ui.markup import escape


class MoodView(Gtk.Box):
    """Pantalla 'Ánimo': analizar la biblioteca (opcional, corre en segundo plano),
    elegir 1+ canciones semilla, y armar una cola de canciones de ánimo parecido.
    Mismo estilo que `ui/spotify_view.py`."""

    __gsignals__ = {
        "analyze-library-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "search-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "play-mood-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # list[int]
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        self._seed_ids: dict[int, str] = {}  # track_id -> título, en orden de inserción

        self._build_analysis_section()
        self._build_seed_picker()
        self._build_seed_list()

    # --- Análisis de la biblioteca (opcional, en segundo plano) ---------------

    def _build_analysis_section(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._analysis_label = Gtk.Label(
            label="Analiza tu biblioteca para tener más canciones entre las que elegir "
            "(opcional — también se analiza sola, de a poco, mientras escuchas).",
            halign=Gtk.Align.START, hexpand=True, wrap=True, css_classes=["dim-label"],
        )
        box.append(self._analysis_label)
        self._analyze_button = Gtk.Button(label="Analizar biblioteca")
        self._analyze_button.connect("clicked", lambda _b: self.emit("analyze-library-requested"))
        box.append(self._analyze_button)
        self.append(box)

        self._analysis_progress = Gtk.ProgressBar(visible=False)
        self.append(self._analysis_progress)

    def show_models_download_progress(self, done: int, total: int) -> None:
        self._analyze_button.set_sensitive(False)
        self._analysis_progress.set_visible(True)
        self._analysis_progress.set_fraction(done / total if total else 0)
        self._analysis_label.set_text(f"Descargando modelos de análisis… ({done}/{total})")

    def show_analysis_progress(self, analyzed: int, total: int) -> None:
        self._analyze_button.set_sensitive(False)
        self._analysis_progress.set_visible(True)
        self._analysis_progress.set_fraction(analyzed / total if total else 1.0)
        self._analysis_label.set_text(f"Analizando biblioteca… {analyzed}/{total}")

    def show_analysis_finished(self, analyzed: int) -> None:
        self._analyze_button.set_sensitive(True)
        self._analysis_progress.set_visible(False)
        cancion_palabra = "canción" if analyzed == 1 else "canciones"
        self._analysis_label.set_text(f"Análisis completo: {analyzed} {cancion_palabra} nuevas.")

    # --- Elegir semillas --------------------------------------------------

    def _build_seed_picker(self) -> None:
        self.append(Gtk.Label(label="Elige una o más canciones semilla", halign=Gtk.Align.START, css_classes=["title-4"]))
        self._search_entry = Gtk.SearchEntry(placeholder_text="Buscar en tu biblioteca")
        self._search_entry.connect("search-changed", lambda entry: self.emit("search-requested", entry.get_text()))
        self.append(self._search_entry)

        self._results_list = Gtk.ListBox(css_classes=["boxed-list"])
        scrolled = Gtk.ScrolledWindow(vexpand=True, min_content_height=160)
        scrolled.set_child(self._results_list)
        self.append(scrolled)

    def show_search_results(self, tracks: list[sqlite3.Row]) -> None:
        while row := self._results_list.get_row_at_index(0):
            self._results_list.remove(row)
        for track in tracks:
            title = track["title"] or track["file_name"]
            subtitle = f"{track['artist'] or ''} — {track['album'] or ''}".strip(" —")
            row = Adw.ActionRow(title=escape(title), subtitle=escape(subtitle))
            add_button = Gtk.Button(
                icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Agregar como semilla"
            )
            add_button.connect(
                "clicked", lambda _b, tid=track["id"], t=title: self._add_seed(tid, t)
            )
            row.add_suffix(add_button)
            self._results_list.append(row)

    # --- Semillas elegidas + reproducir ---------------------------------------

    def _build_seed_list(self) -> None:
        self.append(Gtk.Label(label="Semillas", halign=Gtk.Align.START, css_classes=["title-4"]))
        self._seeds_list = Gtk.ListBox(css_classes=["boxed-list"])
        self.append(self._seeds_list)

        self._play_button = Gtk.Button(
            label="Reproducir por este ánimo", halign=Gtk.Align.CENTER, css_classes=["suggested-action", "pill"],
        )
        self._play_button.set_sensitive(False)
        self._play_button.connect("clicked", lambda _b: self.emit("play-mood-requested", list(self._seed_ids)))
        self.append(self._play_button)

    def _add_seed(self, track_id: int, title: str) -> None:
        if track_id in self._seed_ids:
            return
        self._seed_ids[track_id] = title
        self._refresh_seed_list()

    def _remove_seed(self, track_id: int) -> None:
        self._seed_ids.pop(track_id, None)
        self._refresh_seed_list()

    def _refresh_seed_list(self) -> None:
        while row := self._seeds_list.get_row_at_index(0):
            self._seeds_list.remove(row)
        for track_id, title in self._seed_ids.items():
            row = Adw.ActionRow(title=escape(title))
            remove_button = Gtk.Button(
                icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Quitar semilla"
            )
            remove_button.connect("clicked", lambda _b, tid=track_id: self._remove_seed(tid))
            row.add_suffix(remove_button)
            self._seeds_list.append(row)
        self._play_button.set_sensitive(bool(self._seed_ids))
        self._play_button.set_label(
            "Actualizar cola" if len(self._seed_ids) > 1 else "Reproducir por este ánimo"
        )
