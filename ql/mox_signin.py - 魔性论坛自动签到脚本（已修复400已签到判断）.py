#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
魔性论坛 (mox.moxing.lol) 自动签到脚本
适配：呆呆面板 / 青龙面板 / 通用 Python 环境

【两种使用模式】

模式一：用户名密码自动登录（推荐，全自动）
  环境变量：
    MOX_USERNAME = 你的用户名
    MOX_PASSWORD = 你的密码
    MOX_SECURITY_ANSWER = 安全提问答案（未设置安全提问则留空）
  多账号：多组用 & 分隔，组内用 | 分隔，例如：
    MOX_USERNAME = user1|user2
    MOX_PASSWORD = pass1|pass2

模式二：Cookie 模式（备用）
  环境变量：
    MOX_COOKIE = 浏览器复制的完整 cookie（含 mox_session 和 XSRF-TOKEN）
  多账号：用 & 或换行分隔

【定时建议】每天 00:05 执行一次（Cron: 5 0 * * *）

【依赖】requests（面板一般已内置，若无则 pip install requests）

【说明】本脚本自动获取并填写验证码，无需人工干预。
"""

import os
import re
import sys
import json
import time
import requests
from urllib.parse import unquote

# ============================================================
# 配置区
# ============================================================
BASE_URL = "https://mox.moxing.lol"
LOGIN_API = f"{BASE_URL}/api/forum/login"
SIGNIN_API = f"{BASE_URL}/api/forum/check-in/sign"
CAPTCHA_API = f"{BASE_URL}/api/forum/captcha/generate"
CSRF_URL = f"{BASE_URL}/sanctum/csrf-cookie"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

MAX_RETRIES = 3
RETRY_DELAY = 5


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
    }.get(level, "📢")
    print(f"{prefix} [{timestamp}] {msg}")


def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": BASE_URL,
    })
    return s


def get_csrf(session, referer="/login"):
    try:
        session.get(
            CSRF_URL,
            headers={"Referer": f"{BASE_URL}{referer}"},
            timeout=15,
        )
        xsrf = session.cookies.get("XSRF-TOKEN", "")
        if xsrf:
            token = unquote(xsrf)
            session.headers["X-XSRF-TOKEN"] = token
            return token
        return None
    except Exception as e:
        log(f"获取 CSRF Token 失败: {e}", "WARN")
        return None


def get_captcha(session, referer="/login"):
    """获取验证码（答案直接在响应中返回）"""
    try:
        resp = session.get(
            CAPTCHA_API,
            headers={"Referer": f"{BASE_URL}{referer}"},
            timeout=15,
        )
        data = resp.json()
        key = data.get("key", "")
        answer = data.get("image", "")
        if key and answer:
            log(f"验证码获取成功: {answer}")
            return key, answer
        log(f"验证码响应异常: {data}", "WARN")
        return None, None
    except Exception as e:
        log(f"获取验证码失败: {e}", "WARN")
        return None, None


def parse_cookie_string(cookie_str):
    cookies = {}
    parts = re.split(r'[;&]', cookie_str)
    for part in parts:
        part = part.strip()
        if '=' in part:
            key, value = part.split('=', 1)
            cookies[key.strip()] = value.strip()
    return cookies


# ============================================================
# 登录函数
# ============================================================
def do_login(session, username, password, security_answer=""):
    """使用用户名密码登录，返回 True/False"""
    log(f"正在登录账号: {username}", "LOGIN")

    # 获取 CSRF
    if not get_csrf(session, "/login"):
        log("获取 CSRF 失败", "ERROR")
        return False

    # 获取验证码
    cap_key, cap_answer = get_captcha(session, "/login")
    if not cap_key:
        log("获取验证码失败", "ERROR")
        return False

    # 构建登录数据
    login_data = {
        "username": username,
        "password": password,
        "captcha": cap_answer,
        "captcha_key": cap_key,
    }
    if security_answer:
        login_data["security_answer"] = security_answer

    # 发起登录
    try:
        resp = session.post(
            LOGIN_API,
            json=login_data,
            headers={"Referer": f"{BASE_URL}/login"},
            timeout=20,
        )
        data = resp.json()

        # 检查登录结果
        if data.get("success") or data.get("status") == "success":
            log(f"登录成功: {username}", "SUCCESS")
            return True

        message = data.get("message", "")
        if "验证数据错误" in message or "密码" in message or "用户名" in message:
            log(f"登录失败：{message}", "ERROR")
            return False
        if "验证码" in message:
            log(f"验证码错误，重试登录...", "WARN")
            return False  # 外层会重试
        if "安全提问" in message or "安全问题" in message:
            log(f"需要安全提问答案，请配置 MOX_SECURITY_ANSWER", "ERROR")
            return False

        log(f"登录响应: {json.dumps(data, ensure_ascii=False)[:300]}", "WARN")
        # 如果 HTTP 200 且没有明确错误，可能登录成功
        if resp.status_code == 200 and not data.get("success") is False:
            log("登录可能成功（无明确错误信息）", "SUCCESS")
            return True
        return False

    except Exception as e:
        log(f"登录异常: {e}", "ERROR")
        return False


# ============================================================
# 签到函数
# ============================================================
def do_signin_request(session):
    """执行签到请求（假设已登录），返回 (success, data)"""
    # 获取新鲜 CSRF
    if not get_csrf(session, "/forum/sign"):
        log("获取 CSRF 失败", "WARN")

    # 获取验证码
    cap_key, cap_answer = get_captcha(session, "/forum/sign")
    if not cap_key:
        log("获取验证码失败", "ERROR")
        return False, None

    # 发起签到
    try:
        resp = session.post(
            SIGNIN_API,
            json={
                "captcha": cap_answer,
                "captcha_key": cap_key,
            },
            headers={"Referer": f"{BASE_URL}/forum/sign"},
            timeout=20,
        )

        if resp.status_code == 401 or resp.status_code == 419:
            log("登录态已失效", "ERROR")
            return False, None

        # 尝试解析 JSON（400 也可能是"今日已签到"，需要交给后续逻辑判断）
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            data = {"message": resp.text[:200]}

        if resp.status_code != 200:
            message = data.get("message", "") if isinstance(data, dict) else ""
            # 已签到相关消息不视为错误，交给 parse_signin_result 判断
            already_keywords = ["已签", "重复", "今天", "今日", "再来", "明天", "已经"]
            if any(kw in message for kw in already_keywords):
                log(f"签到返回: {message}", "INFO")
                return True, data
            log(f"签到请求状态码: {resp.status_code}, 响应: {resp.text[:200]}", "WARN")
            return False, None

        return True, data

    except Exception as e:
        log(f"签到请求异常: {e}", "ERROR")
        return False, None


def parse_signin_result(data):
    """解析签到结果，返回 (is_success, message)"""
    if not isinstance(data, dict):
        return False, "响应格式异常"

    message = data.get("message", "")
    success = data.get("success", None)
    status = data.get("status", "")

    # 明确成功
    if success is True or status == "success":
        return True, message or "签到成功"

    # 已签到关键词
    already_keywords = ["已签", "重复", "今天", "今日", "再来", "明天", "已经"]
    if any(kw in message for kw in already_keywords):
        return True, message  # 已签到也算成功

    # 成功关键词
    success_keywords = ["成功", "签到", "奖励", "连续", "获得", "恭喜"]
    if any(kw in message for kw in success_keywords):
        return True, message

    # 明确失败
    if success is False or status == "error":
        return False, message or "签到失败"

    # Server Error 可能是已签到或其他问题
    if "Server Error" in message:
        return False, "服务器错误（可能今日已签到或登录态异常）"

    # 默认：HTTP 200 无明确错误视为成功
    return True, message or "签到完成"


def print_reward_info(data):
    """打印签到奖励信息"""
    if not isinstance(data, dict):
        return
    reward_keywords = [
        "reward", "credit", "points", "coin", "money",
        "amount", "bonus", "prize", "软妹币", "魔币", "魔晶",
        "continuous", "streak", "total", "days", "day",
        "sign", "check", "level", "exp",
    ]
    info = []
    for key, value in data.items():
        kl = key.lower()
        if any(rk in kl for rk in reward_keywords) and value:
            if isinstance(value, (str, int, float, bool)):
                info.append(f"{key}: {value}")
    if "data" in data and isinstance(data["data"], dict):
        for key, value in data["data"].items():
            kl = key.lower()
            if any(rk in kl for rk in reward_keywords) and value:
                if isinstance(value, (str, int, float, bool)):
                    info.append(f"{key}: {value}")
    if info:
        log("签到详情：" + " | ".join(info), "REWARD")


# ============================================================
# 单账号处理
# ============================================================
def process_account_username(username, password, security_answer="", index=1):
    """使用用户名密码模式处理单账号"""
    log(f"===== 账号 {index}: {username} =====")

    session = new_session()

    # 登录（带重试）
    login_ok = False
    for attempt in range(1, MAX_RETRIES + 1):
        if do_login(session, username, password, security_answer):
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
        ok, data = do_signin_request(session)
        if ok:
            success, msg = parse_signin_result(data)
            if success:
                log(f"签到结果: {msg}", "SUCCESS")
                print_reward_info(data)
                return True
            else:
                log(f"签到未成功: {msg}", "WARN")
                if "服务器错误" in msg and attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return False
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    log(f"账号 {username} 签到失败", "ERROR")
    return False


def process_account_cookie(cookie_str, index=1):
    """使用 Cookie 模式处理单账号"""
    log(f"===== 账号 {index} (Cookie模式) =====")

    cookies = parse_cookie_string(cookie_str)
    if "mox_session" not in cookies:
        log("Cookie 中未找到 mox_session", "ERROR")
        return False

    session = new_session()
    session.cookies.update(cookies)

    # 签到（带重试）
    for attempt in range(1, MAX_RETRIES + 1):
        ok, data = do_signin_request(session)
        if ok:
            success, msg = parse_signin_result(data)
            if success:
                log(f"签到结果: {msg}", "SUCCESS")
                print_reward_info(data)
                return True
            else:
                log(f"签到未成功: {msg}", "WARN")
                if "登录态" in msg or "失效" in msg:
                    log("Cookie 可能已过期，请更新", "ERROR")
                    return False
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY)
                    continue
                return False
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    log("签到失败", "ERROR")
    return False


# ============================================================
# 多账号解析
# ============================================================
def parse_multi(value, sep="|"):
    """解析多账号值，返回列表"""
    if not value:
        return []
    # 支持 | 分隔和换行分隔
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
    log("魔性论坛自动签到脚本启动")
    log(f"目标站点: {BASE_URL}")

    # 读取环境变量
    env_username = os.environ.get("MOX_USERNAME", "") or os.environ.get("mox_username", "")
    env_password = os.environ.get("MOX_PASSWORD", "") or os.environ.get("mox_password", "")
    env_security = os.environ.get("MOX_SECURITY_ANSWER", "") or os.environ.get("mox_security_answer", "")
    env_cookie = os.environ.get("MOX_COOKIE", "") or os.environ.get("mox_cookie", "")

    results = []

    # 模式一：用户名密码
    if env_username and env_password:
        usernames = parse_multi(env_username)
        passwords = parse_multi(env_password)
        securities = parse_multi(env_security) if env_security else [""] * len(usernames)

        # 补齐长度
        while len(passwords) < len(usernames):
            passwords.append(passwords[-1] if passwords else "")
        while len(securities) < len(usernames):
            securities.append("")

        log(f"用户名密码模式，共 {len(usernames)} 个账号")

        for i, (user, pwd, sec) in enumerate(zip(usernames, passwords, securities), 1):
            ok = process_account_username(user, pwd, sec, i)
            results.append(ok)
            if i < len(usernames):
                time.sleep(3)

    # 模式二：Cookie
    elif env_cookie:
        accounts = []
        for line in env_cookie.splitlines():
            line = line.strip()
            if line:
                accounts.append(line)
        if len(accounts) == 1 and "&" in accounts[0]:
            parts = accounts[0].split("&")
            if all("mox_session" in p for p in parts):
                accounts = [p.strip() for p in parts if p.strip()]

        log(f"Cookie 模式，共 {len(accounts)} 个账号")

        for i, cookie in enumerate(accounts, 1):
            ok = process_account_cookie(cookie, i)
            results.append(ok)
            if i < len(accounts):
                time.sleep(3)

    else:
        log("未检测到有效配置！", "ERROR")
        log("请设置以下环境变量之一：", "INFO")
        log("  模式一（推荐）: MOX_USERNAME + MOX_PASSWORD", "INFO")
        log("  模式二: MOX_COOKIE", "INFO")
        sys.exit(1)

    # 汇总
    total = len(results)
    success = sum(1 for r in results if r)
    log("===== 签到完成 =====")
    log(f"成功: {success}/{total}")

    if success == total:
        log("全部账号签到成功！", "SUCCESS")
        sys.exit(0)
    elif success == 0:
        log("全部账号签到失败，请检查配置", "ERROR")
        sys.exit(1)
    else:
        log("部分账号签到失败，请检查日志", "WARN")
        sys.exit(0)


if __name__ == "__main__":
    main()
