# -*- coding: utf-8 -*-
"""
必应积分 - curl_cffi 浏览器指纹最小验证脚本
作用：只做 3 次搜索（伪装真实浏览器指纹 + 点进结果 + 拟人间隔），对比前后积分，
     用来判断“requests 裸刷不加分”到底是请求指纹问题，还是账号被风控。

运行前：
  1. 安装依赖（面板 Python 环境 / 终端均可）：pip install curl_cffi
  2. 复用你已配置的环境变量 by（完整 Cookie），无需改动
  3. 直接运行本脚本，看结尾“积分变化”和“结论”

结果解读：
  - 积分增加        -> 浏览器指纹方案有效，可据此把整套脚本重构为 curl_cffi 版
  - 积分没变        -> 再用电脑 Edge 手动搜 1 次对照：
                       · 手动也不涨 = 账号被风控/市场不对（脚本无解，先养号）
                       · 手动能涨   = 指纹仍不够，需要 Playwright 驱动真实浏览器
"""
import os
import re
import time
import random

try:
    from curl_cffi import requests as creq
except ImportError:
    raise SystemExit("缺少依赖 curl_cffi，请先安装：pip install curl_cffi")

BASE = "https://cn.bing.com"
PANEL = "https://cn.bing.com/rewards/panelflyout?channel=bingflyout&partnerId=BingRewards"
# 不同 curl_cffi 版本支持的指纹名不同，按顺序挑第一个可用的（优先 Edge，部分积分绑定 Edge）
IMP_CANDIDATES = ["edge101", "edge99", "chrome124", "chrome120", "chrome116", "chrome"]
TEST_TERMS = ["天气预报", "家常菜做法", "附近美食推荐"]


def parse_cookie(s):
    c = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            c[k.strip()] = v.strip()
    return c


def make_session():
    last_err = None
    for imp in IMP_CANDIDATES:
        try:
            return creq.Session(impersonate=imp), imp
        except Exception as e:
            last_err = e
    raise SystemExit(f"curl_cffi 无可⽤浏览器指纹: {last_err}")


def get_points(s):
    """从国内版面板提取当前积分"""
    try:
        r = s.get(PANEL, timeout=12)
        for pat in [r'"availablePoints"\s*:\s*(\d+)', r'"Balance"\s*:\s*(\d+)']:
            m = re.search(pat, r.text)
            if m:
                return int(m.group(1))
    except Exception as e:
        print("查积分异常:", e)
    return None


def first_result_link(html):
    """提取搜索结果第一条链接（h2>a 或 bing /ck/a 跳转链接），用于模拟真人点进结果"""
    m = re.search(r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"', html)
    if m:
        return m.group(1).replace("&amp;", "&")
    m = re.search(r'href="(https?://[^"]*bing\.com/ck/a\?[^"]+)"', html)
    if m:
        return m.group(1).replace("&amp;", "&")
    return None


def main():
    cookie = os.getenv("by", "").strip()
    if not cookie:
        raise SystemExit("未读到环境变量 by（完整 Cookie）")

    s, imp = make_session()
    s.cookies.update(parse_cookie(cookie))
    print("使用浏览器指纹:", imp)

    p0 = get_points(s)
    print("搜索前积分:", p0)

    print("先访问必应首页建立会话 ...")
    try:
        s.get(BASE + "/", timeout=12)
    except Exception as e:
        print("首页访问异常(可忽略):", str(e)[:80])

    for i, term in enumerate(TEST_TERMS, 1):
        r = s.get(BASE + "/search", params={"q": term, "form": "QBLH"}, timeout=15)
        print(f"搜索[{i}/{len(TEST_TERMS)}] '{term}' HTTP {r.status_code}，页面 {len(r.text)} 字节")
        link = first_result_link(r.text)
        if link:
            try:
                cr = s.get(link, timeout=12)  # 模拟真人点进结果并停留（官方：点结果有助于计分）
                print(f"   点进第一条结果 HTTP {cr.status_code}")
            except Exception as e:
                print("   点结果异常(可忽略):", str(e)[:80])
        else:
            print("   未提取到结果链接，跳过点击")
        if i < len(TEST_TERMS):
            wait = random.randint(8, 15)
            print(f"   拟人等待 {wait} 秒 ...")
            time.sleep(wait)

    print("等待 30 秒让积分到账 ...")
    time.sleep(30)
    p1 = get_points(s)
    print("搜索后积分:", p1)

    if p0 is not None and p1 is not None:
        delta = p1 - p0
        print("积分变化:", f"+{delta}" if delta >= 0 else str(delta))
        if delta > 0:
            print("【结论】curl_cffi 指纹方案有效，积分有增加 -> 我可以据此把整套脚本重构成 curl_cffi 版。")
        else:
            print("【结论】换了浏览器指纹仍不涨。请用电脑 Edge 手动搜 1 次对照：")
            print("        - 手动也不涨：账号被风控/市场不符，先停自动化养号，脚本无解；")
            print("        - 手动能涨  ：需要 Playwright 驱动真实浏览器，我再给你对应方案。")
    else:
        print("【结论】没读到积分，请直接刷新 rewards 面板看“每日搜索”进度是否 +3。")


if __name__ == "__main__":
    main()
