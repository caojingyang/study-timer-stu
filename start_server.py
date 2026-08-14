#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
晚自习系统 - 本地服务器（班级大屏端）
功能：
  1. 本地 HTTP 服务器（服务 study_timer.html 等静态文件）
  2. 文件接收服务（接收移动端发送的文件）
  3. 系统托盘图标（打开接收文件列表 / 打开计时系统 / 退出）
  4. 开机自启动（编译后的可执行文件）
  5. 非静默发送时的弹窗提示
  6. 心跳上报（让移动端检测大屏是否在线）
  7. 离线文件自动下载（大屏上线时自动从数据库读取并下载）
用法：python start_server.py
"""
import http.server
import os
import sys
import socket
import threading
import json
import time
import datetime
import subprocess
import struct
import traceback
import urllib.request
import urllib.error

# ============================================================
# 配置
# ============================================================
PORT = 8080
SUPABASE_URL = 'https://pylcqbwhyqozvpwfzgiy.supabase.co'
SUPABASE_KEY = 'sb_publishable_x0V-7Mj0PyphcH0W2cID0A_W-yUfdME'
HEARTBEAT_INTERVAL = 30  # 秒
APP_NAME = "晚自习系统"  # 开机自启注册名
APP_VERSION = "v2.8.1"

# ============================================================
# 路径工具
# ============================================================
def get_app_dir():
    """获取应用目录（兼容 PyInstaller 打包）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_desktop_dir():
    """获取桌面路径"""
    if sys.platform == 'win32':
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        ctypes.windll.shell32.SHGetFolderPath(None, 0, None, 0, buf)
        return buf.value
    return os.path.expanduser('~/Desktop')

def get_receive_dir():
    """获取接收文件根目录: 桌面/receive"""
    return os.path.join(get_desktop_dir(), 'receive')

def get_user_receive_dir(username):
    """获取用户接收目录: 桌面/receive/<用户名>/<日期>"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    return os.path.join(get_receive_dir(), username, today)

# ============================================================
# UAC 提权
# ============================================================
def is_admin():
    """检查是否以管理员权限运行"""
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def elevate():
    """请求 UAC 提权并重启"""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        params = ' '.join(['"' + arg + '"' for arg in sys.argv])
        ctypes.windll.shell32.ShellExecuteW(None, 'runas', sys.executable, params, None, 1)
        return True
    except:
        return False

# ============================================================
# 开机自启动
# ============================================================
def register_autostart():
    """注册开机自启动（Windows 注册表 HKCU）"""
    if sys.platform != 'win32':
        return
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.join(get_app_dir(), 'start_server.exe')
            if not os.path.exists(exe_path):
                # 未编译，不注册
                winreg.CloseKey(key)
                return
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, '"' + exe_path + '"')
        winreg.CloseKey(key)
    except Exception as e:
        print(f"[自启] 注册失败: {e}")

# ============================================================
# 网络工具
# ============================================================
def get_lan_ip():
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '127.0.0.1'

# ============================================================
# Supabase API
# ============================================================
def sb_request(method, path, body=None):
    """Supabase REST API 请求"""
    url = SUPABASE_URL + path
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json'
    }
    data = None
    if body and method in ('POST', 'PATCH'):
        data = json.dumps(body).encode('utf-8')
        headers['Prefer'] = 'return=representation'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"[Supabase] HTTP {e.code}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        print(f"[Supabase] 请求失败: {e}")
        return None

def update_heartbeat():
    """更新大屏心跳"""
    ip = get_lan_ip()
    now = datetime.datetime.now().isoformat()
    sb_request('PATCH', '/rest/v1/screen_heartbeat?id=eq.1', {
        'last_heartbeat': now,
        'ip_address': ip,
        'port': PORT
    })

def heartbeat_loop():
    """心跳循环线程"""
    while True:
        try:
            update_heartbeat()
        except:
            pass
        time.sleep(HEARTBEAT_INTERVAL)

def pending_files_loop():
    """实时检查待接收文件（每5秒轮询数据库）"""
    while True:
        try:
            process_pending_files()
        except:
            pass
        time.sleep(5)

def get_pending_files():
    """获取待下载的文件列表"""
    result = sb_request('GET', '/rest/v1/pending_files?downloaded=eq.false&order=created_at.asc')
    return result if result else []

def delete_pending_file(file_id):
    """删除已下载的待接收文件记录"""
    sb_request('DELETE', '/rest/v1/pending_files?id=eq.' + str(file_id))

# ============================================================
# 文件下载
# ============================================================
def download_file(url, save_path):
    """下载文件到指定路径"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(save_path, 'wb') as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"[下载] 失败: {e}")
        return False

def process_file_receive(sender, realname, silent, files):
    """处理收到的文件信息：下载文件并保存"""
    save_dir = get_user_receive_dir(sender)
    os.makedirs(save_dir, exist_ok=True)

    downloaded_files = []
    for f in files:
        file_name = f.get('name', 'unknown')
        file_size = f.get('size', 0)
        file_type = f.get('type', '')
        download_url = f.get('downloadUrl') or f.get('shareUrl', '')

        if not download_url:
            continue

        # 处理文件名冲突
        save_path = os.path.join(save_dir, file_name)
        if os.path.exists(save_path):
            name, ext = os.path.splitext(file_name)
            counter = 1
            while os.path.exists(save_path):
                save_path = os.path.join(save_dir, f"{name}_{counter}{ext}")
                counter += 1

        print(f"[接收] 正在下载: {file_name} ({format_size(file_size)})")
        success = download_file(download_url, save_path)
        if success:
            downloaded_files.append({
                'name': os.path.basename(save_path),
                'path': save_path,
                'size': file_size,
                'type': file_type,
                'dir': save_dir
            })
            print(f"[接收] ✓ {file_name}")
        else:
            print(f"[接收] ✗ {file_name} 下载失败")

    # 记录到当日接收历史
    if downloaded_files:
        record = {
            'sender': sender,
            'realname': realname,
            'silent': silent,
            'timestamp': datetime.datetime.now().isoformat(),
            'files': downloaded_files
        }
        save_received_record(record)

        # 非静默发送时弹出提示窗口
        if not silent:
            show_notification_window(sender, realname, downloaded_files)

    return len(downloaded_files)

def format_size(size):
    """格式化文件大小"""
    if not size:
        return '未知'
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"

# ============================================================
# 接收记录存储
# ============================================================
def get_records_file():
    """获取当日接收记录文件路径"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    return os.path.join(get_app_dir(), f'received_{today}.json')

def save_received_record(record):
    """保存接收记录"""
    records_file = get_records_file()
    records = []
    if os.path.exists(records_file):
        try:
            with open(records_file, 'r', encoding='utf-8') as f:
                records = json.load(f)
        except:
            records = []
    records.append(record)
    with open(records_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def load_received_records():
    """加载当日接收记录"""
    records_file = get_records_file()
    if os.path.exists(records_file):
        try:
            with open(records_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

# ============================================================
# 离线文件处理
# ============================================================
def process_pending_files():
    """处理数据库中待下载的文件"""
    pending = get_pending_files()
    if not pending:
        return  # 无待接收文件，静默返回

    # 按发送者分组
    groups = {}
    for pf in pending:
        key = (pf.get('sender_username'), pf.get('sender_realname'), pf.get('silent', True))
        if key not in groups:
            groups[key] = []
        groups[key].append(pf)

    for (sender, realname, silent), items in groups.items():
        files = []
        file_ids = []
        for item in items:
            files.append({
                'name': item.get('file_name', 'unknown'),
                'size': item.get('file_size', 0),
                'type': item.get('file_type', ''),
                'downloadUrl': item.get('download_url', ''),
                'shareUrl': item.get('share_url', '')
            })
            file_ids.append(item.get('id'))

        print(f"[轮询] 发现 {sender} 的 {len(files)} 个文件...")
        count = process_file_receive(sender, realname or sender, silent, files)

        # 删除已处理的记录
        for fid in file_ids:
            if fid:
                delete_pending_file(fid)

        print(f"[轮询] 已接收 {count}/{len(files)} 个文件")

# ============================================================
# GUI: 通知窗口（非静默发送时）
# ============================================================
def get_file_icon_text(file_type, file_name):
    """根据文件类型返回图标文字"""
    if file_type.startswith('image/'):
        return '🖼'
    if file_type == 'application/pdf':
        return '📄'
    if 'word' in file_type or 'msword' in file_type:
        return '📝'
    if 'excel' in file_type or 'spreadsheet' in file_type:
        return '📊'
    if 'powerpoint' in file_type or 'presentation' in file_type:
        return '📽'
    if file_type == 'application/zip' or file_name.endswith('.zip'):
        return '📦'
    if file_type.startswith('text/'):
        return '📃'
    if file_type.startswith('video/'):
        return '🎬'
    if file_type.startswith('audio/'):
        return '🎵'
    return '📎'

def show_notification_window(sender, realname, files):
    """显示非静默发送的文件接收提示窗口"""
    try:
        show_notification_window_impl(sender, realname, files)
    except Exception as e:
        print(f"[通知] 窗口显示失败: {e}")
        traceback.print_exc()

def show_notification_window_impl(sender, realname, files):
    """通知窗口实现（tkinter）"""
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title(f"{realname or sender} 发来文件")
    root.geometry("420x450")
    root.resizable(False, False)

    # 标题
    title_frame = tk.Frame(root, padx=20, pady=15)
    title_frame.pack(fill='x')
    tk.Label(title_frame, text=f"📧 {realname or sender} 发来 {len(files)} 个文件",
             font=('Microsoft YaHei', 13, 'bold')).pack()

    # 文件列表
    list_frame = tk.Frame(root, padx=20)
    list_frame.pack(fill='both', expand=True)

    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=canvas.yview)
    scrollable = tk.Frame(canvas)

    scrollable.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0, 0), window=scrollable, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')

    for f in files:
        item_frame = tk.Frame(scrollable, padx=10, pady=8, relief='groove', bd=1)
        item_frame.pack(fill='x', pady=4)

        icon_text = get_file_icon_text(f.get('type', ''), f.get('name', ''))
        tk.Label(item_frame, text=icon_text, font=('Segoe UI Emoji', 20)).pack(side='left', padx=8)

        info_frame = tk.Frame(item_frame)
        info_frame.pack(side='left', fill='x', expand=True, padx=5)
        tk.Label(info_frame, text=f.get('name', '未知文件'),
                 font=('Microsoft YaHei', 10), anchor='w').pack(fill='x')
        tk.Label(info_frame, text=format_size(f.get('size', 0)),
                 font=('Microsoft YaHei', 8), fg='gray', anchor='w').pack(fill='x')

    # 底部按钮
    btn_frame = tk.Frame(root, padx=20, pady=15)
    btn_frame.pack(fill='x', side='bottom')

    def open_location():
        if files:
            file_path = files[0].get('path', '')
            if file_path and os.path.exists(file_path):
                # 选中第一个文件
                subprocess.run(['explorer', '/select,', file_path])
            elif files[0].get('dir'):
                dir_path = files[0]['dir']
                if os.path.exists(dir_path):
                    subprocess.run(['explorer', dir_path])
        root.destroy()

    tk.Button(btn_frame, text='📂 打开文件位置', command=open_location,
              font=('Microsoft YaHei', 10), bg='#3b82f6', fg='white',
              relief='flat', padx=20, pady=6, cursor='hand2').pack(side='right')

    root.mainloop()

# ============================================================
# GUI: 接收文件列表窗口
# ============================================================
def show_received_files_window():
    """显示当日接收文件列表窗口"""
    try:
        show_received_files_window_impl()
    except Exception as e:
        print(f"[文件列表] 窗口显示失败: {e}")
        traceback.print_exc()

def show_received_files_window_impl():
    """接收文件列表窗口实现"""
    import tkinter as tk
    from tkinter import ttk

    records = load_received_records()

    root = tk.Tk()
    root.title("接收文件列表")
    root.geometry("500x550")
    root.resizable(False, False)

    # 标题
    tk.Label(root, text=f"📋 今日接收文件 ({len(records)} 次)",
             font=('Microsoft YaHei', 14, 'bold'), padx=20, pady=15).pack(fill='x')

    if not records:
        tk.Label(root, text="暂无接收记录", font=('Microsoft YaHei', 11),
                 fg='gray').pack(expand=True)
        tk.Button(root, text='关闭', command=root.destroy,
                  font=('Microsoft YaHei', 10), padx=20, pady=5).pack(side='bottom', pady=15)
        root.mainloop()
        return

    # 滚动区域
    main_frame = tk.Frame(root, padx=20)
    main_frame.pack(fill='both', expand=True)

    canvas = tk.Canvas(main_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(main_frame, orient='vertical', command=canvas.yview)
    scrollable = tk.Frame(canvas)

    scrollable.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0, 0), window=scrollable, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')

    for idx, record in enumerate(records):
        sender = record.get('realname') or record.get('sender', '未知')
        silent = record.get('silent', True)
        ts = record.get('timestamp', '')
        files = record.get('files', [])

        # 尝试解析时间
        try:
            dt = datetime.datetime.fromisoformat(ts)
            time_str = dt.strftime('%H:%M:%S')
        except:
            time_str = ''

        # 卡片（仅显示摘要，点击展开详情）
        card = tk.Frame(scrollable, padx=12, pady=8, relief='solid', bd=1, cursor='hand2')
        card.pack(fill='x', pady=4)

        header = tk.Frame(card)
        header.pack(fill='x')
        silent_tag = ' [静默]' if silent else ''
        tk.Label(header, text=f"📨 {sender} ({len(files)} 个文件{silent_tag})",
                 font=('Microsoft YaHei', 11, 'bold')).pack(side='left')
        tk.Label(header, text=time_str, font=('Microsoft YaHei', 9),
                 fg='gray').pack(side='right')

        # 点击卡片打开详情窗口
        def make_click_handler(rec):
            def handler(event=None):
                show_record_detail_window(rec)
            return handler

        click_handler = make_click_handler(record)
        card.bind('<Button-1>', click_handler)
        for child in card.winfo_children():
            child.bind('<Button-1>', click_handler)
            for grandchild in child.winfo_children():
                grandchild.bind('<Button-1>', click_handler)

    # 底部
    tk.Button(root, text='关闭', command=root.destroy,
              font=('Microsoft YaHei', 10), padx=20, pady=5).pack(side='bottom', pady=10)

    root.mainloop()

def show_record_detail_window(record):
    """显示单条接收记录的详情窗口（类似非静默发送的提示窗口）"""
    import tkinter as tk
    from tkinter import ttk

    sender = record.get('realname') or record.get('sender', '未知')
    files = record.get('files', [])

    root = tk.Tk()
    root.title(f"{sender} 发来的文件")
    root.geometry("420x450")
    root.resizable(False, False)

    # 标题
    title_frame = tk.Frame(root, padx=20, pady=15)
    title_frame.pack(fill='x')
    tk.Label(title_frame, text=f"📧 {sender} 发来 {len(files)} 个文件",
             font=('Microsoft YaHei', 13, 'bold')).pack()

    # 文件列表
    list_frame = tk.Frame(root, padx=20)
    list_frame.pack(fill='both', expand=True)

    canvas = tk.Canvas(list_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=canvas.yview)
    scrollable = tk.Frame(canvas)

    scrollable.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0, 0), window=scrollable, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')

    for f in files:
        item_frame = tk.Frame(scrollable, padx=10, pady=8, relief='groove', bd=1)
        item_frame.pack(fill='x', pady=4)

        icon_text = get_file_icon_text(f.get('type', ''), f.get('name', ''))
        tk.Label(item_frame, text=icon_text, font=('Segoe UI Emoji', 20)).pack(side='left', padx=8)

        info_frame = tk.Frame(item_frame)
        info_frame.pack(side='left', fill='x', expand=True, padx=5)
        tk.Label(info_frame, text=f.get('name', '未知文件'),
                 font=('Microsoft YaHei', 10), anchor='w').pack(fill='x')
        tk.Label(info_frame, text=format_size(f.get('size', 0)),
                 font=('Microsoft YaHei', 8), fg='gray', anchor='w').pack(fill='x')

    # 底部按钮
    btn_frame = tk.Frame(root, padx=20, pady=15)
    btn_frame.pack(fill='x', side='bottom')

    def open_location():
        if files:
            file_path = files[0].get('path', '')
            if file_path and os.path.exists(file_path):
                subprocess.run(['explorer', '/select,', file_path])
            elif files[0].get('dir'):
                dir_path = files[0]['dir']
                if os.path.exists(dir_path):
                    subprocess.run(['explorer', dir_path])
        root.destroy()

    tk.Button(btn_frame, text='📂 打开文件位置', command=open_location,
              font=('Microsoft YaHei', 10), bg='#3b82f6', fg='white',
              relief='flat', padx=20, pady=6, cursor='hand2').pack(side='right')

    root.mainloop()

# ============================================================
# HTTP 服务器
# ============================================================
DIRECTORY = get_app_dir()

CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.htm':  'text/html; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png':  'image/png',
    '.jpg':  'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif':  'image/gif',
    '.svg':  'image/svg+xml',
    '.ico':  'image/x-icon',
    '.woff': 'font/woff',
    '.woff2':'font/woff2',
    '.mp3':  'audio/mpeg',
    '.wav':  'audio/wav',
}

class CORSHandler(http.server.SimpleHTTPRequestHandler):
    """支持 CORS 和文件接收的 HTTP 请求处理器"""

    def log_message(self, format, *args):
        pass  # 静默日志

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        return CONTENT_TYPES.get(ext, super().guess_type(path))

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        """处理 POST 请求"""
        if self.path == '/api/receive-files':
            self.handle_receive_files()
        else:
            self.send_error(404, 'Not Found')

    def handle_receive_files(self):
        """处理文件接收请求"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            # 兼容 no-cors 模式（Content-Type 可能被浏览器改写为 text/plain）
            data = json.loads(body)

            sender = data.get('sender', 'unknown')
            realname = data.get('realname', sender)
            silent = data.get('silent', True)
            files = data.get('files', [])

            print(f"\n[接收] 收到 {sender} 发来的 {len(files)} 个文件 (静默: {silent})")

            # 在后台线程中处理文件下载
            def process_in_background():
                count = process_file_receive(sender, realname, silent, files)
                print(f"[接收] 完成: 成功下载 {count}/{len(files)} 个文件")

            threading.Thread(target=process_in_background, daemon=True).start()

            # 立即返回成功响应
            response = json.dumps({'success': True, 'message': '文件信息已接收，正在下载'}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        except Exception as e:
            print(f"[接收] 错误: {e}")
            traceback.print_exc()
            response = json.dumps({'success': False, 'error': str(e)}).encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

def find_available_port(start_port):
    """查找可用端口"""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            continue
    return start_port

# ============================================================
# 系统托盘
# ============================================================
def create_tray_icon():
    """创建系统托盘图标"""
    try:
        return create_tray_icon_impl()
    except Exception as e:
        print(f"[托盘] 创建失败: {e}")
        print("[托盘] 将以无托盘模式运行")
        return None

def create_tray_icon_impl():
    """托盘图标实现"""
    import pystray
    from PIL import Image

    # 加载图标
    icon_path = os.path.join(get_app_dir(), 'icon.ico')
    if os.path.exists(icon_path):
        try:
            image = Image.open(icon_path)
        except:
            image = Image.new('RGBA', (64, 64), (59, 130, 246, 255))
    else:
        image = Image.new('RGBA', (64, 64), (59, 130, 246, 255))

    def on_open_files(icon, item):
        threading.Thread(target=show_received_files_window, daemon=True).start()

    def on_open_timer(icon, item):
        import webbrowser
        port = PORT
        webbrowser.open(f'http://localhost:{port}/study_timer.html')

    def on_exit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem('📂 打开接收文件列表', on_open_files),
        pystray.MenuItem('⏱ 打开计时系统', on_open_timer),
        pystray.MenuItem('❌ 退出系统', on_exit)
    )

    icon = pystray.Icon(APP_NAME, image, f"{APP_NAME} {APP_VERSION}", menu)
    return icon

# ============================================================
# 主函数
# ============================================================
def main():
    # UAC 提权（如需要）
    if sys.platform == 'win32' and not is_admin():
        print("[启动] 尝试获取管理员权限...")
        if elevate():
            sys.exit(0)
        print("[启动] 未获取管理员权限，继续运行")

    # 注册开机自启动
    register_autostart()

    # 查找可用端口
    global PORT
    PORT = find_available_port(PORT)
    os.chdir(DIRECTORY)

    print("")
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   晚自习系统 - 班级大屏端已启动          ║")
    print(f"  ║   访问地址: http://localhost:{PORT}        ║")
    print(f"  ║   局域网IP: http://{get_lan_ip()}:{PORT}   ║")
    print("  ║   托盘图标已显示，点击操作               ║")
    print("  ╚══════════════════════════════════════════╝")
    print("")

    # 启动心跳线程
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()
    print("[心跳] 心跳上报已启动")

    # 处理离线文件（首次立即检查，之后每5秒实时轮询数据库）
    pending_thread = threading.Thread(target=pending_files_loop, daemon=True)
    pending_thread.start()
    print("[轮询] 数据库文件轮询已启动（每5秒）")

    # 启动 HTTP 服务器
    httpd = http.server.HTTPServer(('0.0.0.0', PORT), CORSHandler)

    # 在后台线程中启动托盘图标
    tray_icon = create_tray_icon()
    if tray_icon:
        tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
        tray_thread.start()
        print("[托盘] 系统托盘图标已显示")

    # 主循环
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务器已停止。")
        httpd.shutdown()


if __name__ == "__main__":
    main()
