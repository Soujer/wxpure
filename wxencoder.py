# -*- coding: utf-8 -*-
"""葵花码编码器（纯 Python 实现，接口与旧版一致）"""

import io

from PIL import Image

ENC_MAX_BYTES = 53


class Encoder:
    """葵花码编码器。"""

    def __init__(self):
        self.ok = False
        self.status = "未加载"
        self.detail = ""

    # ---------- 加载 ----------
    def load(self):
        try:
            import wxcode_draw      # noqa: F401
            import wxcode_core      # noqa: F401
            self.ok = True
            self.status = "就绪"
            self.detail = ""
        except Exception as ex:
            self.ok = False
            self.status = "初始化失败"
            self.detail = str(ex)
        return self.ok

    # ---------- 容量 ----------
    @staticmethod
    def check_content(content):
        """返回 (ok, 字节数)。放不下返回 ok=False。"""
        n = len(content.encode("utf-8"))
        try:
            from wxcode_core import pick_layout
            pick_layout(content)
            return (True, n)
        except Exception:
            return (False, n)

    # ---------- 编码 ----------
    def encode_image(self, content, size=660, logo_ratio=0.28,
                     custom_logo=None, logo_pos=None):
        """-> PIL.Image"""
        if not self.ok:
            raise RuntimeError("编码器未就绪: " + self.status)
        ok, n = self.check_content(content)
        if not ok:
            raise ValueError("内容 %d 字节，超出葵花码容量" % n)
        from wxcode_draw import render_png
        png = render_png(content, 660, logo=custom_logo,
                         logo_pos=logo_pos, logo_ratio=logo_ratio)
        img = Image.open(io.BytesIO(png))
        img.load()
        if size and int(size) != 660:
            img = img.resize((int(size), int(size)), Image.LANCZOS)
        return img

    def encode_png(self, content, size=660, logo_ratio=0.28,
                   custom_logo=None, logo_pos=None):
        """-> bytes(PNG)"""
        img = self.encode_image(content, size, logo_ratio, custom_logo, logo_pos)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def close(self):
        pass
