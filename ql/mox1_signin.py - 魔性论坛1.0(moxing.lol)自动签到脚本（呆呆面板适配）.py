#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
魔性论坛 1.0 (moxing.lol) 自动签到脚本
适配：呆呆面板 / 青龙面板 / 通用 Python 环境

【站点说明】
  本脚本针对魔性论坛 1.0 版本（Discuz! 架构，域名 moxing.lol）
  如需 2.0 版本（mox.moxing.lol，Laravel 架构），请使用对应脚本。

【使用方法】
  在面板中添加环境变量：
    MOX1_USERNAME = 你的用户名
    MOX1_PASSWORD = 你的密码
  多账号用 | 分隔，例如：
    MOX1_USERNAME = user1|user2
    MOX1_PASSWORD = pass1|pass2

【定时建议】每天 00:05 执行一次（Cron: 5 0 * * *）

【依赖】requests（面板一般已内置，若无则 pip install requests）

【签到心情 select 可选值】
  kx=开心, ng=难过, ym=郁闷, yl=努力, cm=沉默,
  shuijiao=睡觉, han=汗, qiao=俏, zheng=正, bie=憋
  默认: kx（开心）
"""

import os
import re
import sys
import time
import hashlib
import requests

# ============================================================
# 配置区
# ============================================================
BASE_URL = "https://moxing.lol"
LOGIN_URL = f"{BASE_URL}/member.php?mod=logging&action=login"
SIGNIN_PAGE = f"{BASE_URL}/plugin.php?id=k_misign:sign"
SIGNIN_API = f"{BASE_URL}/plugin.php?id=k_misign:sign&operation=qiandao&inajax=1"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MAX_RETRIES = 3
RETRY_DELAY = 5
DEFAULT_MOOD = "kx"  # 默认签到心情：开心


# ============================================================
# 工具函数
# ============================================================
def log(msg, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prefix = {
        "INFO": "📢",
        "SUCCESS": "✅",
        "ERROR": "❌",
        "WARN": "⚠️ ",
        "REWARD": "🎁",
        "LOGIN": "🔐",
        "SIGN": "✍️ ",
    }.get(level, "📢")
    print(f"{prefix} [{timestamp}] {msg}")


def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{BASE_URL}/",
    })
    s.cookies.set("is_agree", "1", domain=".moxing.lol", path="/")
    return s


def extract_formhash(html):
    """从 HTML 中提取 formhash"""
    m = re.search(r'name="formhash"\s+value="([^"]+)"', html)
    return m.group(1) if m else None


def extract_loginhash(html):
    """从 HTML 中提取 loginhash"""
    m = re.search(r'loginhash=([A-Za-z0-9]+)', html)
    return m.group(1) if m else None


def parse_xml_response(text):
    """解析 Discuz! AJAX XML 响应，提取 CDATA 内容"""
    m = re.search(r'<!\[CDATA\[(.*?)\]\]>', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 备选：去掉 XML 标签
    clean = re.sub(r'<[^>]+>', '', text).strip()
    return clean


def md5_password(password):
    """Discuz! 密码加密：直接 MD5"""
    return hashlib.md5(password.encode()).hexdigest()


# ============================================================
# 登录函数
# ============================================================
def do_login(session, username, password):
    """Discuz! 登录，返回 True/False"""
    log(f"正在登录账号: {username}", "LOGIN")

    try:
        # 1. 获取登录页面
        resp = session.get(LOGIN_URL, timeout=15)
        formhash = extract_formhash(resp.text)
        loginhash = extract_loginhash(resp.text)

        if not formhash or not loginhash:
            log("获取登录页面信息失败", "ERROR")
            return False

        # 2. MD5 加密密码
        password_hash = md5_password(password)

        # 3. 发起登录
        login_url = (
            f"{BASE_URL}/member.php?mod=logging&action=login"
            f"&loginsubmit=yes&loginhash={loginhash}&inajax=1"
        )
        data = {
            "formhash": formhash,
            "referer": f"{BASE_URL}/./",
            "username": username,
            "password": password_hash,
            "questionid": "0",
            "answer": "",
            "cookietime": "2592000",
        }
        resp = session.post(login_url, data=data, timeout=20)
        result = parse_xml_response(resp.text)

        # 判断登录结果
        if "欢迎您回来" in result or "succeed" in result or "登录成功" in result:
            log(f"登录成功: {username}", "SUCCESS")
            return True
        if "失败" in result or "错误" in result or "密码" in result or "用户名" in result:
            log(f"登录失败: {result[:200]}", "ERROR")
            return False

        # 检查 cookie 是否有 auth（登录成功标志）
        if session.cookies.get("dyHK_bbb3_auth"):
            log(f"登录成功（通过 cookie 判断）: {username}", "SUCCESS")
            return True

        log(f"登录响应: {result[:200]}", "WARN")
        return False

    except Exception as e:
        log(f"登录异常: {type(e).__name__}: {e}", "ERROR")
        return False


# ============================================================
# 签到函数
# ============================================================
def do_signin(session, mood=DEFAULT_MOOD, message=""):
    """执行签到，返回 (success, message)"""
    try:
        # 1. 获取签到页面的 formhash
        resp = session.get(SIGNIN_PAGE, timeout=15)
        formhash = extract_formhash(resp.text)

        if not formhash:
            log("获取签到页面 formhash 失败", "ERROR")
            return False, "获取 formhash 失败"

        # 检查是否已签到
        if "您的签到排名" in resp.text:
            rank_match = re.search(r'您的签到排名[：:]\s*(\d+)', resp.text)
            rank = rank_match.group(1) if rank_match else "未知"
            return True, f"今日已签到（排名: {rank}）"

        # 2. 发起签到
        data = {
            "formhash": formhash,
            "select": mood,
            "qiandaobox": message,
        }
        resp = session.post(SIGNIN_API, data=data, timeout=20)
        result = parse_xml_response(resp.text)

        log(f"签到响应: {result}", "SIGN")

        # 判断签到结果
        if "已签" in result or "已经" in result:
            return True, result
        if "成功" in result or "签到" in result or "恭喜" in result or "获得" in result:
            return True, result
        if "失败" in result or "错误" in result:
            return False, result

        # 默认：有响应内容且无明确错误，视为成功
        if result:
            return True, result
        return False, "签到无响应"

    except Exception as e:
        log(f"签到异常: {type(e).__name__}: {e}", "ERROR")
        return False, str(e)


# ============================================================
# 单账号处理
# ============================================================
def process_account(username, password, index=1):
    """处理单账号的登录+签到"""
    log(f"===== 账号 {index}: {username} =====")

    session = new_session()

    # 登录（带重试）
    login_ok = False
    for attempt in range(1, MAX_RETRIES + 1):
        if do_login(session, username, password):
            login_ok = True
            break
        if attempt < MAX_RETRIES:
            log(f"登录重试 {attempt}/{MAX_RETRIES}...", "WARN")
            time.sleep(RETRY_DELAY)

    if not login_ok:
        log(f"账号 {username} 登录失败，跳过签到", "ERROR")
        return False

    # 签到（带重试）
    for attempt in range(1, MAX_RETRIES + 1):
        success, msg = do_signin(session)
        if success:
            log(f"签到结果: {msg}", "SUCCESS")
            return True
        if attempt < MAX_RETRIES:
            log(f"签到重试 {attempt}/{MAX_RETRIES}...", "WARN")
            time.sleep(RETRY_DELAY)

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
    log("魔性论坛 1.0 (moxing.lol) 自动签到脚本启动")
    log(f"目标站点: {BASE_URL}")

    # 读取环境变量
    env_username = os.environ.get("MOX1_USERNAME", "") or os.environ.get("mox1_username", "")
    env_password = os.environ.get("MOX1_PASSWORD", "") or os.environ.get("mox1_password", "")

    if not env_username or not env_password:
        log("未检测到有效配置！", "ERROR")
        log("请设置环境变量：MOX1_USERNAME 和 MOX1_PASSWORD", "INFO")
        sys.exit(1)

    usernames = parse_multi(env_username)
    passwords = parse_multi(env_password)

    # 补齐密码长度
    while len(passwords) < len(usernames):
        passwords.append(passwords[-1] if passwords else "")

    log(f"共 {len(usernames)} 个账号")

    results = []
    for i, (user, pwd) in enumerate(zip(usernames, passwords), 1):
        ok = process_account(user, pwd, i)
        results.append(ok)
        if i < len(usernames):
            time.sleep(3)

    # 汇总
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
