# -*- coding: utf-8 -*-
r"""wxlinks.py -- 微信各类链接 / 小程序码 payload 的识别与解析

格式依据（逆向自微信客户端）：

  Android classes8.dex:
    weixin://dl/jumpWxa/?appid=%s&userName=%s@app&path=%s&invokeData=%s
                            &pathType=%d&runtimeAppid=%s&runtimeTicket=%s&runtimeSessionId=%s
    weixin://dl/jumpFakeWxa/
    weixin://dl/scanWxaQrcode?qrcodeText=      <- 小程序码文本的入口
    weixin://ecs/alias/openAliasProfileSelector

  Android classes17.dex 正则:
    ^mp://\w+                  -> mp:// 后面只允许由字母数字下划线组成
    ^#小程序://.*

  Android classes11/8/18.dex 常量:
    #小程序://

  Windows Weixin.dll 链接白名单表 (RVA 0x966d2a0):
    www / weixin: / mailto: / applet: / mp: / sns: / announcement:
    mp:// / weixin://dl/business/
    TLD: .net .org .edu .gov .jobs .asia .cn .us .jp .mil .biz .name .pro ...
"""
import re
from urllib.parse import urlparse, parse_qs, quote

# 微信自有域名
WX_HOSTS = {
    "u.wechat.com": ("wechat_short", "微信短链"),
    "weixin.qq.com": ("weixin_short", "微信短链"),
    "mp.weixin.qq.com": ("mp_article", "公众号文章"),
    "servicewechat.com": ("miniprogram", "小程序域名"),
    "channels.weixin.qq.com": ("channels", "视频号"),
    "mmbiz.qpic.cn": ("wx_image", "微信图片"),
    "wx.qlogo.cn": ("wx_avatar", "微信头像"),
    "res.wx.qq.com": ("wx_static", "微信静态资源"),
}

RE_MP = re.compile(r"^mp://(\w+)", re.I)
# 小程序里"复制链接"给出的就是这样一个裸 token（14~16 位字母数字）
RE_BARE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{14,20}$")
RE_XCX = re.compile(r"^#小程序://(.+)$", re.S)
RE_WEIXIN = re.compile(r"^weixin://([^?\s]+)(?:\?(.*))?$", re.I)

# 常见的 weixin:// 内部路由 -> 中文说明
ROUTES = {
    "dl/jumpWxa/": "跳转小程序",
    "dl/jumpWxa": "跳转小程序",
    "dl/jumpFakeWxa/": "跳转小程序(伪装)",
    "dl/scanWxaQrcode": "扫小程序码",
    "dl/business/": "短链跳转",
    "dl/businessShare": "分享落地页",
    "dl/businessWebview": "业务网页",
    "dl/businessView": "业务视图",
    "dl/feedback": "反馈页",
    "dl/moments": "朋友圈",
    "dl/myQRcode": "我的二维码",
    "dl/scan": "扫一扫",
    "dl/log": "日志上传",
    "dl/offlinepay": "离线支付",
    "dl/preloadWxa": "预加载小程序",
    "dl/wmpf/sdk": "半屏小程序 SDK",
    "dl/openBusinessView": "打开业务视图",
    "dl/openbusinesswebview/link": "打开业务网页",
    "dl/opensdkGeta8Key": "开放SDK鉴权",
    "dl/modifyAddress": "改地址",
    "dl/modifyUserName": "改微信号",
    "dl/settings": "设置",
    "dl/settingChat": "聊天设置",
    "dl/security": "安全中心",
    "dl/webreport": "举报",
    "link_profile": "个人名片",
}

# 常见参数名 -> 中文
PARAM_NAMES = {
    "appid": "小程序AppID",
    "userName": "原始ID",
    "username": "微信号",
    "path": "页面路径",
    "invokeData": "启动参数",
    "pathType": "路径类型",
    "runtimeAppid": "运行时AppID",
    "runtimeTicket": "运行时票据",
    "runtimeSessionId": "运行时会话",
    "qrcodeText": "码文本",
    "t": "票据",
    "businessType": "业务类型",
    "query": "查询串",
    "type": "类型",
}


def _params(qs):
    """-> [(原始键, 中文名, 值)]"""
    out = []
    if not qs:
        return out
    for k, vs in parse_qs(qs, keep_blank_values=True).items():
        v = vs[0] if vs else ""
        out.append((k, PARAM_NAMES.get(k, ""), v))
    return out


def classify(text):
    """识别一段扫码/文本内容。

    返回 dict:
        kind   机器可读类型
        label  中文说明
        summary 一句话摘要
        fields 附带的解析结果
    """
    t = (text or "").strip()
    if not t:
        return {"kind": "empty", "label": "空内容", "summary": "", "fields": {}}

    # 0) 裸 token（小程序内"复制链接"直接给这个）
    if RE_BARE_TOKEN.match(t):
        return {"kind": "bare_token", "label": "葵花码载荷(可直接编码)",
                "summary": "葵花码载荷: %s（%d 字节）→ 可直接编成葵花码，扫码跳转"
                           % (t, len(t.encode("utf-8"))),
                "fields": {"short_id": t, "equiv": "mp://" + t, "raw": t}}

    # 1) mp://
    m = RE_MP.match(t)
    if m:
        sid = m.group(1)
        return {"kind": "mp_short", "label": "小程序短链 mp://",
                "summary": "小程序短链，短ID: " + sid,
                "fields": {"short_id": sid, "raw": t}}

    # 2) #小程序://
    m = RE_XCX.match(t)
    if m:
        body = m.group(1)
        parts = body.split("/")
        name = parts[0]
        path = "/".join(parts[1:]) if len(parts) > 1 else ""
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        fields = {"app_name": name, "path": path, "query": query, "raw": t}
        summ = "小程序分享：%s" % name
        # 形如 #小程序://名称/ERRVozy83KJqNRb —— 后半段是小程序短ID
        if re.fullmatch(r"[A-Za-z0-9_-]{10,24}", path or ""):
            fields["short_id"] = path
            fields["equiv"] = "mp://" + path          # 等价的 mp:// 简写形式
            summ += "   短ID: %s   (等价 mp://%s)" % (path, path)
        elif path:
            summ += "  →  %s" % path
        return {"kind": "xcx_share", "label": "小程序分享文本 #小程序://",
                "summary": summ, "fields": fields}

    # 3) weixin://
    m = RE_WEIXIN.match(t)
    if m:
        route = m.group(1)
        qs = m.group(2) or ""
        desc = ROUTES.get(route) or ROUTES.get(route.rstrip("/")) or "微信内部路由"
        params = _params(qs)
        f = {"route": route, "params": {k: v for (k, _n, v) in params}, "raw": t}
        summ = "%s (%s)" % (desc, route)
        if params:
            bits = []
            for (k, cn, v) in params[:4]:
                bits.append("%s=%s" % (cn or k, v if len(v) < 40 else v[:40] + "…"))
            summ += "  " + " ".join(bits)
        return {"kind": "weixin_route", "label": "微信协议 weixin://",
                "summary": summ, "fields": f}

    # 4) http(s)
    low = t.lower()
    if low.startswith(("http://", "https://")):
        try:
            u = urlparse(t)
            host = (u.hostname or "").lower()
        except Exception:
            host = ""
        if host in WX_HOSTS:
            kind, label = WX_HOSTS[host]
            tail = (u.path or "").lstrip("/")
            if kind == "wechat_short":
                return {"kind": kind, "label": label,
                        "summary": "微信短链，ID: " + tail,
                        "fields": {"id": tail, "host": host, "raw": t}}
            if kind == "mp_article":
                return {"kind": kind, "label": label,
                        "summary": "公众号文章: " + tail,
                        "fields": {"id": tail, "host": host, "raw": t}}
            return {"kind": kind, "label": label,
                    "summary": "%s: %s" % (label, host + (u.path or "")),
                    "fields": {"host": host, "path": u.path or "", "raw": t}}
        return {"kind": "url", "label": "普通网址",
                "summary": "网址: " + (host or t[:60]),
                "fields": {"host": host, "raw": t}}

    # 5) 其它已注册协议
    for scheme, label in (("wxfile://", "微信文件"), ("wemeet://", "腾讯会议"),
                          ("wxwork://", "企业微信"), ("mqqwpa://", "QQ"),
                          ("wedocs://", "腾讯文档"), ("wedrive://", "微云"),
                          ("mailto:", "邮件"), ("tel:", "电话")):
        if low.startswith(scheme):
            return {"kind": "scheme", "label": label,
                    "summary": label + ": " + t[:80],
                    "fields": {"raw": t}}

    # 6) 纯文本
    return {"kind": "text", "label": "文本",
            "summary": t if len(t) <= 60 else t[:60] + "…",
            "fields": {"raw": t}}


# 票据规范：base62，长度可变（实测 15 位：ERRVozy83KJqNRb / odqnJL1jJlsRJaJ /
# lgTRw6MprOKob2f；16 位：j3z9KlIQ3ByLDpev）
TICKET_RE = re.compile(r"^[0-9A-Za-z]{14,20}$")


def build_xcx(name, ticket, query=""):
    """生成 #小程序:// 分享文本。

    算法（本地部分，纯字符串拼接）:
        "#小程序://" + 昵称 + "/" + 票据 [+ "?" + 参数]

    依据：dex 里 "#小程序://" 是独立常量而非 %s 模板，说明是代码拼接；
         同一字符串池旁即 Kotlin 属性 $nickname / $path / $query。
    """
    name = (name or "").strip()
    ticket = (ticket or "").strip()
    if not name or not ticket:
        return ""
    s = "#小程序://%s/%s" % (name, ticket)
    if query:
        s += "?" + query.strip().lstrip("?")
    return s


def build_mp(ticket):
    """生成 mp:// 短形式: "mp://" + 票据"""
    ticket = (ticket or "").strip()
    return "mp://" + ticket if ticket else ""


def check_ticket(ticket):
    """校验票据格式 -> (是否合法, 说明)"""
    t = (ticket or "").strip()
    if not t:
        return False, "票据为空"
    if TICKET_RE.match(t):
        return True, "格式合法（%d 位 base62）" % len(t)
    return False, "格式不符：应为 14~20 位字母数字，当前 %d 位" % len(t)


def gen_ticket():
    """随机生成一个格式合法的票据。仅用于格式测试——服务端不认识，无法打开。"""
    import random
    A = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(random.choice(A) for _ in range(15))


# ---- 小程序标识校验 ----
RE_APPID = re.compile(r"^wx[0-9a-f]{16}$", re.I)
RE_GH = re.compile(r"^gh_[0-9a-f]{12}$", re.I)


def check_appid(appid):
    a = (appid or "").strip()
    if not a:
        return False, "AppID 为空"
    if RE_APPID.match(a):
        return True, "格式合法（wx + 16 位十六进制）"
    return False, "格式不符：应为 wx 开头 + 16 位十六进制，当前 %d 位" % len(a)


def check_gh(gh):
    g = (gh or "").strip().replace("@app", "")
    if not g:
        return False, "原始ID 为空"
    if RE_GH.match(g):
        return True, "格式合法（gh_ + 12 位十六进制）"
    return False, "格式不符：应为 gh_ 开头 + 12 位十六进制，当前 %d 位" % len(g)


def build_jumpwxa(appid, gh, path, invoke_data="", path_type=0, encode_path=False):
    """生成 weixin://dl/jumpWxa/ 小程序唤起链接。

    格式（Android classes8.dex）:
        weixin://dl/jumpWxa/?appid=%s&userName=%s@app&path=%s&invokeData=%s
                            &pathType=%d&runtimeAppid=%s&runtimeTicket=%s&runtimeSessionId=%s
    """
    a = (appid or "").strip()
    u = (gh or "").strip().replace("@app", "")
    p = (path or "").strip()
    if not a or not u or not p:
        return ""
    if encode_path:
        p = quote(p, safe="")
    return ("weixin://dl/jumpWxa/?appid=%s&userName=%s@%%61pp&path=%s&invokeData=%s"
            "&pathType=%d&runtimeAppid=&runtimeTicket=&runtimeSessionId="
            % (a, u, p, invoke_data or "", int(path_type))).replace("%61pp", "app")


def build_share(appid, gh, path, msg_type="", share_type="1"):
    """生成 weixin://dl/business/share/ 分享链接。

    格式（Android classes8.dex）:
        weixin://dl/business/share/?appid=%s&type=%s&txt=%s&url=%s&msgType=%s
                                  &appbrandusername=%s&appbrandpath=%s
                                  &userOpenid=%s&tokenValid=%d
    """
    a = (appid or "").strip()
    u = (gh or "").strip().replace("@app", "")
    p = (path or "").strip()
    if not a or not u or not p:
        return ""
    return ("weixin://dl/business/share/?appid=%s&type=%s&txt=&url=&msgType=%s"
            "&appbrandusername=%s@app&appbrandpath=%s&userOpenid=&tokenValid=0"
            % (a, share_type, msg_type or "", u, quote(p, safe="")))


def to_mp(text):
    """#小程序://名称/ID  或  mp://ID  ->  mp://ID"""
    info = classify(text)
    sid = info["fields"].get("short_id") or info["fields"].get("id")
    if info["kind"] in ("mp_short", "xcx_share", "bare_token") and sid:
        return "mp://" + sid
    return ""


def to_xcx(text, name=None):
    """#小程序://名称/ID  或  mp://ID  ->  #小程序://名称/ID（名称未知时占位）"""
    info = classify(text)
    sid = info["fields"].get("short_id")
    if not sid:
        return ""
    nm = name or info["fields"].get("app_name") or "未知小程序"
    return "#小程序://%s/%s" % (nm, sid)


def wechat_uri(text):
    """把扫码文本转成微信客户端能直接打开的 weixin:// URI。

    依据 Android classes8.dex:
        weixin://dl/scanWxaQrcode?qrcodeText=   <- 客户端拿到码文本后走这个路由
        weixin://dl/jumpWxa/?appid=...          <- 直接跳小程序
    mp:// / #小程序:// / u.wechat.com 短链 都统一走 scanWxaQrcode。
    """
    t = (text or "").strip()
    if not t:
        return ""
    info = classify(t)
    k = info["kind"]
    if k in ("mp_short", "xcx_share", "wechat_short", "weixin_short"):
        return "weixin://dl/scanWxaQrcode?qrcodeText=" + quote(t, safe="")
    return t


def open_external(uri):
    """用系统默认程序打开一个 URI（weixin:// 会拉起微信）。"""
    import ctypes
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", str(uri), None, None, 1)
        return rc > 32
    except Exception:
        return False


def enrich(results):
    """给 decode 结果补上 kind/label/summary。results: [dict(format,text,charset)]"""
    for r in results:
        info = classify(r.get("text", ""))
        r.setdefault("kind", info["kind"])
        r.setdefault("kind_label", info["label"])
        r.setdefault("summary", info["summary"])
    return results
