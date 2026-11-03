# -*- coding: utf-8 -*-
"""把图片放到 Windows 剪贴板（CF_DIB）"""

import ctypes
import io
import time


def _open_clipboard(u, tries=10):
    """OpenClipboard 会被别的程序短暂占用，重试几次"""
    for _ in range(tries):
        if u.OpenClipboard(None):
            return True
        time.sleep(0.08)
    raise RuntimeError("剪贴板被其他程序占用，请稍后再试")


def copy_image(pil_image):
    """把 PIL 图像放进剪贴板，可直接 Ctrl+V 粘贴到微信/QQ/画图/文档"""
    out = io.BytesIO()
    pil_image.convert("RGB").save(out, "BMP")
    data = out.getvalue()[14:]          # 去掉 BMP 文件头，剩余为 DIB

    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    _open_clipboard(u)
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0042, len(data))      # GMEM_MOVEABLE | GMEM_ZEROINIT
        if not h:
            raise RuntimeError("剪贴板内存分配失败")
        p = k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k.GlobalUnlock(h)
        if not u.SetClipboardData(8, h):          # CF_DIB = 8
            raise RuntimeError("写入剪贴板失败")
    finally:
        u.CloseClipboard()
    return True


def copy_text(text):
    """把文字放进剪贴板"""
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    buf = (text + "\0").encode("utf-16-le")
    _open_clipboard(u)
    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0042, len(buf))
        p = k.GlobalLock(h)
        ctypes.memmove(p, buf, len(buf))
        k.GlobalUnlock(h)
        u.SetClipboardData(13, h)                 # CF_UNICODETEXT = 13
    finally:
        u.CloseClipboard()
    return True
