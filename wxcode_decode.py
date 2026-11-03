# -*- coding: utf-8 -*-
"""葵花码解码器 —— 纯 Python

流程:
  图片 -> 定位 -> 采样 72x16 -> 去掩码 -> 码字 -> 位流 -> 字母数字串 -> 原文
"""

import math
import time

from wxcode_core import (CHARSET45, CHARSET82, VERSION_TABLE,
                         make_bits, rs_parity, _gmul, _EXP, _LOG)
from wxcode_tables import LAYOUTS, data_words, mask_bit

SLOTS = 72
RINGS = 16
BASE_R = 105.0
STEP_R = 10.0
OUTER_R = BASE_R + STEP_R * (RINGS - 1) + 4.875     # 最外层模块外缘 = 259.875


# ---------- 一、图片 -> 矩阵 ----------
def _load_gray(path_or_bytes):
    from PIL import Image
    import io
    if isinstance(path_or_bytes, Image.Image):
        im = path_or_bytes
    else:
        src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
        im = Image.open(src)
    return im.convert("L")


def _bbox_dark(im, thr):
    w, h = im.size
    px = im.load()
    x0, y0, x1, y1 = w, h, -1, -1
    step = max(1, min(w, h) // 400)
    for y in range(0, h, step):
        for x in range(0, w, step):
            if px[x, y] < thr:
                if x < x0: x0 = x
                if y < y0: y0 = y
                if x > x1: x1 = x
                if y > y1: y1 = y
    if x1 < 0:
        return None
    return x0, y0, x1, y1


def _sample(im, cx, cy, scale, slot_off=0, rot=0):
    """在给定中心/缩放下采样矩阵"""
    px = im.load()
    w, h = im.size
    m = [[0] * RINGS for _ in range(SLOTS)]
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    for s in range(SLOTS):
        th = math.radians(((s + slot_off - 36) * 5.0))
        ct, st = math.cos(th), math.sin(th)
        for r in range(RINGS):
            rad = (BASE_R + STEP_R * r) * scale
            dx, dy = rad * ct, rad * st
            x = int(round(cx + dx * ca - dy * sa))
            y = int(round(cy + dx * sa + dy * ca))
            if not (0 <= x < w and 0 <= y < h):
                continue
            dark = 0
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    xx, yy = x + ox, y + oy
                    if 0 <= xx < w and 0 <= yy < h and px[xx, yy] < 128:
                        dark += 1
            m[s][r] = 1 if dark >= 5 else 0
    return m


# ---------- 二、码字 / 校验 ----------
def _syndromes(cw, npar):
    out = []
    for j in range(npar):
        acc = 0
        for b in cw:
            acc = _gmul(acc, _EXP[j]) ^ b
        out.append(acc)
    return out


def _syndrome_zero(cw, npar):
    return not any(_syndromes(cw, npar))


def _inv(a):
    return 0 if a == 0 else _EXP[255 - _LOG[a]]


def _berlekamp_massey(S, npar):
    """返回错误定位多项式 Λ (Λ[0]=1)，长度 <= npar"""
    C = [1] + [0] * npar
    B = [1] + [0] * npar
    L = 0
    m = 1
    b = 1
    for n in range(npar):
        d = S[n]
        for i in range(1, L + 1):
            d ^= _gmul(C[i], S[n - i])
        if d == 0:
            m += 1
        else:
            coef = _gmul(d, _inv(b))
            T = list(C)
            for i in range(npar + 1 - m):
                C[i + m] ^= _gmul(coef, B[i])
            if 2 * L <= n:
                L = n + 1 - L
                B = T
                b = d
                m = 1
            else:
                m += 1
    return C[:L + 1]


def _rs_correct(cw, npar):
    """纠正码字错误，成功返回新码字，失败返回 None"""
    S = _syndromes(cw, npar)
    if not any(S):
        return bytes(cw)
    Lam = _berlekamp_massey(S, npar)
    t = len(Lam) - 1
    if t <= 0 or 2 * t > npar:
        return None
    n = len(cw)
    # Chien 搜索：X = a^(n-1-j)，错误位置满足 Λ(X^-1)=0
    pos = []
    for j in range(n):
        X = _EXP[(n - 1 - j) % 255]
        Xi = _inv(X)
        acc = 0
        p = 1
        for c in Lam:
            acc ^= _gmul(c, p)
            p = _gmul(p, Xi)
        if acc == 0:
            pos.append((j, X))
    if len(pos) != t:
        return None
    # 用前 t 个综合解线性方程求错误幅值
    A = []
    for i in range(t):
        A.append([_EXP[(_LOG[X] * i) % 255] if X else 0 for _, X in pos] + [S[i]])
    for col in range(t):
        pv = None
        for row in range(col, t):
            if A[row][col]:
                pv = row
                break
        if pv is None:
            return None
        A[col], A[pv] = A[pv], A[col]
        iv = _inv(A[col][col])
        A[col] = [_gmul(x, iv) for x in A[col]]
        for row in range(t):
            if row != col and A[row][col]:
                f = A[row][col]
                A[row] = [a ^ _gmul(f, b) for a, b in zip(A[row], A[col])]
    out = bytearray(cw)
    for k, (j, _X) in enumerate(pos):
        out[j] ^= A[k][t]
    if any(_syndromes(out, npar)):
        return None
    return bytes(out)


def _matrix_to_codewords(m, total, k):
    words = data_words(total)
    npar = total - k
    bits = []
    for s in range(SLOTS):
        w = words[s]
        for r in range(RINGS):
            if (w >> r) & 1:
                bits.append(m[s][r])
    out = []
    for i in range(0, len(bits) - 7, 8):
        v = 0
        for j in range(8):
            v = (v << 1) | bits[i + j]
        out.append(v)
    return bytes(out)


_K_CAND = [14, 20, 25, 35, 43, 46, 30, 38, 41]


def _try_decode_matrix(m):
    """矩阵 -> 文字；尝试全部版式与掩码"""
    for total in (38, 52, 66):
        words = data_words(total)
        idxs = [(s, r) for s in range(SLOTS) for r in range(RINGS) if (words[s] >> r) & 1]
        if len(idxs) < total * 8:
            continue
        base = bytearray(total)
        for i, (s, r) in enumerate(idxs):
            if m[s][r]:
                base[i >> 3] |= 1 << (7 - (i & 7))
        for k in _K_CAND:
            if k >= total - 2:
                continue
            npar = total - k
            for mi in range(32):
                cw = bytearray(base)
                for i, (s, r) in enumerate(idxs):
                    if mask_bit(mi, s, r):
                        cw[i >> 3] ^= 1 << (7 - (i & 7))
                fixed = _rs_correct(cw, npar)
                if fixed is not None:
                    txt = _parse_payload(fixed, k, total)
                    if txt is not None:
                        return txt
    return None


# ---------- 三、位流 -> 原文 ----------
def _bits_of(cw, k):
    b = "".join(format(x, "08b") for x in cw[:k])
    return b


def _parse_payload(cw, k, total):
    b = _bits_of(cw, k)
    if len(b) < 14:
        return None
    mode = int(b[:4], 2)
    if mode == 1:
        return _parse_numeric(b)
    if mode == 2:
        return _parse_alnum(b)
    return None


def _parse_numeric(b):
    if len(b) < 14:
        return None
    cnt = int(b[4:14], 2)
    if cnt <= 0 or cnt > 80:
        return None
    pos = 14
    out = []
    left = cnt
    while left >= 3:
        if pos + 10 > len(b):
            return None
        out.append("%03d" % int(b[pos:pos + 10], 2))
        pos += 10
        left -= 3
    if left == 2:
        out.append("%02d" % int(b[pos:pos + 7], 2))
    elif left == 1:
        out.append("%d" % int(b[pos:pos + 4], 2))
    s = "".join(out)
    return s if s.isdigit() else None


def _parse_alnum(b):
    cnt = int(b[4:13], 2)
    if cnt <= 0 or cnt > 90:
        return None
    pos = 13
    idx = []
    left = cnt
    while left >= 2:
        if pos + 11 > len(b):
            return None
        v = int(b[pos:pos + 11], 2)
        if v >= 45 * 45:
            return None
        idx.append(v // 45)
        idx.append(v % 45)
        pos += 11
        left -= 2
    if left == 1:
        if pos + 6 > len(b):
            return None
        v = int(b[pos:pos + 6], 2)
        if v >= 45:
            return None
        idx.append(v)
    alnum = "".join(CHARSET45[i] for i in idx)
    return _alnum_to_text(alnum)


# ---------- 四、字母数字串 -> 原文（正向有损，用候选枚举 + 验证） ----------
def _enumerate_bytes(target, maxbytes, limit=4.0, cap=64):
    tgt = [CHARSET45.index(c) for c in target]
    n = len(tgt)
    out = []
    t0 = time.time()

    def dfs(bs, eax, dg):
        if time.time() - t0 > limit or len(out) > cap:
            return
        m = len(dg)
        for i in range(m):
            if dg[i] != tgt[n - 1 - i]:
                return
        if m == n - 1 and eax == tgt[0]:
            out.append(list(bs))
            return
        if m >= n or len(bs) >= maxbytes:
            return
        bs.append(0)
        for b in range(256):
            bs[-1] = b
            v = (eax * 256 + b) & 0xFFFFFFFF
            added = []
            t = v
            while t >= 45:
                added.append(t % 45)
                t //= 45
            if len(dg) + len(added) > n:
                continue
            okk = True
            for j, d in enumerate(added):
                if d != tgt[n - 1 - (len(dg) + j)]:
                    okk = False
                    break
            if okk:
                dfs(bs, t, dg + added)
            if len(out) > cap or time.time() - t0 > limit:
                break
        bs.pop()

    dfs([], 0, [])
    return out


def _invertA(body, maxlen=48, limit=2.0):
    target = list(body)[::-1]
    n = len(target)
    sols = []
    best = [maxlen + 1]
    t0 = time.time()

    def done(pos, eax):
        if pos == n and eax == 0:
            return True
        if pos == n - 1 and eax == target[pos]:
            return True
        return False

    def dfs(pos, eax, nd, path):
        if time.time() - t0 > limit or nd > best[0] or nd > maxlen:
            return
        if done(pos, eax):
            if nd < best[0]:
                best[0] = nd
                del sols[:]
            if nd == best[0]:
                sols.append(list(path))
            return
        if pos >= n:
            return
        for d in range(82):
            v = (eax * 82 + d) & 0xFFFFFFFF
            nb = []
            t = v
            while t >= 256:
                nb.append(t & 0xFF)
                t >>= 8
            if len(nb) > n - pos:
                continue
            if target[pos:pos + len(nb)] != nb:
                continue
            if not nb and eax == 0 and d == 0:
                continue
            path.append(d)
            dfs(pos + len(nb), t, nd + 1, path)
            path.pop()

    dfs(0, 0, 0, [])
    return sols


def _alnum_to_text(alnum):
    from wxcode_core import text_to_bytes, bytes_to_b45
    best = None
    for maxb in range(len(alnum) + 2, len(alnum) + 6):
        for bc in _enumerate_bytes(alnum, maxb):
            if not bc or bc[0] != 0:
                continue
            for sol in _invertA(bc[1:]):
                cand = "".join(CHARSET82[d] for d in sol)
                if bytes_to_b45(text_to_bytes(cand)) == alnum:
                    if best is None or len(cand) < len(best):
                        best = cand
        if best:
            return best
    return best


# ---------- 五、对外接口 ----------
def _outer_radius(im, cx, cy, thr=128):
    """径向扫描，返回最外层暗环半径（用于估算比例）"""
    w, h = im.size
    px = im.load()
    rmax = int(min(w, h) / 2) - 1
    last = 0
    for R in range(rmax, 3, -1):
        dark = 0
        n = 0
        for a in range(0, 360, 3):
            x = int(cx + R * math.cos(math.radians(a)))
            y = int(cy + R * math.sin(math.radians(a)))
            if 0 <= x < w and 0 <= y < h:
                n += 1
                if px[x, y] < thr:
                    dark += 1
        if n and dark * 10 >= n:      # 该环暗占比 >= 10%
            last = R
            break
    return last


def decode_image(path_or_bytes):
    """返回解出的文字，失败返回 None"""
    im = _load_gray(path_or_bytes)
    w, h = im.size
    cx, cy = w / 2.0, h / 2.0

    R = _outer_radius(im, cx, cy)
    cands = []
    if R:
        base = R / OUTER_R
        for k in (1.0, 0.99, 1.01, 0.98, 1.02):
            cands.append((cx, cy, base * k))
    bb = _bbox_dark(im, 128)
    if bb:
        x0, y0, x1, y1 = bb
        bx, by = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        for f in (1.0, 1.02, 1.04, 1.06, 1.08):
            cands.append((bx, by, (max(x1 - x0, y1 - y0) / 2.0) / OUTER_R * f))
    for cxx, cyy, sc in cands:
        for off in range(SLOTS):
            m = _sample(im, cxx, cyy, sc, off)
            t = _try_decode_matrix(m)
            if t:
                return t
    return None
