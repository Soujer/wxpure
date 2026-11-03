# -*- coding: utf-8 -*-
r"""wxstore.py -- 编解码数据落盘

所有记录写到 <程序所在目录>\数据\ 下：

    数据\编码记录.csv      时间,内容,字节数,尺寸,Logo占比,图片文件
    数据\解码记录.csv      时间,来源,码制,内容,字符集
    数据\生成的码\*.png    每次生成的码原图
    数据\待解图片\         预留目录

CSV 带 UTF-8 BOM，Excel 直接打开不乱码。
"""
import csv
import datetime
import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(os.path.abspath(__file__))


class Store:
    """把每次编解码都落盘。线程安全（append 是原子小写）。"""

    def __init__(self, root=None):
        self.root = root or os.path.join(app_dir(), "数据")
        self.enc_dir = os.path.join(self.root, "生成的码")
        self.dec_img_dir = os.path.join(self.root, "待解图片")
        for d in (self.root, self.enc_dir, self.dec_img_dir):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass
        self.enc_csv = os.path.join(self.root, "编码记录.csv")
        self.dec_csv = os.path.join(self.root, "解码记录.csv")
        self.enc_count = self._count(self.enc_csv)
        self.dec_count = self._count(self.dec_csv)

    @staticmethod
    def _count(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return max(0, sum(1 for _ in f) - 1)
        except Exception:
            return 0

    @staticmethod
    def _append(path, header, row):
        new = (not os.path.exists(path)) or os.path.getsize(path) == 0
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(header)
            w.writerow(row)

    @staticmethod
    def _safe_name(text, n=24):
        keep = []
        for ch in text:
            keep.append(ch if (ch.isalnum() or ch in "._-") else "_")
        return ("".join(keep)[:n].strip("_")) or "code"

    def _enc_name(self, content, size):
        ts = datetime.datetime.now()
        return "%s_%s_%s.png" % (ts.strftime("%Y%m%d_%H%M%S_%f")[:-3],
                                 self._safe_name(content), int(size)), ts

    def _log_encode(self, ts, content, size, logo_ratio, fname):
        self._append(self.enc_csv,
                     ["时间", "内容", "字节数", "尺寸", "Logo占比", "图片文件"],
                     [ts.strftime("%Y-%m-%d %H:%M:%S"), content,
                      len(content.encode("utf-8")), int(size),
                      round(float(logo_ratio), 3), fname])
        self.enc_count += 1

    def save_encode(self, content, size, logo_ratio, img):
        """img: PIL.Image -> (png路径, 累计条数)"""
        name, ts = self._enc_name(content, size)
        path = os.path.join(self.enc_dir, name)
        try:
            img.save(path)
        except Exception:
            path = ""
            name = ""
        try:
            self._log_encode(ts, content, size, logo_ratio, name)
        except Exception:
            pass
        return path, self.enc_count

    def save_encode_png(self, content, size, logo_ratio, png_bytes):
        """png_bytes: 原始 PNG 数据 -> (png路径, 累计条数)"""
        name, ts = self._enc_name(content, size)
        path = os.path.join(self.enc_dir, name)
        try:
            with open(path, "wb") as f:
                f.write(png_bytes)
        except Exception:
            path = ""
            name = ""
        try:
            self._log_encode(ts, content, size, logo_ratio, name)
        except Exception:
            pass
        return path, self.enc_count

    def save_decode(self, source, rows):
        """rows = [(码制, 内容, 字符集), ...]

        注意：只记录文件名，不记录完整路径（避免把本机目录结构写出去）。
        """
        if not rows:
            return self.dec_count
        src = os.path.basename(source) if source else ""
        if src.startswith("HTTP:"):
            src = "HTTP"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for (fmt, text, cs) in rows:
            try:
                self._append(self.dec_csv,
                             ["时间", "来源", "码制", "内容", "字符集"],
                             [ts, src, fmt, text, cs])
                self.dec_count += 1
            except Exception:
                pass
        return self.dec_count
