#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国内黄金与黄金基金每日行情整理脚本
=====================================
适配：青龙面板 / 呆呆面板（内置 Python3，标准 Cron 调度）
依赖：仅 Python3 标准库（urllib / json / re），无需 pip 安装任何包
功能：
  1. 抓取国内黄金价格：今日现货金价、上海金Au99.99、黄金T+D、伦敦金（参考）
  2. 抓取主要黄金ETF：518880/159934/159937/518800/159812 的最新价、涨跌幅、成交额
  3. 抓取当日黄金相关快讯，作为消息面参考
  4. 输出简洁专业的 Markdown 报告（stdout + 可选写文件 + 多渠道消息通知推送）
【消息通知配置（可选，配置任一即启用对应渠道）】
  在青龙面板/呆呆面板的环境变量中配置以下变量：
    - Server酱:   SERVERCHAN_SENDKEY   （或 SCKEY）
    - PushPlus:   PUSHPLUS_TOKEN
    - 企业微信:   WECOM_WEBHOOK        （机器人 Webhook 地址）
    - 钉钉:       DINGTALK_WEBHOOK + DINGTALK_SECRET（如开启加签）
    - Bark(iOS):  BARK_URL             （如 https://api.day.app/你的key）
    - 青龙面板:   自动检测 sendNotify（青龙原生通知，无需配置变量）
  未配置任何渠道时，脚本仅输出到日志/文件，不报错。
【青龙面板部署】
  脚本管理 -> 新建脚本 -> 粘贴本文件内容 -> 保存（如 gold_report.py）
  定时任务 -> 新建任务:
    名称: 黄金基金每日行情
    命令: task gold_report.py
    定时规则: 0 16 * * *
  运行后可在任务日志查看；若已配置通知渠道，报告将自动推送。
【呆呆面板部署】
  脚本管理 -> 上传本文件 -> 定时任务 -> 命令填 gold_report.py -> 0 16 * * *
主数据源：tmini.net 公开黄金API
辅助数据源：腾讯财经（ETF）、东方财富（快讯）
"""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote, urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

# ---------------- HTTP 基础工具 ----------------
def http_get(url, referer=None, encoding="utf-8", timeout=12):
    """通用 GET 请求，返回解码后的文本；失败返回空字符串"""
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return raw.decode(encoding, "ignore")
            except Exception:
                return raw.decode("utf-8", "ignore")
    except Exception:
        return ""

def http_get_json(url, referer=None, timeout=12):
    """GET 请求并解析 JSON；失败返回 None"""
    text = http_get(url, referer=referer, encoding="utf-8", timeout=timeout)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None

# ---------------- 主行情：tmini.net 黄金接口 ----------------
def fetch_tmini_gold():
    """调用 tmini 黄金价格接口，返回 {品种名: 数据字典}"""
    url = "https://tmini.net/api/gold-price"
    data = http_get_json(url, referer="https://tmini.net/")
    if not data or "metals" not in data:
        return None
    result = {}
    for m in data["metals"]:
        result[m["name"]] = m
    return result

def parse_tmini_spot(item):
    """解析 tmini 单条现货/延期数据，返回结构化字段"""
    try:
        last = float(item["sell_price"])
        prev = float(item["today_price"])
        high = float(item["high_price"])
        low = float(item["low_price"])
        chg = last - prev
        pct = chg / prev * 100 if prev else 0.0
        return {
            "last": last, "prev": prev, "high": high, "low": low,
            "chg": chg, "pct": pct, "unit": item["unit"],
            "update": item["updated"]
        }
    except Exception:
        return None

# ---------------- 辅助：黄金ETF 行情（腾讯接口） ----------------
ETF_LIST = [
    ("sh518880", "华安黄金ETF"),
    ("sz159934", "易方达黄金ETF"),
    ("sz159937", "博时黄金ETF"),
    ("sh518800", "国泰黄金ETF"),
    ("sz159812", "前海开源黄金ETF"),
]

def fetch_tencent_quotes(codes):
    """腾讯行情接口：qt.gtimg.cn/q=code1,code2..."""
    if not codes:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    text = http_get(url, encoding="gbk")
    result = {}
    if not text:
        return result
    for m in re.finditer(r'v_(\w+)="([^"]*)"', text):
        code = m.group(1).upper()
        fields = m.group(2).split("~")
        result[code] = fields
    return result

def parse_etf(fields):
    """解析腾讯 ETF 行情字段"""
    try:
        last = float(fields[3])
        chg = float(fields[31]) if len(fields) > 31 else 0.0
        pct = float(fields[32]) if len(fields) > 32 else 0.0
        high = float(fields[33]) if len(fields) > 33 else None
        low = float(fields[34]) if len(fields) > 34 else None
        amount = 0.0
        if len(fields) > 35 and fields[35]:
            parts = fields[35].split("/")
            if len(parts) >= 3:
                try:
                    amount = float(parts[2])
                except Exception:
                    amount = 0.0
        return {"last": last, "chg": chg, "pct": pct,
                "high": high, "low": low, "amount": amount}
    except Exception:
        return None

# ---------------- 辅助：黄金相关快讯（东方财富） ----------------
NEWS_KEYWORDS = ["黄金", "金价", "金条", "贵金属", "美联储", "美元指数",
                 "美债", "央行购金", "加息", "降息", "避险", "杰克逊霍尔",
                 "PCE", "CPI", "非农"]

def fetch_gold_news(limit=12):
    """抓取东方财富 7x24 快讯，筛选黄金相关"""
    params = urlencode({
        "client": "web", "biz": "web_724", "fastColumn": "102",
        "sortEnd": "", "pageSize": "60", "req_trace": "1",
    })
    url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList?" + params
    data = http_get_json(url)
    if not data or data.get("code") != 0:
        return []
    items = []
    news_list = (data.get("data") or {}).get("fastNewsList") or []
    for it in news_list:
        title = (it.get("title") or "").strip()
        if any(k in title for k in NEWS_KEYWORDS):
            st = (it.get("showTime") or "")[5:16]
            items.append((st, title))
    return items[:limit]

# ---------------- 报告生成 ----------------
def fmt_pct(p):
    sign = "+" if p > 0 else ""
    return f"{sign}{p:.2f}%"

def fmt_amount(v):
    if v >= 1e8:
        return f"{v/1e8:.2f}亿元"
    if v >= 1e4:
        return f"{v/1e4:.0f}万元"
    return f"{v:.0f}元"

def analyze_reason(domestic_pct, news_titles):
    """基于涨跌方向 + 新闻标题，生成框架性分析"""
    lines = []
    if domestic_pct is not None:
        if domestic_pct > 0:
            lines.append(
                f"1. **日内走势**：今日国内现货金价日内上涨{domestic_pct:+.2f}%，"
                f"通常与美元指数走弱、美债收益率下行、避险需求升温或央行购金支撑等因素相关。"
            )
        elif domestic_pct < 0:
            lines.append(
                f"1. **日内走势**：今日国内现货金价日内下跌{domestic_pct:+.2f}%，"
                f"通常与美元走强、美债收益率上行、前期涨幅获利回吐或加息预期升温等因素相关。"
            )
        else:
            lines.append("1. **日内走势**：今日国内金价窄幅震荡，多空力量均衡，等待关键数据指引方向。")
    
    counter = {}
    for t in news_titles:
        title = t[1]
        for k in NEWS_KEYWORDS:
            if k in title:
                counter[k] = counter.get(k, 0) + 1
    if counter:
        hot = sorted(counter.items(), key=lambda x: -x[1])[:4]
        hot_str = "、".join(f"“{k}”" for k, _ in hot)
        lines.append(f"2. **消息面热点**：当日快讯中较活跃关键词为 {hot_str}，反映市场关注焦点所在。")
    
    if news_titles:
        lines.append("3. **当日相关快讯**（节选）：")
        for st, t in news_titles[:5]:
            lines.append(f"   - [{st}] {t[:90]}")
    else:
        lines.append("2. **消息面**：当日未抓取到足够相关快讯，可留意宏观数据与央行表态。")
    return lines

def event_calendar(today):
    """近期关注事件日历（规则性节点）"""
    day = today.day
    events = []
    if day <= 6:
        events.append("美国非农就业数据通常在每月首个周五公布，是判断美联储政策路径的核心指标")
    if 8 <= day <= 15:
        events.append("美国 CPI/PPI 通胀数据通常在每月中旬公布，直接影响金价短期走势")
    if day >= 20:
        events.append("美国 PCE 通胀数据通常在每月末公布，为美联储更关注的通胀口径")
    if today.month == 8 and day >= 20:
        events.append("8月下旬为全球央行杰克逊霍尔年会窗口，央行官员讲话是重要变盘因素")
    return events

def build_report():
    today = date.today()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # ---- 1. 主金价数据（tmini） ----
    tmini = fetch_tmini_gold()
    spot_domestic = None
    spot_9999 = None
    spot_td = None
    spot_london = None
    domestic_pct = None
    
    if tmini:
        if "今日金价" in tmini:
            spot_domestic = parse_tmini_spot(tmini["今日金价"])
            domestic_pct = spot_domestic["pct"] if spot_domestic else None
        if "黄金_9999" in tmini:
            spot_9999 = parse_tmini_spot(tmini["黄金_9999"])
        if "黄金_T+D" in tmini:
            spot_td = parse_tmini_spot(tmini["黄金_T+D"])
        if "伦敦金(现货黄金)" in tmini:
            spot_london = parse_tmini_spot(tmini["伦敦金(现货黄金)"])
    
    # ---- 2. ETF 数据 ----
    tenc = fetch_tencent_quotes([c for c, _ in ETF_LIST])
    etfs = []
    for code, name in ETF_LIST:
        f = tenc.get(code.upper())
        if f:
            d = parse_etf(f)
            if d:
                d["name"] = name
                d["code"] = code[2:]
                etfs.append(d)
    
    # ---- 3. 快讯 ----
    news = fetch_gold_news()
    
    # ---- 组装报告 ----
    out = []
    out.append("# 国内黄金与黄金基金每日行情")
    out.append(f"**数据时间：{now}（价格为当日最新行情，非收盘结算）**")
    out.append("")
    
    # 一、黄金现货与延期行情
    out.append("## 一、黄金现货与延期行情")
    out.append("")
    out.append("| 品种 | 最新价 | 日内涨跌 | 涨跌幅 | 今日最高 | 今日最低 | 单位 |")
    out.append("|:--|:--:|:--:|:--:|:--:|:--:|:--:|")
    
    def add_row(name, data):
        if not data:
            return
        out.append(
            f"| {name} | {data['last']:.2f} | {data['chg']:+.2f} "
            f"| **{fmt_pct(data['pct'])}** | {data['high']:.2f} | {data['low']:.2f} | {data['unit']} |"
        )
    
    add_row("国内现货金价", spot_domestic)
    add_row("上海金 Au99.99", spot_9999)
    add_row("黄金 T+D（延期）", spot_td)
    add_row("伦敦金（现货）", spot_london)
    out.append("")
    
    if not tmini:
        out.append("> ⚠️ 主行情接口暂时无法获取，请稍后重试。")
        out.append("")
    
    # 二、黄金ETF表现
    out.append("## 二、主要黄金ETF表现")
    out.append("")
    if etfs:
        out.append("| 基金 | 代码 | 最新价 | 涨跌 | 涨跌幅 | 成交额 |")
        out.append("|:--|:--:|:--:|:--:|:--:|:--:|")
        for e in etfs:
            out.append(
                f"| {e['name']} | {e['code']} | {e['last']:.3f} | {e['chg']:+.3f} "
                f"| **{fmt_pct(e['pct'])}** | {fmt_amount(e['amount'])} |"
            )
    else:
        out.append("> ℹ️ ETF行情数据暂不可用，接口调整中。")
    out.append("")
    
    # 三、涨跌原因分析
    out.append("## 三、涨跌原因分析（参考）")
    reasons = analyze_reason(domestic_pct, news)
    out.extend(reasons)
    out.append("")
    
    # 四、近期关注事件
    out.append("## 四、近期关注事件")
    events = event_calendar(today)
    if events:
        for i, ev in enumerate(events, 1):
            out.append(f"{i}. {ev}")
    else:
        out.append("1. 关注后续美国通胀/就业数据及美联储官员讲话对金价方向的指引。")
    out.append("")
    
    out.append("---")
    out.append("*数据来源：tmini.net、腾讯财经、东方财富等公开接口。本报告为行情整理与框架性参考，不构成投资建议。*")
    return "\n".join(out)

# ---------------- 多渠道通知 ----------------
def qinglong_notify(title, content):
    """青龙面板原生通知推送"""
    try:
        candidates = []
        ql_dir = os.environ.get("QL_DIR") or os.environ.get("QL_ROOT") or ""
        if ql_dir:
            candidates.append(os.path.join(ql_dir, "scripts"))
        candidates += ["/ql/scripts", "/ql/repo", os.getcwd()]
        for p in candidates:
            if p and os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)
        from sendNotify import send
        send(title, content)
        print("[Notify] 已推送青龙通知")
        return True
    except Exception:
        return False

def _post_json(url, payload, timeout=12):
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data,
                  headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception:
        return ""

def _post_form(url, data_dict, timeout=12):
    data = urlencode(data_dict).encode("utf-8")
    req = Request(url, data=data, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception:
        return ""

def notify_serverchan(title, content):
    key = os.environ.get("SERVERCHAN_SENDKEY") or os.environ.get("SCKEY")
    if not key:
        return False
    _post_form(f"https://sctapi.ftqq.com/{key}.send",
               {"title": title, "desp": content})
    return True

def notify_pushplus(title, content):
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        return False
    _post_json("http://www.pushplus.plus/send",
               {"token": token, "title": title, "content": content,
                "template": "markdown"})
    return True

def notify_wecom(title, content):
    webhook = os.environ.get("WECOM_WEBHOOK")
    if not webhook:
        return False
    _post_json(webhook, {"msgtype": "markdown",
                         "markdown": {"content": f"### {title}\n{content}"}})
    return True

def notify_dingtalk(title, content):
    webhook = os.environ.get("DINGTALK_WEBHOOK")
    if not webhook:
        return False
    secret = os.environ.get("DINGTALK_SECRET")
    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(secret.encode("utf-8"),
                             string_to_sign.encode("utf-8"),
                             digestmod=hashlib.sha256).digest()
        sign = quote(base64.b64encode(hmac_code))
        webhook = f"{webhook}&timestamp={timestamp}&sign={sign}"
    payload = {"msgtype": "markdown",
               "markdown": {"title": title,
                            "text": f"### {title}\n{content}"}}
    resp = _post_json(webhook, payload)
    try:
        r = json.loads(resp)
        if r.get("errcode") == 0:
            return True
        print(f"[Notify][钉钉失败] errcode={r.get('errcode')} errmsg={r.get('errmsg')}")
        return False
    except Exception:
        return False

def notify_bark(title, content):
    base = os.environ.get("BARK_URL")
    if not base:
        return False
    url = f"{base.rstrip('/')}/{quote(title)}"
    _post_form(url, {"body": content})
    return True

def send_notifications(title, content):
    channels = [
        ("Server酱", notify_serverchan),
        ("PushPlus", notify_pushplus),
        ("企业微信", notify_wecom),
        ("钉钉", notify_dingtalk),
        ("Bark", notify_bark),
        ("青龙面板", qinglong_notify),
    ]
    sent = []
    for name, fn in channels:
        try:
            if fn(title, content):
                sent.append(name)
        except Exception:
            pass
    if sent:
        print("[Notify] 已推送通知渠道: " + ", ".join(sent))
    return sent

# ---------------- 主入口 ----------------
def main():
    report = build_report()
    print(report)
    
    # 可选：写入同目录文件
    try:
        path = sys.argv[1] if len(sys.argv) > 1 else "黄金基金每日行情.txt"
        with open(path, "w", encoding="utf-8") as fp:
            fp.write(report)
    except Exception:
        pass
    
    # 多渠道消息通知
    try:
        send_notifications(
            "国内黄金与黄金基金每日行情 " + datetime.now().strftime("%Y-%m-%d"),
            report)
    except Exception:
        pass

if __name__ == "__main__":
    main()
