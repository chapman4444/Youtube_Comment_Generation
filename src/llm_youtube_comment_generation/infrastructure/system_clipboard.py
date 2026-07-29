"""The real clipboard.

On Windows this uses the Win32 API directly rather than Tk, and the reason is
not stylistic. Tk sets the clipboard lazily: the owning process keeps the
data and hands it over only when another application asks. Destroy the root
and exit, as a command-line tool must, and the contents are gone.

That failure is silent and it lies. A read-back check inside the same process
succeeds, so the tool reports "the packet is on your clipboard" and the
operator pastes whatever was there before. It was found exactly that way —
by checking the clipboard from a separate process after the command exited.

`GlobalAlloc` with `GMEM_MOVEABLE` plus `SetClipboardData` transfers
ownership to the system, so the data survives the process that set it.

Deliberately tolerant everywhere else: a clipboard locked by another
application returns False rather than raising. Losing a guided run because
something else held the clipboard for a moment would be absurd.
"""

from __future__ import annotations

import logging
import sys

LOGGER = logging.getLogger(__name__)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _declare(ctypes, wintypes, user32, kernel32) -> None:
    """Give every Win32 call an explicit signature.

    Without argtypes, ctypes assumes a 32-bit int for pointer arguments. On
    64-bit Windows the handle from GlobalAlloc does not fit, and the call
    fails with "int too long to convert" — which is how this was found.
    """

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE


class SystemClipboard:
    """Implements ClipboardPort against the operating system."""

    def read(self) -> str:
        if sys.platform == "win32":
            return self._windows_read()
        return self._tk_read()

    def write(self, text: str) -> bool:
        """Returns whether the text is actually on the clipboard.

        A boolean rather than None because the caller tells the operator it
        worked, and it must not say so when it did not.
        """

        if sys.platform == "win32":
            return self._windows_write(str(text))
        return self._tk_write(str(text))

    # -- Windows ---------------------------------------------------------

    @staticmethod
    def _windows_write(text: str) -> bool:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        _declare(ctypes, wintypes, user32, kernel32)

        # Size taken from the encoded buffer, never computed from len(text).
        # Python counts an emoji as one character; UTF-16 needs two code
        # units for it. Sizing as (len + 1) * 2 therefore under-allocates by
        # one unit per emoji and silently truncates the tail — which on a
        # packet is the FINAL OUTPUT CHECK, the part the model reads last.
        buffer = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buffer)

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            LOGGER.debug("clipboard: GlobalAlloc failed")
            return False

        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            LOGGER.debug("clipboard: GlobalLock failed")
            return False
        try:
            ctypes.memmove(pointer, buffer, size)
        finally:
            kernel32.GlobalUnlock(handle)

        # Another application may hold the clipboard open for a moment.
        for _ in range(10):
            if user32.OpenClipboard(None):
                break
        else:
            kernel32.GlobalFree(handle)
            LOGGER.debug("clipboard: could not be opened")
            return False

        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                LOGGER.debug("clipboard: SetClipboardData failed")
                return False
            # Ownership has passed to the system. Freeing it here would be a
            # double free, which is why the handle is deliberately not
            # released on the success path.
            return True
        finally:
            user32.CloseClipboard()

    @staticmethod
    def _windows_read() -> str:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        _declare(ctypes, wintypes, user32, kernel32)

        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        for _ in range(10):
            if user32.OpenClipboard(None):
                break
        else:
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return ""
            try:
                return ctypes.c_wchar_p(pointer).value or ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    # -- everywhere else -------------------------------------------------

    @staticmethod
    def _tk_read() -> str:
        try:
            import tkinter

            root = tkinter.Tk()
            root.withdraw()
            try:
                return str(root.clipboard_get())
            finally:
                root.destroy()
        except Exception as exc:            # noqa: BLE001 - never fatal
            LOGGER.debug("clipboard read failed: %s", exc)
            return ""

    @staticmethod
    def _tk_write(text: str) -> bool:
        try:
            import tkinter

            root = tkinter.Tk()
            root.withdraw()
            try:
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
            finally:
                root.destroy()
            return True
        except Exception as exc:            # noqa: BLE001 - never fatal
            LOGGER.debug("clipboard write failed: %s", exc)
            return False
