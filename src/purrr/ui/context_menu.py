from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk


def show_context_menu(widget: Gtk.Widget, x: float, y: float, items: list[tuple[str, Callable[[], None]]]) -> None:
    """Menú contextual chico (clic derecho) anclado al punto (x, y) dentro de `widget`.

    `items` es una lista de (etiqueta, callback sin argumentos). Se reconstruye desde cero en
    cada llamada — reemplaza cualquier grupo de acciones "ctxmenu" que `widget` tuviera de un
    clic derecho anterior.
    """
    menu_model = Gio.Menu()
    action_group = Gio.SimpleActionGroup()
    for index, (label, callback) in enumerate(items):
        action_name = f"item{index}"
        action = Gio.SimpleAction.new(action_name, None)

        def _on_activate(_action, _param, cb=callback) -> None:
            cb()

        action.connect("activate", _on_activate)
        action_group.add_action(action)
        menu_model.append(label, f"ctxmenu.{action_name}")

    widget.insert_action_group("ctxmenu", action_group)

    popover = Gtk.PopoverMenu.new_from_model(menu_model)
    popover.set_parent(widget)
    popover.set_has_arrow(False)
    # Gdk.Rectangle(x=.., y=..) silently ignores its constructor kwargs (deprecated no-op in
    # this binding) — hence the attribute assignments below instead.
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
    popover.set_pointing_to(rect)
    # Clic en un ítem del menú: GTK activa la acción ("ctxmenu.itemN") Y cierra el popover como
    # parte de la MISMA emisión de "clicked" del botón interno. Si desparentamos acá adentro
    # (síncrono), a veces la cadena de padres que se usa para resolver la acción ya quedó rota
    # cuando la activación intenta correr — el clic queda sin efecto y sin ningún error visible.
    # Con idle_add el desparentado espera a que termine ese ciclo de eventos.
    popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
    popover.popup()
