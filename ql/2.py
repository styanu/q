#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
湖南电信上新优惠监控（Playwright 版，适用于云服务器IP被瑞数拦截的环境）
=========================================================================
与纯HTTP版的区别：使用 Playwright 无头浏览器打开页面，自动执行瑞数JS挑战，
获取渲染后的真实页面内容，再做指纹对比和钉钉推送。

【青龙环境变量】
  DINGTALK_WEBHOOK   钉钉自定义机器人 Webhook 地址（必填）
  DINGTALK_SECRET    钉钉机器人加签密钥（必填）

【依赖安装（青龙终端执行）】
  pip install playwright
  playwright install chromium

【状态文件】脚本同目录下 hunan_telecom_state.json

【监控源】
  1. 湖南掌厅资费专区
  2. 流量专区-星卡全家畅享福利
  3. 流量专区-互联网卡加包领券
  4. 欢go-融合宽带新装
  5. 欢go-通用流量包
  6. 资费专区主页面（通过浏览器渲染，可获取60+条资费明细）
"""

import os
import re
import sys
import json
import time
import hmac
import hashlib
import base64
import urllib.parse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("请先安装: pip install playwright && playwright install chromium")
    sys.exit(1)

# ---------------- 配置 ----------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "hunan_telecom_state.json")

# 监控源：(名称, URL, 是否需要等待渲染)
SOURCES = [
    ("湖南掌厅资费专区", "https://waphn.189.cn/hd/zifeizq/wap/zfzx/indexPC.html", True),
    ("流量专区-星卡全家畅享福利", "http://flow.hn.189.cn/hnfx/page/infourl?pageid=185&clientid=SMS", True),
    ("流量专区-互联网卡加包领券", "http://flow.hn.189.cn/hnfx/hkly/newhlwkllbDy?tcid=9011809", True),
    ("欢go-融合宽带新装", "https://hn.189.cn/tymall/rh2/index.html", True),
    ("欢go-通用流量包", "http://hn.189.cn/tymall/zifeizq/common/yidong/tongyongllb.html", True),
    ("资费专区主页面", "https://www.189.cn/wapportalweb/rateZone/index.html#/?provCode=600203&use_xbridge3=true&loader_name=forest&need_sec_link=1&sec_link_scene=im&theme=dark", True),
]

KEYWORDS = re.compile(
    r"(元/月|元每月|活动时间|活动名称|套餐|流量|语音|宽带|融合|权益|话费券|红包|"
    r"赠|赠送|优惠|新品|上线|有效期|上下线|档位|月费|月租|eSIM|星卡|畅享|暖心|孝心|条资费)"
)

IGNORE_PATTERNS = [
    re.compile(r"\d{10,}"),
    re.compile(r"[0-9a-f]{16,}", re.I),
]


# ---------------- 工具函数 ----------------
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def html_to_text(html):
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def make_fingerprint(html):
    lines = html_to_text(html)
    kept = []
    for line in lines:
        if not KEYWORDS.search(line):
            continue
        clean = line
        for pat in IGNORE_PATTERNS:
            clean = pat.sub("", clean)
        clean = clean.strip(" -|·•")
        if len(clean) >= 4:
            kept.append(clean)
    kept = sorted(set(kept))
    return "\n".join(kept)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"状态文件读取失败，将重建: {e}")
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log(f"状态文件写入失败: {e}")
        return False


# ---------------- 钉钉推送 ----------------
def dingtalk_sign(secret):
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


def send_dingtalk(title, markdown_text):
    import urllib.request
    import ssl
    webhook = os.environ.get("DINGTALK_WEBHOOK", "").strip()
    secret = os.environ.get("DINGTALK_SECRET", "").strip()
    if not webhook:
        log("未配置 DINGTALK_WEBHOOK，跳过钉钉推送")
        return False
    url = webhook
    if secret:
        ts, sign = dingtalk_sign(secret)
        sep = "&" if "?" in webhook else "?"
        url = f"{webhook}{sep}timestamp={ts}&sign={sign}"
    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            log(f"钉钉推送响应: {body[:200]}")
            return '"errcode": 0' in body or '"errcode":0' in body
    except Exception as e:
        log(f"钉钉推送失败: {e}")
        return False


# ---------------- Playwright 抓取 ----------------
def fetch_with_playwright(page, url, wait_ms=8000):
    """用Playwright打开页面，等待JS渲染（含瑞数挑战），返回页面HTML"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # 等待瑞数JS挑战执行和页面渲染
        page.wait_for_timeout(wait_ms)
        # 额外等待网络空闲
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        html = page.content()
        # 检测是否仍被拦截（页面过短或包含挑战关键词）
        if len(html) < 5000 and ("$_ts" in html or "ICOn4uKYk7jd" in html):
            return False, "页面仍为瑞数挑战页"
        return True, html
    except Exception as e:
        return False, str(e)[:200]


# ---------------- 主逻辑 ----------------
def main():
    log("=" * 55)
    log("湖南电信上新优惠监控（Playwright版）开始运行")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    old_state = load_state()
    old_sources = old_state.get("sources", {})
    is_first_run = not old_sources

    new_state = {"check_time": now, "sources": {}}
    changed = []
    failed = []
    new_added = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
            locale="zh-CN",
        )
        # 移除webdriver标记
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()

        for name, url, need_render in SOURCES:
            log(f"正在抓取: {name}")
            ok, content = fetch_with_playwright(page, url, wait_ms=10000 if "rateZone" in url else 6000)
            if not ok:
                log(f"[失败] {name}: {content[:120]}")
                failed.append((name, url, content[:120]))
                old_fp = old_sources.get(name, {}).get("fingerprint", "")
                new_state["sources"][name] = {
                    "url": url, "status": "error", "fingerprint": old_fp,
                }
                continue

            fp = make_fingerprint(content)
            item_count = len(fp.splitlines())
            new_state["sources"][name] = {
                "url": url, "status": "ok", "fingerprint": fp,
                "item_count": item_count,
            }
            old_fp = old_sources.get(name, {}).get("fingerprint", "")
            if not old_fp:
                new_added.append(name)
                log(f"[首次] {name} 采集到 {item_count} 条关键信息")
            elif old_fp != fp:
                changed.append(name)
                log(f"[变化] {name} 关键信息有更新")
            else:
                log(f"[正常] {name} 无变化（{item_count} 条）")

        browser.close()

    save_state(new_state)

    # ---- 推送逻辑 ----
    all_failed = len(failed) >= len(SOURCES)

    if is_first_run:
        if all_failed:
            title = "⚠️ 湖南电信监控启动（全部抓取失败）"
        else:
            title = "📡 湖南电信优惠监控已启动"
        msg = f"### {title}\n\n**首次运行**，监控 {len(SOURCES)} 个官方页面：\n\n"
        for name, url, _ in SOURCES:
            st = new_state["sources"].get(name, {})
            s = st.get("status", "?")
            icon = {"ok": "✅", "error": "⚠️"}.get(s, "❓")
            label = {"ok": "正常", "error": "抓取失败"}.get(s, s)
            msg += f"- {icon} {name}（{label}）\n"
        if all_failed:
            msg += "\n🚨 所有页面均抓取失败，Playwright可能也被风控拦截。\n"
            msg += "建议检查：① 服务器IP是否被电信封禁；② Playwright浏览器是否正确安装。\n"
        else:
            msg += "\n已建立基线快照，后续仅在发现内容变化时推送。\n"
        msg += f"\n基线建立时间：{now}"
        send_dingtalk(title, msg)
        log("首次运行，已推送启动通知")
        return

    if changed:
        msg = f"### 🔔 湖南电信上新/变化提醒\n\n"
        msg += f"检测到以下官方页面内容发生变化，可能有新套餐或新活动上线：\n\n"
        for name in changed:
            info = new_state["sources"][name]
            msg += f"#### {name}\n"
            msg += f"- 链接：{info['url']}\n"
            msg += f"- 当前关键信息条数：{info.get('item_count', '?')}\n\n"
        if failed:
            msg += f"⚠️ 以下页面本次抓取失败（保留上次快照）：\n"
            for name, url, err in failed:
                msg += f"- {name}：{err}\n"
            msg += "\n"
        msg += f"检查时间：{now}\n\n"
        msg += f"请点击上方链接查看具体新套餐/活动详情，以官方页面为准。"
        send_dingtalk("湖南电信上新提醒", msg)
        log(f"发现变化：{changed}，已推送钉钉")
    elif all_failed:
        msg = (
            f"### ⚠️ 湖南电信监控告警\n\n"
            f"本次所有监控源均抓取失败（{len(failed)}/{len(SOURCES)}）。\n\n"
            f"可能原因：Playwright浏览器异常、网络故障、或IP被风控。\n"
            f"检查时间：{now}\n将在下次运行时重试。"
        )
        send_dingtalk("湖南电信监控告警", msg)
        log("全部源失败，已推送告警")
    else:
        log("无变化，不推送")

    log("运行结束")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"脚本异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
#（注：内容由AI生成）
