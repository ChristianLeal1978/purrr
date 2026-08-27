import sqlite3

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GObject, Gtk

from purrr.db import database
from purrr.ui.library_view import TrackObject, text_column


class FolderNode(GObject.Object):
    """Un nodo del árbol de carpetas: la raíz de una fuente o una de sus subcarpetas."""

    def __init__(
        self, source_id: int, name: str, path: str, display_path: str, children: list["FolderNode"]
    ):
        super().__init__()
        self.source_id = source_id
        self.name = name
        self.path = path  # coincide con tracks.drive_folder_path ("/", "/Album", "/Album/Disc1"…)
        self.display_path = display_path
        self.children = children


def _folder_tree_from_paths(paths: list[str]) -> dict:
    """Arma un dict anidado {segmento: {subsegmento: {...}}} a partir de rutas planas tipo '/A/B'."""
    root: dict = {}
    for path in paths:
        if not path or path == "/":
            continue  # canciones sueltas en la raíz de la fuente, no una subcarpeta
        node = root
        for segment in path.split("/"):
            if segment:
                node = node.setdefault(segment, {})
    return root


def _build_children(source_id: int, parent_path: str, parent_display: str, tree: dict) -> list[FolderNode]:
    nodes = []
    for name in sorted(tree, key=str.lower):
        child_path = f"{parent_path.rstrip('/')}/{name}"
        child_display = f"{parent_display} / {name}"
        child_children = _build_children(source_id, child_path, child_display, tree[name])
        nodes.append(FolderNode(source_id, name, child_path, child_display, child_children))
    return nodes


def build_source_node(source_row: sqlite3.Row) -> FolderNode:
    source_id = source_row["id"]
    display_name = source_row["display_name"]
    tree = _folder_tree_from_paths(database.list_source_folder_paths(source_id))
    children = _build_children(source_id, "/", display_name, tree)
    return FolderNode(source_id, display_name, "/", display_name, children)


class FolderBrowserView(Gtk.Box):
    """Navegación por carpetas/subcarpetas de las fuentes de Drive: elegís una carpeta a la
    izquierda y a la derecha aparecen sus canciones, listas para reproducirse en orden hasta
    la última de esa carpeta."""

    __gsignals__ = {
        "track-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "scan-folder-requested": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),  # source_id, path
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, vexpand=True)
        self._tracks: list[TrackObject] = []
        self._current_node: FolderNode | None = None

        self._root_store = Gio.ListStore(item_type=FolderNode)
        self._tree_model = Gtk.TreeListModel.new(
            self._root_store, passthrough=False, autoexpand=False, create_func=self._create_child_model
        )
        self._tree_selection = Gtk.SingleSelection(model=self._tree_model)
        self._tree_selection.connect("notify::selected-item", self._on_folder_selected)

        tree_factory = Gtk.SignalListItemFactory()
        tree_factory.connect("setup", self._on_tree_setup)
        tree_factory.connect("bind", self._on_tree_bind)

        tree_view = Gtk.ListView(model=self._tree_selection, factory=tree_factory)
        tree_scrolled = Gtk.ScrolledWindow(vexpand=True, hexpand=False, width_request=260)
        tree_scrolled.set_child(tree_view)

        right_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True,
            margin_start=12, margin_top=6, margin_end=6,
        )
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._breadcrumb = Gtk.Label(
            label="Elige una carpeta a la izquierda", halign=Gtk.Align.START, xalign=0, hexpand=True
        )
        self._breadcrumb.add_css_class("heading")
        header_row.append(self._breadcrumb)

        self._scan_button = Gtk.Button(
            icon_name="text-x-generic-symbolic",
            valign=Gtk.Align.CENTER,
            sensitive=False,
            tooltip_text="Leer etiquetas (título/artista/álbum) de esta carpeta, sin descargar "
            "el audio completo",
        )
        self._scan_button.connect("clicked", self._on_scan_clicked)
        header_row.append(self._scan_button)
        right_box.append(header_row)

        self._status_label = Gtk.Label(halign=Gtk.Align.START, xalign=0, visible=False)
        self._status_label.add_css_class("dim-label")
        right_box.append(self._status_label)

        self._track_store = Gio.ListStore(item_type=TrackObject)
        self._track_sort_model = Gtk.SortListModel(model=self._track_store)
        self._track_selection = Gtk.NoSelection(model=self._track_sort_model)
        self._track_view = Gtk.ColumnView(model=self._track_selection)
        self._track_view.append_column(
            text_column("Pista", "track_label", sortable=True, sort_attr="track_number_sort")
        )
        self._track_view.append_column(text_column("Título", "title", expand=True, sortable=True))
        self._track_view.append_column(text_column("Artista", "artist", expand=True, sortable=True))
        self._track_view.append_column(text_column("Álbum", "album", expand=True, sortable=True))
        self._track_view.append_column(
            text_column("Duración", "duration_str", sortable=True, sort_attr="duration_seconds")
        )
        self._track_view.connect("activate", self._on_track_activated)
        self._track_sort_model.set_sorter(self._track_view.get_sorter())

        track_scrolled = Gtk.ScrolledWindow(vexpand=True)
        track_scrolled.set_child(self._track_view)
        right_box.append(track_scrolled)

        self.append(tree_scrolled)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.append(right_box)

    def refresh(self, sources: list[sqlite3.Row]) -> None:
        self._root_store.splice(0, self._root_store.get_n_items(), [build_source_node(s) for s in sources])
        self._current_node = None
        self._track_store.remove_all()
        self._tracks = []
        self._scan_button.set_sensitive(False)
        self._breadcrumb.set_label("Elige una carpeta a la izquierda")

    def get_visible_tracks(self) -> list[TrackObject]:
        """Tracks tal como se ven ahora (respetando el orden de columna que haya elegido el
        usuario), no el orden crudo con que llegaron de la base."""
        return [self._track_selection.get_item(i) for i in range(self._track_selection.get_n_items())]

    def refresh_current_folder(self) -> None:
        """Vuelve a leer de la base la carpeta que está mostrando (p. ej. tras un escaneo de
        metadatos), sin tocar el árbol ni la selección."""
        row = self._tree_selection.get_selected_item()
        if row is not None:
            self._show_folder(row.get_item())

    def _create_child_model(self, item: FolderNode, _user_data=None) -> Gio.ListModel | None:
        if not item.children:
            return None
        store = Gio.ListStore(item_type=FolderNode)
        store.splice(0, 0, item.children)
        return store

    def _on_tree_setup(self, _factory, list_item: Gtk.ListItem) -> None:
        expander = Gtk.TreeExpander()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(Gtk.Image(icon_name="folder-symbolic"))
        box.append(Gtk.Label(halign=Gtk.Align.START))
        expander.set_child(box)
        list_item.set_child(expander)

    def _on_tree_bind(self, _factory, list_item: Gtk.ListItem) -> None:
        row: Gtk.TreeListRow = list_item.get_item()
        expander: Gtk.TreeExpander = list_item.get_child()
        expander.set_list_row(row)
        node: FolderNode = row.get_item()
        expander.get_child().get_last_child().set_text(node.name)

    def _on_folder_selected(self, selection: Gtk.SingleSelection, _pspec) -> None:
        row = selection.get_selected_item()
        if row is None:
            return
        self._show_folder(row.get_item())

    def _show_folder(self, node: FolderNode) -> None:
        self._current_node = node
        self._scan_button.set_sensitive(True)
        track_rows = database.list_tracks_in_folder(node.source_id, node.path)
        self._tracks = [TrackObject(row) for row in track_rows]
        self._track_store.splice(0, self._track_store.get_n_items(), self._tracks)
        cancion_palabra = "canción" if len(self._tracks) == 1 else "canciones"
        self._breadcrumb.set_label(f"{node.display_path}  ·  {len(self._tracks)} {cancion_palabra}")

    def _on_track_activated(self, _view, position: int) -> None:
        track: TrackObject = self._track_selection.get_item(position)
        self.emit("track-activated", track.track_id)

    def _on_scan_clicked(self, _button) -> None:
        if self._current_node is not None:
            self.emit("scan-folder-requested", self._current_node.source_id, self._current_node.path)

    def show_scan_progress(self, stage: str) -> None:
        self._status_label.set_text(stage)
        self._status_label.set_visible(True)

    def hide_scan_progress(self) -> None:
        self._status_label.set_visible(False)
