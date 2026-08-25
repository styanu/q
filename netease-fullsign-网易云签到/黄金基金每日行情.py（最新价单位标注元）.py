#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国内黄金与黄金基金每日行情整理脚本
=====================================
适配：青龙面板 / 呆呆面板（内置 Python3，标准 Cron 调度）
依赖：仅 Python3 标准库（urllib / json / re），无需 pip 安装任何包
功能：
  1. 抓取国内黄金价格：沪金主连、上海金Au99.99、黄金T+D、伦敦金（参考）
  2. 抓取主要黄金ETF：518880/159934/159937/518800/159812 的最新价、涨跌幅、成交额
  3. 抓取当日黄金相关快讯，作为"消息面参考"
  4. 输出简洁专业的 Markdown 报告（stdout + 可选写文件 + 多渠道消息通知推送）

【消息通知配置（可选，配置任一即启用对应渠道）】
  在青龙面板/呆呆面板的环境变量（config 或设置）中配置以下变量：
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
    命令: task gold_report.py        （青龙 v2 标准命令）
    定时规则: 0 16 * * *
  运行后可在任务日志查看；若已配置青龙通知渠道（Server酱/钉钉/企业微信等），
  报告将自动推送。青龙环境变量按面板配置自动注入，无需额外设置。

【呆呆面板部署】
  脚本管理 -> 上传本文件 -> 定时任务 -> 命令填 gold_report.py -> 0 16 * * *

数据源（公开免费接口）：
  沪金/现货金：新浪财经 hq.sinajs.cn
  黄金ETF    ：腾讯财经 qt.gtimg.cn
  快讯       ：东方财富 7x24
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

# ---------------- HTTP 基础 ----------------

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

# ---------------- 行情抓取 ----------------

def fetch_sina_quotes(codes):
    """新浪行情接口：hq.sinajs.cn/list=code1,code2...
    返回 {code: [字段列表]}，编码为 GBK"""
    if not codes:
        return {}
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    text = http_get(url, referer="https://finance.sina.com.cn/", encoding="gbk")
    result = {}
    if not text:
        return result
    # 形如 var hq_str_nf_AU0="...";  (可能有 var hq_str_gds_AUTD=...)
    for m in re.finditer(r'var hq_str_([A-Za-z0-9_]+)="([^"]*)"', text):
        code = m.group(1).upper()
        fields = m.group(2).split(",")
        result[code] = fields
    return result

def fetch_tencent_quotes(codes):
    """腾讯行情接口：qt.gtimg.cn/q=code1,code2...
    返回 {code: [字段列表]}，编码为 GBK"""
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

def parse_gold_futures(fields):
    """解析新浪沪金主连 nf_AU0
    字段: [8]=最新价, [10]=昨结算, [14]=成交量(手)
    涨跌幅=(最新-昨结)/昨结"""
    try:
        last = float(fields[8])
        prev = float(fields[10])
        vol = int(float(fields[14])) if len(fields) > 14 and fields[14] else 0
        chg = last - prev
        pct = chg / prev * 100 if prev else 0.0
        return {"name": "沪金主连", "last": last, "prev": prev, "chg": chg,
                "pct": pct, "vol": vol}
    except Exception:
        return None

def parse_gold_spots(fields):
    """解析新浪上海金交所现货（Au99.99 / T+D）
    gds 字段: [0]=最新价, [4]=最高, [5]=最低, [6]=时间, [7]=昨收, [8]=今开, [9]=成交量
    涨跌幅不在此强求，避免口径误差（仅展示价格与区间）"""
    try:
        last = float(fields[0])
        high = float(fields[4]) if len(fields) > 4 and fields[4] else None
        low = float(fields[5]) if len(fields) > 5 and fields[5] else None
        return {"last": last, "high": high, "low": low}
    except Exception:
        return None

def parse_london_gold(fields):
    """解析新浪伦敦金 hf_XAU: [0]=最新价, [4]=最高, [5]=最低(口径以新浪为准)"""
    try:
        last = float(fields[0])
        high = float(fields[4]) if len(fields) > 4 and fields[4] else None
        low = float(fields[5]) if len(fields) > 5 and fields[5] else None
        return {"last": last, "high": high, "low": low}
    except Exception:
        return None

ETF_LIST = [
    ("sh518880", "华安黄金ETF"),
    ("sz159934", "易方达黄金ETF"),
    ("sz159937", "博时黄金ETF"),
    ("sh518800", "国泰黄金ETF"),
    ("sz159812", "前海开源黄金ETF"),
]

def parse_etf(fields):
    """解析腾讯 ETF 行情
    字段: [1]=名称, [3]=最新, [4]=昨收, [30]=时间, [31]=涨跌额, [32]=涨跌幅,
          [33]=最高, [34]=最低, [35]=价/量/额(手/元)"""
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

# ---------------- 快讯/新闻 ----------------

NEWS_KEYWORDS = ["黄金", "金价", "金条", "贵金属", "美联储", "美元指数",
                 "美债", "央行购金", "加息", "降息", "避险", "杰克逊霍尔",
                 "PCE", "CPI", "非农"]

def fetch_gold_news(limit=12):
    """抓取东方财富 7x24 快讯，筛选黄金/美联储相关，返回 [(时间, 标题)]"""
    params = urlencode({
        "client": "web", "biz": "web_724", "fastColumn": "102",
        "sortEnd": "", "pageSize": "60", "req_trace": "1",
    })
    url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList?" + params
    data = http_get_json(url)
    if not data or data.get("code") != "1":
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
    """格式化百分比"""
    sign = "+" if p > 0 else ""
    return f"{sign}{p:.2f}%"

def fmt_amount(v):
    """成交额格式化：元 -> 亿元/万元"""
    if v >= 1e8:
        return f"{v/1e8:.2f}亿元"
    if v >= 1e4:
        return f"{v/1e4:.0f}万元"
    return f"{v:.0f}元"

def analyze_reason(domestic_pct, news_titles):
    """基于当日涨跌方向 + 新闻标题，生成"涨跌原因参考"（框架性 + 消息面）"""
    lines = []
    if domestic_pct is not None:
        direction = "上涨" if domestic_pct > 0 else ("下跌" if domestic_pct < 0 else "持平")
        if domestic_pct > 0:
            lines.append(
                f"1. **上涨驱动**：今日国内金价收涨{domestic_pct:+.2f}%，通常与美元指数走弱、美债收益率下行（降低持有黄金机会成本）、避险需求升温或央行购金支撑等因素相关。"
            )
        elif domestic_pct < 0:
            lines.append(
                f"1. **下跌压力**：今日国内金价收跌{domestic_pct:+.2f}%，通常与美元走强、美债收益率上行、前期涨幅获利回吐或加息预期升温等因素相关。"
            )
        else:
            lines.append("1. **窄幅震荡**：今日国内金价基本持平，多空力量均衡，等待关键数据或事件指引方向。")
    # 新闻关键词出现频次，作为消息面佐证
    counter = {}
    for t in news_titles:
        title = t[1]
        for k in NEWS_KEYWORDS:
            if k in title:
                counter[k] = counter.get(k, 0) + 1
    if counter:
        hot = sorted(counter.items(), key=lambda x: -x[1])[:4]
        hot_str = "、".join(f"“{k}”" for k, _ in hot)
        lines.append(f"2. **消息面热点**：当日快讯中较活跃关键词为 {hot_str}，反映市场关注焦点所在，可结合下方快讯核实具体触发因素。")
    if news_titles:
        lines.append("3. **当日相关快讯**（节选）：")
        for st, t in news_titles[:5]:
            lines.append(f"   - [{st}] {t[:90]}")
    else:
        lines.append("2. **消息面**：当日未抓取到足够相关快讯，可留意宏观数据与央行表态。")
    return lines

def event_calendar(today):
    """近期关注事件：基于固定规则（每月/每周固定节点）+ 每年固定会议时点。
    只输出"事件类别 + 大致时点"，不写未经确认的具体日期。"""
    day = today.day
    wd = today.weekday()  # 0=周一
    events = []
    # 每月固定数据节点（规则性表述）
    if day <= 6:
        events.append("美国非农就业数据通常在每月首个周五公布，关注就业数据对美联储政策预期的指引")
    if 8 <= day <= 15:
        events.append("美国 CPI/PPI 通胀数据通常在每月中旬公布，是判断加息/降息路径的关键指标")
    if day >= 20:
        events.append("美国 PCE 通胀数据通常在每月末公布，为美联储更关注的通胀口径，将影响金价短期方向")
    # 8月下旬杰克逊霍尔央行年会（年度固定时点）
    if today.month == 8 and day >= 20:
        events.append("8月下旬为全球央行杰克逊霍尔年会窗口，各国央行官员讲话是短期金价的重要变盘因素")
    return events

def build_report():
    today = date.today()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---- 抓数据 ----
    sina = fetch_sina_quotes(["nf_AU0", "gds_AU9999", "gds_AUTD", "hf_XAU"])
    tenc = fetch_tencent_quotes([c for c, _ in ETF_LIST])
    news = fetch_gold_news()

    fut = parse_gold_futures(sina.get("NF_AU0")) if sina.get("NF_AU0") else None
    au9999 = parse_gold_spots(sina.get("GDS_AU9999")) if sina.get("GDS_AU9999") else None
    autd = parse_gold_spots(sina.get("GDS_AUTD")) if sina.get("GDS_AUTD") else None
    xau = parse_london_gold(sina.get("HF_XAU")) if sina.get("HF_XAU") else None

    etfs = []
    for code, name in ETF_LIST:
        f = tenc.get(code.upper())
        if f:
            d = parse_etf(f)
            if d:
                d["name"] = name
                d["code"] = code[2:]
                etfs.append(d)

    # ---- 组装报告 ----
    out = []
    out.append("# 国内黄金与黄金基金每日行情")
    out.append(f"**数据时间：{now}（以当日收盘/最新价为准）**")
    out.append("")

    # 一、行情表现
    out.append("## 一、行情表现")
    if etfs:
        out.append("**主要黄金ETF表现**")
        out.append("")
        out.append("| 基金 | 代码 | 最新价（元） | 涨跌 | 涨跌幅 | 成交额 |")
        out.append("|:--|:--:|:--:|:--:|:--:|:--:|")
        for e in etfs:
            out.append(
                f"| {e['name']} | {e['code']} | {e['last']:.3f} | {e['chg']:+.3f} "
                f"| **{fmt_pct(e['pct'])}** | {fmt_amount(e['amount'])} |"
            )
        out.append("")
    else:
        out.append("（行情数据抓取失败，请检查网络或稍后重试）")
        out.append("")

    # 二、涨跌原因分析
    out.append("## 二、涨跌原因分析（参考）")
    dom_pct = fut["pct"] if fut else None
    reasons = analyze_reason(dom_pct, news)
    out.extend(reasons)
    out.append("")

    # 三、近期关注事件
    out.append("## 三、近期关注事件")
    events = event_calendar(today)
    if events:
        for i, ev in enumerate(events, 1):
            out.append(f"{i}. {ev}")
    else:
        out.append("1. 关注后续美国通胀/就业数据及美联储官员讲话对金价方向的指引。")
    out.append("")
    out.append("---")
    out.append("*数据来源：新浪财经、腾讯财经、东方财富等公开接口。本报告为行情整理与框架性参考，不构成投资建议。*")

    return "\n".join(out)

def qinglong_notify(title, content):
    """青龙面板通知推送（可选）：
    若运行在青龙环境且已配置通知渠道，则推送报告；否则静默跳过。
    兼容青龙 v2/v3：优先从面板目录导入 sendNotify。"""
    try:
        # 青龙面板常见路径探测
        candidates = []
        ql_dir = os.environ.get("QL_DIR") or os.environ.get("QL_ROOT") or ""
        if ql_dir:
            candidates.append(os.path.join(ql_dir, "scripts"))
        candidates += ["/ql/scripts", "/ql/repo", os.getcwd()]
        for p in candidates:
            if p and os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)
        from sendNotify import send  # noqa
        # 推送标题加时间，正文保留报告
        send(title, content)
        print("[Notify] 已推送青龙通知")
        return True
    except Exception as e:
        # 非青龙环境或未配置通知：正常跳过，不影响输出
        return False

def _post_json(url, payload, timeout=12):
    """POST JSON 请求，返回响应文本"""
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data,
                  headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception:
        return ""

def _post_form(url, data_dict, timeout=12):
    """POST 表单请求，返回响应文本"""
    data = urlencode(data_dict).encode("utf-8")
    req = Request(url, data=data, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception:
        return ""

def notify_serverchan(title, content):
    """Server酱（方糖）推送"""
    key = os.environ.get("SERVERCHAN_SENDKEY") or os.environ.get("SCKEY")
    if not key:
        return False
    _post_form(f"https://sctapi.ftqq.com/{key}.send",
               {"title": title, "desp": content})
    return True

def notify_pushplus(title, content):
    """PushPlus 推送"""
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        return False
    _post_json("http://www.pushplus.plus/send",
               {"token": token, "title": title, "content": content,
                "template": "markdown"})
    return True

def notify_wecom(title, content):
    """企业微信机器人推送"""
    webhook = os.environ.get("WECOM_WEBHOOK")
    if not webhook:
        return False
    _post_json(webhook, {"msgtype": "markdown",
                         "markdown": {"content": f"### {title}\n{content}"}})
    return True

def notify_dingtalk(title, content):
    """钉钉机器人推送（支持加签），并校验返回结果
    注意：钉钉自定义机器人的安全设置必须与配置一致，否则推送失败：
      - 加签：填入 DINGTALK_SECRET
      - 自定义关键词：消息需包含该关键词（本脚本标题含"每日行情"，可设关键词"行情"）
      - IP白名单：需将运行脚本服务器的公网IP加入白名单
    """
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
        # 失败：输出钉钉返回的具体原因，便于排查
        print(f"[Notify][钉钉失败] errcode={r.get('errcode')} errmsg={r.get('errmsg')}")
        if r.get("errcode") == 310000:
            print("[Notify][钉钉] 通常是机器人安全设置不匹配：请检查关键词/加签/IP白名单与脚本配置是否一致")
        return False
    except Exception:
        if resp:
            print(f"[Notify][钉钉响应异常] {resp[:200]}")
        else:
            print("[Notify][钉钉无响应] 请检查 DINGTALK_WEBHOOK 地址是否正确、服务器能否访问外网")
        return False

def notify_bark(title, content):
    """Bark（iOS）推送"""
    base = os.environ.get("BARK_URL")
    if not base:
        return False
    url = f"{base.rstrip('/')}/{quote(title)}"
    _post_form(url, {"body": content})
    return True

def send_notifications(title, content):
    """多渠道消息通知总入口：依次尝试已配置的渠道，失败自动忽略。"""
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
    # 多渠道消息通知（可选，未配置或失败自动忽略）
    try:
        send_notifications(
            "国内黄金与黄金基金每日行情 " + datetime.now().strftime("%Y-%m-%d"),
            report)
    except Exception:
        pass

if __name__ == "__main__":
    main()
