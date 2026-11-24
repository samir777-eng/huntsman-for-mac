# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""The lighting service's tray icon on Windows (experimental, untested on a Windows PC), via pystray.

It renders the same menu model as the Mac menu bar (menubar.MenuState / build_menu): Lighting on/off, Presets,
Open Huntsman for Mac, Quit lighting service, plus an optional disabled notice on top (Razer Synapse running).
Clicking the icon itself opens the app (pystray's default item). pystray and Pillow are imported only when the
tray is installed or the icon drawn, so this module imports anywhere; tests pass a fake pystray module.

Handlers run on pystray's thread: keep them short (service.make_menu hands device work to a thread).
"""
import threading
import traceback

from menubar import APP_NAME, MenuState

ACCENT = (106, 215, 255, 255)   # the app's default accent, ice #6ad7ff


def icon_image(size=64):
    """A small keyboard drawn with Pillow (no asset file to ship)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64
    d.rounded_rectangle((2 * s, 14 * s, 62 * s, 50 * s), radius=7 * s, outline=ACCENT, width=max(1, round(4 * s)))
    for row, (y, n, x0) in enumerate(((21, 6, 9), (29, 6, 13), (37, 5, 9))):
        for i in range(n):
            x = (x0 + i * 8) * s
            d.rectangle((x, y * s, x + 4 * s, (y + 4) * s), fill=ACCENT)
    d.rectangle((18 * s, 43 * s, 46 * s, 46 * s), fill=ACCENT)   # space bar
    return img


class TrayMenu(MenuState):
    """The Windows front-end of the shared menu. install() creates the icon; run() blocks in its message loop
    (call it on the main thread); remove() ends it. set_state() may be called from any thread."""

    def __init__(self, *args, pystray=None, image=None, **kw):
        super().__init__(*args, **kw)
        self._pystray, self._image = pystray, image
        self.icon = None
        self._icon_lock = threading.Lock()
        self._removed = False   # remove() was called: install() and run() do nothing from then on

    @property
    def installed(self):
        return self.icon is not None

    def _ps(self):
        if self._pystray is None:
            import pystray
            self._pystray = pystray
        return self._pystray

    def pystray_menu(self):
        return self._menu(self.model())

    def _menu(self, items):
        return self._ps().Menu(*self._items(items))

    def _items(self, items):
        ps = self._ps()
        out = []
        for m in items:
            if m.separator:
                out.append(ps.Menu.SEPARATOR)
            elif m.children:
                out.append(ps.MenuItem(m.title, self._menu(m.children), enabled=m.enabled))
            elif m.action is None:
                out.append(ps.MenuItem(m.title, _nothing, enabled=False))
            else:
                checkable = m.action in ("toggle", "preset")
                out.append(ps.MenuItem(m.title, self._click(m.action, m.payload),
                                       checked=(lambda _item, v=m.checked: v) if checkable else None,
                                       radio=m.action == "preset", enabled=m.enabled, default=m.action == "open"))
        return out

    def _click(self, action, payload):
        def run(_icon, _item):
            self.activate(action, payload)
        return run

    def install(self):
        with self._icon_lock:
            if self.icon is not None or self._removed:
                return
            ps = self._ps()
            self.icon = ps.Icon("huntsman-for-mac-lighting", self._image if self._image is not None else icon_image(),
                                APP_NAME, menu=self.pystray_menu())

    def install_soon(self):
        self.install()

    def run(self, on_ready=None):
        """Show the icon and run its loop until remove(). on_ready() runs once the icon is visible. Returns at once
        when remove() came first (a quit before the loop started): nothing would stop that loop."""
        self.install()
        with self._icon_lock:
            icon = None if self._removed else self.icon
        if icon is None:
            return

        def setup(icon):
            icon.visible = True
            if on_ready is not None:
                try:
                    on_ready()
                except Exception:
                    traceback.print_exc()
        icon.run(setup)

    def _refresh(self):
        icon = self.icon
        if icon is None:
            return
        try:
            icon.menu = self.pystray_menu()
            icon.update_menu()
        except Exception:
            traceback.print_exc()

    def remove(self):
        with self._icon_lock:
            self._removed = True
            icon, self.icon = self.icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                traceback.print_exc()


def _nothing(_icon=None, _item=None):
    pass
