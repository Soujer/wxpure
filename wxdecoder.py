# -*- coding: utf-8 -*-
"""葵花码解码器（纯 Python 实现，接口与旧版 WXDecoder 一致）"""


class WXDecoder:
    """纯 Python 葵花码解码。返回 [(码制, 内容, 字符集), ...]"""

    def __init__(self):
        self.ok = False
        self.status = "未加载"
        self.detail = ""

    def load(self):
        try:
            import wxcode_decode      # noqa: F401
            self.ok = True
            self.status = "就绪"
            self.detail = ""
        except Exception as ex:
            self.ok = False
            self.status = "初始化失败"
            self.detail = str(ex)
        return self.ok

    # ---------- 解码 ----------
    def decode(self, pil_image):
        """PIL.Image -> [(码制, 内容, 字符集), ...]"""
        if not self.ok:
            raise RuntimeError("解码器未就绪: " + self.status)
        from wxcode_decode import decode_image
        txt = decode_image(pil_image)
        return [("WX_CODE", txt, "UTF-8")] if txt else []

    def decode_file(self, path):
        """文件 -> [(码制, 内容, 字符集), ...]；失败会自动放大并加白边重试。"""
        from PIL import Image, ImageOps
        im = Image.open(path)
        got = self.decode(im)
        if not got:
            g = im.convert("L")
            g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
            got = self.decode(ImageOps.expand(g, border=120, fill=255))
        return got

    def decode_bytes(self, data):
        """原始图片字节 -> [(码制, 内容, 字符集), ...]"""
        import io
        from PIL import Image
        return self.decode(Image.open(io.BytesIO(data)))

    def close(self):
        self.ok = False

    def __enter__(self):
        self.load()
        return self

    def __exit__(self, *a):
        self.close()
