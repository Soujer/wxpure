# -*- coding: utf-8 -*-
"""纯 Python HTTP 服务：/encode 生成，/decode 解码"""

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote


def _safe(msg):
    try:
        print(msg)
    except Exception:
        pass


def _fetch_logo(url):
    """从 http(s) 地址加载 Logo 图片"""
    try:
        import urllib.request
        from io import BytesIO
        from PIL import Image
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=10).read()
        return Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def make_handler():
    class H(BaseHTTPRequestHandler):
        server_version = "WXCodePure/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, "application/json; charset=utf-8",
                       json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/help"):
                txt = (
                    '微信葵花码 HTTP 服务\n\n'
                    'GET  /encode?text=内容&size=660      -> 返回 PNG 图片\n'
                    'POST /encode  {"text":"...","size":660,"logo":"http://...","pos":"center"}  -> PNG\n'
                    '    logo: 自定义 Logo 图片地址（http/https），不传则用官方 Logo\n'
                    '    pos : center(中间,默认) / br(右下角) / none(不加)\n'
                    'POST /decode  请求体为图片二进制         -> JSON {"ok":true,"text":"..."}\n'
                    'GET  /decode?file=本地路径               -> JSON\n'
                )
                self._send(200, "text/plain; charset=utf-8", txt.encode("utf-8"))
                return
            if u.path == "/encode":
                text = (q.get("text") or q.get("content") or [""])[0]
                size = int((q.get("size") or ["660"])[0])
                logo = (q.get("logo") or q.get("logo_url") or [""])[0]
                pos = (q.get("pos") or q.get("logo_pos") or ["center"])[0]
                self._do_encode(text, size, unquote(logo), pos)
                return
            if u.path == "/decode":
                f = (q.get("file") or [""])[0]
                if not f:
                    self._json(400, {"ok": False, "error": "缺少 file 参数"})
                    return
                self._do_decode_path(unquote(f))
                return
            self._json(404, {"ok": False, "error": "未知路径"})

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            if u.path == "/encode":
                try:
                    d = json.loads(body.decode("utf-8"))
                except Exception:
                    self._json(400, {"ok": False, "error": "请求体需为 JSON"})
                    return
                self._do_encode(d.get("text", ""), int(d.get("size", 660)),
                                d.get("logo", "") or "", d.get("pos", "center") or "center")
                return
            if u.path == "/decode":
                self._do_decode_bytes(body)
                return
            self._json(404, {"ok": False, "error": "未知路径"})

        def _do_encode(self, text, size, logo_url="", pos="center"):
            if not text:
                self._json(400, {"ok": False, "error": "内容为空"})
                return
            try:
                from wxcode_draw import render_png
                lg = None
                if logo_url:
                    lg = _fetch_logo(logo_url)
                    if lg is None:
                        self._json(400, {"ok": False, "error": "Logo 地址无法加载"})
                        return
                png = render_png(text, max(120, min(2000, size)),
                                 logo=lg, logo_pos=(pos or "center"))
                self._send(200, "image/png", png)
            except Exception as ex:
                self._json(400, {"ok": False, "error": str(ex)})

        def _do_decode_bytes(self, data):
            try:
                from wxcode_decode import decode_image
                t = decode_image(data)
                self._json(200, {"ok": bool(t), "text": t or ""})
            except Exception as ex:
                self._json(500, {"ok": False, "error": str(ex)})

        def _do_decode_path(self, path):
            try:
                from wxcode_decode import decode_image
                t = decode_image(path)
                self._json(200, {"ok": bool(t), "text": t or ""})
            except Exception as ex:
                self._json(500, {"ok": False, "error": str(ex)})

    return H


class Server:
    def __init__(self):
        self.httpd = None
        self.thread = None
        self.port = 0

    def start(self, port=8686):
        if self.httpd:
            return False
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler())
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        _safe("HTTP 服务已启动，端口 %d" % self.port)
        return True

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            self.thread = None
            return True
        return False

    def running(self):
        return self.httpd is not None
