# -*- coding: utf-8 -*-
r"""葵花码工具箱 —— 编码 / 解码 / HTTP 服务

单文件全功能版：界面 + 本机 HTTP 接口，共用同一套微信 QBar 引擎。
支持把图片直接拖进窗口解码；所有编解码记录自动保存到程序目录的 数据\ 下。

    WeChatCodeTool.exe                     打开界面
    WeChatCodeTool.exe --serve             界面 + 自动启动 HTTP 服务
    WeChatCodeTool.exe --serve --port 9000 指定端口
"""
import ctypes
import datetime
import os
import struct
import sys
import threading
import webbrowser

try:
    import winreg
except Exception:
    winreg = None
from ctypes import wintypes

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

if not getattr(sys, "frozen", False):
    _HERE = os.path.dirname(os.path.abspath(__file__))
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)

from wxdecoder import WXDecoder
from wxencoder import Encoder, ENC_MAX_BYTES
from wxsrv import start_server
from wxstore import Store, app_dir
from wxlinks import (classify, wechat_uri, open_external,
                     build_xcx, build_mp, check_ticket, gen_ticket,
                     build_jumpwxa, build_share, check_appid, check_gh)

# ============================ 开机自启动 ============================
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_ID = "WeChatCodeTool"


def current_exe():
    """取程序当前真实位置（用户可能把 EXE 挪到任何地方）。"""
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def _norm(p):
    try:
        return os.path.normcase(os.path.abspath(p))
    except Exception:
        return ""


def _split_cmd(cmd):
    """从注册表命令里取出 exe 路径。支持带引号/不带引号。"""
    cmd = (cmd or "").strip()
    if not cmd:
        return ""
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return cmd[1:end] if end > 0 else cmd.strip('"')
    return cmd.split(" ")[0]


def read_autostart():
    """-> (状态, 已注册的命令)
    状态: 'none' 未设置 / 'ok' 指向当前位置 / 'other' 指向别处 / 'unavailable' 不可用
    """
    if winreg is None:
        return "unavailable", ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, APP_ID)
    except FileNotFoundError:
        return "none", ""
    except OSError:
        return "unavailable", ""
    val = str(val or "")
    reg_exe = _split_cmd(val)
    if not reg_exe:
        return "other", val
    if _norm(reg_exe) == _norm(current_exe()):
        return "ok", val
    return "other", val


def write_autostart(enable, with_serve=True, exe=None):
    """写入/删除开机启动项。exe 默认取当前位置。-> (成功?, 提示)"""
    if winreg is None:
        return False, "当前系统不支持"
    exe = exe or current_exe()
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except OSError:
        return False, "无法写入启动项"
    try:
        if enable:
            cmd = '"%s"' % exe
            if with_serve:
                cmd += " --serve"
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, cmd)
            return True, "已设置开机启动"
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass
            return True, "已关闭开机启动"
    except OSError:
        return False, "操作失败"
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass


C_BG = "#f7f7f7"
C_GREEN = "#07c160"
C_GREY = "#888888"

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")


# ============================ 拖拽支持 ============================

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)


class DropTarget:
    """给一个 tk 顶层窗口装 Windows 原生拖拽（WM_DROPFILES）。"""

    def __init__(self, root, on_files):
        self.on_files = on_files
        self.ok = False
        try:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            self.user32.GetParent.restype = wintypes.HWND
            self.user32.GetParent.argtypes = [wintypes.HWND]
            hwnd = self.user32.GetParent(wintypes.HWND(root.winfo_id())) or \
                wintypes.HWND(root.winfo_id())
            self.hwnd = hwnd
            self.user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                                      ctypes.c_void_p]
            self.user32.SendMessageW.restype = LRESULT
            self.user32.SendMessageW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                                 wintypes.WPARAM, wintypes.LPARAM]
            self.user32.CallWindowProcW.restype = LRESULT
            self.user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                                    ctypes.c_uint, wintypes.WPARAM,
                                                    wintypes.LPARAM]
            self.shell32.DragQueryFileW.restype = ctypes.c_uint
            self.shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                                    wintypes.LPWSTR, wintypes.UINT]
            self.shell32.DragFinish.argtypes = [wintypes.HANDLE]
            self.shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
            self._proc = WNDPROC(self._wndproc)          # 必须持有引用，否则被 GC
            self.shell32.DragAcceptFiles(hwnd, True)
            self._old = self.user32.SetWindowLongPtrW(
                hwnd, GWLP_WNDPROC, ctypes.cast(self._proc, ctypes.c_void_p))
            self.ok = bool(self._old)
        except Exception:
            self.ok = False

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            files = []
            try:
                hdrop = wintypes.HANDLE(wparam)
                n = self.shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                for i in range(n):
                    ln = self.shell32.DragQueryFileW(hdrop, i, None, 0)
                    buf = ctypes.create_unicode_buffer(ln + 1)
                    self.shell32.DragQueryFileW(hdrop, i, buf, ln + 1)
                    files.append(buf.value)
                self.shell32.DragFinish(hdrop)
            except Exception:
                pass
            if files:
                try:
                    self.on_files(files)
                except Exception:
                    pass
            return 0
        return self.user32.CallWindowProcW(self._old, hwnd, msg, wparam, lparam)


def make_hdrop(paths):
    """构造一个 HDROP（用于测试拖拽）。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    data = ("\0".join(paths) + "\0\0").encode("utf-16-le")
    size = 20 + len(data)
    h = k32.GlobalAlloc(0x0042, size)
    p = k32.GlobalLock(h)
    ctypes.memmove(p, struct.pack("<IiiII", 20, 0, 0, 0, 1), 20)
    ctypes.memmove(p + 20, data, len(data))
    k32.GlobalUnlock(h)
    return h


# ============================ 界面 ============================

class App:
    def __init__(self, root, autoserve=False, port=8765):
        self.root = root
        self.autoserve = autoserve
        self.autoport = port
        self.srv = None
        self.custom_logo = None
        self.cur_img = None
        self.cur_meta = None
        self.store = Store()
        self.dec = WXDecoder()
        self.enc = Encoder()

        root.title("葵花码工具箱  ·  编码 / 解码 / HTTP 服务")
        root.geometry("1140x800")
        root.configure(bg=C_BG)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb
        self.tab_dec = tk.Frame(nb, bg=C_BG)
        self.tab_enc = tk.Frame(nb, bg=C_BG)
        self.tab_http = tk.Frame(nb, bg=C_BG)
        nb.add(self.tab_dec, text="   解  码   ")
        nb.add(self.tab_enc, text="   编  码   ")
        self.tab_set = tk.Frame(nb, bg=C_BG)
        nb.add(self.tab_http, text="   HTTP 服 务   ")
        nb.add(self.tab_set, text="   设  置   ")

        self._build_decode()
        self._build_encode()
        self._build_http()
        self._build_settings()
        self._update_count()
        self.drop = DropTarget(root, self._on_drop)
        threading.Thread(target=self._boot, daemon=True).start()

    # ---------------- 启动 ----------------
    def _boot(self):
        okd = self.dec.load()
        oke = self.enc.load()
        self.root.after(0, lambda: self._booted(okd, oke))

    def _booted(self, okd, oke):
        self.enc_lbl.config(text="编码器: " + ("就绪" if oke else "失败"),
                            fg=C_GREEN if oke else "red")
        self.dec_lbl.config(text="解码器: " + ("就绪" if okd else "失败"),
                            fg=C_GREEN if okd else "red")
        self.srv_eng_lbl.config(
            text="引擎状态:  解码器 %s   编码器 %s" % ("就绪" if okd else "失败",
                                                       "就绪" if oke else "失败"),
            fg=C_GREEN if (okd and oke) else "red")
        self._refresh_store_labels()
        self._refresh_autostart()
        if self.autoserve:
            self._start_server(self.autoport)

    def _refresh_store_labels(self):
        s = self.store
        txt = "已保存: 解码 %d 条 / 编码 %d 条   ->   程序目录\\数据\\" % (s.dec_count, s.enc_count)
        try:
            self.store_lbl.config(text=txt)
            self.store_lbl2.config(text=txt)
        except Exception:
            pass

    def _log(self, msg):
        try:
            d = self.store.root
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "运行日志.txt"), "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
        except Exception:
            pass

    def _open_data_dir(self):
        try:
            os.startfile(self.store.root)
        except Exception:
            messagebox.showerror("错误", "打开数据目录失败")

    # ---------------- 拖拽 ----------------
    def _on_drop(self, files):
        imgs = [f for f in files if f.lower().endswith(IMG_EXT)]
        if not imgs:
            messagebox.showinfo("提示", "请拖入图片文件（png / jpg / bmp / gif / webp）")
            return
        self.nb.select(self.tab_dec)
        self._decode_paths(imgs)

    # ---------------- 解码页 ----------------
    def _build_decode(self):
        top = tk.Frame(self.tab_dec, bg=C_BG)
        top.pack(fill="x", padx=12, pady=(10, 6))
        tk.Button(top, text="打开图片（可多选）", command=self._open_imgs,
                  font=("Microsoft YaHei", 11, "bold"), bg=C_GREEN,
                  fg="white").pack(side="left")
        tk.Button(top, text="复制选中内容", command=self._copy_sel,
                  font=("Microsoft YaHei", 10), bg="white").pack(side="left", padx=6)
        tk.Button(top, text="复制全部", command=self._copy_all,
                  font=("Microsoft YaHei", 10), bg="white").pack(side="left")
        tk.Button(top, text="清空列表", command=self._clear,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg=C_GREY).pack(side="left", padx=6)
        tk.Button(top, text="复刻成码", command=self._reencode_sel,
                  font=("Microsoft YaHei", 10), bg=C_GREEN, fg="white",
                  width=10).pack(side="left", padx=(6, 0))
        tk.Button(top, text="用微信打开选中", command=self._open_in_wechat,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg="#0066cc").pack(side="left", padx=(6, 0))
        tk.Button(top, text="打开数据目录", command=self._open_data_dir,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg="#0066cc").pack(side="left", padx=(6, 0))
        self.dec_lbl = tk.Label(top, text="解码器: 加载中…", bg=C_BG, fg=C_GREY,
                                font=("Microsoft YaHei", 9))
        self.dec_lbl.pack(side="right")

        # 手动解析一行文本（小程序里复制出来的裸 token / 各种链接）
        prow = tk.Frame(self.tab_dec, bg=C_BG)
        prow.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(prow, text="解析文本", bg=C_BG,
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self.parse_var = tk.StringVar()
        pe = tk.Entry(prow, textvariable=self.parse_var,
                      font=("Consolas", 10))
        pe.pack(side="left", fill="x", expand=True, padx=6)
        pe.bind("<Return>", lambda e: self._parse_text())
        tk.Button(prow, text="解析", command=self._parse_text,
                  font=("Microsoft YaHei", 9), bg=C_GREEN, fg="white",
                  width=8).pack(side="left")

        # 反向：给名称 + 票据，生成链接文本
        grow = tk.Frame(self.tab_dec, bg=C_BG)
        grow.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(grow, text="生成链接", bg=C_BG,
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self.gen_name = tk.StringVar()
        self.gen_ticket = tk.StringVar()
        tk.Entry(grow, textvariable=self.gen_name, font=("Microsoft YaHei", 9),
                 width=22).pack(side="left", padx=(6, 4))
        tk.Entry(grow, textvariable=self.gen_ticket, font=("Consolas", 9),
                 width=18).pack(side="left", padx=(0, 4))
        tk.Button(grow, text="生成", command=self._build_links,
                  font=("Microsoft YaHei", 9), bg="white", fg=C_GREEN,
                  width=7).pack(side="left")
        tk.Button(grow, text="随机票据", command=self._rand_ticket,
                  font=("Microsoft YaHei", 9), bg="white", fg="#888",
                  width=8).pack(side="left", padx=(4, 0))
        self.gen_hint = tk.Label(grow, text="", bg=C_BG, fg="#888",
                                 font=("Microsoft YaHei", 8))
        self.gen_hint.pack(side="left", padx=8)

        # 小程序 AppID + 原始ID + 路径 -> 唤起链接
        wrow = tk.Frame(self.tab_dec, bg=C_BG)
        wrow.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(wrow, text="小程序", bg=C_BG,
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self.wa_appid = tk.StringVar()
        self.wa_gh = tk.StringVar()
        self.wa_path = tk.StringVar()
        tk.Entry(wrow, textvariable=self.wa_appid, font=("Consolas", 8),
                 width=20).pack(side="left", padx=(6, 3))
        tk.Entry(wrow, textvariable=self.wa_gh, font=("Consolas", 8),
                 width=17).pack(side="left", padx=(0, 3))
        tk.Entry(wrow, textvariable=self.wa_path, font=("Consolas", 8),
                 width=30).pack(side="left", fill="x", expand=True, padx=(0, 3))
        tk.Button(wrow, text="生成", command=self._build_wxa,
                  font=("Microsoft YaHei", 9), bg="white", fg=C_GREEN,
                  width=6).pack(side="left")
        self.wa_hint = tk.Label(wrow, text="", bg=C_BG, fg="#888",
                                font=("Microsoft YaHei", 8))
        self.wa_hint.pack(side="left", padx=6)

        body = tk.Frame(self.tab_dec, bg=C_BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        left = tk.Frame(body, bg="white", bd=2, relief="sunken", width=350)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.dec_preview = tk.Label(left, text="把图片拖到这里\n\n或点左上角【打开图片】",
                                    bg="white", fg="#aaaaaa",
                                    font=("Microsoft YaHei", 11), justify="center")
        self.dec_preview.pack(expand=True)

        right = tk.Frame(body, bg=C_BG)
        right.pack(side="right", fill="both", expand=True, padx=(12, 0))
        cols = ("file", "format", "kind", "text")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=17)
        for c, t, w in (("file", "文件", 150), ("format", "码制", 92),
                        ("kind", "类型", 160), ("text", "内容", 370)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w,
                             anchor="w" if c in ("file", "text") else "center")
        sb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._copy_sel())

        self.store_lbl = tk.Label(self.tab_dec, text="", bg=C_BG, fg=C_GREY,
                                  font=("Microsoft YaHei", 8))
        self.store_lbl.pack(anchor="w", padx=14, pady=(0, 6))

    def _open_imgs(self):
        if not self.dec.ok:
            messagebox.showerror("错误", "解码器未就绪")
            return
        fns = filedialog.askopenfilenames(
            title="选择要解码的图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("全部", "*.*")])
        if fns:
            self._decode_paths(list(fns))

    def _decode_paths(self, paths):
        if not self.dec.ok:
            messagebox.showerror("错误", "解码器不可用：" + self.dec.status)
            return
        self._clear()
        first = None
        hits = 0
        for fn in paths:
            base = os.path.basename(fn)
            try:
                im = Image.open(fn)
                im.load()
            except Exception:
                self.tree.insert("", "end", values=(base, "错误", "-", "无法读取图片"))
                continue
            if first is None:
                first = im
            try:
                got = self.dec.decode_file(fn)
            except Exception as e:
                self._log("解码失败 %s: %s" % (base, e))
                self.tree.insert("", "end", values=(base, "错误", "-", "解码失败"))
                continue
            if got:
                for f, t, c in got:
                    info = classify(t)
                    self.tree.insert("", "end",
                                     values=(base, f, info["label"], t))
                    hits += 1
                self.store.save_decode(fn, got)
            else:
                self.tree.insert("", "end", values=(base, "-", "-", "未识别到码"))
                self.store.save_decode(fn, [("-", "未识别到码", "")])
        if first is not None:
            self._show(first, self.dec_preview)
        self.root.title("葵花码工具箱  ·  本次识别 %d 个码" % hits)
        self._refresh_store_labels()

    def _build_wxa(self):
        """AppID + 原始ID + 路径 -> weixin:// 唤起链接。"""
        a = self.wa_appid.get().strip()
        h = self.wa_gh.get().strip()
        p = self.wa_path.get().strip()
        ok1, m1 = check_appid(a)
        ok2, m2 = check_gh(h)
        self.wa_hint.config(text=("" if (ok1 and ok2) else (m1 if not ok1 else m2)),
                            fg=("#c00" if not (ok1 and ok2) else "#888"))
        if not (ok1 and ok2 and p):
            return
        jump = build_jumpwxa(a, h, p)
        share = build_share(a, h, p)
        n = len(jump.encode("utf-8"))
        self.tree.insert("", "end", values=("(小程序)", "-", "jumpWxa 唤起", jump))
        self.tree.insert("", "end", values=("", "", "business/share", share))
        self.tree.insert("", "end", values=("", "", "长度",
                         "%d 字节（葵花码上限 53 字节）" % n))
        self.root.title("葵花码工具箱  ·  已生成小程序链接")

    def _rand_ticket(self):
        self.gen_ticket.set(gen_ticket())
        self.gen_hint.config(text="已随机生成，仅供格式测试")

    def _build_links(self):
        """按 名称 + 票据 生成三种形式的链接。"""
        name = self.gen_name.get().strip()
        ticket = self.gen_ticket.get().strip()
        ok, msg = check_ticket(ticket)
        self.gen_hint.config(text=("" if ok else msg), fg=("#c00" if not ok else "#888"))
        if not name or not ticket:
            return
        xcx = build_xcx(name, ticket)
        mp = build_mp(ticket)
        self.tree.insert("", "end", values=("(生成)", "-", "#小程序:// 形式", xcx))
        self.tree.insert("", "end", values=("", "", "mp:// 形式", mp))
        self.tree.insert("", "end", values=("", "", "裸票据", ticket))
        self.root.title("葵花码工具箱  ·  已生成链接")

    def _parse_text(self):
        """解析粘贴进来的链接/票据，结果插到列表里。"""
        t = (self.parse_var.get() or "").strip()
        if not t:
            return
        info = classify(t)
        self.tree.insert("", "end", values=("(手动解析)", "-", info["label"], t))
        self.tree.insert("", "end", values=("", "", "摘要", info["summary"]))
        f = info.get("fields") or {}
        for key in ("app_name", "short_id", "route", "host", "id", "path"):
            if f.get(key):
                self.tree.insert("", "end", values=("", "", key, str(f[key])))
        if f.get("equiv"):
            self.tree.insert("", "end", values=("", "", "等价形式", f["equiv"]))
        self.root.title("葵花码工具箱  ·  已解析: " + info["label"])

    def _reencode_sel(self):
        """把选中的载荷原样重新编成葵花码（复刻）。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在列表里选一条")
            return
        v = self.tree.item(sel[0], "values")
        if len(v) < 4 or not v[3] or v[3] in ("-", "未识别到码"):
            messagebox.showinfo("提示", "这一条没有可编码的内容")
            return
        content = v[3]
        ok, nb = Encoder.check_content(content)
        if not ok:
            messagebox.showerror("载荷太长",
                                 "载荷 %d 字节，超过葵花码上限 %d 字节，无法复刻。"
                                 % (nb, ENC_MAX_BYTES))
            return
        if not self.enc.ok:
            messagebox.showerror("错误", "编码器未就绪")
            return
        try:
            ratio = self.center_sz_var.get() / 660.0
            size = int(self.size_var.get())
            img = self.enc.encode_image(content, size, ratio,
                                        custom_logo=self.custom_logo)
        except Exception as e:
            self._log("复刻失败: %s: %s" % (type(e).__name__, e))
            messagebox.showerror("复刻失败", "编码失败，换个码试或检查设置")
            return
        self.cur_img = img
        self.cur_meta = (content, size, ratio)
        path, n = self.store.save_encode(content, size, ratio, img)
        self._refresh_store_labels()
        self.tree.insert("", "end", values=("(复刻)", "-", "已生成新码",
                                            os.path.basename(path or "")))
        try:
            if path and os.path.exists(path):
                os.startfile(path)
        except Exception:
            pass
        self.root.title("葵花码工具箱  ·  已复刻成新码")

    def _open_in_wechat(self):
        """把选中的内容交给微信客户端解析（mp:// #小程序:// u.wechat.com 都行）。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在列表里选一条")
            return
        v = self.tree.item(sel[0], "values")
        if len(v) < 4 or not v[3]:
            messagebox.showinfo("提示", "这一条没有可打开的内容")
            return
        text = v[3]
        uri = wechat_uri(text)
        if not uri:
            return
        # 先复制到剪贴板：PC 版微信不一定理会 weixin:// 路由，粘到聊天里点最稳
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except Exception:
            pass
        ok = open_external(uri)
        tip = ("已复制到剪贴板，并尝试调用微信。\n\n"
               "如果微信没有自动跳出小程序，请把刚才复制的内容\n"
               "直接粘贴到微信任意聊天窗口（文件传输助手也行），\n"
               "再点一下那条消息即可打开。")
        if not ok:
            tip = ("未能调用微信客户端，内容已复制到剪贴板。\n"
                   "请手动粘贴到微信聊天窗口后点击。")
        messagebox.showinfo("用微信打开", tip)

    def _copy_sel(self):
        sel = self.tree.selection()
        if not sel:
            return
        v = self.tree.item(sel[0], "values")
        if len(v) >= 4 and v[3] and not v[3].startswith("未识别") and v[3] != "-":
            self.root.clipboard_clear()
            self.root.clipboard_append(v[3])
            self.root.title("葵花码工具箱  ·  已复制")

    def _copy_all(self):
        out = []
        for it in self.tree.get_children():
            v = self.tree.item(it, "values")
            if len(v) >= 4 and v[3] and not v[3].startswith("未识别") and v[3] != "-":
                out.append(v[3])
        if out:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(out))
            self.root.title("葵花码工具箱  ·  已复制 %d 条" % len(out))

    def _clear(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.dec_preview.config(image="", text="把图片拖到这里\n\n或点左上角【打开图片】")
        self.dec_preview.image = None

    # ---------------- 编码页 ----------------
    def _build_encode(self):
        body = tk.Frame(self.tab_enc, bg=C_BG)
        body.pack(fill="both", expand=True, padx=12, pady=10)
        left = tk.Frame(body, bg=C_BG)
        left.pack(side="left", fill="y", padx=(0, 12))

        tk.Label(left, text="内容（任意文本 / 链接）", bg=C_BG,
                 font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(4, 3))
        self.content_var = tk.StringVar(value="https://u.wechat.com/MFPFmVNlRDSfQKaqo5LSkmk?s=2")
        self.content_var.trace_add("write", lambda *a: self._update_count())
        tk.Entry(left, textvariable=self.content_var, width=44,
                 font=("Consolas", 10)).pack(fill="x")
        self.count_lbl = tk.Label(left, text="", bg=C_BG, fg=C_GREY,
                                  font=("Microsoft YaHei", 9))
        self.count_lbl.pack(anchor="w", pady=(2, 0))

        try:
            self.root.bind("<Control-v>", self._on_ctrl_v)
            self.root.bind("<Control-V>", self._on_ctrl_v)
        except Exception:
            pass

        tk.Label(left, text="尺寸", bg=C_BG,
                 font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(10, 2))
        self.size_var = tk.IntVar(value=660)
        tk.Scale(left, from_=280, to=1280, orient="horizontal", variable=self.size_var,
                 length=300, bg=C_BG).pack(fill="x")
        tk.Label(left, text="（只改输出像素，网格密度固定 16 环）", bg=C_BG, fg="#aaaaaa",
                 font=("Microsoft YaHei", 8)).pack(anchor="w")

        tk.Label(left, text="中间 Logo（圆形填充）", bg=C_BG,
                 font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(10, 2))
        row = tk.Frame(left, bg=C_BG)
        row.pack(fill="x")
        tk.Button(row, text="选图片", command=self._pick_logo,
                  font=("Microsoft YaHei", 9), bg="white",
                  fg=C_GREEN).pack(side="left", expand=True, fill="x", padx=(0, 3))
        tk.Button(row, text="粘贴图片", command=self._paste_logo,
                  font=("Microsoft YaHei", 9), bg="white",
                  fg=C_GREEN).pack(side="left", expand=True, fill="x", padx=(0, 3))
        tk.Button(row, text="清除", command=self._reset_logo,
                  font=("Microsoft YaHei", 9), bg="white",
                  fg=C_GREY).pack(side="left", expand=True, fill="x")
        self.logo_lbl = tk.Label(left, text="未选（中间留空）", bg=C_BG, fg=C_GREY,
                                 font=("Microsoft YaHei", 9), wraplength=300, justify="left")
        self.logo_lbl.pack(anchor="w", pady=(3, 0))
        tk.Label(left, text="Logo 宽度", bg=C_BG,
                 font=("Microsoft YaHei", 10)).pack(anchor="w", pady=(8, 2))
        self.center_sz_var = tk.IntVar(value=224)
        tk.Scale(left, from_=80, to=360, orient="horizontal", variable=self.center_sz_var,
                 length=300, bg=C_BG).pack(fill="x")
        tk.Label(left, text="右下角固定为微信官方小程序 Logo", bg=C_BG, fg="#aaaaaa",
                 font=("Microsoft YaHei", 8)).pack(anchor="w")



        tk.Button(left, text="生  成", command=self._do_gen,
                  font=("Microsoft YaHei", 13, "bold"), bg=C_GREEN, fg="white",
                  height=2).pack(fill="x", pady=(14, 6))
        row2 = tk.Frame(left, bg=C_BG)
        row2.pack(fill="x")
        tk.Button(row2, text="另存为…", command=self._save_png,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg=C_GREEN).pack(side="left", expand=True, fill="x", padx=(0, 4))
        tk.Button(row2, text="送去解码", command=self._send_to_decode,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg="#555555").pack(side="left", expand=True, fill="x")
        tk.Button(left, text="复制图片到剪贴板", command=self._copy_image,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg=C_GREEN).pack(fill="x", pady=(6, 0))
        tk.Button(left, text="打开数据目录", command=self._open_data_dir,
                  font=("Microsoft YaHei", 9), bg="white",
                  fg="#0066cc").pack(fill="x", pady=(6, 0))

        self.enc_lbl = tk.Label(left, text="编码器: 加载中…", bg=C_BG, fg=C_GREY,
                                font=("Microsoft YaHei", 9), wraplength=300, justify="left")
        self.enc_lbl.pack(anchor="w", pady=(10, 0))
        self.store_lbl2 = tk.Label(left, text="", bg=C_BG, fg=C_GREY,
                                   font=("Microsoft YaHei", 8), wraplength=300,
                                   justify="left")
        self.store_lbl2.pack(anchor="w", pady=(4, 0))

        right = tk.Frame(body, bg="white", bd=2, relief="sunken")
        right.pack(side="right", fill="both", expand=True)
        self.preview = tk.Label(right, text="点【生成】", bg="white", fg="gray",
                                font=("Microsoft YaHei", 12))
        self.preview.pack(expand=True)

    def _update_count(self):
        try:
            n = len(self.content_var.get().encode("utf-8"))
        except Exception:
            return
        if n <= ENC_MAX_BYTES:
            self.count_lbl.config(text="内容 %d / %d 字节" % (n, ENC_MAX_BYTES), fg=C_GREY)
        else:
            self.count_lbl.config(text="内容 %d 字节，超出上限 %d！" % (n, ENC_MAX_BYTES),
                                  fg="red")

    def _pick_logo(self):
        fn = filedialog.askopenfilename(
            title="选择 Logo 图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.ico"), ("全部", "*.*")])
        if not fn:
            return
        try:
            im = Image.open(fn)
            im.load()
            self.custom_logo = im.convert("RGBA")
            self.logo_lbl.config(text="使用：%s (%dx%d)" % (os.path.basename(fn),
                                                          im.width, im.height), fg=C_GREEN)
        except Exception:
            messagebox.showerror("错误", "无法读取该图片")

    def _paste_logo(self):
        """从剪贴板直接粘贴 Logo（截图后 Ctrl+C 就能用）"""
        im = None
        try:
            from PIL import ImageGrab
            im = ImageGrab.grabclipboard()
        except Exception:
            im = None
        if im is None:
            messagebox.showinfo("提示", "剪贴板里没有图片。\n\n先用截图或右键复制一张图片，再点这里。")
            return
        if isinstance(im, list):
            try:
                im = Image.open(im[0])
                im.load()
            except Exception:
                messagebox.showerror("错误", "无法读取剪贴板里的图片文件")
                return
        try:
            self.custom_logo = im.convert("RGBA")
        except Exception:
            messagebox.showerror("错误", "剪贴板内容不是有效图片")
            return
        self.logo_lbl.config(
            text="使用：剪贴板图片 (%dx%d)" % (self.custom_logo.width, self.custom_logo.height),
            fg=C_GREEN)
        self._log("已从剪贴板粘贴 Logo %dx%d" % (self.custom_logo.width, self.custom_logo.height))

    def _on_ctrl_v(self, ev=None):
        """Ctrl+V：输入框里正常粘文字，其它地方粘贴 Logo"""
        try:
            w = self.root.focus_get()
            if w is not None and w.winfo_class() in ("Entry", "TEntry", "Text"):
                return None
        except Exception:
            pass
        self._paste_logo()
        return "break"

    def _reset_logo(self):
        self.custom_logo = None
        self.logo_lbl.config(text="未选（中间留空）", fg=C_GREY)

    def _do_gen(self):
        content = self.content_var.get().strip()
        if not content:
            messagebox.showwarning("提示", "先输入内容")
            return
        ok, nb = Encoder.check_content(content)
        if not ok:
            messagebox.showerror("内容太长",
                                 "葵花码容量上限 %d 字节，当前 %d 字节（中文 1 字 = 3 字节）。\n\n"
                                 "请缩短内容。" % (ENC_MAX_BYTES, nb))
            return
        if not self.enc.ok:
            messagebox.showerror("错误", "编码器未就绪")
            return
        try:
            ratio = self.center_sz_var.get() / 660.0
            size = int(self.size_var.get())
            img = self.enc.encode_image(content, size, ratio,
                                        custom_logo=self.custom_logo)
        except Exception as e:
            self._log("生成失败: %s: %s" % (type(e).__name__, e))
            messagebox.showerror("生成失败", "编码失败，请检查内容或重试")
            return
        self.cur_img = img
        self.cur_meta = (content, size, ratio)
        self._show(img, self.preview)
        path, n = self.store.save_encode(content, size, ratio, img)
        self._refresh_store_labels()
        self.root.title("葵花码工具箱  ·  已生成，自动保存到 %s" % os.path.basename(path or ""))

    def _save_png(self):
        if not self.cur_img:
            messagebox.showwarning("提示", "先生成")
            return
        import time
        fn = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")],
            initialfile="wxcode_%d.png" % (int(time.time()) % 100000))
        if fn:
            self.cur_img.save(fn)
            messagebox.showinfo("已保存", fn)

    def _copy_image(self):
        if not self.cur_img:
            messagebox.showwarning("提示", "先生成")
            return
        try:
            from wxclip import copy_image
            copy_image(self.cur_img)
            self.root.title("葵花码工具箱  ·  图片已复制到剪贴板")
            self._log("图片已复制到剪贴板")
        except Exception as e:
            self._log("复制失败: %s: %s" % (type(e).__name__, e))
            messagebox.showerror("复制失败", "无法写入剪贴板")

    def _send_to_decode(self):
        if not self.cur_img:
            messagebox.showwarning("提示", "先生成")
            return
        self.nb.select(self.tab_dec)
        self._clear()
        self._show(self.cur_img, self.dec_preview)
        try:
            got = self.dec.decode(self.cur_img) if self.dec.ok else []
        except Exception:
            got = []
        src = "(刚生成的码)"
        if got:
            for f, t, c in got:
                info = classify(t)
                self.tree.insert("", "end", values=(src, f, info["label"], t))
            self.store.save_decode(src, got)
        else:
            self.tree.insert("", "end", values=(src, "-", "-", "解码失败"))
        self._refresh_store_labels()

    # ---------------- HTTP 服务页 ----------------
    def _build_http(self):
        pad = tk.Frame(self.tab_http, bg=C_BG)
        pad.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(pad, text="本机 HTTP 接口", bg=C_BG,
                 font=("Microsoft YaHei", 13, "bold")).pack(anchor="w")
        tk.Label(pad, text="其它程序 / 前端页面可以直接调用本机接口做解码和编码",
                 bg=C_BG, fg=C_GREY, font=("Microsoft YaHei", 9)).pack(anchor="w", pady=(2, 12))

        row = tk.Frame(pad, bg=C_BG)
        row.pack(fill="x")
        tk.Label(row, text="端口", bg=C_BG, font=("Microsoft YaHei", 10)).pack(side="left")
        self.port_var = tk.StringVar(value=str(self.autoport))
        tk.Entry(row, textvariable=self.port_var, width=8,
                 font=("Consolas", 10)).pack(side="left", padx=(6, 12))
        self.btn_start = tk.Button(row, text="启动服务", command=lambda: self._start_server(),
                                   font=("Microsoft YaHei", 11, "bold"), bg=C_GREEN,
                                   fg="white", width=12)
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(row, text="停止", command=self._stop_server,
                                  font=("Microsoft YaHei", 10), bg="white",
                                  fg="#cc0000", width=8, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        tk.Button(row, text="打开网页", command=self._open_page,
                  font=("Microsoft YaHei", 10), bg="white").pack(side="left", padx=(12, 4))
        tk.Button(row, text="复制地址", command=self._copy_url,
                  font=("Microsoft YaHei", 10), bg="white").pack(side="left")

        self.srv_url_lbl = tk.Label(pad, text="服务未启动", bg=C_BG, fg=C_GREY,
                                    font=("Consolas", 11))
        self.srv_url_lbl.pack(anchor="w", pady=(14, 2))
        self.srv_eng_lbl = tk.Label(pad, text="引擎状态: 加载中…", bg=C_BG, fg=C_GREY,
                                    font=("Microsoft YaHei", 9))
        self.srv_eng_lbl.pack(anchor="w", pady=(0, 12))

        box = tk.LabelFrame(pad, text=" 接口 ", bg=C_BG, fg="#333333",
                            font=("Microsoft YaHei", 10))
        box.pack(fill="both", expand=True)
        txt = (
            "GET   /                        网页测试界面\n"
            "GET   /health                  健康检查\n"
            "POST  /decode                  解码（multipart / 原始字节 / JSON base64）\n"
            "POST  /encode                  编码（JSON -> base64 PNG）\n"
            "GET   /encode?content=xxx      编码（直接返回 PNG 图片）\n"
            "\n"
            "编码可选参数：\n"
            "  size=660        尺寸\n"
            "  logo_ratio=0.28 中间 Logo 宽度占比\n"
            "  pos=center      中间 / br 右下角 / none 不加\n"
            "  logo=图片地址     http(s) 地址或 data:base64 均可\n"
            "\n"
            "示例：\n"
            "  curl --data-binary \"@图片.png\" -H \"Content-Type: image/png\"  http://127.0.0.1:端口/decode\n"
            "  curl -F \"file=@图片.png\"  http://127.0.0.1:端口/decode\n"
            "  curl -X POST http://127.0.0.1:端口/encode -H \"Content-Type: application/json\" -d \"{\\\"content\\\":\\\"hello\\\"}\"\n"
            "  <img src=\"http://127.0.0.1:端口/encode?content=hello\">\n"
            "\n"
            "容量上限 %d 字节（中文约 17 字）。全部接口带 CORS 头，浏览器可直接 fetch。\n"
            "详细文档：程序目录\\API说明.txt"
        ) % ENC_MAX_BYTES
        tk.Label(box, text=txt, bg=C_BG, justify="left", anchor="nw",
                 font=("Consolas", 9), fg="#333333").pack(fill="both", expand=True,
                                                          padx=10, pady=8)

    # ---------------- 设置页 ----------------
    def _build_settings(self):
        pad = tk.Frame(self.tab_set, bg=C_BG)
        pad.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(pad, text="开机自动启动", bg=C_BG,
                 font=("Microsoft YaHei", 13, "bold")).pack(anchor="w")
        tk.Label(pad, text="勾选后，开机会自动运行本程序（按程序当前所在位置登记，"
                           "把程序挪到别处后再点一次即可更新）",
                 bg=C_BG, fg=C_GREY, font=("Microsoft YaHei", 9),
                 wraplength=760, justify="left").pack(anchor="w", pady=(2, 14))

        self.serve_on_boot = tk.BooleanVar(value=True)
        tk.Checkbutton(pad, text="开机启动时同时开启 HTTP 服务",
                       variable=self.serve_on_boot, bg=C_BG,
                       font=("Microsoft YaHei", 10),
                       activebackground=C_BG).pack(anchor="w", pady=(0, 14))

        self.autostart_lbl = tk.Label(pad, text="状态: 检查中…", bg=C_BG, fg=C_GREY,
                                      font=("Microsoft YaHei", 11))
        self.autostart_lbl.pack(anchor="w", pady=(0, 10))

        row = tk.Frame(pad, bg=C_BG)
        row.pack(anchor="w", fill="x")
        self.btn_auto_on = tk.Button(row, text="设置开机启动",
                                     command=self._do_autostart_on,
                                     font=("Microsoft YaHei", 11, "bold"),
                                     bg=C_GREEN, fg="white", width=18)
        self.btn_auto_on.pack(side="left")
        self.btn_auto_upd = tk.Button(row, text="更新为当前位置",
                                      command=self._do_autostart_on,
                                      font=("Microsoft YaHei", 10),
                                      bg="#ff9800", fg="white", width=18)
        self.btn_auto_off = tk.Button(row, text="关闭开机启动",
                                      command=self._do_autostart_off,
                                      font=("Microsoft YaHei", 10),
                                      bg="white", fg="#cc0000", width=16)
        self.btn_auto_off.pack(side="left", padx=8)

        tk.Frame(pad, bg="#dddddd", height=1).pack(fill="x", pady=22)

        tk.Label(pad, text="数据", bg=C_BG,
                 font=("Microsoft YaHei", 13, "bold")).pack(anchor="w")
        tk.Label(pad, text="所有编解码记录保存在程序目录下的 数据\\ 文件夹",
                 bg=C_BG, fg=C_GREY, font=("Microsoft YaHei", 9)).pack(anchor="w", pady=(2, 8))
        tk.Button(pad, text="打开数据目录", command=self._open_data_dir,
                  font=("Microsoft YaHei", 10), bg="white",
                  fg="#0066cc", width=16).pack(anchor="w")

    def _refresh_autostart(self):
        try:
            state, _cmd = read_autostart()
        except Exception:
            state = "unavailable"
        if state == "ok":
            self.autostart_lbl.config(text="状态: 已开启（指向程序当前位置）", fg=C_GREEN)
            self.btn_auto_on.pack_forget()
            self.btn_auto_upd.pack_forget()
            self.btn_auto_off.pack(side="left")
        elif state == "other":
            self.autostart_lbl.config(
                text="状态: 已开启，但登记的是旧位置（程序被移动过）—— 点【更新为当前位置】",
                fg="#ff9800")
            self.btn_auto_on.pack_forget()
            self.btn_auto_upd.pack(side="left")
            self.btn_auto_off.pack(side="left", padx=8)
        elif state == "none":
            self.autostart_lbl.config(text="状态: 未开启", fg=C_GREY)
            self.btn_auto_upd.pack_forget()
            self.btn_auto_on.pack(side="left")
            self.btn_auto_off.pack_forget()
        else:
            self.autostart_lbl.config(text="状态: 当前系统不支持", fg="red")
            self.btn_auto_on.pack_forget()
            self.btn_auto_upd.pack_forget()
            self.btn_auto_off.pack_forget()

    def _do_autostart_on(self):
        ok, msg = write_autostart(True, with_serve=bool(self.serve_on_boot.get()))
        self._refresh_autostart()
        if not ok:
            messagebox.showerror("失败", msg)

    def _do_autostart_off(self):
        ok, msg = write_autostart(False)
        self._refresh_autostart()
        if not ok:
            messagebox.showerror("失败", msg)

    def _start_server(self, port=None):
        if self.srv is not None:
            return
        if port is None:
            try:
                port = int(self.port_var.get())
            except Exception:
                messagebox.showerror("错误", "端口号不对")
                return
        if not (self.dec.ok and self.enc.ok):
            messagebox.showerror("错误", "引擎尚未就绪，请稍候")
            return
        try:
            self.srv = start_server("127.0.0.1", port, self.dec, self.enc,
                                    ENC_MAX_BYTES, store=self.store)
        except OSError:
            self.srv = None
            messagebox.showerror("启动失败", "端口 %d 可能被占用，换个端口试试" % port)
            return
        self.port_var.set(str(port))
        self.srv_url = "http://127.0.0.1:%d" % port
        self.srv_url_lbl.config(text="服务运行中  ->  " + self.srv_url, fg=C_GREEN)
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

    def _stop_server(self):
        if self.srv is None:
            return
        try:
            self.srv.shutdown()
            self.srv.server_close()
        except Exception:
            pass
        self.srv = None
        self.srv_url_lbl.config(text="服务已停止", fg=C_GREY)
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _open_page(self):
        if self.srv is None:
            messagebox.showinfo("提示", "先启动服务")
            return
        webbrowser.open(self.srv_url + "/")

    def _copy_url(self):
        if self.srv is None:
            messagebox.showinfo("提示", "先启动服务")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.srv_url)

    def _on_close(self):
        try:
            self._stop_server()
            self.dec.close()
        except Exception:
            pass
        self.root.destroy()

    @staticmethod
    def _show(im, label):
        try:
            t = im.copy()
            t.thumbnail((470, 470), Image.LANCZOS)
            ph = ImageTk.PhotoImage(t)
            label.config(image=ph, text="")
            label.image = ph
        except Exception:
            pass


def _ensure_std_streams():
    """窗口版 EXE 里 sys.stdout/stderr 是 None，任何 print 都会抛异常。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        d = os.path.join(app_dir(), "数据")
        os.makedirs(d, exist_ok=True)
        f = open(os.path.join(d, "运行日志.txt"), "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f
    except Exception:
        class _Null:
            def write(self, *a):
                pass

            def flush(self, *a):
                pass
        if sys.stdout is None:
            sys.stdout = _Null()
        if sys.stderr is None:
            sys.stderr = _Null()


def _cli_autostart(argv):
    """命令行管理开机启动：--autostart on|off|status"""
    i = argv.index("--autostart")
    act = argv[i + 1] if i + 1 < len(argv) else "status"
    if act == "on":
        ok, msg = write_autostart(True, with_serve=("--no-serve" not in argv))
        print(("成功: " if ok else "失败: ") + msg, flush=True)
    elif act == "off":
        ok, msg = write_autostart(False)
        print(("成功: " if ok else "失败: ") + msg, flush=True)
    else:
        state, _cmd = read_autostart()
        print({"none": "未开启",
               "ok": "已开启（指向当前位置）",
               "other": "已开启，但登记的是旧位置",
               "unavailable": "当前系统不支持"}.get(state, state), flush=True)
    return 0


def main():
    _ensure_std_streams()
    argv = sys.argv[1:]
    if "--autostart" in argv:
        return _cli_autostart(argv)
    autoserve = "--serve" in argv
    port = 8765
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
        elif a.startswith("--port="):
            port = int(a.split("=", 1)[1])
    root = tk.Tk()
    try:
        ttk.Style().configure("TNotebook.Tab", font=("Microsoft YaHei", 11),
                              padding=(14, 6))
    except Exception:
        pass
    app = App(root, autoserve=autoserve, port=port)

    if "--selftest-dnd" in argv:
        # 自检：造一个假拖拽，把 111.png 塞进去，看结果
        def _fire():
            try:
                h = make_hdrop([r"D:\Desk\111.png"])
                app.drop.user32.SendMessageW(app.drop.hwnd, WM_DROPFILES,
                                             wintypes.WPARAM(h), wintypes.LPARAM(0))
                print("SELFTEST: WM_DROPFILES sent", flush=True)
            except Exception as e:
                print("SELFTEST send fail:", e, flush=True)

        def _check():
            rows = [app.tree.item(i, "values") for i in app.tree.get_children()]
            lines = ["SELFTEST drop_ok=%s rows=%d" % (app.drop.ok, len(rows))]
            for r in rows:
                lines.append("   " + repr(r))
            lines.append("SELFTEST dec_count=%d enc_count=%d dir=%s"
                         % (app.store.dec_count, app.store.enc_count, app.store.root))
            txt = "\n".join(lines)
            print(txt, flush=True)
            try:
                with open(os.path.join(app.store.root, "_selftest.txt"), "w",
                          encoding="utf-8") as f:
                    f.write(txt + "\n")
            except Exception:
                pass
            root.destroy()

        root.after(4500, _fire)
        root.after(9000, _check)

    root.mainloop()


if __name__ == "__main__":
    sys.exit(main() or 0)
