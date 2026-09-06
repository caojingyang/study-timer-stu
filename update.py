#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
晚自习系统更新脚本 - UI版本
支持更新: study_timer.html, seat_choose.html, update.py, start_server.py
使用 pywebview 或 tkinter 显示更新进度
每个源超时3秒，失败可手动重试，全部成功后自动运行 build.bat
"""
import os
import sys
import threading
import time
import json
import urllib.request
import urllib.error
import subprocess
import http.server
from urllib.parse import urlparse, parse_qs

# ============ 配置 ============
DOWNLOAD_SOURCES = {
    "study_timer.html": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-stu@main/study_timer.html",
        "https://raw.githubusercontent.com/caojingyang/study-timer-stu/main/study_timer.html",
        "https://wh12z213stu.pages.dev/study_timer.html",
    ],
    "seat_choose.html": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-mob@main/seat_choose.html",
        "https://raw.githubusercontent.com/caojingyang/study-timer-mob/main/seat_choose.html",
        "https://wh12z213mob.pages.dev/seat_choose.html",
    ],
    "update.py": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-stu@main/update.py",
        "https://raw.githubusercontent.com/caojingyang/study-timer-stu/main/update.py",
        "https://wh12z213stu.pages.dev/update.py",
    ],
    "start_server.py": [
        "https://cdn.jsdelivr.net/gh/caojingyang/study-timer-stu@main/start_server.py",
        "https://raw.githubusercontent.com/caojingyang/study-timer-stu/main/start_server.py",
        "https://wh12z213stu.pages.dev/start_server.py",
    ],
}

SOURCE_TIMEOUT = 3       # 每个源超时（秒）
MIN_FILE_SIZE = 1000     # 最小文件大小（字节），低于此值视为错误
HTTP_PORT = 0            # 0=自动选择可用端口

FILE_LABELS = {
    "study_timer.html": "计时系统页面",
    "seat_choose.html": "选座系统页面",
    "update.py": "更新程序",
    "start_server.py": "服务端程序",
}

# ============ 路径工具 ============
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

WORKSPACE = get_app_dir()

def get_update_html():
    """获取 update.html 内容"""
    # PyInstaller 临时目录
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', '')
        if meipass:
            p = os.path.join(meipass, 'update.html')
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f:
                    return f.read()
    # 应用目录
    p = os.path.join(WORKSPACE, 'update.html')
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return f.read()
    # 内嵌回退
    return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>更新</title>
<style>body{font-family:sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#1e293b;padding:30px;border-radius:12px;text-align:center}h1{color:#818cf8}
p{color:#94a3b8;margin-top:10px}</style></head>
<body><div class="card"><h1>系统更新</h1><p>正在更新...</p></div></body></html>"""

# ============ 共享状态 ============
file_status = {}
for fname in DOWNLOAD_SOURCES:
    file_status[fname] = {'state': 'pending', 'progress': 0, 'source': '', 'error': ''}
status_lock = threading.Lock()
downloads_started = False
downloads_lock = threading.Lock()
build_running = False

# ============ 下载逻辑 ============
def download_from_source(url, progress_cb=None):
    """从单个源下载文件，返回 (data, error)"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        })
        with urllib.request.urlopen(req, timeout=SOURCE_TIMEOUT) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            data = b''
            start_time = time.time()
            while True:
                elapsed = time.time() - start_time
                if elapsed > SOURCE_TIMEOUT:
                    return None, '超时'
                chunk = resp.read(8192)
                if not chunk:
                    break
                data += chunk
                if total > 0 and progress_cb:
                    pct = int(len(data) / total * 100)
                    progress_cb(pct)
                elif progress_cb and len(data) > 0:
                    progress_cb(min(99, int(len(data) / 1024)))
            if len(data) < MIN_FILE_SIZE:
                return None, f'文件过小 ({len(data)} bytes)'
            return data, None
    except Exception as e:
        err = str(e)
        if 'timeout' in err.lower() or 'timed out' in err.lower():
            return None, '超时'
        return None, err[:50]

def download_file(filename):
    """下载单个文件，尝试所有源"""
    sources = DOWNLOAD_SOURCES.get(filename, [])
    if not sources:
        return False

    dest = os.path.join(WORKSPACE, filename)

    for i, url in enumerate(sources):
        source_name = url.split('/')[2]

        with status_lock:
            file_status[filename] = {
                'state': 'downloading', 'progress': 0,
                'source': source_name, 'error': ''
            }

        def progress_cb(pct):
            with status_lock:
                if file_status[filename]['state'] == 'downloading':
                    file_status[filename]['progress'] = pct

        data, err = download_from_source(url, progress_cb)

        if data is not None:
            # 备份旧文件
            backup = dest + '.bak'
            if os.path.exists(dest):
                try:
                    os.replace(dest, backup)
                except Exception:
                    pass
            # 写入新文件
            try:
                with open(dest, 'wb') as f:
                    f.write(data)
                # 成功，删除备份
                if os.path.exists(backup):
                    try:
                        os.remove(backup)
                    except Exception:
                        pass
                with status_lock:
                    file_status[filename] = {
                        'state': 'done', 'progress': 100,
                        'source': source_name, 'error': ''
                    }
                return True
            except Exception as e:
                # 写入失败，恢复备份
                if os.path.exists(backup):
                    try:
                        os.replace(backup, dest)
                    except Exception:
                        pass
                with status_lock:
                    file_status[filename] = {
                        'state': 'failed', 'progress': 0,
                        'source': source_name, 'error': f'写入失败: {str(e)[:30]}'
                    }
                return False
        else:
            # 此源失败，尝试下一个
            with status_lock:
                file_status[filename] = {
                    'state': 'downloading', 'progress': 0,
                    'source': source_name, 'error': err or '失败'
                }
            continue

    # 所有源都失败
    with status_lock:
        file_status[filename] = {
            'state': 'failed', 'progress': 0,
            'source': '', 'error': '所有源均失败'
        }
    return False

def download_file_threaded(filename):
    """在线程中下载单个文件"""
    try:
        download_file(filename)
    except Exception as e:
        with status_lock:
            file_status[filename] = {
                'state': 'failed', 'progress': 0,
                'source': '', 'error': f'异常: {str(e)[:30]}'
            }

def start_downloads():
    """启动所有文件下载"""
    global downloads_started
    with downloads_lock:
        if downloads_started:
            return
        downloads_started = True
    for filename in DOWNLOAD_SOURCES:
        t = threading.Thread(target=download_file_threaded, args=(filename,), daemon=True)
        t.start()

def retry_download(filename):
    """重试单个文件下载"""
    with status_lock:
        file_status[filename] = {
            'state': 'pending', 'progress': 0,
            'source': '', 'error': ''
        }
    t = threading.Thread(target=download_file_threaded, args=(filename,), daemon=True)
    t.start()

def check_all_done():
    """检查是否全部完成"""
    with status_lock:
        return all(f['state'] == 'done' for f in file_status.values())

def check_any_failed():
    """检查是否有失败"""
    with status_lock:
        return any(f['state'] == 'failed' for f in file_status.values())

# ============ HTTP 服务器 ============
class UpdateHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/update.html':
            self._serve_html()
        elif self.path == '/api/status':
            self._serve_status()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/start':
            start_downloads()
            self._json_response({'ok': True})
        elif self.path.startswith('/api/retry'):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            fname = params.get('file', [''])[0]
            if fname in DOWNLOAD_SOURCES:
                retry_download(fname)
                self._json_response({'ok': True})
            else:
                self._json_response({'ok': False, 'error': '未知文件'})
        elif self.path == '/api/build':
            self._handle_build()
        else:
            self.send_error(404)

    def _serve_html(self):
        html = get_update_html()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _serve_status(self):
        with status_lock:
            data = {
                'files': {k: dict(v) for k, v in file_status.items()},
                'allDone': check_all_done(),
                'anyFailed': check_any_failed(),
            }
        self._json_response(data)

    def _json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _handle_build(self):
        global build_running
        if build_running:
            self._json_response({'ok': True})
            return
        build_running = True
        self._json_response({'ok': True})
        # 延迟执行 build.bat，让窗口有时间关闭
        def delayed_build():
            time.sleep(0.5)
            run_build_bat()
        threading.Thread(target=delayed_build, daemon=True).start()

    def log_message(self, format, *args):
        pass  # 静默日志

def run_build_bat():
    """运行 build.bat 并退出"""
    bat_path = os.path.join(WORKSPACE, 'build.bat')
    if not os.path.exists(bat_path):
        print('[更新] build.bat 不存在，跳过编译')
        os._exit(0)
    try:
        if sys.platform == 'win32':
            # 使用 CREATE_NEW_CONSOLE 在新窗口中运行
            subprocess.Popen(
                ['cmd', '/c', 'build.bat'],
                cwd=WORKSPACE,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            subprocess.Popen(['bash', 'build.sh'], cwd=WORKSPACE)
    except Exception as e:
        print(f'[更新] 运行 build.bat 失败: {e}')
    # 退出更新程序
    os._exit(0)

def start_http_server():
    """启动 HTTP 服务器，返回端口号"""
    # 让操作系统自动分配可用端口
    server = http.server.HTTPServer(('127.0.0.1', 0), UpdateHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return port

# ============ pywebview 启动 ============
def launch_webview(port):
    """使用 pywebview 显示更新界面"""
    try:
        import webview
        url = f'http://127.0.0.1:{port}/'
        window = webview.create_window(
            '系统更新',
            url,
            width=520,
            height=480,
            resizable=False,
            min_size=(400, 350),
            background_color='#0f172a'
        )
        # 看门狗：30秒后如果窗口仍未关闭，强制检查
        def watchdog():
            time.sleep(30)
            # 如果窗口仍在，检查是否全部完成
            if check_all_done():
                time.sleep(3)
                # 如果窗口还在，尝试关闭
                try:
                    window.destroy()
                except Exception:
                    pass
                run_build_bat()
        threading.Thread(target=watchdog, daemon=True).start()
        webview.start(debug=False)
        # 窗口关闭后，如果全部完成则运行 build.bat
        if check_all_done() and not build_running:
            run_build_bat()
        os._exit(0)
    except ImportError:
        return False
    except Exception as e:
        print(f'[更新] pywebview 启动失败: {e}')
        return False

# ============ tkinter 回退界面 ============
def launch_tkinter(port):
    """使用 tkinter 显示更新界面（pywebview 不可用时回退）"""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title('系统更新')
    root.geometry('520x480')
    root.configure(bg='#0f172a')
    root.attributes('-topmost', True)

    # 标题
    header = tk.Frame(root, bg='#0f172a')
    header.pack(fill='x', padx=20, pady=(16, 8))
    tk.Label(header, text='系统在线更新', font=('Microsoft YaHei', 18, 'bold'),
             fg='#818cf8', bg='#0f172a').pack()
    tk.Label(header, text='从云端下载最新文件并自动编译', font=('Microsoft YaHei', 10),
             fg='#64748b', bg='#0f172a').pack()

    # 文件列表
    list_frame = tk.Frame(root, bg='#0f172a')
    list_frame.pack(fill='both', expand=True, padx=20, pady=8)

    file_frames = {}
    status_labels = {}
    progress_vars = {}
    retry_btns = {}

    for fname in DOWNLOAD_SOURCES:
        frame = tk.Frame(list_frame, bg='#1e293b', padx=12, pady=10)
        frame.pack(fill='x', pady=4)

        label_text = f"{FILE_LABELS.get(fname, fname)}  ({fname})"
        tk.Label(frame, text=label_text, font=('Microsoft YaHei', 10, 'bold'),
                 fg='#e2e8f0', bg='#1e293b', anchor='w').pack(fill='x')

        stat_label = tk.Label(frame, text='等待中...', font=('Microsoft YaHei', 9),
                             fg='#64748b', bg='#1e293b', anchor='w')
        stat_label.pack(fill='x', pady=(2, 4))

        progress = ttk.Progressbar(frame, length=300, mode='determinate')
        progress.pack(fill='x')

        retry_btn = tk.Button(frame, text='重试', font=('Microsoft YaHei', 9),
                           command=lambda fn=fname: retry_download(fn),
                           bg='#334155', fg='#94a3b8', relief='flat',
                           padx=10, pady=2)
        # 初始隐藏

        file_frames[fname] = frame
        status_labels[fname] = stat_label
        progress_vars[fname] = progress
        retry_btns[fname] = retry_btn

    # 全局状态
    global_label = tk.Label(root, text='正在准备更新...', font=('Microsoft YaHei', 12, 'bold'),
                           fg='#818cf8', bg='#0f172a')
    global_label.pack(pady=(8, 16))

    # 更新函数
    def update_ui():
        all_done = True
        any_failed = False

        for fname in DOWNLOAD_SOURCES:
            with status_lock:
                s = dict(file_status.get(fname, {}))
            state = s.get('state', 'pending')
            progress_val = s.get('progress', 0)
            source = s.get('source', '')
            error = s.get('error', '')

            sl = status_labels[fname]
            pb = progress_vars[fname]
            rb = retry_btns[fname]

            frame = file_frames[fname]
            for widget in frame.winfo_children():
                pass  # 保留现有 widget

            if state == 'pending':
                sl.config(text='等待中...', fg='#64748b')
                pb['value'] = 0
                rb.pack_forget()
                all_done = False
            elif state == 'downloading':
                sl.config(text=f'正在从 {source} 下载... {progress_val}%', fg='#60a5fa')
                pb['value'] = progress_val
                rb.pack_forget()
                all_done = False
            elif state == 'done':
                sl.config(text=f'✓ 更新成功 ({source})', fg='#34d399')
                pb['value'] = 100
                rb.pack_forget()
            elif state == 'failed':
                sl.config(text=f'✗ {error}', fg='#f87171')
                pb['value'] = 0
                rb.pack(side='right', pady=(4, 0))
                any_failed = True
                all_done = False

        if all_done:
            global_label.config(text='✅ 全部更新成功！3秒后自动编译...', fg='#10b981')
            root.after(3000, lambda: on_all_done(root))
        elif any_failed:
            global_label.config(text='⚠ 部分文件更新失败，请点击重试', fg='#f87171')
        else:
            global_label.config(text='正在更新中，请稍候...', fg='#818cf8')

        root.after(200, update_ui)

    def on_all_done(win):
        win.destroy()
        run_build_bat()

    # 启动下载和UI更新
    start_downloads()
    update_ui()

    # 看门狗：60秒后如果仍在运行，强制检查
    def watchdog():
        time.sleep(60)
        if check_all_done():
            root.after(0, lambda: on_all_done(root))
    threading.Thread(target=watchdog, daemon=True).start()

    root.mainloop()
    os._exit(0)

# ============ 主函数 ============
def main():
    # 启动 HTTP 服务器
    port = start_http_server()
    print(f'[更新] HTTP 服务器已启动: http://127.0.0.1:{port}/')

    # 尝试 pywebview，失败则回退 tkinter
    if not launch_webview(port):
        print('[更新] pywebview 不可用，使用 tkinter 界面')
        launch_tkinter(port)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'[更新] 致命错误: {e}')
        import traceback
        traceback.print_exc()
        # 最后的回退：命令行模式
        print('\n回退到命令行模式...')
        start_downloads()
        # 等待所有下载完成
        while True:
            if check_all_done() or check_any_failed():
                # 等待所有线程完成
                time.sleep(1)
                if check_all_done() or all(
                    file_status[f]['state'] in ('done', 'failed')
                    for f in DOWNLOAD_SOURCES
                ):
                    break
            time.sleep(1)
        if check_all_done():
            print('\n✅ 全部更新成功！正在运行 build.bat...')
            run_build_bat()
        else:
            print('\n❌ 部分文件更新失败')
            for fname in DOWNLOAD_SOURCES:
                s = file_status[fname]
                if s['state'] == 'failed':
                    print(f'  - {fname}: {s["error"]}')
            input('按回车键退出...')
