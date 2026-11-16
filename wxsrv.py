# -*- coding: utf-8 -*-
r"""wxsrv.py -- 葵花码 HTTP 服务的可复用实现

GUI 和独立服务都用这一份，保证行为一致。

    from wxsrv import start_server
    srv = start_server("127.0.0.1", 8765, dec, enc)   # dec/enc 需有 decode()/encode_png()
"""
import base64
import io
import json
import os
import re
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

from wxlinks import classify


def _fetch_logo(url):
    """从 http(s) 地址加载 Logo 图片（用于 /encode 的 logo 参数）"""
    if not url:
        return None
    try:
        import base64 as _b64
        import io as _io
        from PIL import Image as _Image
        if url.startswith("data:"):
            # data:image/png;base64,xxxx
            payload = url.split(",", 1)[1] if "," in url else ""
            return _Image.open(_io.BytesIO(_b64.b64decode(payload))).convert("RGBA")
        if not (url.startswith("http://") or url.startswith("https://")):
            return None
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=10).read()
        return _Image.open(_io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None

_LOG_PATH = None


def _safe_log(msg):
    """绝不抛异常的日志：控制台不可用（窗口版 EXE）时写文件。"""
    try:
        if sys.stdout is not None:
            sys.stdout.write("[" + msg + "]\n")
            sys.stdout.flush()
            return
    except Exception:
        pass
    if not _LOG_PATH:
        return
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


INDEX_HTML = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>葵花码 HTTP 服务</title>
<style>
body{font-family:"Microsoft YaHei",system-ui;max-width:840px;margin:30px auto;padding:0 16px;color:#222}
h1{margin-bottom:4px}h2{margin-top:30px;border-bottom:2px solid #07c160;padding-bottom:6px}
button{background:#07c160;color:#fff;border:0;padding:9px 18px;border-radius:5px;
font-size:14px;cursor:pointer}input[type=text],textarea,select{padding:8px;
border:1px solid #ccc;border-radius:4px;font-family:Consolas,monospace;box-sizing:border-box}
textarea{width:100%}
pre{background:#f6f6f6;padding:10px;border-radius:5px;overflow:auto;font-size:13px}
img{max-width:300px;border:1px solid #ddd}
.row{display:flex;gap:16px;align-items:flex-start}.muted{color:#888;font-size:12px}
.sm{width:90px}.grey{background:#999}
</style></head><body>
<h1>葵花码 HTTP 服务</h1>
<p class="muted">编码 / 解码均为纯算法实现，不依赖任何引擎文件 &nbsp;|&nbsp; 容量上限 __MAXB__ 字节</p>

<h2>解码</h2>
<input type="file" id="f" multiple accept="image/*">
<button onclick="doDecode()">解码</button>
<pre id="dr">等待…</pre>

<h2>编码</h2>
<textarea id="c" rows="3">https://u.wechat.com/MFPFmVNlRDSfQKaqo5LSkmk?s=2</textarea>

<p>尺寸 <input type="text" class="sm" id="s" value="660">
Logo 位置 <select id="p">
  <option value="center">中间（默认）</option>
  <option value="br">右下角</option>
  <option value="none">不加 Logo</option>
</select>
Logo 宽度 <input type="text" class="sm" id="r" value="0.28"></p>

<p>Logo 图片 <input type="file" id="lf" accept="image/*">
<button type="button" class="grey" onclick="clrLogo()">清除</button>
<img id="lp" style="display:none;max-height:48px;max-width:48px;vertical-align:middle;margin-left:8px;border-radius:4px">
<span class="muted" id="lt">未选则用微信官方 Logo</span></p>
<p class="muted">也可以填图片地址：<input type="text" id="lu" placeholder="http://example.com/logo.png" style="width:340px">
<button type="button" class="grey" onclick="useUrl()">用这个地址</button></p>

<p><button onclick="doEncode()">生成</button></p>
<div class="row"><img id="ei" style="display:none"><pre id="er" style="flex:1"></pre></div>

<script>
let logoData="";
function setLogoPreview(src,name){
  const p=document.getElementById("lp");
  p.src=src;p.style.display="inline-block";
  document.getElementById("lt").textContent=name;}
document.getElementById("lf").addEventListener("change",function(e){
  const f=e.target.files[0]; if(!f) return;
  const rd=new FileReader();
  rd.onload=function(){logoData=rd.result; setLogoPreview(logoData,f.name);};
  rd.readAsDataURL(f);});
function useUrl(){
  const u=document.getElementById("lu").value.trim();
  if(!u) return;
  logoData=u; setLogoPreview(u,u);
}
function clrLogo(){
  logoData="";
  document.getElementById("lf").value="";
  document.getElementById("lu").value="";
  document.getElementById("lp").style.display="none";
  document.getElementById("lt").textContent="未选则用微信官方 Logo";}

async function doDecode(){
 const fs=document.getElementById("f").files; if(!fs.length) return;
 const fd=new FormData(); for(const f of fs) fd.append("file",f,f.name);
 const r=await fetch("/decode",{method:"POST",body:fd});
 document.getElementById("dr").textContent=JSON.stringify(await r.json(),null,2);}

async function doEncode(){
 const body={content:document.getElementById("c").value,
  size:parseInt(document.getElementById("s").value)||660,
  logo_ratio:parseFloat(document.getElementById("r").value)||0.28,
  pos:document.getElementById("p").value};
 if(logoData) body.logo=logoData;
 const r=await fetch("/encode",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify(body)});
 const j=await r.json(); const img=document.getElementById("ei");
 if(j.ok){img.src="data:image/png;base64,"+j.png_base64;img.style.display="block";}
 document.getElementById("er").textContent=JSON.stringify(
  j.ok?{ok:true,format:j.format,bytes:j.bytes}:j,null,2);}
</script></body></html>"""


def parse_multipart(body, boundary):
    """极简 multipart/form-data 解析 -> [(name, filename, ctype, data)]"""
    out = []
    sep = b"--" + boundary
    idx = body.find(sep)
    while idx != -1:
        start = idx + len(sep)
        if body[start:start + 2] == b"--":
            break
        start += 2
        nxt = body.find(sep, start)
        if nxt == -1:
            break
        part = body[start:nxt]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if b"\r\n\r\n" in part:
            head, data = part.split(b"\r\n\r\n", 1)
            name = fname = ctype = ""
            for line in head.split(b"\r\n"):
                ls = line.decode("latin1")
                low = ls.lower()
                if low.startswith("content-disposition:"):
                    m = re.search(r'name="([^"]*)"', ls)
                    if m:
                        name = m.group(1)
                    m = re.search(r'filename="([^"]*)"', ls)
                    if m:
                        fname = m.group(1)
                elif low.startswith("content-type:"):
                    ctype = ls.split(":", 1)[1].strip()
            out.append((name, fname, ctype, data))
        idx = nxt
    return out


def make_handler(dec, enc, max_bytes=53, store=None):
    lock_dec = threading.Lock()
    lock_enc = threading.Lock()

    def decode_one(data, filename=""):
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(data))
        im.load()
        with lock_dec:
            got = dec.decode(im)
            if not got:
                g = im.convert("L")
                g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
                got = dec.decode(ImageOps.expand(g, border=120, fill=255))
        res = []
        for (f, t, c) in got:
            info = classify(t)
            res.append(dict(file=filename, format=f, text=t, charset=c,
                            kind=info["kind"], kind_label=info["label"],
                            summary=info["summary"]))
        return res

    def check_bytes(content):
        try:
            return enc.check_content(content)
        except Exception:
            n = len(content.encode("utf-8"))
            return (n <= max_bytes, n)

    class H(BaseHTTPRequestHandler):
        server_version = "WXCode/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            # 注意：窗口版 EXE 里 sys.stdout 是 None，直接 write 会抛 AttributeError
            # 并导致整个请求被掐断（客户端看到 RemoteDisconnected）。必须用 _safe_log。
            try:
                _safe_log("%s %s" % (self.log_date_time_string(), fmt % args))
            except Exception:
                pass

        def log_error(self, fmt, *args):
            try:
                _safe_log("ERROR " + (fmt % args))
            except Exception:
                pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False, indent=2))

        def do_OPTIONS(self):
            self._send(204, b"")

        def do_GET(self):
            try:
                return self._do_get()
            except Exception as e:
                try:
                    _safe_log("GET %s 失败: %s: %s\n%s"
                              % (self.path, type(e).__name__, e, traceback.format_exc()))
                except Exception:
                    pass
                try:
                    return self._json(500, {"ok": False, "error": "服务器内部错误"})
                except Exception:
                    return

        def _do_get(self):
            u = urlparse(self.path)
            p = u.path.rstrip("/") or "/"
            if p == "/":
                return self._send(200, INDEX_HTML.replace("__MAXB__", str(max_bytes)),
                                  "text/html; charset=utf-8")
            if p == "/health":
                # 只返回能力状态，不返回任何路径 / 模块地址 / 机器信息
                return self._json(200, {
                    "ok": True,
                    "decoder": bool(getattr(dec, "ok", False)),
                    "encoder": bool(getattr(enc, "ok", False)),
                    "encode_max_bytes": max_bytes,
                })
            if p == "/dy":
                q = parse_qs(u.query)
                text = unquote(q.get("text", [""])[0]) or unquote(q.get("content", [""])[0])
                if not text:
                    return self._json(400, {"ok": False, "error": "缺少 text"})
                try:
                    size = int(q.get("size", ["600"])[0])
                except Exception:
                    size = 600
                return self._do_dy(text, size)
            if p == "/encode":
                q = parse_qs(u.query)
                content = unquote(q.get("content", [""])[0])
                if not content:
                    return self._json(400, {"ok": False, "error": "缺少 content"})
                if not getattr(enc, "ok", False):
                    return self._json(503, {"ok": False, "error": "编码器未就绪"})
                ok, nb = check_bytes(content)
                if not ok:
                    return self._json(400, {"ok": False, "bytes": nb, "max_bytes": max_bytes,
                                            "error": "内容 %d 字节，超过上限 %d 字节" % (nb, max_bytes)})
                try:
                    size = int(q.get("size", ["660"])[0])
                    ratio = float(q.get("logo_ratio", ["0.28"])[0])
                    logo_url = unquote(q.get("logo", [""])[0])
                    pos = q.get("pos", ["center"])[0] or "center"
                    with lock_enc:
                        png = enc.encode_png(content, size, ratio,
                                             custom_logo=_fetch_logo(logo_url),
                                             logo_pos=pos)
                except Exception as e:
                    _safe_log("encode 失败: %s: %s" % (type(e).__name__, e))
                    return self._json(400, {"ok": False, "error": "编码失败"})
                return self._send(200, png, "image/png")
            return self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            p = urlparse(self.path).path.rstrip("/") or "/"
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024 * 1024:
                return self._json(413, {"ok": False, "error": "body too large"})
            body = self.rfile.read(n) if n else b""
            try:
                if p == "/decode":
                    return self._do_decode(body)
                if p == "/dy":
                    return self._do_dy_body(body)
                if p == "/dy/decode":
                    return self._do_dy_decode(body)
                if p == "/encode":
                    return self._do_encode(body)
            except Exception as e:
                _safe_log("请求失败: %s: %s\n%s"
                          % (type(e).__name__, e, traceback.format_exc()))
                return self._json(500, {"ok": False, "error": "服务器内部错误"})
            return self._json(404, {"ok": False, "error": "not found"})

        def _do_dy_decode(self, body):
            """图片二进制 -> JSON 识别结果"""
            try:
                import dycode_decode
                r = dycode_decode.decode(body)
            except Exception as e:
                return self._json(400, {"ok": False, "error": str(e)})
            if not r:
                return self._json(200, {"ok": False, "text": "", "error": "未识别到抖音码"})
            return self._json(200, {"ok": True, "text": r["text"],
                                    "format_code": r["format_code"],
                                    "ring_count": r["ring_count"],
                                    "mask_id": r["mask_id"]})

        def _do_dy(self, text, size):
            """生成抖音圆码 PNG"""
            try:
                import io
                import dycode_core
                import dycode_draw
                r = dycode_core.encode(text)
                img = dycode_draw.render(r["rings"], size=max(200, min(2000, int(size))))
                buf = io.BytesIO()
                img.save(buf, "PNG")
                return self._send(200, buf.getvalue(), "image/png")
            except Exception as e:
                _safe_log("dy 生成失败: %s: %s" % (type(e).__name__, e))
                return self._json(400, {"ok": False, "error": str(e)})

        def _do_dy_body(self, body):
            try:
                d = json.loads(body.decode("utf-8"))
            except Exception:
                return self._json(400, {"ok": False, "error": "请求体需为 JSON"})
            text = d.get("text") or d.get("content") or ""
            if not text:
                return self._json(400, {"ok": False, "error": "缺少 text"})
            return self._do_dy(text, int(d.get("size", 600)))

        def _do_decode(self, body):
            raw_ct = self.headers.get("Content-Type") or ""
            ctype = raw_ct.lower()
            blobs = []
            if ctype.startswith("multipart/form-data"):
                m = re.search(r'boundary="?([^";]+)"?', raw_ct)
                if not m:
                    return self._json(400, {"ok": False, "error": "no boundary"})
                for (name, fname, pctype, data) in parse_multipart(body, m.group(1).encode()):
                    if data and (pctype.startswith("image/") or fname or
                                 name in ("file", "image", "images", "img")):
                        blobs.append((fname or name or "upload", data))
            elif ctype.startswith("application/json"):
                j = json.loads(body.decode("utf-8") or "{}")
                vals = []
                for k in ("image_base64", "image", "images", "data", "b64"):
                    v = j.get(k)
                    if isinstance(v, str):
                        vals.append(v)
                    elif isinstance(v, list):
                        vals.extend([x for x in v if isinstance(x, str)])
                for i, v in enumerate(vals):
                    if v.strip().startswith("data:") and "," in v:
                        v = v.split(",", 1)[1]
                    blobs.append(("json_%d" % i, base64.b64decode(v)))
            else:
                if not body:
                    return self._json(400, {"ok": False, "error": "empty body"})
                blobs.append(("raw", body))

            if not blobs:
                return self._json(400, {"ok": False, "error": "没有收到图片"})
            if not getattr(dec, "ok", False):
                return self._json(503, {"ok": False,
                                        "error": "解码器未就绪: " + getattr(dec, "status", "")})

            results, errors = [], []
            for (name, data) in blobs:
                try:
                    rows = decode_one(data, name)
                    results.extend(rows)
                    if store is not None:
                        try:
                            store.save_decode("HTTP",
                                              [(r["format"], r["text"], r["charset"])
                                               for r in rows])
                        except Exception:
                            pass
                except Exception as e:
                    _safe_log("decode 失败: %s: %s" % (type(e).__name__, e))
                    errors.append({"file": os.path.basename(name or ""),
                                   "error": "无法解码该图片"})
            out = {"ok": True, "count": len(results), "results": results}
            if errors:
                out["errors"] = errors
            return self._json(200, out)

        def _do_encode(self, body):
            if not getattr(enc, "ok", False):
                return self._json(503, {"ok": False, "error": "编码器未就绪"})
            ctype = (self.headers.get("Content-Type") or "").lower()
            if not ctype.startswith("application/json"):
                return self._json(415, {"ok": False, "error": "need application/json"})
            j = json.loads(body.decode("utf-8") or "{}")
            content = j.get("content", "")
            if not content:
                return self._json(400, {"ok": False, "error": "缺少 content"})
            ok, nb = check_bytes(content)
            if not ok:
                return self._json(400, {"ok": False, "bytes": nb, "max_bytes": max_bytes,
                                        "error": "内容 %d 字节，超过上限 %d 字节" % (nb, max_bytes)})
            size = int(j.get("size", 660))
            ratio = float(j.get("logo_ratio", 0.28))
            logo_url = j.get("logo", "") or ""
            pos = j.get("pos", "center") or "center"
            with lock_enc:
                png = enc.encode_png(content, size, ratio,
                                     custom_logo=_fetch_logo(logo_url),
                                     logo_pos=pos)
            if store is not None:
                try:
                    store.save_encode_png(content, size, ratio, png)
                except Exception:
                    pass
            if j.get("raw") or parse_qs(urlparse(self.path).query).get("raw"):
                return self._send(200, png, "image/png")
            return self._json(200, {"ok": True, "format": "WX_CODE", "width": size,
                                    "bytes": len(png),
                                    "png_base64": base64.b64encode(png).decode("ascii")})

    return H


def start_server(host, port, dec, enc, max_bytes=53, store=None):
    """在后台线程启动服务，返回 server 对象（调用 .shutdown() 停止）。"""
    global _LOG_PATH
    try:
        base = getattr(store, "root", None) or os.path.join(
            os.path.expanduser("~"), ".wxcode")
        os.makedirs(base, exist_ok=True)
        _LOG_PATH = os.path.join(base, "运行日志.txt")
    except Exception:
        _LOG_PATH = None

    H = make_handler(dec, enc, max_bytes, store)

    class _SafeServer(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # 默认实现会 print 到 sys.stderr（窗口版为 None）→ 再抛一次异常
            try:
                _safe_log("REQUEST ERROR\n%s" % traceback.format_exc())
            except Exception:
                pass

    srv = _SafeServer((host, port), H)
    t = threading.Thread(target=srv.serve_forever, name="wxhttp", daemon=True)
    t.start()
    srv._wx_thread = t
    return srv
