#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动部署脚本：Gitee + Netlify + Cloudflare + CloudBase + GitHub
用法：python deploy.py [all|study|mobile|gitee|netlify|cloudflare|cloudbase|github|seat|domain]
"""
import sys
import os
import json
import base64
import urllib.request
import urllib.error
import zipfile
import io
import shutil
import subprocess
import datetime
import time

# ============ 配置 ============
GITEE_TOKEN = "09d0e5f638b93a80b52b2db517b8e57d"
GITEE_OWNER = "starbusks"
GITEE_REPO = "study_timer"

NETLIFY_TOKEN = "nfp_vwyzzWoDBLcHfDVJFWhaM2ToZD9mtmUC7d6d"
NETLIFY_SITE_TCH = "23277232-1e17-49da-bd52-f6f957a13655"  # wh12z213tch
NETLIFY_SITE_STU = "edef9fc1-8dbc-4b2c-95f1-a37c8b109871"  # wh12z213stu
NETLIFY_SITE_MOB = "309f189b-28d7-44bf-bd51-5b5080786d27"  # wh12z213mob

# Cloudflare Pages 配置
CF_API_TOKEN = "cfut_kJemvOSv6oCN4KJ75Y8W9H1wfdFI6yr3jyuyhOld80fe8fb2"
CF_PROJECT_MOB = "wh12z213mob"
CF_PROJECT_STU = "wh12z213stu"
CF_PROJECT_TCH = "wh12z213tch"

# GitHub 配置
GITHUB_TOKEN = "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"
GITHUB_OWNER = "caojingyang"
GITHUB_REPO_MOB = "study-timer-mob"   # 移动端
GITHUB_REPO_STU = "study-timer-stu"   # 学生端/系统端

# CloudBase 配置（腾讯云开发）
CB_ENV_ID = "wh12z213-d4gi5jt764f91a558"
CB_API_KEY = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjNmYjk2NWJkLWU5OTQtNDc5YS04MjEwLWIzNTY0ZTM1ODY3MyJ9.eyJhdWQiOiJ3aDEyejIxMy1kNGdpNWp0NzY0ZjkxYTU1OCIsImV4cCI6MjUzNDAyMzAwNzk5LCJpYXQiOjE3ODY3ODU0NTcsImF0X2hhc2giOiJBcmpXelNNT1JFQ3ZtT01aT1lPbHBBIiwicHJvamVjdF9pZCI6IndoMTJ6MjEzLWQ0Z2k1anQ3NjRmOTFhNTU4IiwibWV0YSI6eyJwbGF0Zm9ybSI6IkFwaUtleSJ9LCJyb2xlIjoic2VydmljZV9yb2xlIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiYXBpa2V5IiwicHJvdmlkZXJzIjpbImFwaWtleSJdfSwiYWRtaW5pc3RyYXRvcl9pZCI6IjIwODg1NTMxNzA1NzY4NjczMjgiLCJ1c2VyX3R5cGUiOiIiLCJjbGllbnRfdHlwZSI6ImNsaWVudF9zZXJ2ZXIiLCJpc19zeXN0ZW1fYWRtaW4iOnRydWV9.T8YR_AZQ3lPLyDfp_tCJ0baefybTYO9Q-LtFbdCsE9bjjYvJoONyIiVk5pWGcWriaAJoQxhxn68gFwO9lsQF5U4pI_2sbkmBBXIzAbkZy1cW5ABDhREAbBYR21LrPFd5nkms0hjH5TwRR7ll8i6L1fXKoZZosGIQBPECtr96A800dXishQ7NZqx8Afcy1mRm_x1Bt8ChTVoqCOZzK8cOcTHQ3BFYs8t2FXHM-tbO0MsegilFxbJ87OxzIfsn70Whv72YormFiyQXCDL1ZrcNvMFR1ORih123nrQlhUsAXfrtQC643lbFWCk4VzEYDsp2VkYhOr13Sm-L-4faYYrGvA"
# 自定义域名（已备案后启用，替换默认 tcloudbaseapp.com 域名）
CB_CUSTOM_DOMAIN = "wh12z213.online"  # 备案完成后将作为主域名使用
# 默认域名（备案前使用，有访问频率限制）
CB_DEFAULT_URL = f"https://{CB_ENV_ID}-1457662848.tcloudbaseapp.com"
# 最终使用的域名（优先使用自定义域名，未配置时回退到默认域名）
CB_BASE_URL = f"https://{CB_CUSTOM_DOMAIN}" if CB_CUSTOM_DOMAIN else CB_DEFAULT_URL

WORKSPACE = "/workspace"

# ============ Gitee 上传 ============
def upload_to_gitee(filepath, message="更新文件"):
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}/contents/{filename}?access_token={GITEE_TOKEN}&ref=master"

    sha = None
    try:
        req_get = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req_get, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list) and len(data) > 0:
                sha = data[0].get("sha")
            elif isinstance(data, dict):
                sha = data.get("sha")
            elif isinstance(data, list) and len(data) == 0:
                print(f"[Gitee] GET 返回空列表，文件可能不存在: {filename}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[Gitee] 获取文件信息失败: {e.code}")
        else:
            print(f"[Gitee] 文件不存在（404），将创建新文件: {filename}")

    payload = {"content": content, "message": message, "branch": "master"}
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if "content" in result:
                print(f"[Gitee] ✅ {filename} 上传成功")
                return True
            else:
                print(f"[Gitee] ❌ {filename} 上传失败: {result}")
                return False
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:300]
        # 如果 sha 缺失，说明文件已存在但 GET 未返回 sha，尝试二次获取
        if "sha is missing" in error_body or "sha is empty" in error_body:
            print(f"[Gitee] 文件已存在但 sha 未获取，重试中...")
            try:
                retry_url = f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}/contents/{filename}?access_token={GITEE_TOKEN}&ref=master"
                req_retry = urllib.request.Request(retry_url, method="GET")
                with urllib.request.urlopen(req_retry, timeout=15) as resp2:
                    data2 = json.loads(resp2.read().decode())
                    if isinstance(data2, dict):
                        sha = data2.get("sha")
                    elif isinstance(data2, list) and len(data2) > 0:
                        sha = data2[0].get("sha")
            except Exception:
                pass
            if sha:
                payload["sha"] = sha
                data = json.dumps(payload).encode("utf-8")
                req2 = urllib.request.Request(url, data=data, method="PUT")
                req2.add_header("Content-Type", "application/json")
                try:
                    with urllib.request.urlopen(req2, timeout=30) as resp3:
                        result = json.loads(resp3.read().decode())
                        if "content" in result:
                            print(f"[Gitee] ✅ {filename} 上传成功（重试）")
                            return True
                        else:
                            print(f"[Gitee] ❌ {filename} 重试上传失败: {result}")
                            return False
                except urllib.error.HTTPError as e2:
                    print(f"[Gitee] ❌ 重试 HTTP {e2.code}: {e2.read().decode()[:200]}")
                    return False
            else:
                print(f"[Gitee] ❌ {filename} 无法获取 sha: {error_body[:150]}")
                return False
        print(f"[Gitee] ❌ HTTP {e.code}: {error_body[:200]}")
        return False

# ============ GitHub 上传 ============
def upload_to_github(repo, filepath, target_path="index.html", message=None):
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{repo}/contents/{target_path}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "deploy-script"
    }

    sha = None
    try:
        req_get = urllib.request.Request(url, method="GET", headers=headers)
        with urllib.request.urlopen(req_get, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[GitHub] 获取文件信息失败: {e.code}")

    if message is None:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"自动部署: {filename} {now}"

    payload = {"message": message, "content": content, "branch": "main"}
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if "content" in result:
                print(f"[GitHub] ✅ {repo}/{target_path} 上传成功")
                return True
            else:
                print(f"[GitHub] ❌ {repo}/{target_path} 上传失败: {result}")
                return False
    except urllib.error.HTTPError as e:
        print(f"[GitHub] ❌ HTTP {e.code}: {e.read().decode()[:200]}")
        return False

# ============ GitHub 快速推送（按文件名自动映射仓库） ============
GITHUB_FILE_MAP = {
    "study_timer.html": (GITHUB_REPO_STU, "study_timer.html"),
    "mobile.html":      (GITHUB_REPO_MOB, "index.html"),
    "history.html":     (GITHUB_REPO_MOB, "history.html"),
    "seat.html":         (GITHUB_REPO_MOB, "seat.html"),
    "seat_online.html":  (GITHUB_REPO_MOB, "seat_online.html"),
    "ui.html":           (GITHUB_REPO_MOB, "ui.html"),
    "remote.html":       (GITHUB_REPO_MOB, "remote.html"),
    "build.bat":         (GITHUB_REPO_STU, "build.bat"),
    "deploy.py":         (GITHUB_REPO_STU, "deploy.py"),
    "update.py":        (GITHUB_REPO_STU, "update.py"),
}

def push_file_to_github(filename, message=None):
    """按文件名自动映射到 GitHub 仓库并推送"""
    if filename not in GITHUB_FILE_MAP:
        print(f"[GitHub] ❌ 未知文件: {filename}")
        print(f"  支持的文件: {', '.join(GITHUB_FILE_MAP.keys())}")
        return False
    repo, target_path = GITHUB_FILE_MAP[filename]
    filepath = os.path.join(WORKSPACE, filename)
    if not os.path.exists(filepath):
        print(f"[GitHub] ❌ 文件不存在: {filepath}")
        return False
    upload_to_github(repo, filepath, target_path=target_path, message=message)

# ============ Supabase 代理函数代码 ============
def read_function_code():
    """读取 Netlify Function 代理脚本内容"""
    func_path = os.path.join(WORKSPACE, "netlify", "functions", "supabase-proxy.js")
    with open(func_path, "r", encoding="utf-8") as f:
        return f.read()

# ============ Netlify 上传 ============
def upload_to_netlify(site_id, filepath, message="更新", extra_files=None):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(filepath, "index.html")
        # 同步额外文件（如 history.html）
        if extra_files:
            for f in extra_files:
                src = os.path.join(WORKSPACE, f)
                if os.path.exists(src):
                    zf.write(src, f)
        headers_content = "/*.html\n  Content-Type: text/html; charset=UTF-8\n  Cache-Control: public, max-age=0, must-revalidate\n"
        zf.writestr("_headers", headers_content)
        # Netlify 重定向规则：/admin 路径返回 index.html（支持后台管理访问）
        redirects_content = "/admin  /index.html  200\n/admin/*  /index.html  200\n"
        zf.writestr("_redirects", redirects_content)
        # Netlify Function：Supabase 反向代理（解决国内访问 Supabase 慢的问题）
        # 每个 ZIP 中都包含独立的 function 文件
        func_dir = "netlify/functions/"
        zf.writestr(func_dir + "supabase-proxy.js", read_function_code())
    zip_data = zip_buffer.getvalue()

    url = f"https://api.netlify.com/api/v1/sites/{site_id}"
    req = urllib.request.Request(url, data=zip_data, method="PUT")
    req.add_header("Authorization", f"Bearer {NETLIFY_TOKEN}")
    req.add_header("Content-Type", "application/zip")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            if "id" in result:
                print(f"[Netlify] ✅ 部署成功")
                return True
            else:
                print(f"[Netlify] ❌ 部署失败: {result}")
                return False
    except urllib.error.HTTPError as e:
        print(f"[Netlify] ❌ HTTP {e.code}: {e.read().decode()[:200]}")
        return False

# ============ 生成 online 文件 ============
def generate_study_timer_online():
    src = os.path.join(WORKSPACE, "study_timer.html")
    dst = os.path.join(WORKSPACE, "study_timer_online.html")
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("background.png", "https://s41.ax1x.com/2026/07/06/pmBBBa6.jpg")
    content = content.replace("icon.jpg", "https://s41.ax1x.com/2026/07/01/pmdtqLF.png")
    # 将本地 CSS 引用替换为 CDN 地址
    content = content.replace(
        'href="tailwind.min.css?v=2"',
        'href="https://cdn.jsdelivr.net/gh/caojingyang/study-timer-stu@main/tailwind.min.css?v=2"'
    )
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[生成] ✅ study_timer_online.html 已更新")
    return dst

def generate_mobile_online():
    src = os.path.join(WORKSPACE, "mobile.html")
    dst = os.path.join(WORKSPACE, "mobile_online.html")
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("icon.jpg", "https://s41.ax1x.com/2026/07/01/pmdtqLF.png")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[生成] ✅ mobile_online.html 已更新")
    return dst

def generate_teacher_online():
    src = os.path.join(WORKSPACE, "teacher_tools.html")
    dst = os.path.join(WORKSPACE, "teacher_tools_online.html")
    with open(src, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace("icon.jpg", "https://s41.ax1x.com/2026/07/01/pmdtqLF.png")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[生成] ✅ teacher_tools_online.html 已更新")
    return dst

# ============ Cloudflare Pages 部署 ============
def sync_to_cloudflare_pages(src_html, cf_dir, extra_files=None):
    """将 HTML 文件及依赖同步到 Cloudflare Pages 部署目录"""
    shutil.copy2(src_html, os.path.join(cf_dir, "index.html"))
    # 同步本地依赖文件（tailwind.min.css, font-awesome.min.css, fonts/）
    for dep in ["tailwind.min.css", "font-awesome.min.css"]:
        src = os.path.join(WORKSPACE, dep)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(cf_dir, dep))
    fonts_src = os.path.join(WORKSPACE, "fonts")
    fonts_dst = os.path.join(cf_dir, "fonts")
    if os.path.exists(fonts_src):
        if os.path.exists(fonts_dst):
            shutil.rmtree(fonts_dst)
        shutil.copytree(fonts_src, fonts_dst)
    # 同步本地图片
    for img in ["icon.jpg", "background.png", "icon.ico", "timer.mp3"]:
        src = os.path.join(WORKSPACE, img)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(cf_dir, img))
    # 同步额外文件（如 history.html）
    if extra_files:
        for f in extra_files:
            src = os.path.join(WORKSPACE, f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(cf_dir, f))
    print(f"[Cloudflare] ✅ 已同步到 {cf_dir}")

def _find_npx_cmd(cmd_name):
    """在 nvm 路径中查找命令，回退到 npx"""
    candidates = [
        f"/root/.nvm/versions/node/v22.16.0/bin/{cmd_name}",
        os.path.expanduser(f"~/.nvm/versions/node/v22.16.0/bin/{cmd_name}"),
        f"/usr/local/bin/{cmd_name}",
        f"/usr/bin/{cmd_name}",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    try:
        result = subprocess.run(["which", cmd_name], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return f"npx {cmd_name}"

def deploy_to_cloudflare(project_name, cf_dir):
    """使用 Wrangler CLI 部署到 Cloudflare Pages"""
    env = os.environ.copy()
    env["CLOUDFLARE_API_TOKEN"] = CF_API_TOKEN
    # 确保 nvm 路径在 PATH 中
    nvm_bin = "/root/.nvm/versions/node/v22.16.0/bin"
    if os.path.isdir(nvm_bin) and nvm_bin not in env.get("PATH", ""):
        env["PATH"] = nvm_bin + ":" + env.get("PATH", "")
    wrangler = _find_npx_cmd("wrangler")
    cmd = wrangler.split() + [
        "pages", "deploy", cf_dir,
        "--project-name", project_name,
        "--branch", "main",
    ]
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"[Cloudflare] ✅ {project_name} 部署成功")
            return True
        else:
            print(f"[Cloudflare] ❌ {project_name} 部署失败:")
            print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
            return False
    except Exception as e:
        print(f"[Cloudflare] ❌ {project_name} 部署异常: {e}")
        return False

# ============ CloudBase 部署 ============
def _find_tcb():
    """查找 tcb CLI 可执行文件路径"""
    # 尝试常见路径
    candidates = [
        os.path.expanduser("~/.nvm/versions/node/v22.16.0/bin/tcb"),
        "/root/.nvm/versions/node/v22.16.0/bin/tcb",
        "/usr/local/bin/tcb",
        "/usr/bin/tcb",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    # 尝试 which
    try:
        result = subprocess.run(["which", "tcb"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # 尝试 npx
    return "npx tcb"

def _cloudbase_login():
    """使用 API Key 登录 CloudBase（非交互式）"""
    tcb = _find_tcb()
    env = os.environ.copy()
    # 确保 nvm 路径在 PATH 中
    nvm_bin = os.path.dirname(tcb) if tcb != "npx tcb" else ""
    if nvm_bin and nvm_bin not in env.get("PATH", ""):
        env["PATH"] = nvm_bin + ":" + env.get("PATH", "")

    login_cmd = [tcb, "login", "--cloudbase-api-key", CB_API_KEY, "-e", CB_ENV_ID, "--json"]
    try:
        result = subprocess.run(login_cmd, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print("[CloudBase] ✅ API Key 登录成功")
            return True, env
        else:
            # 可能已登录，检查错误是否为 "already logged in"
            combined = result.stdout + result.stderr
            if "already" in combined.lower() or "已登录" in combined:
                print("[CloudBase] ✅ 已登录（复用现有凭据）")
                return True, env
            print(f"[CloudBase] ⚠️ 登录失败: {combined[-200:]}")
            return False, env
    except Exception as e:
        print(f"[CloudBase] ⚠️ 登录异常: {e}")
        return False, env

def deploy_to_cloudbase(src_html, cloud_path, extra_files=None):
    """部署到 CloudBase 静态托管（腾讯云开发）
    src_html: 本地 HTML 文件路径（会重命名为 index.html 上传）
    cloud_path: 云端路径（如 mob）
    extra_files: 额外文件列表（如 history.html）
    """
    import tempfile
    tcb = _find_tcb()

    # 准备临时目录
    tmp_dir = os.path.join(tempfile.gettempdir(), f"cloudbase_{cloud_path}")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)

    # 复制主文件为 index.html
    shutil.copy2(src_html, os.path.join(tmp_dir, "index.html"))
    # 复制额外文件
    if extra_files:
        for f in extra_files:
            src = os.path.join(WORKSPACE, f)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(tmp_dir, f))

    env = os.environ.copy()
    # 确保 nvm 路径在 PATH 中
    nvm_bin = os.path.dirname(tcb) if tcb != "npx tcb" else ""
    if nvm_bin and nvm_bin not in env.get("PATH", ""):
        env["PATH"] = nvm_bin + ":" + env.get("PATH", "")

    # 第一步：使用 API Key 登录（非交互式）
    logged_in, env = _cloudbase_login()
    if not logged_in:
        print(f"[CloudBase] ❌ {cloud_path} 部署失败：无法登录")
        return False

    # 第二步：部署文件
    cmd = [tcb, "hosting", "deploy", tmp_dir, cloud_path, "-e", CB_ENV_ID, "--json"]
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            url = f"{CB_BASE_URL}/{cloud_path}/"
            # 尝试从 JSON 输出中提取文件数
            try:
                data = json.loads(result.stdout)
                total = data.get("data", {}).get("totalFiles", "?")
                success = data.get("data", {}).get("successCount", "?")
                print(f"[CloudBase] ✅ {cloud_path} 部署成功 — {url}（{success}/{total} 文件）")
            except (json.JSONDecodeError, ValueError):
                print(f"[CloudBase] ✅ {cloud_path} 部署成功 — {url}")
            return True
        else:
            print(f"[CloudBase] ❌ {cloud_path} 部署失败:")
            print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
            print(result.stderr[-300:] if len(result.stderr) > 300 else result.stderr)
            return False
    except Exception as e:
        print(f"[CloudBase] ❌ {cloud_path} 部署异常: {e}")
        return False
    finally:
        # 清理临时目录
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)

# ============ 主流程 ============
def deploy_study():
    print("\n========== 部署 study_timer ==========")
    generate_study_timer_online()
    upload_to_gitee(os.path.join(WORKSPACE, "study_timer.html"), "更新晚自习系统")
    upload_to_gitee(os.path.join(WORKSPACE, "start_server.py"), "更新大屏服务端")
    upload_to_gitee(os.path.join(WORKSPACE, "deploy.py"), "更新部署脚本")
    upload_to_netlify(NETLIFY_SITE_STU, os.path.join(WORKSPACE, "study_timer_online.html"), "更新 study_timer_online")
    sync_to_cloudflare_pages(os.path.join(WORKSPACE, "study_timer.html"), os.path.join(WORKSPACE, "cloudflare-pages", "stu"), extra_files=["update.html", "update.py", "start_server.py", "build.bat", "deploy.py"])
    deploy_to_cloudflare(CF_PROJECT_STU, os.path.join(WORKSPACE, "cloudflare-pages", "stu"))
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "study_timer.html"), target_path="study_timer.html")
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "tailwind.min.css"), target_path="tailwind.min.css")
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "update.py"), target_path="update.py")
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "start_server.py"), target_path="start_server.py")
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "update.html"), target_path="update.html")
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "build.bat"), target_path="build.bat")
    upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "deploy.py"), target_path="deploy.py")

def deploy_mobile():
    print("\n========== 部署 mobile ==========")
    generate_mobile_online()
    upload_to_gitee(os.path.join(WORKSPACE, "mobile.html"), "更新移动端")
    upload_to_gitee(os.path.join(WORKSPACE, "remote.html"), "更新远程管理页面")
    upload_to_netlify(NETLIFY_SITE_MOB, os.path.join(WORKSPACE, "mobile_online.html"), "更新 mobile_online", extra_files=["history.html", "seat.html", "seat_online.html", "seat_choose.html", "ui.html", "remote.html"])
    sync_to_cloudflare_pages(os.path.join(WORKSPACE, "mobile.html"), os.path.join(WORKSPACE, "cloudflare-pages", "mob"), extra_files=["history.html", "seat.html", "seat_online.html", "seat_choose.html", "ui.html", "remote.html"])
    deploy_to_cloudflare(CF_PROJECT_MOB, os.path.join(WORKSPACE, "cloudflare-pages", "mob"))
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "seat_online.html"), target_path="seat_online.html")
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "seat_choose.html"), target_path="seat_choose.html")
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "ui.html"), target_path="ui.html")
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "remote.html"), target_path="remote.html")
    # CloudBase
    deploy_to_cloudbase(os.path.join(WORKSPACE, "mobile.html"), "mob", extra_files=["history.html", "seat.html", "seat_online.html", "seat_choose.html", "ui.html", "remote.html"])

def deploy_teacher():
    print("\n========== 部署 teacher ==========")
    generate_teacher_online()
    upload_to_netlify(NETLIFY_SITE_TCH, os.path.join(WORKSPACE, "teacher_tools_online.html"), "更新 teacher_tools_online")
    sync_to_cloudflare_pages(os.path.join(WORKSPACE, "teacher_tools.html"), os.path.join(WORKSPACE, "cloudflare-pages", "tch"))
    deploy_to_cloudflare(CF_PROJECT_TCH, os.path.join(WORKSPACE, "cloudflare-pages", "tch"))

def deploy_all():
    deploy_study()
    deploy_mobile()
    deploy_teacher()

def deploy_seat():
    """部署座位系统文件（seat.html, seat_online.html, seat_choose.html, ui.html）"""
    print("\n========== 部署座位系统 ==========")
    # GitHub
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "seat_online.html"), target_path="seat_online.html")
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "seat_choose.html"), target_path="seat_choose.html")
    upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "ui.html"), target_path="ui.html")
    # Cloudflare Pages
    for f in ["seat.html", "seat_online.html", "seat_choose.html", "ui.html"]:
        src = os.path.join(WORKSPACE, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(WORKSPACE, "cloudflare-pages", "mob", f))
    deploy_to_cloudflare(CF_PROJECT_MOB, os.path.join(WORKSPACE, "cloudflare-pages", "mob"))
    # CloudBase
    deploy_to_cloudbase(os.path.join(WORKSPACE, "mobile.html"), "mob", extra_files=["history.html", "seat.html", "seat_online.html", "seat_choose.html", "ui.html", "remote.html"])

# ============ 自定义域名绑定 ============
def setup_custom_domain(cert_id=None):
    """绑定自定义域名到 CloudBase HTTP 网关"""
    tcb = _find_tcb()

    # 登录
    logged_in, env = _cloudbase_login()
    if not logged_in:
        print(f"[CloudBase] 无法登录，域名绑定失败")
        return False

    # 检查域名是否已绑定
    print(f"[CloudBase] 检查域名 {CB_CUSTOM_DOMAIN} 绑定状态...")
    check_cmd = [tcb, "api", "tcb", "DescribeHTTPServiceRoute",
                 "--api-version", "2018-06-08", "--json",
                 "--body", json.dumps({
                     "EnvId": CB_ENV_ID,
                     "Filters": [{"Name": "Domain", "Values": [CB_CUSTOM_DOMAIN]}],
                     "Offset": 0,
                     "Limit": 10
                 })]
    try:
        result = subprocess.run(check_cmd, env=env, capture_output=True, text=True, timeout=30)
        raw = result.stdout.strip()
        # tcb api 输出可能包含前缀行，提取 JSON
        json_start = raw.find('{')
        if json_start >= 0:
            raw = raw[json_start:]
        data = json.loads(raw) if raw else {}
        existing = data.get("Response", data).get("Domains", [])
        if existing:
            print(f"[CloudBase] 域名 {CB_CUSTOM_DOMAIN} 已绑定")
            domain = existing[0]
            print(f"  状态: {domain.get('Status')}")
            print(f"  DNS状态: {domain.get('DNSStatus')}")
            cname = domain.get("Cname", "")
            if cname:
                print(f"  CNAME 目标: {cname}")
                print(f"  请在 DNS 解析中添加 CNAME 记录指向: {cname}")
            return True
    except Exception as e:
        print(f"[CloudBase] 查询域名状态失败: {e}")

    # 绑定域名
    print(f"[CloudBase] 正在绑定域名 {CB_CUSTOM_DOMAIN}...")
    domain_config = {
        "Domain": CB_CUSTOM_DOMAIN,
        "AccessType": "DIRECT",
        "Protocol": "HTTP_AND_HTTPS",
        "Enable": True
    }
    if cert_id:
        domain_config["CertId"] = cert_id

    bind_cmd = [tcb, "api", "tcb", "CreateHTTPServiceRoute",
                "--api-version", "2018-06-08", "--json",
                "--body", json.dumps({
                    "EnvId": CB_ENV_ID,
                    "Domain": domain_config
                })]
    try:
        result = subprocess.run(bind_cmd, env=env, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        # tcb api 输出可能包含 "ℹ → TCB.xxx" 前缀行，提取 JSON 部分
        json_start = output.find('{')
        if json_start > 0:
            output = output[json_start:]
        elif json_start < 0:
            output = ''
        try:
            data = json.loads(output) if output else {}
            if "error" in data:
                error_msg = data["error"].get("message", str(data["error"]))
                if "NotICP" in str(data["error"].get("code", "")) or "未备案" in error_msg:
                    print(f"[CloudBase] ❌ 域名 {CB_CUSTOM_DOMAIN} 尚未完成 ICP 备案！")
                    print(f"  请前往腾讯云备案控制台完成备案: https://console.cloud.tencent.com/beian")
                    print(f"  备案审核通常需要 1-20 个工作日")
                elif "AlreadyExist" in str(data["error"].get("code", "")):
                    print(f"[CloudBase] 域名已存在，跳过")
                else:
                    print(f"[CloudBase] ❌ 绑定失败: {error_msg}")
                return False
            else:
                print(f"[CloudBase] ✅ 域名 {CB_CUSTOM_DOMAIN} 绑定成功！")
                # 查询 CNAME 信息
                time.sleep(2)
                try:
                    result2 = subprocess.run(check_cmd, env=env, capture_output=True, text=True, timeout=30)
                    data2 = json.loads(result2.stdout)
                    domains = data2.get("Response", data2).get("Domains", [])
                    if domains:
                        cname = domains[0].get("Cname", "")
                        status = domains[0].get("Status", "")
                        if cname:
                            print(f"[CloudBase] 请在 DNS 解析中添加 CNAME 记录:")
                            print(f"  记录类型: CNAME")
                            print(f"  主机记录: @")
                            print(f"  记录值: {cname}")
                        print(f"  域名状态: {status}")
                except Exception:
                    pass
                return True
        except json.JSONDecodeError:
            print(f"[CloudBase] 绑定结果: {output}")
            return result.returncode == 0
    except Exception as e:
        print(f"[CloudBase] ❌ 绑定异常: {e}")
        return False

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "study":
        deploy_study()
    elif cmd == "mobile":
        deploy_mobile()
    elif cmd == "teacher":
        deploy_teacher()
    elif cmd == "gitee":
        upload_to_gitee(os.path.join(WORKSPACE, "study_timer.html"), "更新晚自习系统")
    elif cmd == "netlify":
        deploy_study()
        deploy_mobile()
        deploy_teacher()
    elif cmd == "cloudflare":
        deploy_study()
        deploy_mobile()
        deploy_teacher()
    elif cmd == "cloudbase":
        deploy_to_cloudbase(os.path.join(WORKSPACE, "mobile.html"), "mob", extra_files=["history.html", "seat.html", "seat_online.html", "seat_choose.html", "ui.html", "remote.html"])
    elif cmd == "domain":
        # 绑定自定义域名
        # 用法: python deploy.py domain [cert_id]
        cert_id = sys.argv[2] if len(sys.argv) > 2 else None
        print(f"\n========== 绑定自定义域名 {CB_CUSTOM_DOMAIN} ==========")
        setup_custom_domain(cert_id)
    elif cmd == "seat":
        deploy_seat()
    elif cmd == "github":
        upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "study_timer.html"))
        upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "update.py"), target_path="update.py")
        upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "start_server.py"), target_path="start_server.py")
        upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "update.html"), target_path="update.html")
        upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "build.bat"), target_path="build.bat")
        upload_to_github(GITHUB_REPO_STU, os.path.join(WORKSPACE, "deploy.py"), target_path="deploy.py")
        upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "seat_online.html"), target_path="seat_online.html")
        upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "seat_choose.html"), target_path="seat_choose.html")
        upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "ui.html"), target_path="ui.html")
        upload_to_github(GITHUB_REPO_MOB, os.path.join(WORKSPACE, "remote.html"), target_path="remote.html")
    elif cmd == "push":
        # 快速推送单个文件到 GitHub
        # 用法: python deploy.py push <文件名> [commit消息]
        if len(sys.argv) < 3:
            print("用法: python deploy.py push <文件名> [commit消息]")
            print("支持的文件: study_timer.html, mobile.html, history.html, seat.html, seat_online.html, ui.html, remote.html, update.py")
            sys.exit(1)
        push_file_to_github(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        deploy_all()
