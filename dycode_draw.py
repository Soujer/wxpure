# -*- coding: utf-8 -*-
"""抖音圆码绘制 —— 纯 Python (Pillow)

几何全部按参考实现 432px 输出实测（比例为 相对画布边长）：
  数据环半径（由外到内） 0.3657 / 0.3021 / 0.2681 / 0.2338 (/0.2014)
  ring k 画在第 k 个半径上（ring0 在最外圈，承载 15 位格式字段）
  模块径向厚度 0.0116；中心圆盘 4 环 0.2037，5 环 0.1829
  盘内白色圆环 0.0787；定位标记中心 0.435（45/135/225°），外径 0.044
  右上角 315° 为图片/徽标槽位
"""
import math
from PIL import Image, ImageDraw

RADII = {
    3: [0.3657, 0.3021, 0.2681],
    4: [0.3657, 0.3021, 0.2681, 0.2338],
    5: [0.3657, 0.3021, 0.2681, 0.2338, 0.2014],
}
DISC = {3: 0.2037, 4: 0.2037, 5: 0.1829}
DISC_RING = 0.0787
THICK = 0.0116
THICK0 = 0.0231   # 最外环（格式环）更粗：官方 432px 实测约 10px
MARK_R = 0.430
BADGE_R = 0.434    # 右上角 logo 中心半径（按样图实测）
BADGE_OR = 0.056  # 右上角 logo 半径（约为定位环的 2 倍）
MARK_OR = 0.048
MARKER_ANGLES = (45.0, 135.0, 225.0)
BADGE_ANGLE = 315.0


def render(rings, size=600, dark="#161823", light="#ffffff", transparent=False,
           logo=False, marker=True, center_image=None, badge=True,
           badge_image=None, gap=0.30, supersample=None, frame=True):
    n_ring = len(rings)
    if n_ring not in RADII:
        raise ValueError("环数 %d 不支持" % n_ring)
    ss = supersample
    if ss is None:
        ss = 3 if size <= 520 else 2
    S = size * ss
    c = S / 2.0
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0) if transparent else light)
    d = ImageDraw.Draw(img)
    col = dark

    n = len(rings[0])
    step = 360.0 / n
    th = max(1, int(round(THICK * S)))

    for k in range(n_ring):
        r = RADII[n_ring][k] * S
        row = rings[k]
        j = 0
        th_k = max(1, int(round((THICK0 if k == 0 else THICK) * S)))
        rb = r + th_k / 2.0        # PIL 的 arc 向内描边，box 放大半线宽才能让墨迹居中
        box = [c - rb, c - rb, c + rb, c + rb]
        while j < n:
            if not row[j]:
                j += 1
                continue
            # 每个模块单独一个圆角块（官方版式：相邻模块之间同样留缝）
            a0 = (j + gap / 2) * step
            a1 = (j + 1 - gap / 2) * step
            j += 1
            d.arc(box, a0, a1, fill=col, width=th_k)
            for a in ((a0, a1) if th_k <= max(2, int(round(0.014 * S))) else ()):
                cx = c + r * math.cos(math.radians(a))
                cy = c + r * math.sin(math.radians(a))
                rr = th_k / 2.0
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col)

    if marker:
        mr = MARK_R * S
        mo = MARK_OR * S
        for ang in MARKER_ANGLES:
            t = math.radians(ang)
            fx, fy = c + mr * math.cos(t), c + mr * math.sin(t)
            d.ellipse([fx - mo, fy - mo, fx + mo, fy + mo], outline=col,
                      width=max(2, int(round(mo * 0.38))))
            d.ellipse([fx - mo * 0.26, fy - mo * 0.26, fx + mo * 0.26, fy + mo * 0.26], fill=col)

    dr = DISC[n_ring] * S
    if center_image is None:
        d.ellipse([c - dr, c - dr, c + dr, c + dr], fill=col)
        # 圆盘外留一圈白，避免与最内数据环在低分辨率下粘连
        d.ellipse([c - dr, c - dr, c + dr, c + dr], outline=light,
                  width=max(1, int(round(S * 0.004))))
        if logo:
            # 白色圆环 + 播放三角（与官方版式一致）
            rr = DISC_RING * S
            d.ellipse([c - rr, c - rr, c + rr, c + rr], outline=light,
                      width=max(2, int(round(S * 0.006))))
            s = rr * 0.52
            d.polygon([(c - s * 0.42, c - s), (c - s * 0.42, c + s), (c + s, c)], fill=light)
    else:
        ci = center_image.convert("RGBA")
        dr = dr * 0.94
        tgt = int(dr * 2)
        ci = ci.resize((tgt, tgt), Image.LANCZOS)
        mask = Image.new("L", (tgt, tgt), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, tgt - 1, tgt - 1], fill=255)
        img.paste(ci, (int(c - dr), int(c - dr)), mask)

    if badge or badge_image is not None:
        t = math.radians(BADGE_ANGLE)
        br = BADGE_OR * S
        bx = c + BADGE_R * S * math.cos(t)
        by = c + BADGE_R * S * math.sin(t)
        if badge_image is not None:
            bi = badge_image.convert("RGBA").resize((int(br * 2), int(br * 2)), Image.LANCZOS)
            mask = Image.new("L", (int(br * 2), int(br * 2)), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, int(br * 2) - 1, int(br * 2) - 1], fill=255)
            img.paste(bi, (int(bx - br), int(by - br)), mask)
        else:
            try:
                import dycode_assets
                logo_img = dycode_assets.douyin_logo(int(br * 2))
                mask = Image.new("L", logo_img.size, 0)
                ImageDraw.Draw(mask).ellipse([0, 0, logo_img.size[0] - 1, logo_img.size[1] - 1], fill=255)
                img.paste(logo_img, (int(bx - br), int(by - br)), mask)
            except Exception:
                draw_douyin_logo(d, bx, by, br, col, light)
    if frame:
        draw_frame(d, c, S, col)
    if ss != 1:
        img = img.resize((size, size), Image.LANCZOS)
    return img


# 官方外圈装饰：4 段圆弧，每段 64°，分别以 0/90/180/270° 为中心，
# 在 45/135/225/315°（定位环与图片位）处自然断开
FRAME_R = 0.4440
FRAME_W = 0.0380
FRAME_SPAN = 64.0


def draw_frame(d, c, S, col):
    r = FRAME_R * S
    w = max(2, int(round(FRAME_W * S)))
    rb = r + w / 2.0
    for center in (0.0, 90.0, 180.0, 270.0):
        d.arc([c - rb, c - rb, c + rb, c + rb],
              center - FRAME_SPAN / 2, center + FRAME_SPAN / 2, fill=col, width=w)


def draw_douyin_logo(d, cx, cy, r, col, bg):
    """抖音音符徽标：外圈 + 音符（竖杆 + 旗 + 圆点）"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col,
              width=max(2, int(round(r * 0.15))))
    stem = cx + r * 0.14
    top = cy - r * 0.50
    bot = cy + r * 0.18
    w = max(2, int(round(r * 0.13)))
    d.line([(stem, top), (stem, bot)], fill=col, width=w)
    d.line([(stem, top), (stem + r * 0.44, top + r * 0.10)], fill=col, width=w)
    d.line([(stem, top + r * 0.14), (stem + r * 0.44, top + r * 0.24)], fill=col,
           width=max(2, int(round(r * 0.09))))
    d.ellipse([stem - r * 0.32, bot - r * 0.14, stem + r * 0.08, bot + r * 0.24], fill=col)


def save(rings, path, **kw):
    render(rings, **kw).save(path)
    return path


if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"F:\code\wxpure")
    import dycode_core as core
    r = core.encode("https://bing.com")
    save(r["rings"], "dy_py_test.png", size=600)
    print("saved dy_py_test.png  format", r["format_code"], "rings", r["ring_count"])
