# -*- coding: utf-8 -*-
"""
====================================================================
必应积分助手 · 真实 Edge 自动化版（Playwright / Windows）
--------------------------------------------------------------------
原理：调用你电脑自带的“真实 Microsoft Edge”打开页面、执行网页 JS、
     真实搜索并点进结果、真人化滚动与停留，从而被必应正常计分
     （requests / curl_cffi 只拿 HTML、不跑 JS，所以不加分）。

登录：首次运行会弹出 Edge，手动登录一次微软账号（勾选“保持登录”），
     登录态保存在脚本目录的 edge_profile 文件夹，以后自动复用，无需再抓 Cookie。

依赖：只依赖 playwright（钉钉用系统标准库发送，不需要 requests）
     安装：pip install playwright
     （用系统自带 Edge，无需执行 playwright install）

定时：用 Windows“任务计划程序”每天跑一次即可（见同目录部署说明）。
====================================================================
"""
import os
import re
import sys
import time
import random
import hmac
import hashlib
import base64
import json
import traceback
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, quote_plus
from urllib import request as urlrequest

# Windows 任务计划重定向日志时，强制 UTF-8 输出，避免 emoji/中文触发编码崩溃
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ==================== 配置区（直接改这里；也支持同名环境变量覆盖）====================
def CFG(name, default):
    v = os.getenv(name)
    return v if v not in (None, "") else default

def CFG_BOOL(name, default=False):
    return str(CFG(name, str(default)).strip().lower()) in ("1", "true", "yes", "on")

# ---- 钉钉推送（可选，留空 webhook 则不推送）----
DINGTALK_WEBHOOK = CFG("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = CFG("DINGTALK_SECRET", "")
DINGTALK_AT_ALL = CFG_BOOL("DINGTALK_AT_ALL", False)
ONLY_NOTIFY_ON_ERROR = CFG_BOOL("ONLY_NOTIFY_ON_ERROR", False)  # True=仅失败才推

# ---- 刷分参数 ----
SEARCH_PC_TIMES = int(CFG("BING_PC_TIMES", "6"))        # 电脑搜索次数（拿满每日电脑分即可，6 次稳妥）
SEARCH_MOBILE_TIMES = int(CFG("BING_MOBILE_TIMES", "6"))  # 手机搜索次数（设备模拟；不需要设 0）
DO_DAILY_SET = CFG_BOOL("BING_DAILYSET", True)         # 是否做“每日集”（DYNAMIC_TASKS=True 时被统一动态抓取覆盖）
DO_QUIZ = CFG_BOOL("BING_QUIZ", True)                  # 是否做“每日问答/测验”（同上）
DYNAMIC_TASKS = CFG_BOOL("BING_DYNAMIC_TASKS", True)   # 自动抓取面板“所有未完成任务”并完成（无需维护q.txt，每日集每天自动更新）
MIN_DELAY = int(CFG("BING_MIN_DELAY", "6"))            # 每次操作之间最小间隔秒
MAX_DELAY = int(CFG("BING_MAX_DELAY", "14"))           # 最大间隔秒（拉开间隔更像真人）
POST_WAIT = int(CFG("BING_POST_WAIT", "45"))           # 全部做完等积分到账秒数

# ---- 浏览器 ----
HEADLESS = CFG_BOOL("BING_HEADLESS", False)  # 首次登录必须 False；以后想完全后台可改 True
PROFILE_DIR = CFG("BING_PROFILE_DIR", "")    # 留空=脚本目录下 edge_profile（登录态目录）
COOKIE_BY = CFG("by", "")                    # 可选：额外注入完整 Cookie 作为补充，一般留空即可
URL_FILE = CFG("BING_URL_FILE", "")          # 自定义任务链接文件，默认脚本同目录 q.txt（每行一个网址）

# ==================== 常量 ====================
BASE = "https://cn.bing.com"
PANEL = "https://cn.bing.com/rewards/panelflyout?channel=bingflyout&partnerId=BingRewards"
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 EdgA/128.0.0.0")
ANTI_ARGS = ["--disable-blink-features=AutomationControlled", "--no-first-run",
             "--no-default-browser-check"]
HIDE_WEBDRIVER = ("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                  "window.chrome={runtime:{}};")

SEARCH_TERMS = [
    "今天天气", "天气预报", "附近美食推荐", "家常菜做法", "早餐吃什么", "晚餐食谱",
    "减肥餐", "快递查询", "火车票", "机票价格", "附近酒店", "超市营业时间",
    "药店", "医院挂号", "公交路线", "地铁线路", "打车优惠", "外卖优惠券",
    "汽车保养", "违章查询", "社保查询", "公积金", "银行利率", "理财产品",
    "最新手机推荐", "笔记本电脑排行", "科技新闻", "AI工具", "Python教程",
    "电脑技巧", "路由器推荐", "固态硬盘", "机械键盘", "显示器推荐", "显卡排行",
    "智能手表", "平板推荐", "扫地机器人", "空气净化器", "电动牙刷", "电影推荐",
    "电视剧排行", "音乐排行榜", "游戏攻略", "旅游攻略", "景点推荐", "拍照技巧",
    "博物馆", "温泉", "民宿推荐", "露营装备", "钓鱼技巧", "宠物饲养", "健身计划",
    "瑜伽入门", "英语学习", "学习方法", "读书笔记", "雅思", "四六级", "办公软件技巧",
    "Excel技巧", "简历模板", "面试技巧", "职场沟通", "优惠券", "性价比推荐",
    "品牌对比", "小红书种草", "什么值得买", "今日新闻", "热点事件", "知乎热榜",
    "头条新闻", "IT之家", "快科技", "汽车之家", "心理健康", "睡眠改善",
]

# ==================== 基础工具 ====================
def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)

def rand_sleep(a=None, b=None):
    time.sleep(random.randint(a or MIN_DELAY, b or MAX_DELAY))

def pick_terms(n):
    pool = SEARCH_TERMS[:]
    random.shuffle(pool)
    terms, used = [], set()
    for t in pool:
        if len(terms) >= n:
            break
        if t not in used:
            used.add(t)
            # 偶尔加个自然修饰
            if random.random() < 0.3:
                t = f"{t} {random.choice(['推荐', '怎么', '攻略', '2026', '哪个好'])}"
            terms.append(t[:30])
    while len(terms) < n:
        terms.append(f"{random.choice(SEARCH_TERMS)} {random.randint(1, 999)}")
    return terms

# ==================== 钉钉推送（标准库实现，无额外依赖）====================
def ding_signed_url(webhook, secret):
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                      hashlib.sha256).digest()
    sign = quote_plus(base64.b64encode(digest))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign}"

def send_dingtalk(title, text):
    if not DINGTALK_WEBHOOK:
        return "未配置 DINGTALK_WEBHOOK，跳过推送"
    url = ding_signed_url(DINGTALK_WEBHOOK, DINGTALK_SECRET)
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"isAtAll": DINGTALK_AT_ALL},
    }
    try:
        req = urlrequest.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
        with urlrequest.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("errcode") == 0:
            return "钉钉推送成功"
        return f"钉钉返回异常: {data}"
    except Exception as e:
        return f"钉钉推送异常: {e}"

def build_report(r):
    ok = r["ok"]
    title = f"必应积分(真实Edge)：{'成功' if ok else '存在失败'}"
    L = ["### 必应积分执行报告（真实 Edge）",
         f"> 时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
         f"> 账号：{r.get('name') or '未知'}", ""]
    L.append(f"- 电脑搜索：{r['pc_ok']}/{r['pc_total']} 次")
    if r["mob_total"]:
        L.append(f"- 手机搜索：{r['mob_ok']}/{r['mob_total']} 次")
    L.append(f"- 每日集：处理 {r['set_done']} 个")
    L.append(f"- 问答测验：{r['quiz_groups']} 组 / 答题 {r['quiz_answered']} 题")
    if r.get("dyn_total"):
        L.append(f"- 动态任务(面板自动抓取)：完成 {r['dyn_ok']}/{r['dyn_total']}")
    if r.get("url_total"):
        L.append(f"- 任务链接(q.txt)：打开 {r['url_ok']}/{r['url_total']}")
    p0, p1 = r.get("pts0"), r.get("pts1")
    if p0 is not None and p1 is not None:
        L.append(f"- 积分：{p0} → {p1}（{'+' if p1 - p0 >= 0 else ''}{p1 - p0}）")
    elif p1 is not None:
        L.append(f"- 当前积分：{p1}")
    L.append(f"- 耗时：{r['cost_sec']} 秒")
    if r["errors"]:
        L.append("")
        L.append("**异常：**")
        for e in r["errors"][:5]:
            L.append(f"- {e}")
    if DINGTALK_AT_ALL:
        L.append("\n@所有人")
    return title, "\n".join(L)

# ==================== 面板解析 ====================
def panel_text(ctx):
    resp = ctx.request.get(PANEL, timeout=15000)
    if resp.ok:
        return resp.text()
    return ""

def get_points(html):
    for pat in [r'"availablePoints"\s*:\s*(\d+)', r'"balance"\s*:\s*(\d+)',
                r'(\d{1,3}(?:,\d{3})+)\s*<']:
        m = re.search(pat, html or "", re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    return None

def get_account_name(page):
    try:
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(1500)
        m = re.search(r'id="id_n"[^>]*>([^<]+)<', page.content())
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None

def extract_urls(html, kind):
    """从面板提取 destinationUrl。kind: 'daily' 或 'quiz'"""
    raw = re.findall(r'"destinationUrl"\s*:\s*"(https?://[^"]+)"', html or "", re.I)
    out, seen = [], set()
    for u in raw:
        u = u.replace("\\u0026", "&").replace("&amp;", "&").replace("\\u002f", "/")
        low = u.lower()
        if kind == "daily":
            hit = any(k in low for k in ["rnoreward", "dailyset", "ml2x", "tgrew", "dailyset"])
            hit = hit and "quiz" not in low
        else:
            hit = ("quiz" in low or "quote" in low or "trivia" in low) and "dailyset" not in low
        if hit and u not in seen:
            seen.add(u)
            out.append(u)
    return out

def load_task_urls():
    """读取 q.txt：每行一个网址，忽略空行和 # 注释，自动去重。
    优先 BING_URL_FILE，其次脚本同目录 q.txt，再次当前目录 q.txt。"""
    cands = []
    if URL_FILE:
        cands.append(URL_FILE)
    cands.append(str(Path(__file__).resolve().parent / "q.txt"))
    cands.append("q.txt")
    fp = next((p for p in cands if p and Path(p).is_file()), None)
    if not fp:
        return []
    out, seen = [], set()
    for line in Path(fp).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.lower().startswith("http") and line not in seen:
            seen.add(line)
            out.append(line)
    return out

# ---------- 面板“所有未完成任务”动态解析（按 JSON 对象归属，避免关键词漏掉新任务）----------
def _decode_json_str(s):
    return (s.replace(r"\/", "/").replace("\\u0026", "&").replace("\\u002f", "/")
             .replace("&amp;", "&").replace("\\u0022", '"'))

def _obj_span(text, anchor):
    """从 destinationUrl 位置向前定位所属对象起点 {，再字符串感知地配平到结尾 }"""
    depth = 0
    start = -1
    for i in range(anchor - 1, -1, -1):
        c = text[i]
        if c == '}':
            depth += 1
        elif c == '{':
            if depth == 0:
                start = i
                break
            depth -= 1
    if start < 0:
        return -1, -1
    depth = 0
    in_str = esc = False
    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return start, j
    return start, -1

def _task_is_done(block):
    if re.search(r'"(?:isComplete|complete|completed)"\s*:\s*true', block, re.I):
        return True
    mm = re.search(r'"pointProgressMax"\s*:\s*(\d+)', block)
    m = re.search(r'"pointProgress"\s*:\s*(\d+)', block)
    if mm and m and int(mm.group(1)) > 0 and int(m.group(1)) >= int(mm.group(1)):
        return True
    am = re.search(r'"activityProgressMax"\s*:\s*(\d+)', block)
    a = re.search(r'"activityProgress"\s*:\s*(\d+)', block)
    if am and a and int(am.group(1)) > 0 and int(a.group(1)) >= int(am.group(1)):
        return True
    if re.search(r'"status"\s*:\s*"(?:complete|completed|done)"', block, re.I):
        return True
    return False

def _task_kind(url):
    u = url.lower()
    if any(k in u for k in ["quiz", "puzzle", "quote", "trivia", "thisorthat"]):
        return "quiz"
    if "explore.microsoft" in u:
        return "explore"
    if "/search" in u:
        return "search"
    return "page"

def extract_all_tasks(html, include_done=False):
    """解析面板里全部任务，默认只返回未完成任务。每项 {url,done,kind,title}"""
    tasks, seen = [], set()
    for m in re.finditer(r'"destinationUrl"\s*:\s*"((?:[^"\\]|\\.)*)"', html or "", re.I):
        raw = m.group(1).replace(r"\/", "/").replace("\\u0026", "&").replace("\\u002f", "/").replace("&amp;", "&")
        if not raw.lower().startswith("http"):
            continue
        s, e = _obj_span(html, m.start())
        block = html[s:e + 1] if s >= 0 and e > s else html[max(0, m.start() - 1200):m.end() + 300]
        done = _task_is_done(block)
        if done and not include_done:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        title = ""
        tm = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', block)
        if tm:
            tt = tm.group(1).replace(r"\/", "/")
            if tt and not tt.lower().startswith("partner_") and len(tt) < 40:
                title = tt
        if not title:
            qm = re.search(r'[?&]q=([^&]+)', raw)
            if qm:
                from urllib.parse import unquote_plus
                title = unquote_plus(qm.group(1))[:24]
        tasks.append({"url": raw, "done": done, "kind": _task_kind(raw), "title": title})
    return tasks

# ==================== 真实浏览器动作 ====================
def human_search(ctx, term):
    """新开标签页真实搜索 -> 滚动 -> 点进第一条结果 -> 停留 -> 关闭"""
    page = ctx.new_page()
    try:
        page.goto(f"{BASE}/search?q={quote(term)}&form=QBLH",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(random.randint(1200, 2600))
        try:
            page.mouse.wheel(0, 420)
            page.wait_for_timeout(700)
            page.mouse.wheel(0, 520)
            page.wait_for_timeout(600)
        except Exception:
            pass
        for sel in ["li.b_algo h2 a", "#b_results li h2 a", "h2 a[href^='http']", "a[href^='http']"]:
            el = page.query_selector(sel)
            if el:
                try:
                    el.scroll_into_view_if_needed(timeout=2000)
                    el.click(timeout=2500)
                    page.wait_for_timeout(random.randint(3000, 6000))  # 在落地页停留（点结果有助于计分）
                    break
                except Exception:
                    continue
        return True
    except Exception as e:
        log(f"  搜索 '{term}' 异常: {str(e)[:100]}")
        return False
    finally:
        try:
            page.close()
        except Exception:
            pass

def answer_quiz_page(page, max_q=10):
    """在一个测验页里逐题作答（兼容经典问答/此或彼/周猜的常见选择器，失败不报错）"""
    answered = 0
    for _ in range(max_q):
        page.wait_for_timeout(1500)
        opts = []
        for sel in [".btq_opts a", "div.btq_opt a", "[class*='btq_opt'] a",
                    "#rqansContainer .rqOption", "#rqInputContainer label",
                    ".wk_options a", "ul.btq_opts li"]:
            try:
                opts = [o for o in page.query_selector_all(sel) if o.is_visible()]
            except Exception:
                opts = []
            if opts:
                break
        if not opts:
            break
        try:
            opts[0].scroll_into_view_if_needed(timeout=1500)
            opts[0].click(timeout=2000)
            answered += 1
        except Exception:
            pass
        page.wait_for_timeout(1500)
        # 点错后必应会标出正确项，再点正确项
        for csel in [".btq_opts a.correct", "[class*='option'][class*='correct']",
                     "a[aria-checked='true']", ".rqOption.correct", "li.selected > a",
                     ".btq_opts .correct"]:
            c = page.query_selector(csel)
            try:
                if c and c.is_visible():
                    c.click(timeout=1500)
                    break
            except Exception:
                pass
        page.wait_for_timeout(1200)
        # 进入下一题
        for nsel in ["input.rqbtn", "#rqbtn", "a:has-text('Next')", "button:has-text('Next')",
                     "a:has-text('下一题')", "button:has-text('继续')", ".btq_next",
                     "input[value*='Next']"]:
            nxt = page.query_selector(nsel)
            try:
                if nxt and nxt.is_visible():
                    nxt.click(timeout=1500)
                    break
            except Exception:
                pass
    return answered

def open_and_complete(ctx, url, is_quiz):
    page = ctx.new_page()
    try:
        page.goto(url.replace("www.bing.com", "cn.bing.com"),
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1800)
        try:
            page.mouse.wheel(0, 500)
        except Exception:
            pass
        n = answer_quiz_page(page) if is_quiz else 0
        page.wait_for_timeout(random.randint(3000, 6000))  # 让页面 JS 完成上报
        return True, n
    except Exception as e:
        return False, 0
    finally:
        try:
            page.close()
        except Exception:
            pass

# ==================== 主流程 ====================
def run():
    started = time.time()
    result = {"name": None, "pc_total": SEARCH_PC_TIMES, "pc_ok": 0,
              "mob_total": SEARCH_MOBILE_TIMES, "mob_ok": 0,
              "set_done": 0, "quiz_groups": 0, "quiz_answered": 0,
              "dyn_total": 0, "dyn_ok": 0,
              "url_total": 0, "url_ok": 0,
              "pts0": None, "pts1": None, "errors": [], "ok": True, "cost_sec": 0}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("缺少 playwright，请先在命令行执行：pip install playwright")

    udd = Path(PROFILE_DIR) if PROFILE_DIR else (Path(__file__).resolve().parent / "edge_profile")
    udd.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        log("启动真实 Microsoft Edge ...")
        ctx = p.chromium.launch_persistent_context(
            str(udd), channel="msedge", headless=HEADLESS,
            no_viewport=not HEADLESS,
            viewport=None if not HEADLESS else {"width": 1280, "height": 860},
            locale="zh-CN", timezone_id="Asia/Shanghai", args=ANTI_ARGS,
            ignore_default_args=["--enable-automation"])
        ctx.add_init_script(HIDE_WEBDRIVER)
        if COOKIE_BY:
            try:
                ck = []
                for part in COOKIE_BY.split(";"):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        ck.append({"name": k.strip(), "value": v.strip(),
                                   "domain": ".bing.com", "path": "/"})
                ctx.add_cookies(ck)
                log("已补充注入 by Cookie")
            except Exception as e:
                result["errors"].append(f"Cookie注入失败: {e}")

        try:
            home = ctx.pages[0] if ctx.pages else ctx.new_page()

            # 1) 等待/确认登录（首次会给 120 秒手动登录）
            log("检查登录状态 ...")
            pts = None
            for i in range(40):
                try:
                    pts = get_points(panel_text(ctx))
                except Exception:
                    pts = None
                if pts is not None:
                    break
                if i == 0:
                    log("未检测到登录：请在弹出的 Edge 窗口登录微软账号（勾选保持登录），最多等待 120 秒 ...")
                time.sleep(3)
            if pts is None:
                raise RuntimeError("等待登录超时：未能在 120 秒内检测到登录态")
            result["pts0"] = pts
            result["name"] = get_account_name(home)
            log(f"登录正常，账号={result['name'] or '未知'}，当前积分={pts}")

            # 2) 电脑搜索
            if SEARCH_PC_TIMES > 0:
                log(f"===== 电脑搜索 {SEARCH_PC_TIMES} 次 =====")
                for i, term in enumerate(pick_terms(SEARCH_PC_TIMES), 1):
                    ok = human_search(ctx, term)
                    result["pc_ok"] += 1 if ok else 0
                    if not ok:
                        result["errors"].append(f"电脑搜索第{i}次失败")
                    log(f"  电脑搜索[{i}/{SEARCH_PC_TIMES}] '{term}' {'✅' if ok else '❌'}")
                    if i < SEARCH_PC_TIMES:
                        rand_sleep()

            # 3) 手机搜索（独立的移动设备模拟上下文，复用登录态）
            if SEARCH_MOBILE_TIMES > 0:
                log(f"===== 手机搜索 {SEARCH_MOBILE_TIMES} 次（设备模拟）=====")
                mb = None
                try:
                    state = ctx.storage_state()
                    mb = p.chromium.launch(channel="msedge", headless=HEADLESS, args=ANTI_ARGS,
                                          ignore_default_args=["--enable-automation"])
                    mctx = mb.new_context(
                        storage_state=state, is_mobile=True, device_scale_factor=2,
                        viewport={"width": 390, "height": 844}, user_agent=MOBILE_UA,
                        locale="zh-CN", timezone_id="Asia/Shanghai")
                    mctx.add_init_script(HIDE_WEBDRIVER)
                    for i, term in enumerate(pick_terms(SEARCH_MOBILE_TIMES), 1):
                        ok = human_search(mctx, term)
                        result["mob_ok"] += 1 if ok else 0
                        if not ok:
                            result["errors"].append(f"手机搜索第{i}次失败")
                        log(f"  手机搜索[{i}/{SEARCH_MOBILE_TIMES}] '{term}' {'✅' if ok else '❌'}")
                        if i < SEARCH_MOBILE_TIMES:
                            rand_sleep()
                    mctx.close()
                except Exception as e:
                    result["errors"].append(f"手机搜索整体失败: {str(e)[:120]}")
                    log(f"手机搜索失败(不影响电脑分): {e}")
                finally:
                    if mb:
                        try:
                            mb.close()
                        except Exception:
                            pass

            # 4) 动态抓取面板“所有未完成任务”并真实完成（每日集/问答/拼图/金句/额外任务全覆盖，每天自动更新、无需维护链接）
            if DYNAMIC_TASKS:
                log("===== 动态抓取面板未完成任务 =====")
                try:
                    tasks = extract_all_tasks(panel_text(ctx))
                    result["dyn_total"] = len(tasks)
                    log(f"  发现未完成任务 {len(tasks)} 个")
                    tag_map = {"quiz": "问答", "explore": "探索", "search": "任务", "page": "页面"}
                    for i, t in enumerate(tasks, 1):
                        ok, n = open_and_complete(ctx, t["url"], is_quiz=(t["kind"] == "quiz"))
                        result["dyn_ok"] += 1 if ok else 0
                        if t["kind"] == "quiz":
                            result["quiz_groups"] += 1 if ok else 0
                            result["quiz_answered"] += n
                        else:
                            result["set_done"] += 1 if ok else 0
                        if not ok:
                            result["errors"].append(f"任务[{t.get('title') or t['url'][:30]}]打开失败")
                        log(f"  [{i}/{len(tasks)}][{tag_map.get(t['kind'], t['kind'])}] "
                            f"{t.get('title') or t['url'][:40]} {'✅' if ok else '❌'}")
                        rand_sleep(3, 7)
                except Exception as e:
                    result["errors"].append(f"动态任务失败: {str(e)[:120]}")
            else:
                # 4a) 每日集（真实点开活动页，让 JS 自行上报）
                if DO_DAILY_SET:
                    log("===== 每日集 =====")
                    try:
                        urls = extract_urls(panel_text(ctx), "daily")
                        log(f"  发现每日集活动 {len(urls)} 个")
                        for i, u in enumerate(urls[:6], 1):
                            ok, _ = open_and_complete(ctx, u, is_quiz=("quiz" in u.lower()))
                            result["set_done"] += 1 if ok else 0
                            log(f"  每日集[{i}] {'✅' if ok else '❌'}")
                            rand_sleep(3, 7)
                    except Exception as e:
                        result["errors"].append(f"每日集失败: {str(e)[:120]}")

                # 4b) 每日问答/测验（真实点选作答）
                if DO_QUIZ:
                    log("===== 每日问答/测验 =====")
                    try:
                        urls = extract_urls(panel_text(ctx), "quiz")
                        log(f"  发现问答 {len(urls)} 组")
                        for i, u in enumerate(urls[:5], 1):
                            ok, n = open_and_complete(ctx, u, is_quiz=True)
                            result["quiz_groups"] += 1 if ok else 0
                            result["quiz_answered"] += n
                            log(f"  问答[{i}] 作答 {n} 题 {'✅' if ok else '❌'}")
                            rand_sleep(3, 7)
                    except Exception as e:
                        result["errors"].append(f"问答失败: {str(e)[:120]}")

            # 5.5) q.txt 自定义任务链接（用真实页面逐个打开，测验类自动作答）
            try:
                turls = load_task_urls()
                result["url_total"] = len(turls)
                if turls:
                    log(f"===== q.txt 任务链接 {len(turls)} 个（真实打开）=====")
                    for i, u in enumerate(turls, 1):
                        low = u.lower()
                        is_quiz = any(k in low for k in ["quiz", "puzzle", "quote"])
                        okk, _ = open_and_complete(ctx, u, is_quiz=is_quiz)
                        result["url_ok"] += 1 if okk else 0
                        if not okk:
                            result["errors"].append(f"任务链接{i}打开失败")
                        log(f"  链接[{i}/{len(turls)}] {'✅' if okk else '❌'}")
                        rand_sleep(3, 7)
            except Exception as e:
                result["errors"].append(f"任务链接整体失败: {str(e)[:120]}")

            # 6) 等积分到账并复查
            log(f"等待 {POST_WAIT} 秒让积分到账 ...")
            time.sleep(POST_WAIT)
            result["pts1"] = get_points(panel_text(ctx))
            log(f"积分：{result['pts0']} → {result['pts1']}")

        except Exception as e:
            result["ok"] = False
            result["errors"].append(f"主流程异常: {str(e)[:150]}")
            log(f"主流程异常: {e}")
            traceback.print_exc()
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    result["cost_sec"] = int(time.time() - started)
    # 判定整体成功：搜索至少有成功、积分有增长（若读到）、无异常
    if result["pc_ok"] == 0 and result["mob_ok"] == 0:
        result["ok"] = False
    if result["errors"]:
        result["ok"] = False
    if result["pts0"] is not None and result["pts1"] is not None and result["pts1"] < result["pts0"]:
        result["ok"] = False
    return result

def main():
    log("======== 必应积分 · 真实 Edge 版开始 ========")
    try:
        r = run()
    except Exception as e:
        r = {"name": None, "pc_total": 0, "pc_ok": 0, "mob_total": 0, "mob_ok": 0,
             "set_done": 0, "quiz_groups": 0, "quiz_answered": 0,
             "pts0": None, "pts1": None, "errors": [f"启动失败: {e}"],
             "ok": False, "cost_sec": 0}
        traceback.print_exc()

    delta = (r["pts1"] - r["pts0"]) if (r["pts0"] is not None and r["pts1"] is not None) else None
    log("======== 执行结束 ========")
    log(f"电脑搜索 {r['pc_ok']}/{r['pc_total']}，手机搜索 {r['mob_ok']}/{r['mob_total']}，"
        f"每日集 {r['set_done']}，问答 {r['quiz_answered']} 题，"
        f"积分 {r['pts0']}→{r['pts1']}" + (f"（{'+' if (delta or 0) >= 0 else ''}{delta}）" if delta is not None else ""))
    log("整体结果：" + ("成功 ✅" if r["ok"] else "存在失败 ❌"))

    title, text = build_report(r)
    if ONLY_NOTIFY_ON_ERROR and r["ok"]:
        log("仅失败推送模式，本次成功，跳过钉钉")
    else:
        log(send_dingtalk(title, text))

    sys.exit(0 if r["ok"] else 1)

if __name__ == "__main__":
    main()
