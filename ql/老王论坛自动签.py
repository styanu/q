#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
老王论坛 (laowang3ih2so.com) 自动签到脚本
适配：呆呆面板 / 青龙面板 / 通用 Python 环境

【站点说明】
  Discuz! + k_misign 签到插件，登录和签到各需一次滑块验证码
  脚本自动破解滑块验证码，无需人工干预

【使用方法】
  在面板中添加环境变量：
    LW_USERNAME = 你的用户名
    LW_PASSWORD = 你的密码
  多账号用 | 分隔，例如：
    LW_USERNAME = user1|user2
    LW_PASSWORD = pass1|pass2

【定时建议】每天 00:10 执行一次（Cron: 10 0 * * *）

【依赖】requests, Pillow（面板一般已内置，若无则 pip install requests pillow）

【验证码破解原理】
  滑块验证码图片分三段：上段(干净背景)、中段(拼图块+黑底)、下段(带缺口背景)
  1. 从中段提取拼图块内容(非黑色像素)作为模板
  2. 在下段背景中做掩码模板匹配，找到缺口位置
  3. 生成类人鼠标拖动轨迹(加速-匀速-减速)
  4. 用硬编码密钥做XOR+Base64+FNV-1a签名后提交验证
"""

import os
import re
import sys
import json
import time
import random
import base64
import hashlib
import requests
import numpy as np
from PIL import Image

# ============================================================
# 配置区
# ============================================================
BASE_URL = "https://laowang3ih2so.com"
CAPTCHA_URL = f"{BASE_URL}/captcha/"
LOGIN_URL = f"{BASE_URL}/member.php?mod=logging&action=login"
SIGNIN_PAGE = f"{BASE_URL}/plugin.php?id=k_misign:sign"

# 验证码硬编码密钥（从网站JS中提取）
HMAC_SECRET = "GWDiugh398huiw0ioOYGd0934hew"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MAX_CAPTCHA_RETRIES = 8
MAX_LOGIN_RETRIES = 3
MAX_SIGNIN_RETRIES = 3


# ============================================================
# 工具函数
# ============================================================
def log(msg, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prefix = {
        "INFO": "📢", "SUCCESS": "✅", "ERROR": "❌",
        "WARN": "⚠️ ", "REWARD": "🎁", "LOGIN": "🔐",
        "SIGN": "✍️ ", "CAPTCHA": "🔧",
    }.get(level, "📢")
    print(f"{prefix} [{timestamp}] {msg}")


def new_session():
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# ============================================================
# 滑块验证码破解
# ============================================================
def find_gap_position(img_path):
    """从验证码图片中找到滑块缺口位置（二维模板匹配）"""
    try:
        img = Image.open(img_path).convert("RGB")
        arr = np.array(img).astype(float)

        # 中段(y=150~300)：黑底+拼图块，找拼图块位置
        mid = arr[150:300]
        mid_gray = np.mean(mid, axis=2)
        mask_mid = mid_gray > 30  # 非黑色像素
        rows = np.where(mask_mid.any(axis=1))[0]
        if len(rows) < 10:
            return None

        # 拼图块中心y，提取50x50拼图块
        pyc = int(np.mean(rows))
        py0 = max(0, pyc - 25)
        py1 = min(150, py0 + 50)
        if py1 - py0 < 50:
            py0 = max(0, py1 - 50)

        puzzle = mid[py0:py1, 0:50]
        puzzle_mask = np.mean(puzzle, axis=2) > 30
        if puzzle_mask.sum() < 200:  # 掩码像素太少
            return None

        # 下段(y=300~450)：带缺口背景，做掩码模板匹配
        bottom = arr[300:450]
        best_x, best_y, best_diff = 0, 0, float("inf")
        for y in range(0, 100):
            for x in range(0, 190):
                region = bottom[y:y + 50, x:x + 50]
                if region.shape != puzzle.shape:
                    continue
                diff = np.abs(region[puzzle_mask] - puzzle[puzzle_mask]).sum()
                if diff < best_diff:
                    best_diff, best_x, best_y = diff, x, y

        return best_x
    except Exception as e:
        return None


def generate_track(target_x, duration_ms=700):
    """生成类人鼠标拖动轨迹"""
    points = [{"x": 0.0, "y": 0.0, "t": 0}]
    num = random.randint(20, 30)
    for i in range(1, num):
        p = i / num
        # ease-in-out: 加速-匀速-减速
        if p < 0.4:
            eased = 2.5 * p * p
        elif p < 0.8:
            eased = 0.4 + (p - 0.4) * 0.9
        else:
            t = (p - 0.8) / 0.2
            eased = 0.76 + 0.24 * (1 - (1 - t) ** 3)
        x = target_x * min(eased, 1.0) + random.uniform(-0.8, 0.8)
        y = random.uniform(-1, 1)
        t = int(duration_ms * p + random.uniform(-3, 3))
        points.append({
            "x": round(x, 2), "y": round(y, 2),
            "t": max(t, points[-1]["t"] + random.randint(15, 35))
        })
    points[-1]["x"] = float(target_x)
    points[-1]["t"] = duration_ms
    return points


def compute_track_info(track):
    """计算轨迹特征（与网站JS一致）"""
    if len(track) < 2:
        return {"valid": False}
    total_time = track[-1]["t"]
    total_dist, speeds, directions = 0, [], []
    for i in range(1, len(track)):
        dx = track[i]["x"] - track[i - 1]["x"]
        dy = track[i]["y"] - track[i - 1]["y"]
        dt = track[i]["t"] - track[i - 1]["t"]
        if dt > 0:
            dist = (dx * dx + dy * dy) ** 0.5
            total_dist += dist
            speeds.append(dist / dt)
            directions.append(np.arctan2(dy, dx))
    avg_s = sum(speeds) / len(speeds) if speeds else 0
    var_s = sum((s - avg_s) ** 2 for s in speeds) / len(speeds) if speeds else 0
    dir_changes = sum(
        1 for i in range(1, len(directions))
        if abs(directions[i] - directions[i - 1]) > np.pi / 4
    )
    return {
        "valid": True, "points": len(track), "totalTime": total_time,
        "totalDist": round(total_dist, 2), "avgSpeed": round(avg_s, 4),
        "maxSpeed": round(max(speeds), 4) if speeds else 0,
        "minSpeed": round(min(speeds), 4) if speeds else 0,
        "speedVar": round(var_s, 4), "dirChanges": dir_changes,
        "finalX": track[-1]["x"] - track[0]["x"],
    }


def solve_slider_captcha(session, referer=None):
    """破解滑块验证码，返回验证token，失败返回None"""
    if referer:
        session.headers["Referer"] = referer

    for attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
        try:
            # 下载验证码图片
            img_url = f"{CAPTCHA_URL}tncode.php?t={int(time.time() * 1000)}"
            resp = session.get(img_url, timeout=15)
            img_path = f"/tmp/captcha_{int(time.time()*1000)}_{attempt}.webp"
            with open(img_path, "wb") as f:
                f.write(resp.content)

            # 找缺口位置
            gap_x = find_gap_position(img_path)
            if gap_x is None:
                continue

            # 生成轨迹
            track = generate_track(gap_x)
            track_info = compute_track_info(track)
            track_str = json.dumps(track_info, separators=(",", ":"))

            # XOR加密
            xor_result = "".join(
                chr(ord(track_str[i]) ^ ord(HMAC_SECRET[i % len(HMAC_SECRET)]))
                for i in range(len(track_str))
            )
            encrypted = base64.b64encode(xor_result.encode()).decode()

            # FNV-1a签名
            timestamp = int(time.time() * 1000)
            norm_offset = f"{gap_x:.2f}"
            combined = track_str + str(timestamp) + norm_offset + HMAC_SECRET
            h = 0x811c9dc5
            for c in combined:
                h ^= ord(c)
                h += (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24)
            signature = (h & 0xFFFFFFFF)

            # 提交验证
            post_data = (
                f"tn_r={norm_offset}&track={requests.utils.quote(encrypted)}"
                f"&ts={timestamp}&sign={signature:x}"
            )
            resp = session.post(
                f"{CAPTCHA_URL}check.php",
                data=post_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            result = resp.text.strip()

            if "_ok" in result:
                log(f"验证码第{attempt}次破解成功 (缺口x={gap_x})", "CAPTCHA")
                return result

        except Exception:
            continue

    log(f"验证码破解失败（重试{MAX_CAPTCHA_RETRIES}次）", "ERROR")
    return None


# ============================================================
# 登录函数
# ============================================================
def do_login(session, username, password):
    """Discuz!登录（含滑块验证码）"""
    log(f"正在登录: {username}", "LOGIN")

    try:
        # 获取登录页面
        session.headers["Referer"] = LOGIN_URL
        resp = session.get(LOGIN_URL, timeout=15)
        formhash = re.search(r'name="formhash" value="([^"]+)"', resp.text)
        loginhash = re.search(r'loginhash=([A-Za-z0-9]+)', resp.text)
        if not formhash or not loginhash:
            log("获取登录页面信息失败", "ERROR")
            return False
        formhash = formhash.group(1)
        loginhash = loginhash.group(1)

        # 破解登录验证码
        token = solve_slider_captcha(session, LOGIN_URL)
        if not token:
            return False

        # MD5密码
        password_md5 = hashlib.md5(password.encode()).hexdigest()

        # 提交登录
        login_api = (
            f"{BASE_URL}/member.php?mod=logging&action=login"
            f"&loginsubmit=yes&loginhash={loginhash}&inajax=1"
        )
        login_data = {
            "formhash": formhash,
            "referer": f"{BASE_URL}/./",
            "username": username,
            "password": password_md5,
            "questionid": "0",
            "answer": "",
            "cookietime": "2592000",
            "clicaptcha-submit-info": token,
        }
        resp = session.post(login_api, data=login_data, timeout=20)

        # 检查登录结果
        if session.cookies.get("X9wU_2132_auth") or "欢迎" in resp.text:
            log(f"登录成功: {username}", "SUCCESS")
            return True

        log(f"登录失败: {resp.text[:200]}", "ERROR")
        return False

    except Exception as e:
        log(f"登录异常: {type(e).__name__}: {e}", "ERROR")
        return False


# ============================================================
# 签到函数
# ============================================================
def is_signed_in(session):
    """检查是否已签到"""
    try:
        session.headers["Referer"] = SIGNIN_PAGE
        resp = session.get(SIGNIN_PAGE, timeout=15)
        # 已签到特征：visted类 或 没有签到按钮
        has_sign_btn = bool(re.search(
            r'href="plugin\.php\?id=k_misign:sign&operation=qiandao&formhash=[^"]+"',
            resp.text
        ))
        is_visted = "visted" in resp.text or "visited" in resp.text
        return (not has_sign_btn) or is_visted
    except Exception:
        return False


def do_signin(session):
    """执行签到（含第二次滑块验证码）"""
    try:
        # 获取签到页面
        session.headers["Referer"] = SIGNIN_PAGE
        resp = session.get(SIGNIN_PAGE, timeout=15)

        # 检查是否已签到
        sign_link = re.search(
            r'href="(plugin\.php\?id=k_misign:sign&operation=qiandao&formhash=[^"]+)"',
            resp.text
        )
        if not sign_link:
            log("今日已签到（无签到按钮）", "SUCCESS")
            return True

        sign_url = sign_link.group(1)
        log(f"找到签到链接，开始签到...", "SIGN")

        # 点击签到 → 获取验证页面
        resp = session.get(f"{BASE_URL}/{sign_url}", timeout=15)

        # 提取验证表单action
        form_action = re.search(r'<form[^>]*action="([^"]+)"', resp.text)
        if form_action:
            form_action = form_action.group(1).replace("&amp;", "&")
        else:
            form_action = f"{BASE_URL}/{sign_url}"

        # 破解签到验证码（第二次）
        log("破解签到验证码...", "CAPTCHA")
        token = solve_slider_captcha(session, form_action)
        if not token:
            log("签到验证码破解失败", "ERROR")
            return False

        # 提交签到表单
        session.headers["Referer"] = form_action
        resp = session.post(
            form_action,
            data={"clicaptcha-submit-info": token},
            timeout=20,
        )

        # 验证签到结果
        time.sleep(1)
        if is_signed_in(session):
            log("签到成功！", "SUCCESS")
            return True
        else:
            log(f"签到结果未知，响应: {resp.text[:200]}", "WARN")
            return False

    except Exception as e:
        log(f"签到异常: {type(e).__name__}: {e}", "ERROR")
        return False


# ============================================================
# 单账号处理
# ============================================================
def process_account(username, password, index=1):
    log(f"===== 账号 {index}: {username} =====")
    session = new_session()

    # 登录（带重试）
    login_ok = False
    for attempt in range(1, MAX_LOGIN_RETRIES + 1):
        if do_login(session, username, password):
            login_ok = True
            break
        if attempt < MAX_LOGIN_RETRIES:
            log(f"登录重试 {attempt}/{MAX_LOGIN_RETRIES}...", "WARN")
            time.sleep(3)

    if not login_ok:
        log(f"账号 {username} 登录失败", "ERROR")
        return False

    # 签到（带重试）
    for attempt in range(1, MAX_SIGNIN_RETRIES + 1):
        if do_signin(session):
            return True
        if attempt < MAX_SIGNIN_RETRIES:
            log(f"签到重试 {attempt}/{MAX_SIGNIN_RETRIES}...", "WARN")
            time.sleep(3)

    log(f"账号 {username} 签到失败", "ERROR")
    return False


# ============================================================
# 多账号解析
# ============================================================
def parse_multi(value, sep="|"):
    if not value:
        return []
    items = []
    for line in value.splitlines():
        line = line.strip()
        if line:
            items.extend([x.strip() for x in line.split(sep) if x.strip()])
    if not items and sep in value:
        items = [x.strip() for x in value.split(sep) if x.strip()]
    return items if items else [value.strip()]


# ============================================================
# 主函数
# ============================================================
def main():
    log("老王论坛 (laowang3ih2so.com) 自动签到脚本启动")
    log(f"目标站点: {BASE_URL}")

    env_username = os.environ.get("LW_USERNAME", "") or os.environ.get("lw_username", "")
    env_password = os.environ.get("LW_PASSWORD", "") or os.environ.get("lw_password", "")

    if not env_username or not env_password:
        log("未检测到有效配置！", "ERROR")
        log("请设置环境变量：LW_USERNAME 和 LW_PASSWORD", "INFO")
        sys.exit(1)

    usernames = parse_multi(env_username)
    passwords = parse_multi(env_password)
    while len(passwords) < len(usernames):
        passwords.append(passwords[-1] if passwords else "")

    log(f"共 {len(usernames)} 个账号")

    results = []
    for i, (user, pwd) in enumerate(zip(usernames, passwords), 1):
        ok = process_account(user, pwd, i)
        results.append(ok)
        if i < len(usernames):
            time.sleep(5)

    total = len(results)
    success = sum(1 for r in results if r)
    log("===== 签到完成 =====")
    log(f"成功: {success}/{total}")

    if success == total:
        log("全部账号签到成功！", "SUCCESS")
        sys.exit(0)
    elif success == 0:
        log("全部账号签到失败，请检查账号密码", "ERROR")
        sys.exit(1)
    else:
        log("部分账号签到失败，请检查日志", "WARN")
        sys.exit(0)


if __name__ == "__main__":
    main()
