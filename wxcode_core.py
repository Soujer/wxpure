# -*- coding: utf-8 -*-
"""微信葵花码 (WX_CODE) 编码核心 —— 纯 Python，不依赖任何 DLL

流程:
  文字 -> 字母数字串 -> 位流 -> 数据码字 -> RS 纠错 -> 完整码字流

已与 wxocr.dll 逐字节比对验证:
  字母数字模式 13/13 精确匹配, 数字模式 6/6, 跨版本 6/6 完全一致
"""

CHARSET82 = ("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
             "!#$&'()*+,/:;=?@-._~")
CHARSET45 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"

_M = 0xFFFFFFFF

# 版本选择表: (位流需要位数的上限, 总码字, 数据码字)
# (位流需要位数的上限, 总码字, 数据码字) —— 均已与 DLL 验证的版式
VERSION_TABLE = [
    (112, 38, 14),
    (160, 38, 20),
    (200, 38, 25),
    (280, 52, 35),
    (344, 66, 43),
]


# ---------- 文字 -> 字母数字串（截断 Horner 两步） ----------
def text_to_bytes(text):
    eax, out = 0, []
    for ch in text:
        d = CHARSET82.find(ch)
        if d < 0:
            raise ValueError("字符 %r 不在支持的字符集内" % ch)
        eax = (eax * 82 + d) & _M
        while eax >= 256:
            out.append(eax & 0xFF)
            eax >>= 8
    if eax:
        out.append(eax)
    out.reverse()
    return bytes([0x00] + out)


def bytes_to_b45(bs):
    eax, out = 0, []
    for b in bs:
        eax = (eax * 256 + b) & _M
        while eax >= 45:
            out.append(eax % 45)
            eax //= 45
    if eax:
        out.append(eax)
    out.reverse()
    return "".join(CHARSET45[i] for i in out)


def text_to_alnum(text):
    return bytes_to_b45(text_to_bytes(text))


# ---------- 位流 ----------
def bits_numeric(text):
    b = format(1, "04b") + format(len(text), "010b")
    i = 0
    while i + 3 <= len(text):
        b += format(int(text[i:i + 3]), "010b")
        i += 3
    r = len(text) - i
    if r == 2:
        b += format(int(text[i:i + 2]), "07b")
    elif r == 1:
        b += format(int(text[i:i + 1]), "04b")
    return b


def bits_alnum(s):
    idx = [CHARSET45.index(c) for c in s]
    b = format(2, "04b") + format(len(s), "09b")
    i = 0
    while i + 1 < len(idx):
        b += format(idx[i] * 45 + idx[i + 1], "011b")
        i += 2
    if i < len(idx):
        b += format(idx[i], "06b")
    return b


def make_bits(text):
    return bits_numeric(text) if text.isdigit() else bits_alnum(text_to_alnum(text))


# ---------- 数据码字 ----------
def make_data_codewords(text, k):
    bits = make_bits(text)
    room = k * 8 - len(bits)
    if room < 0:
        raise ValueError("载荷过长")
    bits += "0" * min(4, room)
    while len(bits) % 8:
        bits += "0"
    out = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    p = 0
    while len(out) < k:
        out.append(0xEC if p % 2 == 0 else 0x11)
        p += 1
    return bytes(out)


# ---------- RS 纠错（GF 256 / 0x11D） ----------
def _make_gf(poly=0x11D):
    exp, log = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        exp[i], log[x] = x, i
        x <<= 1
        if x & 0x100:
            x ^= poly
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _make_gf()


def _gmul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def rs_parity(data, nsym):
    gen = [1]
    for i in range(nsym):
        g = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            g[j] ^= c
            g[j + 1] ^= _gmul(c, _EXP[i])
        gen = g
    msg = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = msg[i]
        if coef:
            for j in range(1, len(gen)):
                msg[i + j] ^= _gmul(gen[j], coef)
    return bytes(msg[len(data):])


# ---------- 对外接口 ----------
def pick_layout(text):
    """返回 (总码字, 数据码字, 校验码字)"""
    need = len(make_bits(text))
    for lim, total, k in VERSION_TABLE:
        if need <= lim:
            return total, k, total - k
    raise ValueError("载荷过长（需要 %d 位，上限 %d 位）" % (need, VERSION_TABLE[-1][0]))


def encode_codewords(text):
    """文字 -> 完整码字流（数据码字 + RS 校验码字）"""
    total, k, nsym = pick_layout(text)
    data = make_data_codewords(text, k)
    return data + rs_parity(data, nsym)
