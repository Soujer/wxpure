# -*- coding: utf-8 -*-
"""抖音圆码 (BEF_CODE_TYPE_DY_CODE) 编码核心 —— 纯 Python

结构与微信葵花码同族（同一套“环形码”框架），但版式不同：
  · 每环 120 个模块（3°/模块），版本 3
  · 格式码 4/5/6 -> 3/4/5 条数据环；默认 5 = 4 环 = RS(52,40)
  · 载荷 = QR 字节模式位流（4 位模式 + 8 位长度 + UTF-8 + 终止符 + 0xEC/0x11 填充）
  · 每环有结构掩码：定位环、间隙、格式字段 15 位、参数字段 18 位
  · 位到模块的位置由 scramble 置换打乱，再按 mask_predicate 异或

实测/移植依据：ikenxuan/qrcode (MIT) 的 packages/wasm/src/dy/{encoder,layout,gf256}.rs
"""

# ---------------- GF(256) / RS ----------------
_POLY = 0x11D
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= _POLY
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def gmul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def rs_encode(message, nsym, fcr=0):
    g = [1]
    for j in range(nsym):
        root = _EXP[(fcr + j) % 255]
        nxt = [0] * (len(g) + 1)
        for i, c in enumerate(g):
            nxt[i] ^= c
            nxt[i + 1] ^= gmul(c, root)
        g = nxt
    work = list(message) + [0] * nsym
    for i in range(len(message)):
        c = work[i]
        if c:
            for j, gj in enumerate(g):
                work[i + j] ^= gmul(gj, c)
    return bytes(list(message) + work[len(work) - nsym:])


# ---------------- 版式静态表 ----------------
RING_MODULES = 120
MAX_RINGS = 5

STRUCT_MASKS = [
    [0xff, 0x3f, 0xff, 0xff, 0xff, 0xcf, 0xff, 0xff, 0xff, 0xf3, 0xff, 0xff, 0x07, 0x80, 0xff],
    [0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x3f, 0xf0, 0xff],
    [0xff] * 15,
    [0xff] * 15,
]


def _mask_bits(m):
    return [((m[i >> 3] >> (i & 7)) & 1) for i in range(RING_MODULES)]


STRUCT_BITS = [_mask_bits(m) for m in STRUCT_MASKS] + [[1] * RING_MODULES]

FORMAT_START, FORMAT_LEN, FORMAT_XOR = 105, 15, 0x6492
FORMAT_CODEWORDS = [0x0537, 0x0a6e, 0x0f59, 0x11eb, 0x14dc, 0x1b85]

FIELD18_START, FIELD18_LEN = 45, 18
FIELD18_FALLBACK_XOR = 0x25412
CW18 = [
    0x00000, 0x01f25, 0x0216f, 0x03e4a, 0x042de, 0x05dfb, 0x063b1, 0x07c94, 0x085bc, 0x09a99,
    0x0a4d3, 0x0bbf6, 0x0c762, 0x0d847, 0x0e60d, 0x0f928, 0x10b78, 0x1145d, 0x12a17, 0x13532,
    0x149a6, 0x15683, 0x168c9, 0x177ec, 0x18ec4, 0x191e1, 0x1afab, 0x1b08e, 0x1cc1a, 0x1d33f,
    0x1ed75, 0x1f250, 0x209d5, 0x216f0, 0x228ba, 0x2379f, 0x24b0b, 0x2542e, 0x26a64, 0x27541,
    0x28c69, 0x2934c, 0x2ad06, 0x2b223, 0x2ceb7, 0x2d192, 0x2efd8, 0x2f0fd, 0x302ad, 0x31d88,
    0x323c2, 0x33ce7, 0x34073, 0x35f56, 0x3611c, 0x37e39, 0x38711, 0x39834, 0x3a67e, 0x3b95b,
    0x3c5cf, 0x3daea, 0x3e4a0, 0x3fb85,
]

T_EVEN = [0, 2, 1, 3]
T_ODD = [2, 0, 3, 1]

# RS 布局: format_code -> [(ecc, blocks, data), ...]
RS_LAYOUTS = {
    4: [(8, 1, 29)],
    5: [(12, 1, 40)],
    6: [(14, 1, 53)],
}
FORMAT_RINGS = {4: 3, 5: 4, 6: 5}
FIXED_DARK = [(0, 100), (0, 109)]


def mask_predicate(mask_id, w):
    if mask_id == 0:
        return w & 1
    if mask_id == 1:
        return w % 3
    if mask_id == 2:
        return (w & (w - w // 3)) & 1
    if mask_id == 3:
        return (w % 3) & (w % 5)
    if mask_id == 4:
        return (w & (w + w // 7)) & 1
    if mask_id == 5:
        return (w % 3) & (w % 7)
    if mask_id == 6:
        return ((w & (w - w // 3)) & (w - w // 5)) & 1
    if mask_id in (7, 8):
        return ((w & (w - w // 5)) & (w + w // 7)) & 1
    return 0


def scrambled_positions(mask_id, ring_count, modules_per_ring=RING_MODULES):
    t = T_ODD if mask_id & 1 else T_EVEN
    step = modules_per_ring // 4
    ring_period = 2 * step * ring_count
    out = []
    for w2 in range(modules_per_ring * ring_count):
        w9 = w2 // step
        w12 = ((w9 % 2) + 2 * (w9 // (2 * ring_count))) % 4
        ring = (w2 % ring_period) // (2 * step)
        w21 = step * t[w12] + (w2 % step)
        out.append((ring, w21))
    return out


def collect_positions(struct_bits, start, count):
    pos, i = [], start
    for _ in range(RING_MODULES * 4):
        j = i % RING_MODULES
        if struct_bits[j]:
            pos.append(j)
            if len(pos) == count:
                return pos
        i += 1
    return pos


# ---------------- 编码 ----------------
def build_message(text, capacity):
    data = text.encode("utf-8")
    if not data:
        raise ValueError("文本不能为空")
    if len(data) > capacity - 2:
        raise ValueError("文本过长：UTF-8 %d 字节，当前版式上限 %d 字节" % (len(data), capacity - 2))
    bits = [0, 1, 0, 0]                     # 0100 字节模式
    bits += [(len(data) >> s) & 1 for s in range(7, -1, -1)]
    for b in data:
        bits += [(b >> s) & 1 for s in range(7, -1, -1)]
    cap = capacity * 8
    bits += [0] * min(4, max(0, cap - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    if len(bits) > cap:
        raise ValueError("文本过长")
    out = []
    for i in range(0, len(bits), 8):
        v = 0
        for b in bits[i:i + 8]:
            v = (v << 1) | b
        out.append(v)
    pad = 0
    for i in range(len(bits) // 8, capacity):
        out.append(0xEC if pad % 2 == 0 else 0x11)
        pad += 1
    return bytes(out)


def encode(text, format_code=None, param=20, field_xor=True):
    """返回 dict(rings, payload, message, format_code, param, mask_id, ring_count)"""
    if not 0 <= param <= 63:
        raise ValueError("param 必须是 0..63")
    if format_code is None:
        format_code = 6 if len(text.encode("utf-8")) > 38 else 5
    if format_code not in RS_LAYOUTS:
        raise ValueError("只实现格式码 4..6（版本 3）；格式码 %s 属于版本 5" % format_code)

    layout = RS_LAYOUTS[format_code]
    capacity = sum(b * (d + e) for e, b, d in layout)
    total_data = sum(b * d for e, b, d in layout)

    message = build_message(text, total_data)

    payload = bytearray(capacity)
    off = 0
    moff = 0
    for ecc, blocks, data_len in layout:
        block_size = data_len + ecc
        for blk in range(blocks):
            chunk = message[moff:moff + data_len]
            enc = rs_encode(chunk, ecc)
            payload[off + blk * block_size: off + blk * block_size + len(enc)] = enc
            moff += data_len
        off += blocks * block_size

    ring_count = FORMAT_RINGS[format_code]
    mask_id = param & 0x0F

    masks = [list(STRUCT_BITS[r]) for r in range(ring_count)]
    fmt_pos = collect_positions(STRUCT_BITS[0], FORMAT_START, FORMAT_LEN)
    fld_pos = collect_positions(STRUCT_BITS[1], FIELD18_START, FIELD18_LEN)
    for p in fmt_pos:
        masks[0][p] = 0
    for p in fld_pos:
        masks[1][p] = 0

    rings = [list(m) for m in masks]
    for r, p in FIXED_DARK:
        if r < ring_count:
            rings[r][p] = 1

    v15 = FORMAT_CODEWORDS[format_code - 1] ^ FORMAT_XOR
    n = len(fmt_pos)
    for i, p in enumerate(fmt_pos):
        rings[0][p] = (v15 >> (n - 1 - i)) & 1

    v18 = CW18[param] ^ (FIELD18_FALLBACK_XOR if field_xor else 0)
    n = len(fld_pos)
    for i, p in enumerate(fld_pos):
        rings[1][p] = (v18 >> (n - 1 - i)) & 1

    bits = []
    for byte in payload:
        bits += [(byte >> s) & 1 for s in range(7, -1, -1)]

    idx = 0
    for (ring, pos) in scrambled_positions(mask_id, ring_count):
        if masks[ring][pos] == 0:
            continue
        if idx >= len(bits):
            rings[ring][pos] = 0
            idx += 1
            continue
        bit = bits[idx]
        idx += 1
        if mask_predicate(mask_id, pos) == 0:
            bit ^= 1
        rings[ring][pos] = bit

    return {
        "rings": rings,
        "payload": bytes(payload),
        "message": message,
        "format_code": format_code,
        "param": param,
        "mask_id": mask_id,
        "ring_count": ring_count,
    }


if __name__ == "__main__":
    r = encode("https://bing.com")
    print("format", r["format_code"], "rings", r["ring_count"], "param", r["param"], "mask", r["mask_id"])
    print("message", len(r["message"]), "payload", len(r["payload"]))
    print("payload hex:", r["payload"].hex())
