# -*- coding: utf-8 -*-
"""官方样式渲染：调用随包携带的 Node + 官方实现（@ikenxuan/qrcode，MIT）

工具优先用这条路径出图（与官方像素级一致），Node 不可用时自动回退到
纯 Python 渲染器 dycode_draw。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

NODE_CANDIDATES = [
    r"E:\SOFT\nvm4w\nodejs\node.exe",
    r"D:\biancheng\nodejs\node.exe",
    r"C:\Program Files\nodejs\node.exe",
    r"C:\Program Files (x86)\nodejs\node.exe",
]


def engine_dir():
    """dyengine 目录：打包后在 _MEIPASS，源码运行时在同级目录"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "dyengine")
        if os.path.isdir(p):
            return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "dyengine")


def find_node():
    n = shutil.which("node")
    if n:
        return n
    for p in NODE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def available():
    d = engine_dir()
    ok = (os.path.isfile(os.path.join(d, "render_dy.mjs"))
          and os.path.isdir(os.path.join(d, "node_modules")))
    return ok and find_node() is not None


def render(text, out_path, size=600, dark="#161823", transparent=False,
           frame=True, badge=True, logo=True, center_image=None,
           badge_image=None, module_style="rounded", timeout=60):
    """用官方实现出图；成功返回 True"""
    node = find_node()
    if node is None:
        return False
    d = engine_dir()
    script = os.path.join(d, "render_dy.mjs")
    if not (os.path.isfile(script) and os.path.isdir(os.path.join(d, "node_modules"))):
        return False

    payload = {
        "data": text, "size": int(size), "dark": dark,
        "transparent": bool(transparent), "frame": bool(frame),
        "badge": bool(badge), "logo": bool(logo),
        "moduleStyle": module_style,
    }
    if center_image:
        payload["centerImage"] = os.path.abspath(center_image)
    if badge_image:
        payload["badgeImage"] = os.path.abspath(badge_image)

    cmd = [node, script, json.dumps(payload, ensure_ascii=False), os.path.abspath(out_path)]
    env = dict(os.environ)
    env.setdefault("NODE_NO_WARNINGS", "1")
    try:
        r = subprocess.run(cmd, cwd=d, capture_output=True, timeout=timeout, env=env)
    except Exception:
        return False
    if r.returncode != 0 or not os.path.isfile(out_path):
        return False
    return os.path.getsize(out_path) > 0


def render_with_pil(text, out_path, center_pil=None, badge_pil=None, **kw):
    """支持直接传 PIL 图片（内部落临时文件）"""
    tmps = []
    try:
        if center_pil is not None:
            fd, p1 = tempfile.mkstemp(suffix="_center.png"); os.close(fd)
            center_pil.save(p1); tmps.append(p1); kw["center_image"] = p1
        if badge_pil is not None:
            fd, p2 = tempfile.mkstemp(suffix="_badge.png"); os.close(fd)
            badge_pil.save(p2); tmps.append(p2); kw["badge_image"] = p2
        return render(text, out_path, **kw)
    finally:
        for t in tmps:
            try:
                os.remove(t)
            except Exception:
                pass


def render_bytes(text, **kw):
    """返回 PNG bytes 或 None"""
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        if render(text, tmp, **kw):
            with open(tmp, "rb") as f:
                return f.read()
        return None
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


if __name__ == "__main__":
    print("node:", find_node())
    print("engine:", engine_dir(), "available:", available())
    ok = render("测试官方样式", "official_test.png", size=600)
    print("render ok:", ok)
