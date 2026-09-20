#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
崩坏：星穹铁道 米游社每日签到脚本（青龙面板专用）
=====================================================

功能：自动完成「崩坏：星穹铁道」米游社签到（国服），支持多账号、多角色（UID）自动识别，
      签到结果自动推送（推送加 PushPlus / Server酱 / 青龙自带通知）。

青龙面板配置：
  1. 环境变量（变量名任选其一，多账号用 & 或换行分隔）：
       HKRPG_COOKIE   = 账号1的Cookie&账号2的Cookie
       （也可用 MIHOYO_COOKIE / mihoyo_cookie 作为变量名）
  2. 推送（可选，三选一即可）：
       PUSHPLUS_TOKEN = 推送加 token        （http://www.pushplus.plus）
       PUSHPLUS_TOPIC = 推送加群组编码（可选）
       SERVERPUSHKEY  = Server酱 SendKey     （https://sct.ftqq.com）
       （以上都未配置时，会尝试调用青龙自带 notify 推送）
  3. 定时任务 cron 建议： 30 0 * * *   （每天 00:30 执行一次）

Cookie 获取方式：
  1. 浏览器打开签到页：
     https://act.mihoyo.com/bbs/event/signin/hkrpg/e202304121516551.html
  2. 登录后按 F12 打开开发者工具 -> Network（网络）-> 刷新页面，
     在任意一个请求的 Request Headers 里复制完整的 Cookie。
  3. Cookie 至少需包含：ltoken、ltuid、cookie_token、account_id 等字段。

说明：Cookie 有有效期（约一个月），失效后需重新获取。
"""

import os
import re
import sys
import time
import json
import uuid
import random
import string
import hashlib
import subprocess

import requests

# --------------------------- 常量配置 ---------------------------

ACT_ID = "e202304121516551"          # 星穹铁道国服签到活动 ID
GAME_BIZ = "hkrpg_cn"                # 星穹铁道游戏标识
LANG = "zh-cn"

WEB_API = "https://api-takumi.mihoyo.com"
SIGN_URL = f"{WEB_API}/event/luna/sign"
INFO_URL = f"{WEB_API}/event/luna/info?lang={LANG}"
HOME_URL = f"{WEB_API}/event/luna/home?lang={LANG}"
ROLES_URL = f"{WEB_API}/binding/api/getUserGameRolesByCookie?game_biz={GAME_BIZ}"

DS_SALT_WEB = "d9200c846b10886e8c874fc33c8f308b"   # 网页端签名盐（米游社）
APP_VERSION = "2.109.0"                            # 米游社版本号

USER_AGENT = ("Mozilla/5.0 (Linux; Android 12; Unspecified Device) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
              f"Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{APP_VERSION}")

# --------------------------- 工具函数 ---------------------------


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def random_text(num: int) -> str:
    return "".join(random.sample(string.ascii_lowercase + string.digits, num))


def get_ds() -> str:
    """生成米游社网页端 DS 动态签名。"""
    t = str(int(time.time()))
    r = random_text(6)
    c = md5(f"salt={DS_SALT_WEB}&t={t}&r={r}")
    return f"{t},{r},{c}"


def get_device_id(cookie: str) -> str:
    """根据 Cookie 生成稳定的设备 ID（同一 Cookie 每次一致，降低风控概率）。"""
    return str(uuid.uuid3(uuid.NAMESPACE_URL, cookie))


def build_headers(cookie: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "DS": get_ds(),
        "x-rpc-channel": "miyousheluodi",
        "Origin": "https://act.mihoyo.com",
        "x-rpc-app_version": APP_VERSION,
        "User-Agent": USER_AGENT,
        "x-rpc-client_type": "5",                 # 5 = 手机网页端
        "Referer": "https://act.mihoyo.com/",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "zh-CN,en-US;q=0.8",
        "X-Requested-With": "com.mihoyo.hyperion",
        "Cookie": cookie,
        "x-rpc-device_id": get_device_id(cookie),
    }


def tidy_cookie(cookie: str) -> str:
    """去重整理 Cookie（去掉重复键，保留最后一次出现）。"""
    pairs = []
    seen = set()
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key = part.split("=", 1)[0].strip()
        if key in seen:
            continue
        seen.add(key)
        pairs.append(f"{key}={part.split('=', 1)[1].strip()}")
    return "; ".join(pairs)


def load_cookies() -> list:
    """从环境变量读取 Cookie，支持多账号（用 & / # / 换行 分隔）。"""
    raw = None
    for name in ("HKRPG_COOKIE", "MIHOYO_COOKIE", "mihoyo_cookie", "SR_COOKIE"):
        if os.environ.get(name):
            raw = os.environ[name]
            break
    if not raw:
        return []
    # 按 & / # / 换行 切分
    parts = re.split(r"[&#\r\n]+", raw)
    cookies = []
    for p in parts:
        p = p.strip()
        if p and "=" in p and p not in cookies:
            cookies.append(tidy_cookie(p))
    return cookies


# --------------------------- 业务请求 ---------------------------


def http_get(url: str, cookie: str, params: dict = None) -> dict:
    headers = build_headers(cookie)
    resp = requests.get(url, headers=headers, params=params, timeout=20)
    return resp.json()


def http_post(url: str, cookie: str, body: dict) -> dict:
    headers = build_headers(cookie)
    resp = requests.post(url, headers=headers, json=body, timeout=20)
    return resp.json()


def get_roles(cookie: str) -> list:
    """获取该账号下绑定的星穹铁道角色列表。"""
    data = http_get(ROLES_URL, cookie)
    if data.get("retcode") != 0:
        return []
    return data.get("data", {}).get("list", [])


def get_rewards(cookie: str) -> list:
    """获取本月签到奖励列表。"""
    data = http_get(HOME_URL, cookie, params={"act_id": ACT_ID})
    if data.get("retcode") != 0:
        return []
    return data.get("data", {}).get("awards", [])


def get_info(cookie: str, region: str, uid: str) -> dict:
    """获取某角色的签到状态。"""
    data = http_get(INFO_URL, cookie, params={"act_id": ACT_ID, "region": region, "uid": uid})
    if data.get("retcode") != 0:
        return {}
    return data.get("data", {})


def do_sign(cookie: str, region: str, uid: str) -> dict:
    """执行签到。"""
    return http_post(SIGN_URL, cookie, {"act_id": ACT_ID, "region": region, "uid": uid})


def reward_name(awards: list, idx: int) -> str:
    """根据索引返回奖励描述，越界则返回占位。"""
    if not awards or idx < 0 or idx >= len(awards):
        return "未知"
    item = awards[idx]
    return f"{item.get('name', '未知')} x{item.get('cnt', 0)}"


# --------------------------- 通知推送 ---------------------------


def send_notify(title: str, content: str) -> bool:
    """按优先级推送：推送加 -> Server酱 -> 青龙自带 notify。"""
    sent = False

    # 1) 推送加 PushPlus
    token = os.environ.get("PUSHPLUS_TOKEN") or os.environ.get("PUSH_PLUS_TOKEN")
    if token:
        try:
            payload = {"token": token, "title": title,
                       "content": content.replace("\n", "<br>")}
            topic = os.environ.get("PUSHPLUS_TOPIC")
            if topic:
                payload["topic"] = topic
            resp = requests.post("http://www.pushplus.plus/send",
                                 json=payload, timeout=15)
            if resp.json().get("code") == 200:
                sent = True
        except Exception as e:  # noqa: BLE001
            print(f"[通知] 推送加发送失败: {e}")

    # 2) Server酱
    key = os.environ.get("SERVERPUSHKEY") or os.environ.get("SCT_KEY")
    if key and not sent:
        try:
            resp = requests.post(
                f"https://sctapi.ftqq.com/{key}.send",
                data={"title": title, "desp": content}, timeout=15)
            if resp.json().get("code") == 0:
                sent = True
        except Exception as e:  # noqa: BLE001
            print(f"[通知] Server酱发送失败: {e}")

    # 3) 青龙自带通知命令
    if not sent:
        try:
            subprocess.run(["notify", title, content],
                           check=False, timeout=20, capture_output=True)
            sent = True
        except Exception as e:  # noqa: BLE001
            print(f"[通知] 青龙 notify 发送失败: {e}")

    return sent


# --------------------------- 主流程 ---------------------------


def sign_one_account(cookie: str) -> tuple:
    """单个账号签到，返回 (成功数, 失败数, 结果文本)。"""
    lines = []
    success = fail = 0

    roles = get_roles(cookie)
    if not roles:
        lines.append("  ⚠ 未绑定星穹铁道角色，跳过")
        return success, fail, "\n".join(lines)

    awards = get_rewards(cookie)

    for role in roles:
        nickname = role.get("nickname", "未知")
        uid = role.get("game_uid", "")
        region = role.get("region", "")
        level = role.get("level", 0)
        if not uid or not region:
            continue

        # 随机延迟，降低请求频率
        time.sleep(random.uniform(1, 3))

        info = get_info(cookie, region, uid)
        if not info:
            lines.append(f"  ✗ {nickname}(Lv.{level}) 查询状态失败")
            fail += 1
            continue

        total_day = int(info.get("total_sign_day", 0))

        if info.get("is_sign"):
            idx = total_day - 1
            lines.append(f"  ✓ {nickname}(Lv.{level}) 今日已签到，累计 {total_day} 天，"
                         f"今日奖励：{reward_name(awards, idx)}")
            success += 1
            continue

        if info.get("first_bind"):
            lines.append(f"  ✗ {nickname}(Lv.{level}) 首次绑定，请先手动签到一次")
            fail += 1
            continue

        resp = do_sign(cookie, region, uid)
        retcode = resp.get("retcode")
        data = resp.get("data") or {}

        if retcode == 0 and data.get("success") == 0:
            # 签到成功：签到前 total_day 为过去已签天数，今日为第 total_day+1 天
            new_day = total_day + 1
            lines.append(f"  ✓ {nickname}(Lv.{level}) 签到成功，累计 {new_day} 天，"
                         f"今日奖励：{reward_name(awards, total_day)}")
            success += 1
        elif retcode == -5003:
            lines.append(f"  ✓ {nickname}(Lv.{level}) 今日已签到，累计 {total_day} 天，"
                         f"今日奖励：{reward_name(awards, total_day - 1)}")
            success += 1
        elif retcode == 1034 or data.get("success") == 1 or data.get("gt"):
            lines.append(f"  ✗ {nickname}(Lv.{level}) 触发验证码/风控，本次失败")
            fail += 1
        else:
            msg = resp.get("message") or json.dumps(resp, ensure_ascii=False)
            lines.append(f"  ✗ {nickname}(Lv.{level}) 签到失败: {msg}")
            fail += 1

    return success, fail, "\n".join(lines)


def main() -> None:
    cookies = load_cookies()
    if not cookies:
        print("未检测到 Cookie 环境变量，请在青龙面板配置 HKRPG_COOKIE（多账号用 & 分隔）")
        sys.exit(1)

    print(f"共检测到 {len(cookies)} 个账号，开始签到...")

    all_lines = []
    total_ok = total_fail = 0

    for i, cookie in enumerate(cookies, 1):
        print(f"\n—— 账号 {i} ——")
        try:
            ok, fail, text = sign_one_account(cookie)
        except Exception as e:  # noqa: BLE001
            ok, fail, text = 0, 1, f"  ✗ 异常: {e}"
        total_ok += ok
        total_fail += fail
        block = f"账号 {i}：\n{text}"
        all_lines.append(block)
        print(block)

    summary = (f"\n—— 签到结果汇总 ——\n"
               f"成功 {total_ok} 项，失败 {total_fail} 项")
    print(summary)

    # 推送通知
    content = "\n".join(all_lines) + summary
    title = f"星穹铁道签到 成功{total_ok} 失败{total_fail}"
    if send_notify(title, content):
        print("[通知] 推送完成")
    else:
        print("[通知] 未配置推送渠道，跳过推送")

    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    main()
