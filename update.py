#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
晚自习系统更新脚本
多源回退下载最新的 study_timer.html 到本地（覆盖）
用法：python update.py
"""
import os
import sys
import urllib.request
import urllib.error
import traceback

# ============ 配置 ============
# 下载源列表（按优先级排序，逐个尝试直到成功）
# 1. jsDelivr CDN — 镜像 GitHub，国内有节点，速度快，无内容审核
# 2. GitHub raw — 原始源，稳定但国内偶尔较慢
# 3. Cloudflare Pages — 全球 CDN，已部署的在线版本
DOWNLOAD_SOURCES = [
    "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-stu@main/index.html",
    "https://raw.githubusercontent.com/caojingyang/study-timer-stu/main/index.html",
    "https://wh12z213stu.pages.dev/",
]

# 兼容 PyInstaller 打包后的路径：优先使用 exe 所在目录
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

WORKSPACE = get_app_dir()
DEST_FILE = os.path.join(WORKSPACE, "study_timer.html")

# ============ 图形化提示 ============
def _import_tkinter():
    """尝试导入 tkinter，返回模块或 None"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        return tk, messagebox
    except ImportError:
        return None, None

def _is_gui_available():
    """检测当前环境是否支持图形界面"""
    # Windows / macOS 默认支持
    if sys.platform in ('win32', 'darwin'):
        return True
    # Linux 需要有 DISPLAY 环境变量
    return bool(os.environ.get('DISPLAY'))

def show_graphical_result(success, title, message):
    """弹出图形化提示框（成功/失败均适用）"""
    tk, messagebox = _import_tkinter()
    if not tk or not _is_gui_available():
        return False  # 无法显示图形界面

    try:
        root = tk.Tk()
        root.withdraw()  # 隐藏主窗口
        root.attributes('-topmost', True)  # 置顶显示
        if success:
            messagebox.showinfo(title, message, parent=root)
        else:
            messagebox.showerror(title, message, parent=root)
        root.destroy()
        return True
    except Exception:
        return False

# ============ 多源下载 ============
def download_from_sources(sources):
    """
    逐个尝试下载源，返回 (data, source_url) 或 (None, None)
    """
    errors = []
    for i, url in enumerate(sources):
        source_name = url.split('/')[2]  # 提取域名
        try:
            print(f"  [{i+1}/{len(sources)}] 尝试从 {source_name} 下载...")
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                if len(data) < 1000:
                    # 文件太小，可能是错误页面
                    raise ValueError(f"文件过小 ({len(data)} bytes)，可能是错误页面")
                print(f"  [{i+1}/{len(sources)}] ✅ {source_name} 下载成功 ({len(data)/1024:.1f} KB)")
                return data, url
        except Exception as e:
            err_msg = f"{source_name}: {e}"
            errors.append(err_msg)
            print(f"  [{i+1}/{len(sources)}] ❌ {source_name} 失败 — {e}")
    return None, None

# ============ 主流程 ============
if __name__ == "__main__":
    print("")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   晚自习系统 - 在线更新本地文件           ║")
    print("  ╚══════════════════════════════════════════╝")
    print("")
    print(f"  [信息] 正在下载最新版本（多源回退）...")
    print(f"  [目标] {DEST_FILE}")
    print("")

    data, used_source = download_from_sources(DOWNLOAD_SOURCES)

    if data is not None:
        # 备份现有文件
        if os.path.exists(DEST_FILE):
            backup = DEST_FILE + ".bak"
            os.replace(DEST_FILE, backup)
            print(f"  [备份] 已备份旧版本为 study_timer.html.bak")

        # 写入新文件
        with open(DEST_FILE, "wb") as f:
            f.write(data)

        size_kb = len(data) / 1024
        source_name = used_source.split('/')[2]
        print(f"  ✅ 下载成功！文件大小: {size_kb:.1f} KB（来源: {source_name}）")

        # 更新成功，删除备份
        backup = DEST_FILE + ".bak"
        if os.path.exists(backup):
            os.remove(backup)
            print(f"  [清理] 已删除旧版本备份")
        print("")

        # 图形化提示 - 成功
        success_msg = (
            f"✅ 更新成功！\n\n"
            f"文件大小: {size_kb:.1f} KB\n"
            f"下载来源: {source_name}\n"
            f"保存路径: {DEST_FILE}\n\n"
            f"请重新启动晚自习系统以加载最新版本。"
        )
        if not show_graphical_result(True, "晚自习系统更新", success_msg):
            print("  [提示] 图形界面不可用，请查看上方控制台输出。")

    else:
        # 所有源都失败
        print(f"  ❌ 所有下载源均失败！")
        print("")

        # 恢复备份
        if os.path.exists(DEST_FILE + ".bak"):
            os.replace(DEST_FILE + ".bak", DEST_FILE)
            print(f"  [恢复] 已从备份恢复原文件")

        # 图形化提示 - 失败
        error_msg = (
            f"❌ 更新失败！\n\n"
            f"所有下载源均无法访问。\n"
            f"已从备份恢复原文件。\n\n"
            f"请检查网络连接后稍后重试。"
        )
        if not show_graphical_result(False, "晚自习系统更新失败", error_msg):
            print("  [提示] 图形界面不可用，请查看上方控制台输出。")

    # 防止窗口一闪而过（双击运行时）
    print("")
    print("  按回车键退出...")
    try:
        input()
    except EOFError:
        pass
