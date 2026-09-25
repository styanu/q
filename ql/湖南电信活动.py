#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
湖南电信上新优惠监控（青龙面板版）
====================================
功能：定时抓取湖南电信多个官方资费/活动页面，与上次快照对比，
      发现内容变化（新套餐 / 新活动 / 资费调整）时通过钉钉机器人推送提醒。

【青龙环境变量】
  DINGTALK_WEBHOOK   钉钉自定义机器人 Webhook 地址（必填）
  DINGTALK_SECRET    钉钉机器人加签密钥（必填，安全设置选"加签"时给出）

【依赖】纯 Python 标准库，无需 pip install。

【状态文件】脚本同目录下 hunan_telecom_state.json，自动创建，用于对比变化。
            青龙中通常位于 /ql/data/scripts/ 下。

【监控源说明】
  主资费专区 www.189.cn/wapportalweb/rateZone 是 Vue 单页应用，数据走加密接口，
  脚本无法直接抓取其 60 条明细；因此采用以下可直接抓取的官方静态页面作为监控源，
  覆盖湖南电信主要套餐与活动上新渠道：
    1. 湖南掌厅资费专区（完整资费表：5G畅享/星卡/暖心卡/孝心卡/eSIM/宽带等）
    2. 流量专区-星卡全家畅享福利活动
    3. 流量专区-互联网卡加包领话费券活动
    4. 欢go网站-融合宽带新装活动
    5. 欢go网站-通用流量包（含暖心包/加餐包）

【使用】
  青龙面板 → 环境变量 → 新增 DINGTALK_WEBHOOK、DINGTALK_SECRET
  青龙面板 → 脚本管理 → 上传本脚本 → 添加定时任务（建议每天 1 次，如 23 10 * * *）
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
import urllib.request
import ssl

# ---------------- 配置 ----------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "hunan_telecom_state.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 监控源：(名称, URL)
SOURCES = [
    ("湖南掌厅资费专区", "https://waphn.189.cn/hd/zifeizq/wap/zfzx/indexPC.html"),
    ("流量专区-星卡全家畅享福利", "http://flow.hn.189.cn/hnfx/page/infourl?pageid=185&clientid=SMS"),
    ("流量专区-互联网卡加包领券", "http://flow.hn.189.cn/hnfx/hkly/newhlwkllbDy?tcid=9011809"),
    ("欢go-融合宽带新装", "https://hn.189.cn/tymall/rh2/index.html"),
    ("欢go-通用流量包", "http://hn.189.cn/tymall/zifeizq/common/yidong/tongyongllb.html"),
]

# 指纹提取关键词（只保留含这些词的行，过滤广告/动态元素）
KEYWORDS = re.compile(
    r"(元/月|元每月|活动时间|活动名称|套餐|流量|语音|宽带|融合|权益|话费券|红包|"
    r"赠|赠送|优惠|新品|上线|有效期|上下线|档位|月费|月租|eSIM|星卡|畅享|暖心|孝心)"
)

# 忽略的动态片段（时间戳、随机参数等）
IGNORE_PATTERNS = [
    re.compile(r"\d{10,}"),          # 长数字（时间戳/随机ID）
    re.compile(r"[0-9a-f]{16,}", re.I),  # hash
]


# ---------------- 工具函数 ----------------
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch(url, timeout=20):
    """抓取页面，返回 (成功bool, 文本或错误信息)"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            # 自动识别编码
            charset = "utf-8"
            ct = resp.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w-]+)", ct, re.I)
            if m:
                charset = m.group(1)
            try:
                text = raw.decode(charset, errors="replace")
            except Exception:
                text = raw.decode("utf-8", errors="replace")
            return True, text
    except Exception as e:
        return False, str(e)


def is_ruishu_blocked(html):
    """检测是否为瑞数动态防护的 JS 挑战页（电信全站部署）。
    特征：页面很短、包含 $_ts 变量或 ICOn4uKYk7jd meta 标签、无实际业务文本。"""
    if len(html) < 3500 and ("$_ts" in html or "ICOn4uKYk7jd" in html or "nsd=" in html):
        return True
    return False


def html_to_text(html):
    """去脚本/样式/标签，返回纯文本行列表"""
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
    """提取页面关键信息行，排序后拼接，作为稳定指纹"""
    lines = html_to_text(html)
    kept = []
    for line in lines:
        if not KEYWORDS.search(line):
            continue
        # 过滤动态片段
        clean = line
        for pat in IGNORE_PATTERNS:
            clean = pat.sub("", clean)
        clean = clean.strip(" -|·•")
        if len(clean) >= 4:
            kept.append(clean)
    # 去重并排序，消除页面顺序波动
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
    """钉钉加签：返回 (timestamp, sign)"""
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
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
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


# ---------------- 主逻辑 ----------------
def main():
    log("=" * 55)
    log("湖南电信上新优惠监控 开始运行")
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    old_state = load_state()
    old_sources = old_state.get("sources", {})
    is_first_run = not old_sources

    new_state = {"check_time": now, "sources": {}}
    changed = []   # 内容变化的源
    failed = []    # 抓取失败的源（网络错误）
    blocked = []   # 被瑞数风控拦截的源
    new_added = [] # 本次新增的监控源（首次或配置变更）

    for name, url in SOURCES:
        ok, content = fetch(url)
        if not ok:
            log(f"[失败] {name}: {content[:120]}")
            failed.append((name, url, content[:120]))
            old_fp = old_sources.get(name, {}).get("fingerprint", "")
            new_state["sources"][name] = {
                "url": url, "status": "error", "fingerprint": old_fp,
            }
            continue

        # 检测瑞数动态防护挑战页（电信全站部署，云服务器IP常见）
        if is_ruishu_blocked(content):
            log(f"[风控] {name}: 返回瑞数JS挑战页（当前IP可能被拦截）")
            blocked.append((name, url))
            old_fp = old_sources.get(name, {}).get("fingerprint", "")
            new_state["sources"][name] = {
                "url": url, "status": "blocked", "fingerprint": old_fp,
            }
            continue

        fp = make_fingerprint(content)
        new_state["sources"][name] = {
            "url": url, "status": "ok", "fingerprint": fp,
            "item_count": len(fp.splitlines()),
        }
        old_fp = old_sources.get(name, {}).get("fingerprint", "")
        if not old_fp:
            new_added.append(name)
            log(f"[首次] {name} 采集到 {len(fp.splitlines())} 条关键信息")
        elif old_fp != fp:
            changed.append(name)
            log(f"[变化] {name} 关键信息有更新")
        else:
            log(f"[正常] {name} 无变化（{len(fp.splitlines())} 条）")

    save_state(new_state)

    # ---- 推送逻辑 ----
    all_unavailable = (len(failed) + len(blocked)) >= len(SOURCES)

    if is_first_run:
        msg = (
            f"### 📡 湖南电信优惠监控已启动\n\n"
            f"**首次运行**，监控 {len(SOURCES)} 个官方页面：\n\n"
        )
        for name, url in SOURCES:
            st = new_state["sources"].get(name, {})
            s = st.get("status", "?")
            icon = {"ok": "✅", "blocked": "🚫", "error": "⚠️"}.get(s, "❓")
            label = {"ok": "正常", "blocked": "风控拦截", "error": "抓取失败"}.get(s, s)
            msg += f"- {icon} {name}（{label}）：{url}\n"
        if all_unavailable:
            msg += (
                f"\n⚠️ **本次所有源均无法获取真实内容**（{len(blocked)} 个被瑞数风控拦截，"
                f"{len(failed)} 个网络错误）。\n"
                f"电信官方页面全站部署了瑞数动态防护，**云服务器/数据中心 IP 通常会被拦截**，"
                f"建议将青龙部署在**家庭宽带/住宅 IP** 下运行，或配合 Playwright 无头浏览器执行 JS 挑战。\n"
            )
        else:
            msg += f"\n已建立基线快照，后续仅在发现页面内容变化时推送。\n"
        msg += (
            f"\n基线建立时间：{now}\n\n"
            f"> 说明：主资费专区(rateZone)为加密单页应用无法直接抓取，"
            f"本脚本通过掌厅资费专区+流量专区+欢go活动页多源覆盖上新渠道。"
        )
        send_dingtalk("湖南电信监控启动", msg)
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
        if blocked:
            msg += f"🚫 以下页面被瑞数风控拦截（保留上次快照，未参与本次比对）：\n"
            for name, url in blocked:
                msg += f"- {name}\n"
            msg += "\n"
        if failed:
            msg += f"⚠️ 以下页面本次抓取失败：\n"
            for name, url, err in failed:
                msg += f"- {name}：{err}\n"
            msg += "\n"
        msg += f"检查时间：{now}\n\n"
        msg += f"请点击上方链接查看具体新套餐/活动详情，以官方页面为准。"
        send_dingtalk("湖南电信上新提醒", msg)
        log(f"发现变化：{changed}，已推送钉钉")
    elif all_unavailable:
        # 所有源都被风控或失败时才告警，避免单个源临时故障打扰
        msg = (
            f"### ⚠️ 湖南电信监控告警\n\n"
            f"本次所有监控源均无法获取真实内容：\n\n"
            f"- 瑞数风控拦截：{len(blocked)} 个\n"
            f"- 网络/抓取错误：{len(failed)} 个\n\n"
        )
        if blocked:
            msg += "**被风控页面**：\n"
            for name, url in blocked:
                msg += f"- {name}\n"
            msg += "\n"
        if failed:
            msg += "**抓取失败**：\n"
            for name, url, err in failed:
                msg += f"- {name}：{err}\n"
            msg += "\n"
        msg += (
            f"电信官方页面全站部署瑞数动态防护，云服务器IP易被拦截。\n"
            f"建议：① 将青龙部署在家庭宽带IP下；② 或改用 Playwright 无头浏览器抓取。\n"
            f"检查时间：{now}\n将在下次运行时重试。"
        )
        send_dingtalk("湖南电信监控告警", msg)
        log("全部源不可用，已推送告警")
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
