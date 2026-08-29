#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
晚自习系统更新脚本
多源回退下载最新文件到本地（覆盖）
支持更新：study_timer.html, ui.html, seat_online.html
用法：python update.py [all|study_timer|ui|seat_online]
"""
import os
import sys
import urllib.request
import urllib.error
import traceback

# ============ 配置 ============
# 下载源列表（按优先级排序，逐个尝试直到成功）
# 每个文件的下载源
DOWNLOAD_SOURCES = {
    "study_timer.html": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-stu@main/study_timer.html",
        "https://raw.githubusercontent.com/caojingyang/study-timer-stu/main/study_timer.html",
        "https://wh12z213stu.pages.dev/",
    ],
    "ui.html": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-mob@main/ui.html",
        "https://raw.githubusercontent.com/caojingyang/study-timer-mob/main/ui.html",
        "https://wh12z213mob.pages.dev/ui.html",
    ],
    "seat_online.html": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-mob@main/seat_online.html",
        "https://raw.githubusercontent.com/caojingyang/study-timer-mob/main/seat_online.html",
        "https://wh12z213mob.pages.dev/seat_online.html",
    ],
}

# 兼容 PyInstaller 打包后的路径：优先使用 exe 所在目录
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

WORKSPACE = get_app_dir()

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
    if sys.platform in ('win32', 'darwin'):
        return True
    return bool(os.environ.get('DISPLAY'))

def show_graphical_result(success, title, message):
    """弹出图形化提示框（成功/失败均适用）"""
    tk, messagebox = _import_tkinter()
    if not tk or not _is_gui_available():
        return False

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
                    raise ValueError(f"文件过小 ({len(data)} bytes)，可能是错误页面")
                print(f"  [{i+1}/{len(sources)}] ✅ {source_name} 下载成功 ({len(data)/1024:.1f} KB)")
                return data, url
        except Exception as e:
            err_msg = f"{source_name}: {e}"
            errors.append(err_msg)
            print(f"  [{i+1}/{len(sources)}] ❌ {source_name} 失败 — {e}")
    return None, None

# ============ 下载单个文件 ============
def download_file(filename):
    """下载单个文件，返回 (success, source_name)"""
    sources = DOWNLOAD_SOURCES.get(filename)
    if not sources:
        print(f"  ❌ 未知文件: {filename}")
        return False, None

    dest_file = os.path.join(WORKSPACE, filename)
    print(f"\n  [更新] {filename}")
    print(f"  [目标] {dest_file}")

    data, used_source = download_from_sources(sources)

    if data is not None:
        # 备份现有文件
        if os.path.exists(dest_file):
            backup = dest_file + ".bak"
            os.replace(dest_file, backup)
            print(f"  [备份] 已备份旧版本")

        # 写入新文件
        with open(dest_file, "wb") as f:
            f.write(data)

        size_kb = len(data) / 1024
        source_name = used_source.split('/')[2]
        print(f"  ✅ 下载成功！文件大小: {size_kb:.1f} KB（来源: {source_name}）")

        # 更新成功，删除备份
        backup = dest_file + ".bak"
        if os.path.exists(backup):
            os.remove(backup)
            print(f"  [清理] 已删除旧版本备份")

        return True, source_name
    else:
        print(f"  ❌ 所有下载源均失败！")
        # 恢复备份
        if os.path.exists(dest_file + ".bak"):
            os.replace(dest_file + ".bak", dest_file)
            print(f"  [恢复] 已从备份恢复原文件")
        return False, None

# ============ 主流程 ============
if __name__ == "__main__":
    print("")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   晚自习系统 - 在线更新本地文件           ║")
    print("  ╚══════════════════════════════════════════╝")
    print("")

    # 确定要更新的文件
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "all":
        files_to_update = list(DOWNLOAD_SOURCES.keys())
    elif cmd in DOWNLOAD_SOURCES:
        files_to_update = [cmd]
    elif cmd == "study":
        files_to_update = ["study_timer.html"]
    elif cmd == "ui":
        files_to_update = ["ui.html"]
    elif cmd == "seat_online":
        files_to_update = ["seat_online.html"]
    else:
        print(f"  用法: python update.py [all|study_timer|ui|seat_online]")
        print(f"  支持的文件: {', '.join(DOWNLOAD_SOURCES.keys())}")
        sys.exit(1)

    print(f"  [信息] 正在更新 {len(files_to_update)} 个文件...")
    print("")

    success_files = []
    failed_files = []

    for filename in files_to_update:
        success, source_name = download_file(filename)
        if success:
            success_files.append((filename, source_name))
        else:
            failed_files.append(filename)

    # 汇总
    print("")
    print("  ════════════════════════════════════════")
    if success_files:
        print(f"  ✅ 成功更新 {len(success_files)} 个文件:")
        for fn, src in success_files:
            print(f"     - {fn} (来源: {src})")
    if failed_files:
        print(f"  ❌ 更新失败 {len(failed_files)} 个文件:")
        for fn in failed_files:
            print(f"     - {fn}")
    print("")

    all_success = len(failed_files) == 0

    # 图形化提示
    if all_success:
        file_list = "\n".join(f"  - {fn}" for fn, _ in success_files)
        success_msg = (
            f"✅ 更新成功！\n\n"
            f"已更新文件:\n{file_list}\n\n"
            f"请重新启动晚自习系统以加载最新版本。"
        )
        if not show_graphical_result(True, "晚自习系统更新", success_msg):
            print("  [提示] 图形界面不可用，请查看上方控制台输出。")
    else:
        error_msg = (
            f"❌ 部分文件更新失败！\n\n"
            f"失败: {', '.join(failed_files)}\n"
            f"请检查网络连接后稍后重试。"
        )
        if not show_graphical_result(False, "晚自习系统更新", error_msg):
            print("  [提示] 图形界面不可用，请查看上方控制台输出。")

    # 防止窗口一闪而过（双击运行时）
    print("")
    print("  按回车键退出...")
    try:
        input()
    except EOFError:
        pass
