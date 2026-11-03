# -*- coding: utf-8 -*-
"""Windows 原生文件拖拽（WM_DROPFILES）"""

import ctypes
from ctypes import wintypes

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)


class DropTarget:
    """给 tk 顶层窗口装拖拽支持"""

    def __init__(self, root, on_files):
        self.on_files = on_files
        self.ok = False
        try:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            self.user32.GetParent.restype = wintypes.HWND
            self.user32.GetParent.argtypes = [wintypes.HWND]
            hwnd = self.user32.GetParent(wintypes.HWND(root.winfo_id())) or \
                wintypes.HWND(root.winfo_id())
            self.hwnd = hwnd
            self.user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                                      ctypes.c_void_p]
            self.user32.CallWindowProcW.restype = LRESULT
            self.user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                                    ctypes.c_uint, wintypes.WPARAM,
                                                    wintypes.LPARAM]
            self.shell32.DragQueryFileW.restype = ctypes.c_uint
            self.shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                                    wintypes.LPWSTR, wintypes.UINT]
            self.shell32.DragFinish.argtypes = [wintypes.HANDLE]
            self.shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            self._proc = WNDPROC(self._wndproc)
            self.shell32.DragAcceptFiles(hwnd, True)
            self._old = self.user32.SetWindowLongPtrW(
                hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p))
            self.ok = bool(self._old)
        except Exception:
            self.ok = False

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            files = []
            try:
                hdrop = wintypes.HANDLE(wparam)
                n = self.shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                for i in range(n):
                    ln = self.shell32.DragQueryFileW(hdrop, i, None, 0)
                    buf = ctypes.create_unicode_buffer(ln + 1)
                    self.shell32.DragQueryFileW(hdrop, i, buf, ln + 1)
                    files.append(buf.value)
                self.shell32.DragFinish(hdrop)
            except Exception:
                pass
            if files:
                try:
                    self.on_files(files)
                except Exception:
                    pass
            return 0
        return self.user32.CallWindowProcW(self._old, hwnd, msg, wparam, lparam)
