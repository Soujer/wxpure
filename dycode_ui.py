# -*- coding: utf-8 -*-
"""抖音圆码（抖音码 / BEF_CODE_TYPE_DY_CODE）标签页

功能与葵花码页对齐：
  · 生成：内容 / 尺寸 / 前景色 / 透明底 / 定位标记 / 中心播放图标
  · 中心图片：选择文件、剪贴板粘贴（Ctrl+V）、清除
  · 右上角抖音 logo：默认显示，可换成自己的图片或关闭
  · 识别：选图片或直接把图拖进来（主界面「解码」页也会自动回退到抖音码）
"""
import io
import os
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageGrab, ImageTk

import dycode_core as core
import dycode_draw as draw

MAX_BYTES_4R = 38     # 四环（格式码 5）
MAX_BYTES_5R = 51     # 五环（格式码 6）


def _out(msg):
    """GUI 版 exe 没有 stdout，print 会抛异常；此时把结果写到文件。"""
    try:
        print(msg, flush=True)
        return True
    except Exception:
        return False


def build(app, parent, C_BG="#f7f7f7", C_GREY="#888888", C_FG="#222222"):
    st = {"img": None, "rings": None, "center": None, "badge_img": None}

    outer = tk.Frame(parent, bg=C_BG)
    outer.pack(fill="both", expand=True, padx=14, pady=12)
    left = tk.Frame(outer, bg=C_BG)
    left.pack(side="left", fill="both", expand=True)
    right = tk.Frame(outer, bg=C_BG)
    right.pack(side="right", fill="both", padx=(16, 0))

    # ---------- 内容 ----------
    tk.Label(left, text="内容（UTF-8，四环 ≤38 字节 / 五环 ≤51 字节）",
             bg=C_BG, fg=C_FG, anchor="w").pack(fill="x")
    txt = tk.Text(left, height=4, wrap="word", relief="solid", bd=1,
                  font=("Microsoft YaHei UI", 10))
    txt.pack(fill="x", pady=(4, 4))
    txt.insert("1.0", "https://www.douyin.com/user/MS4wLjABAAAA")

    count = tk.Label(left, text="", bg=C_BG, fg=C_GREY, anchor="w")
    count.pack(fill="x")

    def _cap_bytes():
        s = txt.get("1.0", "end").rstrip("\n")
        n = len(s.encode("utf-8"))
        if n <= MAX_BYTES_4R:
            note, fg = "四环（格式码 5，RS 52/40）", C_GREY
        elif n <= MAX_BYTES_5R:
            note, fg = "五环（格式码 6，RS 67/53）", "#b26a00"
        else:
            note, fg = "超出容量，请缩短", "#c0392b"
        count.config(text="%d 字节 · %s" % (n, note), fg=fg)
        return s

    txt.bind("<KeyRelease>", lambda e: _cap_bytes())

    # ---------- 参数行 ----------
    row = tk.Frame(left, bg=C_BG)
    row.pack(fill="x", pady=(8, 2))
    tk.Label(row, text="尺寸", bg=C_BG, fg=C_FG).pack(side="left")
    size_var = tk.StringVar(value="600")
    ttk.Combobox(row, textvariable=size_var, width=7, state="readonly",
                 values=("400", "500", "600", "800", "1024")).pack(side="left", padx=(4, 12))

    tk.Label(row, text="前景色", bg=C_BG, fg=C_FG).pack(side="left")
    color_var = tk.StringVar(value="#161823")
    tk.Entry(row, textvariable=color_var, width=9).pack(side="left", padx=(4, 12))

    trans_var = tk.IntVar(value=0)
    tk.Checkbutton(row, text="透明底", variable=trans_var, bg=C_BG).pack(side="left", padx=(0, 10))
    mark_var = tk.IntVar(value=1)
    tk.Checkbutton(row, text="定位标记", variable=mark_var, bg=C_BG).pack(side="left", padx=(0, 10))
    logo_var = tk.IntVar(value=0)
    tk.Checkbutton(row, text="中心播放图标", variable=logo_var, bg=C_BG).pack(side="left")

    # ---------- 中心图片 ----------
    crow = tk.Frame(left, bg=C_BG)
    crow.pack(fill="x", pady=(6, 2))
    tk.Label(crow, text="中心图片", bg=C_BG, fg=C_FG).pack(side="left")
    center_lbl = tk.Label(crow, text="未选（显示播放图标）", bg=C_BG, fg=C_GREY, anchor="w")
    center_lbl.pack(side="left", padx=(6, 8), fill="x", expand=True)

    # ---------- 右上角徽标 ----------
    brow = tk.Frame(left, bg=C_BG)
    brow.pack(fill="x", pady=(2, 2))
    badge_var = tk.IntVar(value=1)
    tk.Checkbutton(brow, text="右上角抖音 logo", variable=badge_var, bg=C_BG).pack(side="left")
    badge_lbl = tk.Label(brow, text="（内置音符）", bg=C_BG, fg=C_GREY, anchor="w")
    badge_lbl.pack(side="left", padx=(6, 8), fill="x", expand=True)

    def _preview():
        cur = st["img"]
        if cur is None:
            return
        disp = cur.convert("RGBA")
        bgimg = Image.new("RGBA", disp.size, (255, 255, 255, 255))
        bgimg.alpha_composite(disp)
        w = 380
        bgimg = bgimg.resize((w, w), Image.LANCZOS)
        st["photo"] = ImageTk.PhotoImage(bgimg)
        canvas.config(image=st["photo"], width=w, height=w)

    def _gen():
        s = _cap_bytes()
        if not s:
            messagebox.showwarning("提示", "请先输入内容")
            return
        try:
            r = core.encode(s)
        except Exception as e:
            messagebox.showerror("编码失败", str(e))
            return
        size = int(size_var.get())
        img = None
        # 优先用官方渲染引擎（像素级复刻官方样式）
        try:
            import dycode_official
            if dycode_official.available():
                fd, tmp = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                try:
                    badge_pil = st["badge_img"]
                    if badge_pil is None and badge_var.get():
                        try:
                            import dycode_assets
                            badge_pil = dycode_assets.douyin_logo(192)
                        except Exception:
                            badge_pil = None
                    ok = dycode_official.render_with_pil(
                        s, tmp, center_pil=st["center"], badge_pil=badge_pil,
                        size=size, dark=color_var.get(),
                        transparent=bool(trans_var.get()),
                        frame=True, badge=bool(badge_var.get()),
                        logo=bool(logo_var.get()))
                    if ok:
                        img = Image.open(tmp).convert("RGBA")
                finally:
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
        except Exception as e:
            app._log("官方渲染引擎不可用：%s" % e)
        if img is None:
            # 回退：纯 Python 渲染
            try:
                img = draw.render(r["rings"], size=size,
                                  dark=color_var.get(), transparent=bool(trans_var.get()),
                                  logo=bool(logo_var.get()), marker=bool(mark_var.get()),
                                  center_image=st["center"],
                                  badge=bool(badge_var.get()),
                                  badge_image=st["badge_img"])
                app._log("使用内置渲染器（未找到 Node，样式为纯 Python 复刻）")
            except Exception as e:
                messagebox.showerror("绘制失败", str(e))
                return
        st["img"] = img
        st["rings"] = r
        _preview()
        app._log("抖音圆码：%d 字节 → 格式码 %d（%d 环）"
                 % (len(s.encode("utf-8")), r["format_code"], r["ring_count"]))

    # 中心图片操作
    def _pick_center():
        p = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                                                 ("全部", "*.*")])
        if not p:
            return
        try:
            st["center"] = Image.open(p).convert("RGBA")
            center_lbl.config(text=os.path.basename(p), fg="#07c160")
            _gen()
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _paste_center():
        try:
            im = ImageGrab.grabclipboard()
        except Exception as e:
            messagebox.showinfo("提示", "读取剪贴板失败：%s" % e)
            return
        if isinstance(im, list) and im:
            try:
                im = Image.open(im[0])
            except Exception:
                im = None
        if im is None:
            messagebox.showinfo("提示", "剪贴板里没有图片")
            return
        st["center"] = im.convert("RGBA")
        center_lbl.config(text="来自剪贴板 %d×%d" % im.size, fg="#07c160")
        _gen()

    def _clear_center():
        st["center"] = None
        center_lbl.config(text="未选（显示播放图标）", fg=C_GREY)
        _gen()

    def _pick_badge():
        p = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                                                 ("全部", "*.*")])
        if not p:
            return
        try:
            st["badge_img"] = Image.open(p).convert("RGBA")
            badge_var.set(1)
            badge_lbl.config(text=os.path.basename(p), fg="#07c160")
            _gen()
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _reset_badge():
        st["badge_img"] = None
        badge_lbl.config(text="（内置音符）", fg=C_GREY)
        _gen()

    tk.Button(crow, text="选择", width=6, command=_pick_center).pack(side="right", padx=(4, 0))
    tk.Button(crow, text="粘贴", width=6, command=_paste_center).pack(side="right", padx=(4, 0))
    tk.Button(crow, text="清除", width=6, command=_clear_center).pack(side="right")

    tk.Button(brow, text="自定义", width=7, command=_pick_badge).pack(side="right", padx=(4, 0))
    tk.Button(brow, text="恢复", width=6, command=_reset_badge).pack(side="right")

    # ---------- 生成 / 保存 / 复制 ----------
    btns = tk.Frame(left, bg=C_BG)
    btns.pack(fill="x", pady=(10, 2))

    def _save():
        if st["img"] is None:
            messagebox.showinfo("提示", "先点生成")
            return
        p = filedialog.asksaveasfilename(defaultextension=".png",
                                         filetypes=[("PNG", "*.png")])
        if p:
            st["img"].save(p)
            app._log("已保存: " + p)

    def _copy():
        if st["img"] is None:
            return
        try:
            import win32clipboard  # noqa
        except Exception:
            messagebox.showinfo("提示", "未安装 pywin32，请直接保存")
            return
        buf = io.BytesIO()
        st["img"].convert("RGB").save(buf, "BMP")
        data = buf.getvalue()[14:]
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()
        app._log("抖音圆码已复制到剪贴板")

    tk.Button(btns, text="生 成", width=10, command=_gen).pack(side="left")
    tk.Button(btns, text="保存 PNG", width=10, command=_save).pack(side="left", padx=8)
    tk.Button(btns, text="复制图片", width=10, command=_copy).pack(side="left")

    # ---------- 识别 ----------
    dec_row = tk.Frame(left, bg=C_BG)
    dec_row.pack(fill="x", pady=(10, 2))
    dec_lbl = tk.Label(dec_row, text="识别：把抖音码图片拖进来，或点右侧按钮",
                       bg=C_BG, fg=C_GREY, anchor="w")
    dec_lbl.pack(side="left", fill="x", expand=True)

    def _decode_src(src, name=""):
        try:
            import dycode_decode
            r = dycode_decode.decode(src)
        except Exception as e:
            dec_lbl.config(text="识别失败：%s" % e, fg="#c0392b")
            return None
        if not r:
            dec_lbl.config(text="没识别到抖音码%s" % (("：" + name) if name else ""), fg="#c0392b")
            return None
        txt.delete("1.0", "end")
        txt.insert("1.0", r["text"])
        _cap_bytes()
        dec_lbl.config(text="已识别（格式码 %d / %d 环）：%s"
                            % (r["format_code"], r["ring_count"], r["text"][:40]), fg="#07c160")
        app._log("抖音圆码解码：%s" % r["text"])
        return r

    def _dec_file():
        p = filedialog.askopenfilename(filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                                                 ("全部", "*.*")])
        if p:
            _decode_src(p, os.path.basename(p))

    tk.Button(dec_row, text="选择图片解码", width=12, command=_dec_file).pack(side="right")

    canvas = tk.Label(right, bg="white", relief="solid", bd=1, width=380, height=380)
    canvas.pack()

    # 整个标签页支持 Ctrl+V 粘贴中心图（焦点不在文本框时）
    def _on_paste(ev=None):
        if isinstance(ev.widget, tk.Text):
            return None
        _paste_center()
        return "break"
    parent.bind_all("<Control-v>", _on_paste, add="+")

    _cap_bytes()
    _gen()

    st["decode_src"] = _decode_src
    st["gen"] = _gen
    app.dy_tab_state = st
    return st


def cli(argv):
    """dycode_ui.cli(['内容', '-o', 'out.png', '--size', '600'])"""
    import argparse
    p = argparse.ArgumentParser(prog="dy")
    p.add_argument("text")
    p.add_argument("-o", "--out", default="dycode.png")
    p.add_argument("--size", type=int, default=600)
    p.add_argument("--color", default="#161823")
    p.add_argument("--transparent", action="store_true")
    p.add_argument("--logo", action="store_true")
    p.add_argument("--no-marker", action="store_true")
    p.add_argument("--no-badge", action="store_true")
    p.add_argument("--center", default="")
    p.add_argument("--badge", default="")
    a = p.parse_args(argv)
    try:
        r = core.encode(a.text)
    except Exception as e:
        _out("编码失败：%s" % e)
        return 1
    ci = Image.open(a.center).convert("RGBA") if a.center else None
    bi = Image.open(a.badge).convert("RGBA") if a.badge else None
    made = False
    if bi is None and not a.no_badge:
        try:
            import dycode_assets
            bi = dycode_assets.douyin_logo(192)
        except Exception:
            bi = None
    try:
        import dycode_official
        if dycode_official.available():
            made = dycode_official.render_with_pil(
                a.text, a.out, center_pil=ci, badge_pil=bi, size=a.size,
                dark=a.color, transparent=a.transparent, frame=True,
                badge=not a.no_badge, logo=bool(a.logo))
    except Exception:
        made = False
    if not made:
        img = draw.render(r["rings"], size=a.size, dark=a.color,
                          transparent=a.transparent, logo=bool(a.logo),
                          marker=not a.no_marker, center_image=ci,
                          badge=not a.no_badge, badge_image=bi)
        img.save(a.out)
    msg = ("ok: %s  格式码 %d  环数 %d  payload %d 字节"
           % (a.out, r["format_code"], r["ring_count"], len(r["payload"])))
    if not _out(msg):
        try:
            with open(a.out + ".txt", "w", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
    return 0


def cli_decode(argv):
    import json
    import dycode_decode
    out = []
    shown = True
    for p in argv:
        r = dycode_decode.decode(p)
        out.append({"file": p, "ok": bool(r), "text": (r or {}).get("text", ""),
                    "format_code": (r or {}).get("format_code"),
                    "ring_count": (r or {}).get("ring_count")})
        shown = _out("%s -> %s" % (p, (r or {}).get("text", "(未识别)"))) and shown
    if not shown:
        try:
            with open("dy_decode.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False, indent=1))
        except Exception:
            pass
    return 0 if all(o["ok"] for o in out) else 1


if __name__ == "__main__":
    import sys
    sys.exit(cli(sys.argv[1:]))
