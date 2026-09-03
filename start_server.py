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
# 数据库已迁移至腾讯 CloudBase PostgreSQL（PostgREST 兼容）
CB_DB_URL = 'https://wh12z213-d4gi5jt764f91a558.api.tcloudbasegateway.com/v1/rdb'
CB_API_KEY = 'eyJhbGciOiJSUzI1NiIsImtpZCI6IjNmYjk2NWJkLWU5OTQtNDc5YS04MjEwLWIzNTY0ZTM1ODY3MyJ9.eyJhdWQiOiJ3aDEyejIxMy1kNGdpNWp0NzY0ZjkxYTU1OCIsImV4cCI6MjUzNDAyMzAwNzk5LCJpYXQiOjE3ODY3ODU0NTcsImF0X2hhc2giOiJBcmpXelNNT1JFQ3ZtT01aT1lPbHBBIiwicHJvamVjdF9pZCI6IndoMTJ6MjEzLWQ0Z2k1anQ3NjRmOTFhNTU4IiwibWV0YSI6eyJwbGF0Zm9ybSI6IkFwaUtleSJ9LCJyb2xlIjoic2VydmljZV9yb2xlIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiYXBpa2V5IiwicHJvdmlkZXJzIjpbImFwaWtleSJdfSwiYWRtaW5pc3RyYXRvcl9pZCI6IjIwODg1NTMxNzA1NzY4NjczMjgiLCJ1c2VyX3R5cGUiOiIiLCJjbGllbnRfdHlwZSI6ImNsaWVudF9zZXJ2ZXIiLCJpc19zeXN0ZW1fYWRtaW4iOnRydWV9.T8YR_AZQ3lPLyDfp_tCJ0baefybTYO9Q-LtFbdCsE9bjjYvJoONyIiVk5pWGcWriaAJoQxhxn68gFwO9lsQF5U4pI_2sbkmBBXIzAbkZy1cW5ABDhREAbBYR21LrPFd5nkms0hjH5TwRR7ll8i6L1fXKoZZosGIQBPECtr96A800dXishQ7NZqx8Afcy1mRm_x1Bt8ChTVoqCOZzK8cOcTHQ3BFYs8t2FXHM-tbO0MsegilFxbJ87OxzIfsn70Whv72YormFiyQXCDL1ZrcNvMFR1ORih123nrQlhUsAXfrtQC643lbFWCk4VzEYDsp2VkYhOr13Sm-L-4faYYrGvA'
HEARTBEAT_INTERVAL = 30  # 秒
CLEANUP_INTERVAL = 1800  # 数据库清理间隔（秒），30分钟
APP_NAME = "晚自习系统"  # 开机自启注册名
APP_VERSION = "v2.9.1"

# 放学自动关机配置
SCHOOL_END_HOUR = 21       # 放学时间：21:45
SCHOOL_END_MINUTE = 45
SHUTDOWN_DELAY_MIN = 1     # 放学后1分钟触发
SHUTDOWN_COUNTDOWN = 60    # 关机倒计时（秒）

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

def get_ui_path():
    """获取 ui.html 路径（兼容 PyInstaller 打包）"""
    ui_path = os.path.join(get_app_dir(), 'ui.html')
    if os.path.exists(ui_path):
        return ui_path
    # PyInstaller 打包的资源在 _MEIPASS 目录
    if hasattr(sys, '_MEIPASS'):
        bundled = os.path.join(sys._MEIPASS, 'ui.html')
        if os.path.exists(bundled):
            return bundled
    return ui_path  # 返回默认路径，由调用方判断是否存在

def _open_file_async(file_path):
    """在后台线程中打开文件（避免阻塞UI线程）"""
    def _open():
        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.call(['open', file_path])
            else:
                subprocess.call(['xdg-open', file_path])
        except Exception as e:
            print(f"[文件] 打开失败: {e}")
    threading.Thread(target=_open, daemon=True).start()

def _open_file_dir_async(file_path):
    """在后台线程中打开文件所在文件夹并选中文件"""
    def _open():
        try:
            if sys.platform == 'win32':
                # Windows: 打开资源管理器并选中文件
                if os.path.isdir(file_path):
                    os.startfile(file_path)
                else:
                    subprocess.run(['explorer', '/select,', os.path.normpath(file_path)])
            elif sys.platform == 'darwin':
                if os.path.isdir(file_path):
                    subprocess.call(['open', file_path])
                else:
                    subprocess.call(['open', '-R', file_path])
            else:
                dir_path = os.path.dirname(file_path) if not os.path.isdir(file_path) else file_path
                subprocess.call(['xdg-open', dir_path])
        except Exception as e:
            print(f"[文件] 打开文件夹失败: {e}")
    threading.Thread(target=_open, daemon=True).start()

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
    """注册开机自启动（Windows 注册表 HKCU，静默启动）"""
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
        # 开机自启时添加 --silent 参数，静默启动到托盘，不显示窗口
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, '"' + exe_path + '" --silent')
        winreg.CloseKey(key)
        print("[自启] 开机自启已注册（静默启动模式）")
    except Exception as e:
        print(f"[自启] 注册失败: {e}")

def unregister_autostart():
    """取消开机自启动"""
    if sys.platform != 'win32':
        return
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
            print("[自启] 开机自启已取消")
        except FileNotFoundError:
            pass  # 不存在则忽略
        winreg.CloseKey(key)
    except Exception as e:
        print(f"[自启] 取消失败: {e}")

def is_silent_mode():
    """检查是否为静默启动模式（--silent 参数）"""
    return '--silent' in sys.argv or '/silent' in sys.argv

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
# CloudBase 数据库 API（PostgREST 兼容）
# ============================================================
def sb_request(method, path, body=None, prefer=None):
    """CloudBase PostgREST API 请求
    path 参数使用 /rest/{table} 格式（已从旧 /rest/v1/ 迁移）
    prefer: 额外的 Prefer 头（如 'resolution=merge-duplicates' 实现 UPSERT）
    """
    url = CB_DB_URL + path
    headers = {
        'Authorization': 'Bearer ' + CB_API_KEY,
        'Content-Type': 'application/json'
    }
    data = None
    if body and method in ('POST', 'PATCH'):
        data = json.dumps(body).encode('utf-8')
        prefer_parts = ['return=representation']
        if prefer:
            prefer_parts.append(prefer)
        headers['Prefer'] = ','.join(prefer_parts)
    elif prefer:
        headers['Prefer'] = prefer
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode('utf-8')
            # DELETE 可能返回 204 空响应
            if not resp_body or resp.status == 204:
                return [] if method == 'GET' else True
            return json.loads(resp_body)
    except urllib.error.HTTPError as e:
        err_body = ''
        try:
            err_body = e.read().decode()[:200]
        except:
            pass
        print(f"[CloudBase] HTTP {e.code}: {err_body}")
        return None
    except Exception as e:
        print(f"[CloudBase] 请求失败: {e}")
        return None

# 诊断状态跟踪
_last_heartbeat_time = None
_last_heartbeat_error = None
_last_poll_time = None
_last_poll_error = None
_last_poll_result = None  # 'empty' / 'processed' / 'error'
_poll_count = 0

# 失败重试跟踪（文件ID -> 已尝试次数）
_failed_retries = {}

def update_heartbeat():
    """更新大屏心跳（UPSERT：不存在则插入，存在则更新）"""
    global _last_heartbeat_time, _last_heartbeat_error
    ip = get_lan_ip()
    now = datetime.datetime.now().isoformat()
    result = sb_request('POST', '/rest/screen_heartbeat', {
        'id': 1,
        'last_heartbeat': now,
        'ip_address': ip,
        'port': PORT
    }, prefer='resolution=merge-duplicates')
    if result is not None:
        _last_heartbeat_time = now
        _last_heartbeat_error = None
    else:
        _last_heartbeat_error = 'sb_request returned None'
    return result is not None

def heartbeat_loop():
    """心跳循环线程"""
    while True:
        try:
            update_heartbeat()
        except Exception as e:
            global _last_heartbeat_error
            _last_heartbeat_error = str(e)
            print(f"[心跳] 异常: {e}")
        time.sleep(HEARTBEAT_INTERVAL)

def pending_files_loop():
    """实时检查待接收文件（每5秒轮询数据库）"""
    global _last_poll_time, _last_poll_error, _last_poll_result, _poll_count
    while True:
        _poll_count += 1
        try:
            process_pending_files()
            _last_poll_time = datetime.datetime.now().isoformat()
            _last_poll_error = None
        except Exception as e:
            _last_poll_time = datetime.datetime.now().isoformat()
            _last_poll_error = f"{type(e).__name__}: {e}"
            print(f"[轮询] 第{_poll_count}次异常: {e}")
            traceback.print_exc()
        time.sleep(5)

def get_pending_files():
    """获取待下载的文件列表"""
    result = sb_request('GET', '/rest/pending_files?downloaded=eq.false&order=created_at.asc')
    return result if result else []

def delete_pending_file(file_id):
    """删除已下载的待接收文件记录"""
    sb_request('DELETE', '/rest/pending_files?id=eq.' + str(file_id))

# ============================================================
# 数据库过期数据清理
# ============================================================
def sb_delete_by_filter(table, filter_str):
    """删除满足条件的记录"""
    sb_request('DELETE', f'/rest/{table}?{filter_str}')

def sb_get_all(table, select='*'):
    """获取表中所有记录"""
    result = sb_request('GET', f'/rest/{table}?select={select}')
    return result if result else []

def cleanup_expired_data():
    """清理数据库中的过期数据（不影响文件接收和心跳功能）"""
    now = datetime.datetime.now()
    now_iso = now.isoformat()
    errors = []

    # 1. 清理过期验证码（verify_codes 表）
    try:
        codes = sb_get_all('verify_codes')
        for code in codes:
            if code.get('expires_at') and datetime.datetime.fromisoformat(code['expires_at'].replace('Z', '+00:00')).replace(tzinfo=None) < now:
                sb_delete_by_filter('verify_codes', 'id=eq.' + str(code['id']))
    except Exception as e:
        errors.append(f'verify_codes: {e}')

    # 2. 清理过期密码重置链接（reset_tokens 表）
    try:
        tokens = sb_get_all('reset_tokens')
        for token in tokens:
            if token.get('expires_at') and datetime.datetime.fromisoformat(token['expires_at'].replace('Z', '+00:00')).replace(tzinfo=None) < now:
                sb_delete_by_filter('reset_tokens', 'id=eq.' + str(token['id']))
    except Exception as e:
        errors.append(f'reset_tokens: {e}')

    # 3. 清理超过90天的发送通知历史（notification_history 表）
    try:
        cutoff_90d = (now - datetime.timedelta(days=90)).isoformat()
        # 使用 lt 操作符：created_at < cutoff
        sb_delete_by_filter('notification_history', f'created_at=lt.{cutoff_90d}')
    except Exception as e:
        errors.append(f'notification_history: {e}')

    # 4. 清理超过90天的文件发送历史（file_transfer_history 表）
    try:
        cutoff_90d_fth = (now - datetime.timedelta(days=90)).isoformat()
        sb_delete_by_filter('file_transfer_history', f'created_at=lt.{cutoff_90d_fth}')
    except Exception as e:
        errors.append(f'file_transfer_history: {e}')

    # 5. 清理已下载的待发送文件及超过90天的待发送文件（pending_files 表）
    #    注意：不清理未下载且未过期的文件，避免丢失待接收文件
    try:
        cutoff_90d_pf = (now - datetime.timedelta(days=90)).isoformat()
        # 删除已下载的记录
        sb_delete_by_filter('pending_files', 'downloaded=eq.true')
        # 删除超过90天的记录
        sb_delete_by_filter('pending_files', f'created_at=lt.{cutoff_90d_pf}')
    except Exception as e:
        errors.append(f'pending_files: {e}')

    # 6. 清理大屏心跳表（screen_heartbeat）
    #    - 删除多余行（id != 1）
    #    - 若心跳超过24小时，删除该行
    try:
        hb_rows = sb_get_all('screen_heartbeat')
        hb_cutoff = (now - datetime.timedelta(hours=24)).isoformat()
        for hb in hb_rows:
            if hb.get('id') != 1:
                sb_delete_by_filter('screen_heartbeat', 'id=eq.' + str(hb['id']))
            elif hb.get('last_heartbeat') and hb['last_heartbeat'] < hb_cutoff:
                sb_delete_by_filter('screen_heartbeat', 'id=eq.' + str(hb['id']))
    except Exception as e:
        errors.append(f'screen_heartbeat: {e}')

    # 7. 清理超过90天的登录记录（login_records 表）
    try:
        cutoff_90d_lr = (now - datetime.timedelta(days=90)).isoformat()
        sb_delete_by_filter('login_records', f'created_at=lt.{cutoff_90d_lr}')
    except Exception as e:
        errors.append(f'login_records: {e}')

    # 8. 清理超过90天的修改请求记录（modify_requests 表）
    try:
        cutoff_90d_mr = (now - datetime.timedelta(days=90)).isoformat()
        sb_delete_by_filter('modify_requests', f'created_at=lt.{cutoff_90d_mr}')
    except Exception as e:
        errors.append(f'modify_requests: {e}')

    # 9. 清理超过5天的座位表推送数据（seat_choose 表）
    try:
        cutoff_5d_sc = (now - datetime.timedelta(days=5)).isoformat()
        sb_delete_by_filter('seat_choose', f'created_at=lt.{cutoff_5d_sc}')
    except Exception as e:
        errors.append(f'seat_choose: {e}')

    if errors:
        print(f"[清理] 部分清理失败: {'; '.join(errors)}")
    else:
        print(f"[清理] 过期数据清理完成 ({now.strftime('%Y-%m-%d %H:%M:%S')})")

def cleanup_loop():
    """数据库清理循环线程（每30分钟执行一次）"""
    # 首次启动延迟60秒，避免与其他启动任务竞争
    time.sleep(60)
    while True:
        try:
            cleanup_expired_data()
        except Exception as e:
            print(f"[清理] 清理异常: {e}")
        time.sleep(CLEANUP_INTERVAL)

# ============================================================
# 放学自动关机
# ============================================================
def get_today_schedule_exists():
    """检查今日是否有晚自习时间表（避免非晚自习日触发关机）"""
    today = datetime.date.today().isoformat()
    result = sb_request('GET', f'/rest/schedules?date=eq.{today}&select=date&limit=1')
    return bool(result)

def show_shutdown_countdown():
    """显示放学关机倒计时窗口（置顶显示）"""
    try:
        show_shutdown_countdown_impl()
    except Exception as e:
        print(f"[关机] 倒计时窗口异常: {e}")
        traceback.print_exc()

def show_shutdown_countdown_impl():
    """关机倒计时窗口实现（tkinter）— 简洁黑色背景 + 倒计时"""
    import tkinter as tk

    # 获取屏幕尺寸（全屏覆盖）
    screen_w = None
    screen_h = None
    try:
        temp_root = tk.Tk()
        screen_w = temp_root.winfo_screenwidth()
        screen_h = temp_root.winfo_screenheight()
        temp_root.destroy()
    except:
        screen_w, screen_h = 1920, 1080

    root = tk.Tk()
    root.title("放学提醒")
    root.geometry(f"{screen_w}x{screen_h}+0+0")
    root.overrideredirect(True)       # 无边框全屏
    root.attributes('-topmost', True)  # 置顶
    root.configure(bg='#000000')      # 纯黑背景

    # ===== 主画布（全屏，纯黑背景） =====
    canvas = tk.Canvas(root, width=screen_w, height=screen_h, highlightthickness=0, bg='#000000')
    canvas.pack(fill='both', expand=True)

    # 坐标辅助
    cx = screen_w // 2
    cy = screen_h // 2

    # ===== 顶部文字 =====
    banner_text = canvas.create_text(cx, cy - 200, text="放学啦",
                                      fill='#ffffff', font=('Microsoft YaHei', 48, 'bold'))

    # ===== 倒计时数字 =====
    countdown_num = canvas.create_text(cx, cy + 20, text=str(SHUTDOWN_COUNTDOWN),
                                        fill='#ffffff', font=('Microsoft YaHei', 120, 'bold'))

    # ===== 副文字 =====
    sub_text = canvas.create_text(cx, cy + 120, text="秒后电脑将自动关机",
                                   fill='#cccccc', font=('Microsoft YaHei', 22))

    # ===== 进度条 =====
    bar_w = min(screen_w - 200, 600)
    bar_x1 = cx - bar_w // 2
    bar_x2 = cx + bar_w // 2
    bar_y1 = cy + 170
    bar_y2 = cy + 180
    bar_bg = canvas.create_rectangle(bar_x1, bar_y1, bar_x2, bar_y2, fill='#222222', outline='#333333', width=1)
    bar_fill = canvas.create_rectangle(bar_x1, bar_y1, bar_x2, bar_y2, fill='#6366f1', outline='')

    # ===== 取消按钮 =====
    btn_w, btn_h = 300, 70
    btn_x1 = cx - btn_w // 2
    btn_y1 = cy + 220
    btn_x2 = cx + btn_w // 2
    btn_y2 = btn_y1 + btn_h

    def draw_rounded_rect(c, x1, y1, x2, y2, r=20, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r,
               x2, y2-r, x2, y2, x2-r, y2,
               x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return c.create_polygon(pts, smooth=True, **kw)

    btn_rect = draw_rounded_rect(canvas, btn_x1, btn_y1, btn_x2, btn_y2, r=20, fill='#1a1a1a', outline='#333333', width=2)
    btn_text = canvas.create_text(cx, btn_y1 + btn_h // 2,
                                   text=f"取消关机（{SHUTDOWN_COUNTDOWN}s）",
                                   fill='#888888', font=('Microsoft YaHei', 22, 'bold'))

    # ===== 状态变量 =====
    remaining = [SHUTDOWN_COUNTDOWN]
    shutdown_cancelled = [False]

    # ===== 倒计时更新（每秒） =====
    def update_countdown():
        if shutdown_cancelled[0]:
            return
        if remaining[0] <= 0:
            canvas.itemconfig(countdown_num, text="关机")
            canvas.itemconfig(sub_text, text="正在关闭电脑...")
            root.after(300, do_shutdown)
            return

        canvas.itemconfig(countdown_num, text=str(remaining[0]))
        canvas.itemconfig(btn_text, text=f"取消关机（{remaining[0]}s）")

        # 进度条：按比例缩短
        progress_ratio = remaining[0] / SHUTDOWN_COUNTDOWN
        new_x2 = bar_x1 + int((bar_x2 - bar_x1) * progress_ratio)
        canvas.coords(bar_fill, bar_x1, bar_y1, new_x2, bar_y2)

        remaining[0] -= 1
        root.after(1000, update_countdown)

    def do_shutdown():
        if shutdown_cancelled[0]:
            return
        print("[关机] 倒计时结束，正在关闭电脑...")
        root.destroy()
        if sys.platform == 'win32':
            os.system('shutdown /s /f /t 0')
        else:
            os.system('poweroff')

    def cancel_shutdown():
        shutdown_cancelled[0] = True
        print("[关机] 用户取消了关机")
        root.destroy()

    # 按钮点击
    canvas.tag_bind(btn_rect, '<Button-1>', lambda e: cancel_shutdown())
    canvas.tag_bind(btn_text, '<Button-1>', lambda e: cancel_shutdown())
    # 点击空白处也可取消
    canvas.bind('<Button-1>', lambda e: cancel_shutdown())
    # ESC 键取消
    root.bind('<Escape>', lambda e: cancel_shutdown())

    # 按钮悬停效果
    def on_enter(event):
        canvas.itemconfig(btn_rect, fill='#2a2a2a', outline='#555555')
        canvas.itemconfig(btn_text, fill='#cccccc')
    def on_leave(event):
        canvas.itemconfig(btn_rect, fill='#1a1a1a', outline='#333333')
        canvas.itemconfig(btn_text, fill='#888888')
    canvas.tag_bind(btn_rect, '<Enter>', on_enter)
    canvas.tag_bind(btn_rect, '<Leave>', on_leave)
    canvas.tag_bind(btn_text, '<Enter>', on_enter)
    canvas.tag_bind(btn_text, '<Leave>', on_leave)

    # 启动倒计时
    update_countdown()
    root.mainloop()


def school_end_monitor():
    """放学监控线程：放学后1分钟触发关机倒计时窗口"""
    triggered_date = None  # 记录已触发的日期，每天只触发一次
    while True:
        try:
            now = datetime.datetime.now()
            today_str = now.date().isoformat()

            # 每天只触发一次
            if triggered_date != today_str:
                # 计算触发时间：放学时间 + 1分钟
                school_end = now.replace(hour=SCHOOL_END_HOUR, minute=SCHOOL_END_MINUTE, second=0, microsecond=0)
                trigger_time = school_end + datetime.timedelta(minutes=SHUTDOWN_DELAY_MIN)

                if now >= trigger_time:
                    # 检查今日是否有晚自习时间表
                    if get_today_schedule_exists():
                        print(f"[放学] 已过放学时间（{SCHOOL_END_HOUR}:{SCHOOL_END_MINUTE:02d}），"
                              f"触发关机倒计时（{SHUTDOWN_COUNTDOWN}s）")
                        triggered_date = today_str
                        show_shutdown_countdown()
                    else:
                        # 今日无时间表，跳过关机
                        triggered_date = today_str
                        print(f"[放学] 今日无晚自习时间表，跳过自动关机")
        except Exception as e:
            print(f"[放学] 监控异常: {e}")

        time.sleep(10)  # 每10秒检查一次

# ============================================================
# 文件下载
# ============================================================
def download_file(url, save_path):
    """下载文件到指定路径
    返回: (success: bool, error_type: str|None)
    error_type: 'not_found'=文件已过期/不存在, 'network'=网络错误, 'timeout'=超时, None=成功
    """
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
        return True, None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[下载] 文件已过期/不存在 (404): {url}")
            return False, 'not_found'
        print(f"[下载] HTTP错误 {e.code}: {e.reason}")
        return False, 'http_error'
    except urllib.error.URLError as e:
        if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
            print(f"[下载] 超时: {url}")
            return False, 'timeout'
        print(f"[下载] 网络错误: {e}")
        return False, 'network'
    except Exception as e:
        print(f"[下载] 失败: {e}")
        return False, 'unknown'
    finally:
        # 下载失败时清理残留的部分文件
        if os.path.exists(save_path):
            try:
                # 检查是否是成功下载的完整文件（通过Content-Length对比）
                # 如果文件存在但函数返回失败，说明是部分文件，需清理
                pass  # 清理逻辑在调用方处理，这里不自动删除
            except:
                pass

def process_file_receive(sender, realname, silent, files):
    """处理收到的文件信息：下载文件并保存
    返回: (成功下载数, 已完成文件ID列表, 失败文件ID列表, 过期文件ID列表)
    """
    save_dir = get_user_receive_dir(sender)
    os.makedirs(save_dir, exist_ok=True)

    downloaded_files = []
    done_ids = []      # 成功下载的文件ID
    failed_ids = []    # 下载失败（网络/超时等，可重试）的文件ID
    expired_ids = []   # 文件已过期/不存在（404，不可恢复）的文件ID

    for f in files:
        file_name = f.get('name', 'unknown')
        file_size = f.get('size', 0)
        file_type = f.get('type', '')
        download_url = f.get('downloadUrl') or f.get('shareUrl', '')
        file_id = f.get('_id')  # 内部传递的数据库记录ID

        if not download_url:
            if file_id:
                expired_ids.append(file_id)  # 无URL视为不可恢复
            continue

        # 处理文件名冲突：重名文件追加全角序号，如 report（2）.pdf、report（3）.pdf
        save_path = os.path.join(save_dir, file_name)
        if os.path.exists(save_path):
            name, ext = os.path.splitext(file_name)
            counter = 2
            while os.path.exists(save_path):
                save_path = os.path.join(save_dir, f"{name}（{counter}）{ext}")
                counter += 1

        print(f"[接收] 正在下载: {file_name} ({format_size(file_size)})")
        print(f"[接收] URL: {download_url[:80]}")
        success, error_type = download_file(download_url, save_path)
        if success:
            # 验证下载的文件不是HTML页面（可能是shareUrl而非downloadUrl）
            try:
                with open(save_path, 'rb') as check_f:
                    first_bytes = check_f.read(512)
                if first_bytes.startswith(b'<!DOCTYPE') or first_bytes.startswith(b'<html') or first_bytes.startswith(b'<HTML'):
                    print(f"[接收] ⚠ {file_name} 下载内容是HTML页面，非实际文件！URL可能是分享页而非下载链接")
                    os.unlink(save_path)
                    if file_id:
                        expired_ids.append(file_id)
                    continue
            except:
                pass
            downloaded_files.append({
                'name': os.path.basename(save_path),
                'path': save_path,
                'size': file_size,
                'type': file_type,
                'dir': save_dir
            })
            if file_id:
                done_ids.append(file_id)
            print(f"[接收] ✓ {file_name}")
        else:
            # 下载失败，清理残留的部分文件
            if os.path.exists(save_path):
                try:
                    os.unlink(save_path)
                    print(f"[接收] 已清理残留文件: {save_path}")
                except:
                    pass
            if file_id:
                if error_type == 'not_found':
                    expired_ids.append(file_id)
                    print(f"[接收] ✗ {file_name} 文件已过期，源站已删除")
                else:
                    failed_ids.append(file_id)
                    print(f"[接收] ✗ {file_name} 下载失败 ({error_type})，稍后重试")

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

    return len(downloaded_files), done_ids, failed_ids, expired_ids

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
MAX_DOWNLOAD_RETRIES = 5  # 最大重试次数

def process_pending_files():
    """处理数据库中待下载的文件
    - 成功下载的记录：立即删除
    - 文件已过期(404)的记录：立即删除（不可恢复）
    - 下载失败(网络/超时)的记录：保留，下次轮询重试
    - 超过 MAX_DOWNLOAD_RETRIES 次重试的记录：删除并记录日志
    """
    global _last_poll_result
    pending = get_pending_files()
    if not pending:
        _last_poll_result = 'empty'
        return  # 无待接收文件，静默返回

    _last_poll_result = 'processing'
    print(f"[轮询] 检测到 {len(pending)} 个待接收文件，开始处理...")

    # 按发送者分组
    groups = {}
    for pf in pending:
        key = (pf.get('sender_username'), pf.get('sender_realname'), pf.get('silent', True))
        if key not in groups:
            groups[key] = []
        groups[key].append(pf)

    for (sender, realname, silent), items in groups.items():
        files = []
        for item in items:
            files.append({
                '_id': item.get('id'),  # 传递数据库记录ID用于跟踪
                'name': item.get('file_name', 'unknown'),
                'size': item.get('file_size', 0),
                'type': item.get('file_type', ''),
                'downloadUrl': item.get('download_url', ''),
                'shareUrl': item.get('share_url', '')
            })

        print(f"[轮询] 发现 {sender} 的 {len(files)} 个文件...")
        count, done_ids, failed_ids, expired_ids = process_file_receive(
            sender, realname or sender, silent, files
        )

        # 1. 删除成功下载的记录
        for fid in done_ids:
            delete_pending_file(fid)
            _failed_retries.pop(fid, None)  # 清除重试计数

        # 2. 删除已过期(404)的记录（不可恢复）
        for fid in expired_ids:
            delete_pending_file(fid)
            _failed_retries.pop(fid, None)
            print(f"[轮询] 文件已过期，已删除记录 {fid}")

        # 3. 对失败记录更新重试计数
        for fid in failed_ids:
            _failed_retries[fid] = _failed_retries.get(fid, 0) + 1
            if _failed_retries[fid] >= MAX_DOWNLOAD_RETRIES:
                print(f"[轮询] 文件 {fid} 重试 {_failed_retries[fid]} 次仍失败，放弃并删除记录")
                delete_pending_file(fid)
                _failed_retries.pop(fid, None)
            else:
                print(f"[轮询] 文件 {fid} 第 {_failed_retries[fid]}/{MAX_DOWNLOAD_RETRIES} 次重试，稍后再试")

        print(f"[轮询] 已接收 {count}/{len(files)} 个文件"
              + (f"，过期 {len(expired_ids)}" if expired_ids else "")
              + (f"，待重试 {len(failed_ids)}" if failed_ids else ""))

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

# 全局标记：通知窗口显示中，避免并发弹出多个窗口阻塞线程
_notification_window_open = False

def show_notification_window(sender, realname, files):
    """显示非静默发送的文件接收提示窗口（非阻塞，在新线程中运行）"""
    global _notification_window_open
    # 防止并发弹出多个通知窗口（主轮询线程/HTTP线程都不会被阻塞）
    if _notification_window_open:
        print("[通知] 已有通知窗口显示中，跳过本次弹窗")
        return
    _notification_window_open = True

    def _run():
        global _notification_window_open
        try:
            show_notification_window_impl(sender, realname, files)
        except Exception as e:
            print(f"[通知] 窗口显示失败: {e}")
            traceback.print_exc()
        finally:
            _notification_window_open = False

    threading.Thread(target=_run, daemon=True).start()

# 通知窗口自动关闭超时（毫秒）：避免长期占用线程导致后续通知被屏蔽
NOTIFICATION_WINDOW_TIMEOUT_MS = 30 * 1000

def show_notification_window_impl(sender, realname, files):
    """通知窗口实现（tkinter）

    该函数运行在独立线程中（由 show_notification_window 调起），
    自带超时自动关闭与异常清理，确保线程一定会退出、不会长期占用。
    """
    import tkinter as tk
    from tkinter import ttk

    if not files:
        print("[通知] 无文件可显示，跳过弹窗")
        return

    root = tk.Tk()
    root.title(f"{realname or sender} 发来文件")
    root.geometry("420x450")
    root.resizable(False, False)

    # 统一的关闭清理逻辑，防止重复 destroy
    closed = {'flag': False}

    def _cleanup():
        if closed['flag']:
            return
        closed['flag'] = True
        try:
            root.destroy()
        except Exception:
            pass

    # 窗口关闭按钮（X）走统一清理
    root.protocol("WM_DELETE_WINDOW", _cleanup)

    # 超时自动关闭：避免窗口无人处理时长期占用线程
    try:
        root.after(NOTIFICATION_WINDOW_TIMEOUT_MS, _cleanup)
    except Exception as e:
        print(f"[通知] 设置超时失败: {e}")

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
        try:
            if files:
                file_path = files[0].get('path', '')
                if file_path and os.path.exists(file_path):
                    # 后台线程打开并选中文件，避免 explorer 阻塞 UI 线程
                    _open_file_dir_async(file_path)
                else:
                    dir_path = files[0].get('dir', '')
                    if dir_path and os.path.exists(dir_path):
                        _open_file_dir_async(dir_path)
        except Exception as e:
            print(f"[通知] 打开文件位置失败: {e}")
        _cleanup()

    tk.Button(btn_frame, text='📂 打开文件位置', command=open_location,
              font=('Microsoft YaHei', 10), bg='#3b82f6', fg='white',
              relief='flat', padx=20, pady=6, cursor='hand2').pack(side='right')

    try:
        root.mainloop()
    finally:
        _cleanup()

# ============================================================
# GUI: 接收文件列表窗口
# ============================================================
# 全局标记：防止重复打开窗口
_file_list_window_open = False
_webview_started = False

def show_received_files_window():
    """显示接收文件列表窗口（非阻塞）

    所有 UI 工作（WebView 或 Tkinter 回退）都在独立的工作线程中执行，
    调用方（托盘菜单/HTTP 等）不会被阻塞。通过 _file_list_window_open
    标记防止并发重复打开。
    """
    global _file_list_window_open

    # 防止重复打开
    if _file_list_window_open:
        print("[文件列表] 窗口已打开，跳过重复请求")
        return

    _file_list_window_open = True
    threading.Thread(target=_show_received_files_window_worker, daemon=True).start()


def _show_received_files_window_worker():
    """文件列表窗口工作线程：优先 WebView，失败回退 Tkinter"""
    global _file_list_window_open, _webview_started
    try:
        # 优先尝试 pywebview（HTML界面，不唤起浏览器，不卡顿）
        ui_path = get_ui_path()
        if os.path.exists(ui_path):
            try:
                import webview
                url = f'http://127.0.0.1:{PORT}/ui.html'
                print(f"[文件列表] 使用 WebView 打开: {url}")

                # 首次启动需调用 webview.start()（阻塞至窗口关闭）；
                # 已启动则直接创建新窗口。两者均在当前工作线程中执行，
                # 不会阻塞调用方。
                if not _webview_started:
                    webview.create_window(
                        '接收文件列表',
                        url,
                        width=780,
                        height=640,
                        resizable=True,
                        min_size=(600, 500),
                        background_color='#667eea'
                    )
                    _webview_started = True
                    webview.start(debug=False)
                else:
                    webview.create_window(
                        '接收文件列表',
                        url,
                        width=780,
                        height=640,
                        resizable=True,
                        min_size=(600, 500),
                        background_color='#667eea'
                    )
                return
            except ImportError:
                print("[文件列表] pywebview 未安装，使用 Tkinter 界面")
            except Exception as e:
                print(f"[文件列表] WebView 异常: {e}")
                traceback.print_exc()
        # 回退到 Tkinter
        show_received_files_window_tk()
    except Exception as e:
        print(f"[文件列表] 窗口显示失败: {e}")
        traceback.print_exc()
    finally:
        _file_list_window_open = False

def show_received_files_window_tk():
    """Tkinter 版本接收文件列表窗口（回退方案）"""
    import tkinter as tk
    from tkinter import ttk

    try:
        records = load_received_records()

        root = tk.Tk()
        root.title("接收文件列表")
        root.geometry("500x550")
        root.resizable(False, False)

        # 统一关闭逻辑（_file_list_window_open 标记由调用方的工作线程 finally 重置）
        def _close():
            try:
                root.destroy()
            except Exception:
                pass

        root.protocol("WM_DELETE_WINDOW", _close)

        # 标题
        tk.Label(root, text=f"📋 今日接收文件 ({len(records)} 次)",
                 font=('Microsoft YaHei', 14, 'bold'), padx=20, pady=15).pack(fill='x')

        if not records:
            tk.Label(root, text="暂无接收记录", font=('Microsoft YaHei', 11),
                     fg='gray').pack(expand=True)
            tk.Button(root, text='关闭', command=_close,
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
        tk.Button(root, text='关闭', command=_close,
                  font=('Microsoft YaHei', 10), padx=20, pady=5).pack(side='bottom', pady=10)

        root.mainloop()
    except Exception as e:
        print(f"[文件列表] Tkinter 窗口异常: {e}")
        traceback.print_exc()

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
                _open_file_dir_async(file_path)
            elif files[0].get('dir'):
                dir_path = files[0]['dir']
                if os.path.exists(dir_path):
                    _open_file_dir_async(dir_path)
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

    def do_GET(self):
        """处理 GET 请求：静态文件 + API 端点"""
        path = self.path.split('?')[0]  # 去掉查询参数
        if path == '/api/status':
            self.handle_status()
        elif path == '/api/diagnostic':
            self.handle_diagnostic()
        elif path == '/api/received-records':
            self.handle_received_records()
        elif path == '/api/open-file':
            self.handle_open_file()
        elif path == '/api/open-file-dir':
            self.handle_open_file_dir()
        elif path == '/api/open-receive-dir':
            self.handle_open_receive_dir()
        elif path == '/ui.html' or path == '/ui':
            self.handle_ui_page()
        else:
            super().do_GET()

    def handle_status(self):
        """诊断端点：返回大屏内部状态"""
        try:
            pending = get_pending_files()
            status = {
                'app_version': APP_VERSION,
                'port': PORT,
                'lan_ip': get_lan_ip(),
                'pending_files_count': len(pending),
                'pending_files': [
                    {
                        'id': str(pf.get('id', ''))[:8] + '...',
                        'name': pf.get('file_name', '?'),
                        'sender': pf.get('sender_username', '?'),
                        'created_at': pf.get('created_at', '?'),
                        'downloaded': pf.get('downloaded', '?'),
                        'download_url': pf.get('download_url', '?')[:60] + '...'
                    }
                    for pf in pending
                ],
                'failed_retries': {str(k)[:8]+'...': v for k, v in _failed_retries.items()},
                'heartbeat_last': _last_heartbeat_time,
                'heartbeat_error': _last_heartbeat_error,
                'poll_count': _poll_count,
                'poll_last': _last_poll_time,
                'poll_last_error': _last_poll_error,
                'time_now': datetime.datetime.now().isoformat()
            }
            body = json.dumps(status, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            err = json.dumps({'error': str(e)}, ensure_ascii=False).encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(err)))
            self.end_headers()
            self.wfile.write(err)

    def handle_diagnostic(self):
        """深度诊断：测试数据库连通性 + EasySend可达性 + 文件下载测试"""
        diag = {'time': datetime.datetime.now().isoformat(), 'tests': {}}

        # 1. 数据库连通性测试
        try:
            result = sb_request('GET', '/rest/screen_heartbeat?select=id,last_heartbeat&limit=1')
            diag['tests']['database'] = {
                'status': 'ok' if result is not None else 'error',
                'detail': f'返回 {len(result) if result else 0} 条心跳记录' if result else 'sb_request返回None',
                'heartbeat': result[0] if result else None
            }
        except Exception as e:
            diag['tests']['database'] = {'status': 'error', 'detail': str(e)}

        # 2. pending_files 查询测试
        try:
            pending = get_pending_files()
            diag['tests']['pending_files_query'] = {
                'status': 'ok',
                'count': len(pending),
                'files': [{'name': pf.get('file_name'), 'url': pf.get('download_url', '')[:80]}
                          for pf in pending[:5]]
            }
        except Exception as e:
            diag['tests']['pending_files_query'] = {'status': 'error', 'detail': str(e)}

        # 3. EasySend 可达性测试
        try:
            test_url = 'https://easysend.co'
            req = urllib.request.Request(test_url, headers={'User-Agent': 'Mozilla/5.0'}, method='HEAD')
            with urllib.request.urlopen(req, timeout=10) as resp:
                diag['tests']['easysend_reachable'] = {
                    'status': 'ok', 'http_code': resp.status
                }
        except urllib.error.HTTPError as e:
            diag['tests']['easysend_reachable'] = {
                'status': 'ok', 'detail': f'HTTP {e.code} (服务可达，HEAD被拒属正常)'
            }
        except Exception as e:
            diag['tests']['easysend_reachable'] = {
                'status': 'error', 'detail': f'{type(e).__name__}: {e}'
            }

        # 4. 如果有pending文件，测试第一个文件的下载URL
        try:
            pending = get_pending_files()
            if pending:
                test_file = pending[0]
                test_dl_url = test_file.get('download_url', '')
                if test_dl_url:
                    req2 = urllib.request.Request(test_dl_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
                    }, method='HEAD')
                    try:
                        with urllib.request.urlopen(req2, timeout=15) as resp2:
                            diag['tests']['file_download_test'] = {
                                'status': 'ok',
                                'file': test_file.get('file_name'),
                                'http_code': resp2.status,
                                'content_type': resp2.headers.get('Content-Type'),
                                'content_length': resp2.headers.get('Content-Length')
                            }
                    except urllib.error.HTTPError as e:
                        diag['tests']['file_download_test'] = {
                            'status': 'error',
                            'file': test_file.get('file_name'),
                            'http_code': e.code,
                            'detail': f'文件可能已过期或不存在 ({e.code})'
                        }
                    except Exception as e:
                        diag['tests']['file_download_test'] = {
                            'status': 'error',
                            'file': test_file.get('file_name'),
                            'detail': f'{type(e).__name__}: {e}'
                        }
            else:
                diag['tests']['file_download_test'] = {'status': 'skip', 'detail': '无待接收文件'}
        except Exception as e:
            diag['tests']['file_download_test'] = {'status': 'error', 'detail': str(e)}

        # 5. 线程状态
        diag['tests']['threads'] = {
            'poll_count': _poll_count,
            'poll_last_time': _last_poll_time,
            'poll_last_error': _last_poll_error,
            'heartbeat_last_time': _last_heartbeat_time,
            'heartbeat_last_error': _last_heartbeat_error,
            'failed_retries_count': len(_failed_retries)
        }

        body = json.dumps(diag, ensure_ascii=False, indent=2).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status=200):
        """发送 JSON 响应"""
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_received_records(self):
        """返回当日接收文件记录列表（UI用）"""
        try:
            records = load_received_records()
            # 按时间倒序排列
            records_sorted = sorted(records, key=lambda r: r.get('timestamp', ''), reverse=True)
            self._send_json({'records': records_sorted})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def handle_open_file(self):
        """打开指定文件"""
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            rec_idx = int(params.get('rec', ['-1'])[0])
            file_idx = int(params.get('file', ['-1'])[0])

            records = load_received_records()
            records_sorted = sorted(records, key=lambda r: r.get('timestamp', ''), reverse=True)

            if 0 <= rec_idx < len(records_sorted) and 0 <= file_idx < len(records_sorted[rec_idx].get('files', [])):
                file_path = records_sorted[rec_idx]['files'][file_idx].get('path', '')
                if file_path and os.path.exists(file_path):
                    _open_file_async(file_path)
                    self._send_json({'success': True})
                else:
                    self._send_json({'error': '文件不存在'}, 404)
            else:
                self._send_json({'error': '索引越界'}, 400)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def handle_open_file_dir(self):
        """打开文件所在文件夹"""
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            rec_idx = int(params.get('rec', ['-1'])[0])
            file_idx = int(params.get('file', ['-1'])[0])

            records = load_received_records()
            records_sorted = sorted(records, key=lambda r: r.get('timestamp', ''), reverse=True)

            if 0 <= rec_idx < len(records_sorted) and 0 <= file_idx < len(records_sorted[rec_idx].get('files', [])):
                file_path = records_sorted[rec_idx]['files'][file_idx].get('path', '')
                if file_path and os.path.exists(file_path):
                    _open_file_dir_async(file_path)
                    self._send_json({'success': True})
                else:
                    self._send_json({'error': '文件不存在'}, 404)
            else:
                self._send_json({'error': '索引越界'}, 400)
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def handle_open_receive_dir(self):
        """打开接收文件夹根目录"""
        try:
            receive_dir = get_receive_dir()
            os.makedirs(receive_dir, exist_ok=True)
            _open_file_dir_async(receive_dir)
            self._send_json({'success': True})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def handle_ui_page(self):
        """返回 ui.html 页面（从资源文件读取，支持打包进exe）"""
        try:
            ui_path = get_ui_path()
            if os.path.exists(ui_path):
                with open(ui_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                body = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404, 'UI Page Not Found')
        except Exception as e:
            self.send_error(500, str(e))

    def do_POST(self):
        # 处理关机请求
        if self.path == '/shutdown':
            import threading
            def shutdown_thread():
                import time
                time.sleep(0.5)
                print("[关机] 收到HTML关机请求，正在关闭电脑...")
                if sys.platform == 'win32':
                    os.system('shutdown /s /f /t 0')
                else:
                    os.system('poweroff')
            threading.Thread(target=shutdown_thread, daemon=True).start()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'OK')
            return
        """处理 POST 请求"""
        if self.path == '/api/receive-files':
            self.handle_receive_files()
        elif self.path == '/api/upload':
            self.handle_upload_file()
        elif self.path == '/api/upload-init':
            self.handle_upload_init()
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
                try:
                    count, done_ids, failed_ids, expired_ids = process_file_receive(sender, realname, silent, files)
                    print(f"[接收] 完成: 成功下载 {count}/{len(files)} 个文件"
                          + (f"，过期 {len(expired_ids)}" if expired_ids else "")
                          + (f"，失败 {len(failed_ids)}" if failed_ids else ""))
                except Exception as e:
                    print(f"[接收] 后台下载线程异常: {e}")
                    traceback.print_exc()

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

    def handle_upload_init(self):
        """局域网直传：初始化上传（返回上传端点信息）"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
            data = json.loads(body) if body else {}

            sender = data.get('sender', 'unknown')
            file_count = data.get('file_count', 0)

            # 创建接收目录
            sender_dir = get_user_receive_dir(sender)
            os.makedirs(sender_dir, exist_ok=True)

            response = json.dumps({
                'success': True,
                'message': 'Ready to receive files',
                'upload_endpoint': f'/api/upload',
                'max_chunk_size': 1024 * 1024  # 1MB per chunk
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        except Exception as e:
            print(f"[直传] 初始化失败: {e}")
            response = json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False).encode('utf-8')
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    def handle_upload_file(self):
        """局域网直传：接收文件（支持multipart/form-data和二进制）"""
        try:
            content_type = self.headers.get('Content-Type', '')
            content_length = int(self.headers.get('Content-Length', 0))

            # 从查询参数获取元数据
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path + '?' + self.headers.get('X-Query', ''))
            # 实际从path获取
            parsed_path = urlparse(self.path)
            params = parse_qs(parsed_path.query)

            sender = params.get('sender', ['unknown'])[0]
            file_name = params.get('name', ['unknown'])[0]
            file_type = params.get('type', [''])[0]
            silent = params.get('silent', ['true'])[0] == 'true'
            realname = params.get('realname', [sender])[0]

            # 如果是 multipart/form-data，解析表单
            if 'multipart/form-data' in content_type:
                # 解析multipart上传
                import cgi
                fs = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={'REQUEST_METHOD': 'POST',
                             'CONTENT_TYPE': content_type,
                             'CONTENT_LENGTH': content_length}
                )

                sender = fs.getfirst('sender', 'unknown')
                realname = fs.getfirst('realname', sender)
                file_name = fs.getfirst('name', 'unknown')
                file_type = fs.getfirst('type', '')
                silent = fs.getfirst('silent', 'true') == 'true'

                file_item = fs['file'] if 'file' in fs else None
                if not file_item or not file_item.filename:
                    raise ValueError('No file uploaded')

                file_name = file_item.filename or file_name
                file_data = file_item.file.read()
            else:
                # 二进制上传
                file_data = self.rfile.read(content_length)

            # 保存文件
            sender_dir = get_user_receive_dir(sender)
            os.makedirs(sender_dir, exist_ok=True)

            save_path = os.path.join(sender_dir, file_name)
            # 处理文件名冲突：重名文件追加全角序号，如 report（2）.pdf、report（3）.pdf
            if os.path.exists(save_path):
                name, ext = os.path.splitext(file_name)
                counter = 2
                while os.path.exists(save_path):
                    save_path = os.path.join(sender_dir, f"{name}（{counter}）{ext}")
                    counter += 1

            with open(save_path, 'wb') as f:
                f.write(file_data)

            actual_size = os.path.getsize(save_path)
            print(f"[直传] 收到文件: {file_name} ({format_size(actual_size)}) from {sender}")

            # 保存接收记录
            record = {
                'sender': sender,
                'realname': realname,
                'silent': silent,
                'timestamp': datetime.datetime.now().isoformat(),
                'files': [{
                    'name': os.path.basename(save_path),
                    'path': save_path,
                    'size': actual_size,
                    'type': file_type
                }]
            }
            save_received_record(record)

            # 弹窗提示（非静默时）
            if not silent:
                try:
                    show_notification_window(sender, realname or sender, record['files'])
                except:
                    pass

            response = json.dumps({
                'success': True,
                'file_name': os.path.basename(save_path),
                'file_size': actual_size,
                'saved_path': save_path
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        except Exception as e:
            print(f"[直传] 接收失败: {e}")
            traceback.print_exc()
            response = json.dumps({'success': False, 'error': str(e)}, ensure_ascii=False).encode('utf-8')
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

    def on_open_seat(icon, item):
        import webbrowser
        webbrowser.open(f'http://localhost:{PORT}/seat_choose.html')

    def on_exit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem('📂 打开接收文件列表', on_open_files),
        pystray.MenuItem('⏱ 打开计时系统', on_open_timer),
        pystray.MenuItem('🪑 智能选座系统', on_open_seat),
        pystray.MenuItem('❌ 退出系统', on_exit)
    )

    icon = pystray.Icon(APP_NAME, image, f"{APP_NAME} {APP_VERSION}", menu)
    return icon

# ============================================================
# 主函数
# ============================================================
def main():
    silent = is_silent_mode()

    # 静默模式下隐藏控制台窗口（Windows）
    if silent and sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(
                ctypes.windll.kernel32.GetConsoleWindow(), 0  # SW_HIDE
            )
        except:
            pass

    # UAC 提权（如需要）
    if sys.platform == 'win32' and not is_admin():
        if not silent:
            print("[启动] 尝试获取管理员权限...")
        if elevate():
            sys.exit(0)
        if not silent:
            print("[启动] 未获取管理员权限，继续运行")

    # 注册开机自启动
    register_autostart()

    # 查找可用端口
    global PORT
    PORT = find_available_port(PORT)
    os.chdir(DIRECTORY)

    if not silent:
        print("")
        print("  ╔══════════════════════════════════════════╗")
        print("  ║   晚自习系统 - 班级大屏端已启动          ║")
        print(f"  ║   访问地址: http://localhost:{PORT}        ║")
        print(f"  ║   局域网IP: http://{get_lan_ip()}:{PORT}   ║")
        print("  ║   托盘图标已显示，点击操作               ║")
        print("  ╚══════════════════════════════════════════╝")
        print("")

    # ===== 启动自检：验证数据库连通性 =====
    if not silent:
        print("[自检] 正在测试数据库连通性...")
    try:
        test_result = sb_request('GET', '/rest/screen_heartbeat?select=id&limit=1')
        if test_result is not None:
            if not silent:
                print(f"[自检] ✓ 数据库连通正常 (返回 {len(test_result)} 条记录)")
        else:
            if not silent:
                print("[自检] ✗ 数据库查询返回 None！请检查 CB_DB_URL 和 CB_API_KEY")
                print(f"[自检]   CB_DB_URL = {CB_DB_URL}")
                print(f"[自检]   CB_API_KEY 前30字符 = {CB_API_KEY[:30]}...")
    except Exception as e:
        if not silent:
            print(f"[自检] ✗ 数据库连接异常: {e}")

    if not silent:
        print("[自检] 正在测试 pending_files 表查询...")
    try:
        test_pending = get_pending_files()
        if not silent:
            print(f"[自检] ✓ pending_files 查询正常 (待接收: {len(test_pending)} 个)")
            for pf in test_pending[:3]:
                print(f"[自检]   - {pf.get('file_name', '?')} | URL: {pf.get('download_url', '?')[:60]}")
    except Exception as e:
        if not silent:
            print(f"[自检] ✗ pending_files 查询异常: {e}")

    if not silent:
        print("[自检] 正在测试 EasySend 可达性...")
    try:
        test_req = urllib.request.Request('https://easysend.co', headers={'User-Agent': 'Mozilla/5.0'}, method='HEAD')
        with urllib.request.urlopen(test_req, timeout=10) as test_resp:
            if not silent:
                print(f"[自检] ✓ EasySend 可达 (HTTP {test_resp.status})")
    except urllib.error.HTTPError as e:
        if not silent:
            print(f"[自检] ✓ EasySend 可达 (HTTP {e.code}, HEAD 被拒属正常)")
    except Exception as e:
        if not silent:
            print(f"[自检] ✗ EasySend 不可达: {e}")
            print("[自检]   ⚠ 如果大屏无法访问 easysend.co，文件将无法下载！")

    if not silent:
        print("[自检] 自检完成。")
        print("")

    # 启动心跳线程
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()
    if not silent:
        print("[心跳] 心跳上报已启动")

    # 处理离线文件（首次立即检查，之后每5秒实时轮询数据库）
    pending_thread = threading.Thread(target=pending_files_loop, daemon=True)
    pending_thread.start()
    if not silent:
        print("[轮询] 数据库文件轮询已启动（每5秒）")

    # 启动数据库清理线程（每30分钟清理过期数据）
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    if not silent:
        print("[清理] 数据库过期数据清理已启动（每30分钟）")

    # 启动放学自动关机监控线程
    shutdown_thread = threading.Thread(target=school_end_monitor, daemon=True)
    shutdown_thread.start()
    if not silent:
        print(f"[放学] 放学自动关机监控已启动（{SCHOOL_END_HOUR}:{SCHOOL_END_MINUTE:02d} "
              f"后{SHUTDOWN_DELAY_MIN}分钟触发，倒计时{SHUTDOWN_COUNTDOWN}s）")

    # 启动 HTTP 服务器
    httpd = http.server.HTTPServer(('0.0.0.0', PORT), CORSHandler)

    # 在后台线程中启动托盘图标
    tray_icon = create_tray_icon()
    if tray_icon:
        tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
        tray_thread.start()
        if not silent:
            print("[托盘] 系统托盘图标已显示")

    # 主循环
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        if not silent:
            print("\n  服务器已停止。")
        httpd.shutdown()


if __name__ == "__main__":
    main()
