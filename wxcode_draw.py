# -*- coding: utf-8 -*-
"""葵花码矩阵与图形渲染 —— 纯 Python

几何:
  72 个槽（角度步长 5°），16 个环（半径 105 + 10*k）
  槽 slot 的角度 = (slot - 36) * 5 度
  模块索引 i = slot * 16 + ring
"""

import math
from wxcode_core import encode_codewords, pick_layout
from wxcode_tables import fixed_bit, mask_bit, data_words, mask_for

SLOTS = 72
RINGS = 16
BASE_R = 105.0
STEP_R = 10.0
DOT_R = 4.875
BR_BLANK_RATIO = 1.36      # 右下角 logo 外围白色留白直径 / logo 直径

# 掩码由模板固化，按版式自动配套


def build_matrix(text, mask_id=None):
    """返回 72x16 矩阵, matrix[slot][ring] = 1 表示暗"""
    total, k, nsym = pick_layout(text)
    if mask_id is None:
        mask_id = mask_for(total, k)
    cw = encode_codewords(text)
    words = data_words(total)
    bits = "".join(format(b, "08b") for b in cw)
    m = [[0] * RINGS for _ in range(SLOTS)]
    n = 0
    for slot in range(SLOTS):
        w = words[slot]
        for ring in range(RINGS):
            if (w >> ring) & 1:
                d = int(bits[n])
                n += 1
                m[slot][ring] = d ^ mask_bit(mask_id, slot, ring)
            else:
                m[slot][ring] = fixed_bit(total, k, slot, ring)
    return m


def module_xy(slot, ring, size=660.0, cx=None, cy=None):
    """模块中心的画布坐标"""
    if cx is None:
        cx = size / 2.0
    if cy is None:
        cy = size / 2.0
    sc = size / 660.0
    th = math.radians((slot - 36) * 5.0)
    rad = (BASE_R + STEP_R * ring) * sc
    return cx + rad * math.cos(th), cy + rad * math.sin(th)


def _logo_image(logo):
    """取 logo（PIL RGBA）；None 表示用官方 logo"""
    if logo is None:
        try:
            from wxcode_logo import get_default_logo
            return get_default_logo()
        except Exception:
            return None
    return logo


def _circle_crop(img, size_px):
    """把图裁剪成正方形并做圆形透明遮罩"""
    from PIL import Image, ImageDraw, ImageChops
    l = img.copy()
    w, h = l.size
    side = min(w, h)
    l = l.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    l = l.resize((size_px, size_px), Image.LANCZOS)
    if l.mode != "RGBA":
        l = l.convert("RGBA")
    mask = Image.new("L", (size_px * 4, size_px * 4), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size_px * 4 - 1, size_px * 4 - 1], fill=255)
    mask = mask.resize((size_px, size_px), Image.LANCZOS)
    alpha = l.split()[3]
    l.putalpha(ImageChops.multiply(alpha, mask))
    return l


def render_png(text, size=660, mask_id=None, logo=None, logo_pos=None,
               logo_ratio=0.28, show_br=True, bg="white", fg="black"):
    """生成 PNG 字节

    logo      : 中间圆形 Logo（PIL 图像）；None 表示中间留空
    show_br   : 右下角官方小程序 Logo（恒定使用官方 Logo，不可替换）
    logo_pos  : 兼容旧参数，"none" 表示什么 Logo 都不加
    logo_ratio: 中间白底圆直径占画布比例（上限受数据环限制）
    """
    from PIL import Image, ImageDraw

    if logo_pos == "none":
        show_br = False
        logo = None
    elif logo_pos == "br":
        logo = None

    m = build_matrix(text, mask_id)
    sc = size / 660.0
    img = Image.new("RGB", (size, size), bg)
    dr = ImageDraw.Draw(img)
    half = max(0.75, DOT_R * sc)
    dot = half * 2.0

    def disc(x, y):
        dr.ellipse([x - half, y - half, x + half, y + half], fill=fg)

    # 三组定位符
    for fx, fy in ((170.900970, 170.900970), (170.900970, 489.099030), (489.099030, 170.900970)):
        px, py = fx * sc, fy * sc
        for rr, col in ((25.0, fg), (17.0, bg), (5.0, fg)):
            r2 = rr * sc
            dr.ellipse([px - r2, py - r2, px + r2, py + r2], fill=col)

    # ---- 右下角 Logo 覆盖范围内要整体跳过的模块（避免切出半个点） ----
    skip = set()
    if show_br:
        lw_ = 110.0 * sc
        bcx = (437.634583 + 55.0) * sc
        bcy = (437.634583 + 55.0) * sc
        brink = lw_ * BR_BLANK_RATIO / 2.0 + half + 0.5
        for sl in range(SLOTS):
            for rg in range(RINGS):
                x, y = module_xy(sl, rg, size)
                if (x - bcx) ** 2 + (y - bcy) ** 2 <= brink * brink:
                    skip.add((sl, rg))

    # 数据/模板模块
    for slot in range(SLOTS):
        runs, cur = [], []
        for ring in range(RINGS):
            if m[slot][ring] and (slot, ring) not in skip:
                cur.append(ring)
            else:
                if cur:
                    runs.append(cur); cur = []
        if cur:
            runs.append(cur)
        for run in runs:
            if len(run) == 1:
                disc(*module_xy(slot, run[0], size))
            else:
                x1, y1 = module_xy(slot, run[0], size)
                x2, y2 = module_xy(slot, run[-1], size)
                dr.line([x1, y1, x2, y2], fill=fg, width=max(1, int(round(dot))))
                disc(x1, y1)
                disc(x2, y2)

    # ---------- 中间：自定义 Logo 圆形填充 ----------
    if logo is not None:
        lg = _logo_image(logo)
        if lg is not None:
            ratio = min(logo_ratio, 98.0 / 330.0)
            disc_r = size * ratio / 2.0
            cx = cy = size / 2.0
            dr.ellipse([cx - disc_r, cy - disc_r, cx + disc_r, cy + disc_r], fill=bg)
            logo_r = disc_r * 0.86
            ls = max(2, int(round(logo_r * 2)))
            try:
                l2 = _circle_crop(lg, ls)
                img.paste(l2, (int(round(cx - ls / 2.0)), int(round(cy - ls / 2.0))), l2)
            except Exception:
                pass

    # ---------- 右下角：固定官方小程序 Logo ----------
    if show_br:
        lg = _logo_image(None)
        lx = 437.634583 * sc
        ly = 437.634583 * sc
        lw = max(4, int(round(110.0 * sc)))
        ccx = lx + lw / 2.0
        ccy = ly + lw / 2.0
        bw = lw * BR_BLANK_RATIO
        dr.ellipse([ccx - bw / 2.0, ccy - bw / 2.0, ccx + bw / 2.0, ccy + bw / 2.0], fill=bg)
        if lg is not None:
            try:
                l3 = lg.copy()
                if l3.mode != "RGBA":
                    l3 = l3.convert("RGBA")
                l3 = l3.resize((lw, lw), Image.LANCZOS)
                img.paste(l3, (int(round(lx)), int(round(ly))), l3)
            except Exception:
                pass
        else:
            dr.ellipse([lx, ly, lx + lw, ly + lw], outline=(7, 193, 96), width=2)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_svg(text, size=660, mask_id=None, logo=None, logo_pos="center",
               logo_ratio=0.28):
    """生成 SVG 文本（Logo 以内嵌 data URI 形式加入）"""
    m = build_matrix(text, mask_id)
    sc = size / 660.0
    L = ['<svg width="%d" height="%d" version="1.1" xmlns="http://www.w3.org/2000/svg">'
         % (size, size)]

    # ---- Logo 定义 ----
    logo_uri = None
    if logo_pos != "none":
        lg = _logo_image(logo)
        if lg is not None:
            try:
                import io as _io
                import base64 as _b64
                buf = _io.BytesIO()
                lg.save(buf, format="PNG")
                logo_uri = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
            except Exception:
                logo_uri = None

    if logo_pos == "center" and logo_uri:
        ratio = min(logo_ratio, 98.0 / 330.0)
        disc_r = size * ratio / 2.0
        c = size / 2.0
        ls = disc_r * 0.86
        L.append('<defs><clipPath id="lgclip">'
                 '<circle cx="%.3f" cy="%.3f" r="%.3f"/></clipPath></defs>'
                 % (c, c, ls))
        L.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="white"/>' % (c, c, disc_r))
        L.append('<image xlink:href="%s" x="%.3f" y="%.3f" width="%.3f" height="%.3f" '
                 'clip-path="url(#lgclip)" preserveAspectRatio="xMidYMid slice"/>'
                 % (logo_uri, c - ls, c - ls, ls * 2, ls * 2))

    for fx, fy in ((170.900970, 170.900970), (170.900970, 489.099030), (489.099030, 170.900970)):
        for rr, col in ((25.0, "black"), (17.0, "white"), (5.0, "black")):
            L.append('<circle cx="%.6f" cy="%.6f" r="%.6f" fill="%s"/>'
                     % (fx * sc, fy * sc, rr * sc, col))

    w = max(1, int(round(DOT_R * 2 * sc)))
    for slot in range(SLOTS):
        runs, cur = [], []
        for ring in range(RINGS):
            if m[slot][ring]:
                cur.append(ring)
            else:
                if cur:
                    runs.append(cur); cur = []
        if cur:
            runs.append(cur)
        for run in runs:
            x1, y1 = module_xy(slot, run[0], size)
            x2, y2 = module_xy(slot, run[-1], size)
            if len(run) > 1:
                L.append('<line x1="%.6f" y1="%.6f" x2="%.6f" y2="%.6f" '
                         'style="stroke:rgb(0,0,0); stroke-width:%d"/>'
                         % (x1, y1, x2, y2, w))
            r = DOT_R * sc
            L.append('<circle cx="%.6f" cy="%.6f" r="%.6f" fill="black"/>' % (x1, y1, r))
            if len(run) > 1:
                L.append('<circle cx="%.6f" cy="%.6f" r="%.6f" fill="black"/>'
                         % (x2, y2, r))

    if logo_pos == "br" and logo_uri:
        lx = 437.634583 * sc
        ly = 437.634583 * sc
        lw = 110.0 * sc
        L.append('<circle cx="%.3f" cy="%.3f" r="%.3f" fill="white"/>'
                 % (lx + lw / 2.0, ly + lw / 2.0, lw * BR_BLANK_RATIO / 2.0))
        L.append('<image xlink:href="%s" x="%.3f" y="%.3f" width="%.3f" height="%.3f"/>'
                 % (logo_uri, lx, ly, lw, lw))

    L.append("</svg>")
    return "\n".join(L)
