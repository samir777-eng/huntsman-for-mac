# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Menu bar status item: Lighting on/off, a presets submenu, Open Huntsman for Mac, Quit (the lighting service
passes quit_title="Quit lighting service"; service.py owns the icon).

The menu is built from a plain model (build_menu -> list of MenuItem) so it can be tested without Cocoa;
StatusMenu turns the model into an NSStatusItem and calls the handlers.

The lighting service (service.py) owns the icon. It runs its own Cocoa loop (an accessory NSApplication); the
status item is created on the main thread once that loop runs (install(), or install_soon() from another thread).

Handlers run on the main thread: keep them short and hand device work (engine, USB) to a thread.
set_state() may be called from any thread.
"""
import threading
import traceback
from dataclasses import dataclass

APP_NAME = "Huntsman for Mac"
_TARGET_CLASS = None  # the ObjC menu target class, defined the first time a menu is installed


@dataclass(frozen=True)
class MenuItem:
    title: str
    action: str | None = None        # "toggle" | "preset" | "open" | "quit" | None
    checked: bool = False
    enabled: bool = True
    children: tuple = ()
    separator: bool = False
    payload: str | None = None       # the preset name for "preset"


SEPARATOR = MenuItem("", separator=True)


def build_menu(enabled, presets, active, quit_title=f"Quit {APP_NAME}"):
    if presets:
        sub = tuple(MenuItem(p, "preset", checked=(p == active), payload=p) for p in presets)
    else:
        sub = (MenuItem("No presets yet", enabled=False),)
    return [
        MenuItem("Lighting", "toggle", checked=bool(enabled)),
        MenuItem("Presets", children=sub),
        SEPARATOR,
        MenuItem(f"Open {APP_NAME}", "open"),
        SEPARATOR,
        MenuItem(quit_title, "quit"),
    ]


class StatusMenu:
    """on_toggle(new_enabled: bool), on_preset(name), on_open(), on_quit().

    The menu shows state; it doesn't change it by itself. After a handler acts, call set_state() with
    the new state (e.g. on_toggle -> engine on/off -> menu.set_state(enabled=...)).
    """

    def __init__(self, on_toggle, on_preset, on_open, on_quit, presets=(), enabled=True, active=None,
                 quit_title=f"Quit {APP_NAME}"):
        self.handlers = {"toggle": lambda _p: on_toggle(not self.enabled), "preset": on_preset,
                         "open": lambda _p: on_open(), "quit": lambda _p: on_quit()}
        self.presets, self.enabled, self.active = list(presets), bool(enabled), active
        self.quit_title = quit_title
        self._lock = threading.Lock()
        self._item = None
        self._target = None

    @property
    def installed(self):
        return self._item is not None

    def model(self):
        with self._lock:
            return build_menu(self.enabled, self.presets, self.active, self.quit_title)

    def activate(self, action, payload=None):
        """Runs the handler for a menu action. Never raises (it is called from Cocoa)."""
        fn = self.handlers.get(action)
        if fn is None:
            return
        try:
            fn(payload)
        except Exception:
            traceback.print_exc()

    def set_state(self, enabled=None, presets=None, active=...):
        """Update what the menu shows; any thread. active=None clears the checkmark, omit it to keep it."""
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if presets is not None:
                self.presets = list(presets)
            if active is not ...:
                self.active = active
        if self.installed:
            _on_main(self._rebuild)

    # Cocoa layer (main thread only below) ------------------------------------------------------------

    def install_soon(self):
        """Create the status item on the main thread; callable from any thread (e.g. webview.start's func)."""
        _on_main(self.install)

    def install(self):
        """Create the status item. Main thread only, with the Cocoa loop running (or about to)."""
        if self.installed:
            return
        from AppKit import NSImage, NSStatusBar, NSVariableStatusItemLength
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = item.button()
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("keyboard", APP_NAME)
        if image is not None:
            image.setTemplate_(True)  # follows the light/dark menu bar
            button.setImage_(image)
        else:
            button.setTitle_("Huntsman")
        button.setToolTip_(APP_NAME)
        self._target = _target_class().alloc().init()
        self._target.menu = self
        self._item = item
        self._rebuild()

    def remove(self):
        """Take the status item out of the menu bar (main thread). Safe when never installed."""
        item, self._item = self._item, None
        if item is not None:
            from AppKit import NSStatusBar
            NSStatusBar.systemStatusBar().removeStatusItem_(item)

    def _rebuild(self):
        if self._item is not None:
            self._item.setMenu_(self._ns_menu(self.model()))

    def _ns_menu(self, items):
        from AppKit import NSControlStateValueOff, NSControlStateValueOn, NSMenu, NSMenuItem
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for m in items:
            if m.separator:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            ns = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(m.title, "menuAction:" if m.action else None,
                                                                         "q" if m.action == "quit" else "")
            if m.action:
                ns.setTarget_(self._target)
                ns.setRepresentedObject_((m.action, m.payload))
            ns.setEnabled_(m.enabled)
            ns.setState_(NSControlStateValueOn if m.checked else NSControlStateValueOff)
            if m.children:
                ns.setSubmenu_(self._ns_menu(m.children))
            menu.addItem_(ns)
        return menu


def _on_main(fn):
    from Foundation import NSThread
    if NSThread.isMainThread():
        fn()
    else:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(fn)


def _target_class():
    """The NSObject subclass that receives menu clicks; defined once per process (ObjC class names are global)."""
    global _TARGET_CLASS
    if _TARGET_CLASS is None:
        import objc
        from Foundation import NSObject

        try:
            _TARGET_CLASS = objc.lookUpClass("HuntsmanMenuTarget")  # already defined (module reloaded)
        except objc.nosuchclass_error:
            class HuntsmanMenuTarget(NSObject):
                def menuAction_(self, sender):
                    action, payload = sender.representedObject()
                    menu = getattr(self, "menu", None)
                    if menu is not None:
                        menu.activate(str(action), None if payload is None else str(payload))

            _TARGET_CLASS = HuntsmanMenuTarget
    return _TARGET_CLASS
