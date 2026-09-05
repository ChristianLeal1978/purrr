import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GObject, Gtk

from purrr.db import database
from purrr.ui.context_menu import show_context_menu
from purrr.ui.library_view import TrackObject, apply_now_playing, text_column


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
        "add-to-album-requested": (GObject.SignalFlags.RUN_FIRST, None, (object,)),  # list[int]
        "add-folder-to-album-requested": (GObject.SignalFlags.RUN_FIRST, None, (int, str)),  # source_id, path
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, vexpand=True)
        self._tracks: list[TrackObject] = []
        self._current_node: FolderNode | None = None
        self._now_playing_track_id: int | None = None

        self._root_store = Gio.ListStore(item_type=FolderNode)
        self._tree_model = Gtk.TreeListModel.new(
            self._root_store, passthrough=False, autoexpand=False, create_func=self._create_child_model
        )
        # autoselect=False: sin esto, Gtk.SingleSelection selecciona solo el primer nodo apenas
        # se llena el árbol (en cada refresh()), pisando la restauración de "última carpeta
        # abierta" con la raíz de la primera fuente.
        self._tree_selection = Gtk.SingleSelection(model=self._tree_model, autoselect=False)
        self._tree_selection.connect("notify::selected-item", self._on_folder_selected)

        tree_factory = Gtk.SignalListItemFactory()
        tree_factory.connect("setup", self._on_tree_setup)
        tree_factory.connect("bind", self._on_tree_bind)

        tree_view = Gtk.ListView(model=self._tree_selection, factory=tree_factory)
        tree_scrolled = Gtk.ScrolledWindow(vexpand=False, hexpand=True)
        tree_scrolled.set_child(tree_view)
        tree_scrolled.set_size_request(-1, 220)

        right_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True,
            margin_start=12, margin_top=12, margin_end=12,
        )

        self._scan_progress_bar = Gtk.ProgressBar(visible=False)
        self._scan_progress_bar.add_css_class("purrr-scan-progress")
        right_box.append(self._scan_progress_bar)

        self._track_store = Gio.ListStore(item_type=TrackObject)
        self._track_sort_model = Gtk.SortListModel(model=self._track_store)
        self._track_selection = Gtk.NoSelection(model=self._track_sort_model)
        self._track_view = Gtk.ColumnView(model=self._track_selection)
        self._track_view.append_column(
            text_column(
                "Pista", "track_label", sortable=True, sort_attr="track_number_sort",
                on_context_menu=self._on_track_context_menu,
            )
        )
        self._track_view.append_column(
            text_column(
                "Título", "title", expand=True, sortable=True, on_context_menu=self._on_track_context_menu
            )
        )
        self._track_view.append_column(
            text_column(
                "Artista", "artist", expand=True, sortable=True, on_context_menu=self._on_track_context_menu
            )
        )
        self._track_view.append_column(
            text_column(
                "Álbum", "album", expand=True, sortable=True, on_context_menu=self._on_track_context_menu
            )
        )
        self._track_view.append_column(
            text_column(
                "Duración", "duration_str", sortable=True, sort_attr="duration_seconds",
                on_context_menu=self._on_track_context_menu,
            )
        )
        self._track_view.connect("activate", self._on_track_activated)
        self._track_sort_model.set_sorter(self._track_view.get_sorter())

        track_scrolled = Gtk.ScrolledWindow(vexpand=True)
        track_scrolled.set_child(self._track_view)
        right_box.append(track_scrolled)

        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True, wide_handle=True)
        paned.set_start_child(tree_scrolled)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)
        paned.set_end_child(right_box)
        paned.set_resize_end_child(True)
        paned.set_shrink_end_child(False)
        paned.set_position(220)
        self.append(paned)

    def refresh(self, sources: list[sqlite3.Row]) -> None:
        self._root_store.splice(0, self._root_store.get_n_items(), [build_source_node(s) for s in sources])
        self._current_node = None
        self._track_store.remove_all()
        self._tracks = []

    def get_visible_tracks(self) -> list[TrackObject]:
        """Tracks tal como se ven ahora (respetando el orden de columna que haya elegido el
        usuario), no el orden crudo con que llegaron de la base."""
        return [self._track_selection.get_item(i) for i in range(self._track_selection.get_n_items())]

    def set_now_playing(self, track_id: int | None) -> None:
        self._now_playing_track_id = track_id
        apply_now_playing(self._track_store, track_id)

    def refresh_current_folder(self) -> None:
        """Vuelve a leer de la base la carpeta que está mostrando (p. ej. tras un escaneo de
        metadatos), sin tocar el árbol ni la selección."""
        row = self._tree_selection.get_selected_item()
        if row is not None:
            self._show_folder(row.get_item())

    def select_folder(self, source_id: int, path: str) -> None:
        """Expande el árbol hasta esa carpeta y la selecciona (para restaurar la última vista)."""
        if not path or path == "/":
            return
        i = 0
        while i < self._tree_model.get_n_items():
            row = self._tree_model.get_item(i)
            node: FolderNode = row.get_item()
            if node.source_id == source_id and node.path == path:
                self._tree_selection.select_item(i, True)
                return
            is_ancestor = node.source_id == source_id and (
                node.path == "/" or path.startswith(node.path.rstrip("/") + "/")
            )
            if is_ancestor and not row.get_expanded():
                row.set_expanded(True)
                continue  # no avanzar: en la próxima vuelta ya están sus hijos insertados acá
            i += 1

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

        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect(
            "pressed", lambda _g, _n, x, y, li=list_item, w=box: self._on_folder_context_menu(li, w, x, y)
        )
        box.add_controller(gesture)

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
        track_rows = database.list_tracks_in_folder(node.source_id, node.path)
        self._tracks = [TrackObject(row) for row in track_rows]
        self._track_store.splice(0, self._track_store.get_n_items(), self._tracks)
        apply_now_playing(self._track_store, self._now_playing_track_id)
        database.set_state("last_folder_source_id", str(node.source_id))
        database.set_state("last_folder_path", node.path)

    def _on_track_activated(self, _view, position: int) -> None:
        track: TrackObject = self._track_selection.get_item(position)
        self.emit("track-activated", track.track_id)

    def _on_track_context_menu(self, list_item: Gtk.ListItem, widget: Gtk.Widget, x: float, y: float) -> None:
        track: TrackObject = list_item.get_item()
        show_context_menu(
            widget, x, y,
            [("Agregar a álbumes", lambda: self.emit("add-to-album-requested", [track.track_id]))],
        )

    def _on_folder_context_menu(self, list_item: Gtk.ListItem, widget: Gtk.Widget, x: float, y: float) -> None:
        row: Gtk.TreeListRow = list_item.get_item()
        node: FolderNode = row.get_item()
        show_context_menu(
            widget, x, y,
            [
                (
                    "Agregar a álbumes",
                    lambda: self.emit("add-folder-to-album-requested", node.source_id, node.path),
                ),
                (
                    "Leer etiquetas (incluye subcarpetas)",
                    lambda: self.emit("scan-folder-requested", node.source_id, node.path),
                ),
            ],
        )

    def show_scan_progress(self, actual: int, total: int) -> None:
        self._scan_progress_bar.set_fraction(actual / total if total else 0.0)
        self._scan_progress_bar.set_visible(True)

    def hide_scan_progress(self) -> None:
        self._scan_progress_bar.set_visible(False)

