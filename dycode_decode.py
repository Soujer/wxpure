# -*- coding: utf-8 -*-
"""抖音圆码解码 —— 纯 Python

流程（编码的逆过程）：
  1. 定位：优先找中心暗圆盘（作品分享码），拿不到再按"图像居中 + 尺度搜索"；
  2. 由圆盘半径推各环半径（环/盘比例与设计一致）；
  3. 逐环采 120 个模块（3°/模块），旋转 120 种候选；
  4. 环0 取 15 位格式字段（^0x6492）→ 汉明距离≤3 → 格式码 → 环数/RS 布局；
  5. 环1 取 18 位参数字段（可 ^0x25412 反码）→ 参数 → 掩码 id；
  6. 按 scramble 逆序取位、去掩码 → 载荷码字 → RS 纠错；
  7. 按 QR 字节模式解析出文本。
"""
import io
import math

import numpy as np
from PIL import Image

import dycode_core as core

# ---- 环半径 / 圆盘半径（设计常量，与 layout.rs 一致）----
try:
    import dycode_draw as _draw
    _RAD = _draw.RADII
    _DISC = _draw.DISC
    RING_RADII = {k: [ratio * 100.0 for ratio in v] for k, v in _RAD.items()}
    DISC_RADIUS = {k: v * 100.0 for k, v in _DISC.items()}
except Exception:  # 保底：设计常量
    RING_RADII = {3: [86.4, 71.45, 63.45], 4: [86.4, 71.45, 63.45, 55.45],
                  5: [86.4, 71.45, 63.45, 55.45, 47.45]}
    DISC_RADIUS = {3: 48.36, 4: 48.36, 5: 43.5}
N_MOD = 120

FORMAT_MAX_HAMMING = 3
FIELD_MAX_HAMMING = 3


# ------------------------- GF(256) / RS 纠错 -------------------------
def _poly_eval(coeffs, x):
    y = 0
    for c in coeffs:
        y = core.gmul(y, x) ^ c
    return y


def _syndromes(codeword, nsym):
    return [_poly_eval(codeword, core._EXP[j % 255]) for j in range(nsym)]


def _hamming(a, b):
    v = a ^ b
    return bin(v).count("1")


def _bits_to_int(bits, positions):
    v = 0
    for p in positions:
        v = (v << 1) | (int(bits[p]) & 1)
    return v


def _berlekamp_massey(synd):
    lam = [1]
    prev = [1]
    L, m, b = 0, 1, 1
    for n in range(len(synd)):
        d = synd[n]
        for i in range(1, L + 1):
            if i < len(lam):
                d ^= core.gmul(lam[i], synd[n - i])
        if d == 0:
            m += 1
            continue
        coef = core._EXP[(core._LOG[d] - core._LOG[b]) % 255] if b else 0
        shifted = [0] * m + prev
        nxt = lam + [0] * max(0, len(shifted) - len(lam))
        for i in range(len(shifted)):
            nxt[i] ^= core.gmul(coef, shifted[i])
        if 2 * L <= n:
            L = n + 1 - L
            prev = lam
            b = d
            m = 1
        else:
            m += 1
        lam = nxt
    while len(lam) > 1 and lam[-1] == 0:
        lam.pop()
    return lam


def rs_correct(codeword, nsym):
    """返回 (纠正后的码字, 错误数) 或 None"""
    synd = _syndromes(codeword, nsym)
    if not any(synd):
        return list(codeword), 0
    lam = _berlekamp_massey(synd)
    nerr = len(lam) - 1
    if nerr == 0 or 2 * nerr > nsym:
        return None
    n = len(codeword)
    lam_rev = lam[::-1]
    positions = []
    for i in range(n):
        x = core._EXP[(n - 1 - i) % 255]
        xinv = core._EXP[(255 - core._LOG[x]) % 255]
        if _poly_eval(lam_rev, xinv) == 0:
            positions.append((i, x))
    if len(positions) != nerr:
        return None
    omega = [0] * nsym
    for i, sc in enumerate(synd):
        if sc == 0:
            continue
        for j, lj in enumerate(lam):
            if i + j < nsym:
                omega[i + j] ^= core.gmul(sc, lj)
    dlam = [0] * max(0, len(lam) - 1)
    for i in range(1, len(lam)):
        if i & 1:
            dlam[i - 1] = lam[i]
    omega_rev = omega[::-1]
    dlam_rev = dlam[::-1]
    out = list(codeword)
    for index, x in positions:
        xinv = core._EXP[(255 - core._LOG[x]) % 255]
        num = _poly_eval(omega_rev, xinv)
        den = _poly_eval(dlam_rev, xinv)
        if den == 0:
            return None
        mag = core.gmul(x, core._EXP[(core._LOG[num] - core._LOG[den]) % 255] if num else 0)
        out[index] ^= mag
    if any(_syndromes(out, nsym)):
        return None
    return out, nerr


# ------------------------- 图像处理 -------------------------
def _load(src):
    """读入并归一化：透明底合成白底，小图放大到 800 长边"""
    if isinstance(src, (bytes, bytearray)):
        im = Image.open(io.BytesIO(src))
    else:
        im = Image.open(src)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        g = bg.convert("L")
    else:
        g = im.convert("L")
    m = min(g.size)
    if m < 600:
        k = 800.0 / m
        g = g.resize((int(g.width * k), int(g.height * k)), Image.LANCZOS)
    return g


def _find_dark_disc(gray):
    """找最大的近圆形暗色连通块，返回 (cx, cy, r) 或 None"""
    a = np.asarray(gray).astype(np.float32)
    h, w = a.shape
    ink = a < 110
    # 逐行扫一遍做粗略的连通域（8 邻接，用 BFS）
    seen = np.zeros((h, w), dtype=bool)
    best = None
    for y in range(0, h):
        row = ink[y]
        if not row.any():
            continue
        xs = np.nonzero(row & ~seen[y])[0]
        for x0 in xs:
            if seen[y, x0]:
                continue
            stack = [(y, x0)]
            seen[y, x0] = True
            area = 0
            sx = sy = 0
            minx, maxx, miny, maxy = x0, x0, y, y
            while stack:
                cy_, cx_ = stack.pop()
                area += 1
                sx += cx_
                sy += cy_
                if cx_ < minx: minx = cx_
                if cx_ > maxx: maxx = cx_
                if cy_ < miny: miny = cy_
                if cy_ > maxy: maxy = cy_
                for dy in (-1, 0, 1):
                    ny = cy_ + dy
                    if ny < 0 or ny >= h:
                        continue
                    for dx in (-1, 0, 1):
                        nx = cx_ + dx
                        if nx < 0 or nx >= w:
                            continue
                        if ink[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            bw = maxx - minx + 1
            bh = maxy - miny + 1
            if area < (min(h, w) ** 2) * 0.01:
                continue
            fill = area / float(bw * bh)
            if not (0.6 < fill < 0.95):
                continue
            if abs(bw - bh) > 0.35 * max(bw, bh):
                continue
            r = (bw + bh) / 4.0          # 用外接框估半径（避开内部白环/图标的影响）
            if best is None or area > best[0]:
                best = (area, sx / area, sy / area, r)
    return None if best is None else (best[1], best[2], best[3])


def _sample_ring(ink, cx, cy, r, rotation):
    th = (np.arange(N_MOD) + 0.5 + rotation) * 2 * math.pi / N_MOD
    xs = cx + r * np.cos(th)
    ys = cy + r * np.sin(th)
    h, w = ink.shape
    xi = np.clip(xs.astype(int), 0, w - 1)
    yi = np.clip(ys.astype(int), 0, h - 1)
    # 3x3 多数投票
    acc = np.zeros(N_MOD)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            acc += ink[np.clip(yi + dy, 0, h - 1), np.clip(xi + dx, 0, w - 1)]
    return (acc >= 5).astype(np.uint8)


def _fmt_positions():
    return core.collect_positions(core.STRUCT_BITS[0], core.FORMAT_START, core.FORMAT_LEN)


def _fld_positions():
    return core.collect_positions(core.STRUCT_BITS[1], core.FIELD18_START, core.FIELD18_LEN)


def _sample_all_rotations(ink, cx, cy, r):
    """一次采样 120 个旋转位姿：返回 (120, 120) 的 0/1 矩阵 [rot, module]"""
    h, w = ink.shape
    js = np.arange(N_MOD)
    out = np.zeros((N_MOD, N_MOD), dtype=np.uint8)
    th0 = (js + 0.5) * 2 * math.pi / N_MOD
    for rot in range(N_MOD):
        th = th0 + rot * 2 * math.pi / N_MOD
        xs = cx + r * np.cos(th)
        ys = cy + r * np.sin(th)
        xi = np.clip(xs.astype(int), 0, w - 1)
        yi = np.clip(ys.astype(int), 0, h - 1)
        acc = np.zeros(N_MOD)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                acc += ink[np.clip(yi + dy, 0, h - 1), np.clip(xi + dx, 0, w - 1)]
        out[rot] = (acc >= 5).astype(np.uint8)
    return out


def _try_decode_at(ink, cx, cy, disc_r, verbose=False):
    """在给定圆心/圆盘半径下尝试解码，返回结果 dict 或 None"""
    fmt_pos = _fmt_positions()
    fld_pos = _fld_positions()
    for ring_count in (4, 5, 3):
        scale = disc_r / DISC_RADIUS[ring_count]
        radii = [r * scale for r in RING_RADII[ring_count]]
        bits0 = _sample_all_rotations(ink, cx, cy, radii[0])
        values = [(_bits_to_int(bits0[rot], fmt_pos) ^ core.FORMAT_XOR, rot)
                  for rot in range(N_MOD)]
        cands = []
        for v, rot in values:
            bd, bfc = 99, 0
            for idx, cw in enumerate(core.FORMAT_CODEWORDS):
                d = _hamming(v, cw)
                if d < bd:
                    bd, bfc = d, idx + 1
            if bd <= FORMAT_MAX_HAMMING and core.FORMAT_RINGS.get(bfc) == ring_count:
                cands.append((bd, bfc, rot))
        if not cands:
            continue
        cands.sort()
        for bd, best_fc, rot in cands[:3]:
            bits1 = _sample_all_rotations(ink, cx, cy, radii[1])[rot]
            raw = _bits_to_int(bits1, fld_pos)
            param = None
            for cand in (raw, raw ^ core.FIELD18_FALLBACK_XOR):
                bi, bdd = 0, 99
                for idx, cw in enumerate(core.CW18):
                    d = _hamming(cand, cw)
                    if d < bdd:
                        bi, bdd = idx, d
                if bdd <= FIELD_MAX_HAMMING:
                    param = bi
                    break
            if param is None:
                continue
            mask_id = param & 0x0F
            rings = [_sample_all_rotations(ink, cx, cy, radii[k])[rot]
                     for k in range(ring_count)]
            masks = [list(core.STRUCT_BITS[k]) for k in range(ring_count)]
            for pp in fmt_pos:
                masks[0][pp] = 0
            for pp in fld_pos:
                masks[1][pp] = 0
            bits = []
            for (ring, pos) in core.scrambled_positions(mask_id, ring_count):
                if masks[ring][pos] == 0:
                    continue
                b = int(rings[ring][pos])
                if core.mask_predicate(mask_id, pos) == 0:
                    b ^= 1
                bits.append(b)
            payload = bytearray()
            for i in range(0, len(bits) - 7, 8):
                v8 = 0
                for k in range(8):
                    v8 = (v8 << 1) | bits[i + k]
                payload.append(v8)
            layout = core.RS_LAYOUTS[best_fc]
            total = sum(b * (d + e) for e, b, d in layout)
            payload = payload[:total]
            msg = bytearray()
            off = 0
            okall = True
            for ecc, blocks, dlen in layout:
                bs = dlen + ecc
                for _ in range(blocks):
                    block = list(payload[off:off + bs])
                    res = rs_correct(block, ecc) if ecc else (block, 0)
                    if res is None:
                        okall = False
                        break
                    msg.extend(res[0][:dlen])
                    off += bs
                if not okall:
                    break
            if not okall:
                continue
            text = _parse_bitstream(bytes(msg))
            if text is None:
                continue
            if verbose:
                print("hit: fc=%d param=%d mask=%d rot=%d hd=%d" % (best_fc, param, mask_id, rot, bd))
            return {"text": text, "format_code": best_fc, "param": param,
                    "mask_id": mask_id, "ring_count": ring_count,
                    "rotation": rot, "circle": (cx, cy, disc_r * scale)}
    return None


def _parse_bitstream(msg):
    bits = []
    for byte in msg:
        bits += [(byte >> s) & 1 for s in range(7, -1, -1)]
    if len(bits) < 12:
        return None
    mode = 0
    for i in range(4):
        mode = (mode << 1) | bits[i]
    if mode != 4:
        return None
    n = 0
    for i in range(4, 12):
        n = (n << 1) | bits[i]
    if n == 0 or 12 + 8 * n > len(bits):
        return None
    data = bytearray()
    for i in range(n):
        v = 0
        for k in range(8):
            v = (v << 1) | bits[12 + 8 * i + k]
        data.append(v)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode(src, verbose=False):
    """src: 图片路径或 bytes；成功返回 dict，失败返回 None"""
    gray = _load(src)
    a = np.asarray(gray).astype(np.float32)
    ink = a < 128
    h, w = ink.shape
    m = min(w, h)

    anchors = []
    disc = _find_dark_disc(gray)
    if disc:
        cx, cy, r = disc
        for f in np.arange(0.90, 1.101, 0.01):
            anchors.append((cx, cy, r * f))

    # 居中扫描：圆盘半径从 10% 到 46%，覆盖官方/第三方各种版式
    ccx, ccy = w / 2.0, h / 2.0
    for frac in np.arange(0.10, 0.465, 0.004):
        anchors.append((ccx, ccy, m * frac))

    for (cx, cy, r) in anchors:
        res = _try_decode_at(ink, cx, cy, r, verbose)
        if res:
            return res
    return None


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        r = decode(p, verbose=True)
        print(p, "->", r and r["text"], r and ("fc=%d ring=%d" % (r["format_code"], r["ring_count"])))
