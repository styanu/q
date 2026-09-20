#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 必应积分（Microsoft Rewards）自动搜索 - 青龙面板脚本
---------------------------------------------------------------------
【原理】登录 bing.com 后，用账号的 _U cookie 模拟桌面端 / 移动端
        正常搜索请求，每日自动完成 PC 端 + 移动端搜索任务。

【青龙环境变量】（青龙面板 -> 配置 -> 新增变量）
  BING_U_COOKIE   必需：登录 bing.com 后浏览器里的 _U cookie 值
                  获取方法：浏览器登录 bing.com -> F12 -> 网络/应用 ->
                  找任意请求的 Cookie -> 复制 _U= 后面那一长串值
  BING_COOKIE     可选：完整 Cookie 字符串（填了就优先用它，不用 _U）
  BING_PC_NUM     可选：桌面端搜索次数，默认 30
  BING_MOBILE_NUM 可选：移动端搜索次数，默认 20
  BING_SLEEP      可选：每次搜索间隔秒数（随机范围），默认 6~14
  BING_WEBHOOK    可选：完成后推送到该地址（支持企业微信/钉钉机器人，
                  传完整机器人 webhook 地址即可；不填则只打印日志）

【定时】建议每天 1~2 次，例如：30 8 * * *
        （积分每日 0 点刷新，PC+手机各搜满即可，不要超频）

⚠️ 风险提示：使用程序自动搜索违反 Microsoft Rewards 服务条款，
   有导致积分清零 / 账号受限的风险，后果自负，仅供学习研究。
=====================================================================
"""

import os
import sys
import time
import random
import datetime
import subprocess

try:
    import requests
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "requests", "-q"]
    )
    import requests

# ---------------- UA 配置 ----------------
UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)
UA_MOBILE = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

# ---------------- 搜索词库（随机组合，保证每次搜索内容不同）----------------
NOUNS = [
    "天气", "新闻", "美食", "旅游攻略", "电影推荐", "音乐", "健身", "菜谱",
    "历史", "科技", "财经", "汽车", "手机评测", "摄影", "宠物", "养花",
    "编程", "Python教程", "英语学习", "职场", "理财", "电影", "电视剧",
    "足球", "篮球", "游戏", "小说", "漫画", "动漫", "科普", "健康",
    "中医", "装修", "租房", "考研", "育儿", "心理学", "经济学", "哲学",
    "人工智能", "新能源", "航天", "考古", "地理", "海洋", "天文",
]
ADJ = [
    "今日", "最新", "2025", "2026", "热门", "经典", "入门", "实用",
    "详细", "免费", "排行榜", "前十名", "哪个好", "怎么", "为什么",
    "推荐", "完整版", "小技巧", "大全", "视频", "图片",
]


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def build_quotes(n: int) -> list:
    """随机拼 n 个不重复的搜索词"""
    seen, out = set(), []
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        q = f"{random.choice(ADJ)}{random.choice(NOUNS)}"
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def get_cookie() -> str:
    full = os.environ.get("BING_COOKIE", "").strip()
    if full:
        return full
    u = os.environ.get("BING_U_COOKIE", "").strip()
    if u:
        return f"_U={u}"
    return ""


def one_search(session: requests.Session, query: str, ua: str,
               cookie: str, tag: str) -> bool:
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cookie": cookie,
        "Referer": "https://www.bing.com/",
    }
    params = {"q": query, "form": "QBLH", "sp": "-1", "cvid": str(int(time.time()))}
    try:
        r = session.get(
            "https://www.bing.com/search",
            headers=headers, params=params, timeout=20,
        )
        ok = r.status_code == 200
        log(f"  [{tag}] {query}  ->  HTTP {r.status_code} "
            f"({'成功' if ok else '失败'})")
        return ok
    except Exception as e:
        log(f"  [{tag}] {query}  -> 异常: {e}")
        return False


def run_batch(session, cookie, count, ua, tag, sleep_range):
    if count <= 0:
        log(f"{tag}: 次数为 0，跳过")
        return 0, 0
    quotes = build_quotes(count)
    log(f"{tag}: 开始 {count} 次搜索，词 {quotes[0]} 等")
    ok = 0
    for i, q in enumerate(quotes, 1):
        if one_search(session, q, ua, cookie, f"{tag} {i}/{count}"):
            ok += 1
        # 最后一次不再等待
        if i < count:
            time.sleep(random.uniform(*sleep_range))
    log(f"{tag}: 完成，成功 {ok}/{count}")
    return ok, count - ok


def notify(text: str) -> None:
    webhook = os.environ.get("BING_WEBHOOK", "").strip()
    if not webhook:
        return
    try:
        if "qyapi.weixin" in webhook:
            payload = {"msgtype": "text", "text": {"content": text}}
        else:  # 钉钉
            payload = {"msgtype": "text", "text": {"content": text}}
        requests.post(webhook, json=payload, timeout=10)
        log("推送已发送")
    except Exception as e:
        log(f"推送失败: {e}")


def main():
    log("=" * 50)
    log("必应积分自动搜索开始")

    cookie = get_cookie()
    if not cookie:
        log("❌ 未配置 Cookie！请在青龙环境变量里设置 "
            "BING_U_COOKIE（登录 bing.com 后的 _U 值）")
        sys.exit(1)

    pc_num = int(os.environ.get("BING_PC_NUM", "30") or 30)
    mob_num = int(os.environ.get("BING_MOBILE_NUM", "20") or 20)
    sleep_min, sleep_max = 6, 14
    if os.environ.get("BING_SLEEP"):
        try:
            v = int(os.environ["BING_SLEEP"])
            sleep_min, sleep_max = v, v + 8
        except ValueError:
            pass

    # 桌面端先访问首页，建立会话 cookie
    sess_pc = requests.Session()
    sess_pc.get("https://www.bing.com/",
                headers={"User-Agent": UA_PC, "Cookie": cookie}, timeout=20)
    pc_ok, pc_fail = run_batch(sess_pc, cookie, pc_num, UA_PC,
                                "桌面端", (sleep_min, sleep_max))

    time.sleep(random.uniform(3, 6))

    # 移动端
    sess_m = requests.Session()
    sess_m.get("https://www.bing.com/",
               headers={"User-Agent": UA_MOBILE, "Cookie": cookie}, timeout=20)
    m_ok, m_fail = run_batch(sess_m, cookie, mob_num, UA_MOBILE,
                              "移动端", (sleep_min, sleep_max))

    total_ok = pc_ok + m_ok
    total = pc_num + mob_num
    summary = (f"必应积分搜索完成：成功 {total_ok}/{total} "
               f"(桌面 {pc_ok}/{pc_num}，移动 {m_ok}/{mob_num})")
    log(summary)
    log("=" * 50)
    notify(summary)


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
