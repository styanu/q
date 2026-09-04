# 当前脚本来自于 http://script.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cc 脚本库下载！
# 脚本库官方QQ群1群: 429274456
# 脚本库官方QQ群2群: 1077801222
# 脚本库官方QQ群3群: 433030897
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。

"""
必应积分助手（国内版）—— 青龙优化版
====================================
作者: By_cyt
版本: v1.3.0（2026-09-01）

v1.3.0 更新内容：
  1. 多账号支持：环境变量 by 用换行或 # 分隔，自动遍历所有账号
  2. 账号名称显示：从必应首页提取登录账号名，日志首行显示
  3. 多账号日志格式：第一个账号带"总共X账号"前缀，后续账号不带，账号之间空行分隔
  4. 已完成活动自动跳过：每日搜索/每日集/每日问答检测到已完成时，显示当前进度并跳过
  5. 每日搜索默认 15 次（环境变量 BING_SEARCH_TIMES 可调整，上限 20）
  6. 搜索词库扩充为 165 个正常人类搜索词（生活/科技/娱乐/学习/购物/热点）
  7. Quiz 日志优化：题目+正确答案分行显示，已完成自动检测
  8. 每日集 URL 提取修复：修复 \u0022 Unicode 转义未解码导致 URL 损坏的 bug
  9. 日志格式统一：标题行无时间戳，内容行带 [YYYY-MM-DD HH:MM:SS] 时间戳
  10. 标题行等号对齐：三个标题行总宽度一致（每日集短1字，每边多加1个等号）
  11. 正文行缩进1个空格

功能：
  1. 每日搜索（默认 15 次/天，国内版最多 15 点 = 前 5 次有积分）
  2. 每日集活动（自动提取活动 URL，访问页面 + 调用 reportActivity API 触发积分）
  3. 每日问答 Quiz（自动提取正确答案，调用 quiz/record API 判分，逐题完成）
  4. 积分状态查询（容错，rewards.bing.com 不通时跳过）
  5. 多账号批量执行

已验证（2026-08-31 ~ 2026-09-01 抓包实测）：
  - 搜索接口：GET /search?q=<词>&form=QBRE 可正常触发积分（必须带 form=QBRE）
  - 每日集活动：POST /rewardsapp/reportActivity 触发积分有效，
    积分到账有延迟（约 30-60 秒），本版已做最终等待
  - Cookie 含 _U 和 _RwBf 字段即可正常工作
  - 每日集 URL 必须正确解码 \u0022 为 %22，否则活动无法完成

不支持（需真实浏览器）：
  - Edge 浏览 30 分钟/天（需真实 Edge 浏览器保持活动）
  - 拼图任务（需页面拖拽交互）
  - 等级专属福利（带锁，需等级达标）

环境变量：
  by         【必填】登录必应后的完整 Cookie（从 cn.bing.com 抓取，浏览器F12→Application→Cookies 复制全部，多账号用换行或 # 分隔）
  BING_DELAY        搜索/活动间隔秒数，格式 "3-8"（默认 "3-8"）
  BING_SEARCH_TIMES 每日搜索次数，默认 15（国内版前 5 次有积分，上限 20）
  BING_WAIT_SECONDS 最终积分查询前等待秒数，默认 60（等积分延迟到账）

依赖：requests
cron: 20 8 * * *
new Env('必应积分助手_国内版_青龙优化版')
"""
import os
import re
import time
import random
import requests
from urllib.parse import unquote_plus

# ============== 配置 ============
BASE = "https://cn.bing.com"
REWARDS_PANEL = "https://cn.bing.com/rewards/panelflyout?channel=bingflyout&partnerId=BingRewards"
REWARDS_API = "https://rewards.bing.com/api/getuserinfo?type=1"

PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0")
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36")

# 正常人类搜索词库（分类随机，避免一言 API 的奇怪句子）
NORMAL_SEARCH_TERMS = [
    # ========= 生活日常 =======
    "今天天气", "天气预报", "附近美食推荐", "家常菜做法", "早餐吃什么",
    "晚餐食谱", "减肥餐", "快递查询", "火车票", "机票价格",
    "附近酒店", "超市营业时间", "药店", "医院挂号", "公交路线",
    "地铁线路", "打车优惠", "外卖优惠券", "家政服务", "搬家公司",
    "水电缴费", "燃气费查询", "物业费", "停车位", "洗车",
    "汽车保养", "违章查询", "驾照换证", "身份证办理", "社保查询",
    "公积金", "个税计算", "银行利率", "理财产品", "保险推荐",
    # ========= 科技数码 =======
    "最新手机推荐", "笔记本电脑排行", "科技新闻", "AI工具", "Python教程",
    "软件下载", "电脑技巧", "WiFi设置", "路由器推荐", "固态硬盘",
    "机械键盘", "鼠标推荐", "显示器推荐", "显卡排行", "CPU对比",
    "主板推荐", "电源推荐", "机箱推荐", "散热器", "耳机推荐",
    "音箱推荐", "智能手表", "手环推荐", "平板推荐", "电子书阅读器",
    "投影仪", "扫地机器人", "空气净化器", "加湿器", "电动牙刷",
    # ========= 娱乐休闲 =======
    "电影推荐", "电视剧排行", "音乐排行榜", "游戏攻略", "小说推荐",
    "旅游攻略", "景点推荐", "拍照技巧", "综艺推荐", "演唱会门票",
    "话剧演出", "展览推荐", "博物馆", "动物园", "游乐园",
    "滑雪场", "温泉", "民宿推荐", "露营装备", "钓鱼技巧",
    "宠物饲养", "花卉养殖", "手工DIY", "绘画教程", "书法入门",
    "吉他教程", "钢琴入门", "舞蹈教学", "健身计划", "瑜伽入门",
    # ========= 学习提升 =======
    "英语学习", "考研资料", "公务员考试", "在线课程", "学习方法",
    "知识问答", "读书笔记", "考证", "雅思", "托福",
    "四六级", "教师资格证", "会计证", "心理咨询师", "健康管理师",
    "编程入门", "数据分析", "设计教程", "办公软件技巧", "PPT模板",
    "Excel技巧", "Word教程", "简历模板", "面试技巧", "职场沟通",
    # ========= 购物消费 =======
    "淘宝热销", "京东比价", "优惠券", "打折", "性价比推荐",
    "商品评价", "品牌对比", "拼多多", "双十一", "618",
    "年货节", "双十二", "会员日", "秒杀", "团购",
    "海淘", "代购", "奢侈品", "二手交易", "闲鱼",
    "转转", "得物", "小红书种草", "什么值得买", "慢慢买",
    # ========= 热点资讯 =======
    "今日新闻", "热点事件", "热搜榜", "微博热搜", "知乎热榜",
    "抖音热点", "B站热门", "头条新闻", "澎湃新闻", "36氪",
    "虎嗅", "知乎日报", "少数派", "差评", "酷安",
    "IT之家", "快科技", "太平洋电脑网", "中关村在线", "汽车之家",
]

used_terms = set()


# ============== 工具 ============
def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def log_title(msg):
    print(f"\n{msg}", flush=True)


def parse_cookie(s):
    c = {}
    for part in s.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            c[k.strip()] = v.strip()
    return c


def get_search_term():
    """生成正常人类搜索词，随机词库 + 随机修饰，去重"""
    for _ in range(30):
        base = random.choice(NORMAL_SEARCH_TERMS)
        modifier = random.choice(["", "", "", "", "2026", "最新", "推荐", "攻略",
                                   "大全", "哪个好", "怎么样", "2026年", "排行"])
        term = f"{base} {modifier}".strip() if modifier else base
        if term not in used_terms and 0 < len(term) <= 30:
            return term
    return f"{random.choice(NORMAL_SEARCH_TERMS)} {int(time.time()) % 1000}"


def make_session(cookie_str):
    session = requests.Session()
    session.cookies.update(parse_cookie(cookie_str))
    return session


def get_headers(ua, referer=None):
    h = {
        "User-Agent": ua,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        h["Referer"] = referer
    return h


def get_username(session):
    """从必应首页获取账号名称"""
    try:
        r = session.get("https://cn.bing.com/", headers=get_headers(PC_UA), timeout=10)
        m = re.search(r'id="id_n"[^>]*>([^<]+)<', r.text)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return None


# ============== 核心功能 ============
def do_search(session, term, ua=PC_UA):
    """执行一次搜索（必须带 form=QBRE 才会计入每日搜索积分）"""
    try:
        r = session.get(f"{BASE}/search", params={"q": term, "form": "QBRE"},
                        headers=get_headers(ua, f"{BASE}/"), timeout=15)
        return r.status_code == 200
    except Exception as e:
        log(f"  搜索异常: {e}")
        return False


def extract_daily_set_activities(html):
    """从 Rewards 面板 JSON 提取每日集活动 URL（不依赖字段顺序）"""
    activities = []
    # 提取所有 destinationUrl，过滤出每日集活动（含 rnoreward/DailySet/ML2X/tgrew）
    urls = re.findall(r'"destinationUrl"\s*:\s*"(https?://[^"]*bing\.com/search\?[^"]*)"', html)
    seen = set()
    for url in urls:
        url = url.replace("\\u0026", "&").replace("&amp;", "&").replace("\\u0022", "%22")
        if any(k in url for k in ["rnoreward", "DailySet", "ML2X9E", "ML2X9F", "tgrew4", "ML2G76"]):
            if url not in seen:
                seen.add(url)
                activities.append({"url": url, "complete": False})
    return activities


def get_daily_set_status(html):
    """获取每日集完成状态，如 '1/3'"""
    m = re.search(r'partner_dset_titleArg0"\s*:\s*"(\d+)"', html)
    m2 = re.search(r'partner_dset_titleArg1"\s*:\s*"(\d+)"', html)
    if m and m2:
        return int(m.group(1)), int(m2.group(1))
    # 备用：从文本匹配
    m = re.search(r'每日集\((\d+)/(\d+)\s*活动\)', html)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def get_daily_search_status(html):
    """获取每日搜索积分状态，返回 (已赚, 上限)"""
    # 面板里用 pointProgress/pointProgressMax 表示进度，每日搜索上限是 15
    for m in re.finditer(r'"pointProgressMax"\s*:\s*15\s*,\s*"pointProgress"\s*:\s*(\d+)', html):
        return int(m.group(1)), 15
    for m in re.finditer(r'"pointProgress"\s*:\s*(\d+)\s*,\s*"pointProgressMax"\s*:\s*15', html):
        return int(m.group(1)), 15
    return None, None


def extract_ig_iid(html):
    """从搜索页面 HTML 提取 IG 和 IID"""
    ig = ""
    iid = "SERP.5057"
    m = re.search(r'IG["\s:=]+([A-Fa-f0-9]{32})', html)
    if m:
        ig = m.group(1)
    m = re.search(r'IID["\s:=]+(SERP\.\d+)', html)
    if m:
        iid = m.group(1)
    return ig, iid


def extract_quiz_total(html):
    """从Quiz页面提取总题数"""
    for m in re.finditer(r'(\d+)\s*/\s*(\d+)', html):
        cur, tot = int(m.group(1)), int(m.group(2))
        if tot in (3, 5, 7, 10) and 1 <= cur <= tot:
            return tot
    return None


def get_quiz_panel_status(html, quiz_url):
    """从面板提取指定Quiz的完成状态，返回 (已完成布尔值, 总积分)"""
    q_match = re.search(r'[?&]q=([^&]+)', quiz_url)
    if not q_match:
        return None, None
    q_text = q_match.group(1)
    for m in re.finditer(r'destinationUrl"\s*:\s*"([^"]*)"', html, re.I):
        if q_text in m.group(1):
            start = max(0, m.start() - 2000)
            end = min(len(html), m.end() + 300)
            block = html[start:end]
            prog = re.search(r'"pointProgress"\s*:\s*(\d+)', block)
            pmax = re.search(r'"pointProgressMax"\s*:\s*(\d+)', block)
            if prog and pmax:
                return int(prog.group(1)) >= int(pmax.group(1)), int(pmax.group(1))
    return None, None


def report_activity(session, activity_url, page_html, ig, iid):
    """调用 reportActivity API 触发积分"""
    from urllib.parse import urlparse, parse_qs, urlencode
    parsed = urlparse(activity_url.replace("www.bing.com", "cn.bing.com"))
    params = parse_qs(parsed.query)
    report_params = {
        "IG": ig,
        "IID": iid,
        "q": params.get("q", [""])[0],
    }
    for k in ["form", "FORM", "OCID", "PUBL", "CREA", "filters"]:
        if k in params:
            report_params[k] = params[k][0]
    report_params["rnoreward"] = "1"
    report_params["ajaxreq"] = "1"

    report_url = "https://cn.bing.com/rewardsapp/reportActivity?" + urlencode(report_params)
    try:
        r = session.post(report_url, headers={
            "User-Agent": PC_UA,
            "Referer": activity_url.replace("www.bing.com", "cn.bing.com"),
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def complete_daily_set(session, delay_min, delay_max):
    """完成每日集活动"""
    log_title("======== 每日集 ========")
    try:
        r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
        if r.status_code != 200:
            log(f"  面板访问失败: {r.status_code}")
            return 0
    except Exception as e:
        log(f"  面板访问异常: {e}")
        return 0

    done, total = get_daily_set_status(r.text)
    if done is not None:
        log(f" 当前进度: {done}/{total}")
        if done >= total:
            log(" ✅ 每日集已全部完成")
            return total

    activities = extract_daily_set_activities(r.text)
    log(f"  提取到 {len(activities)} 个活动")

    # 只处理未完成的
    pending = [a for a in activities if not a["complete"]]
    log(f"  未完成: {len(pending)} 个")

    for i, act in enumerate(pending):
        url = act["url"]
        log(f"  活动[{i+1}]: {url[:60]}...")
        try:
            # 1. 访问活动页面
            r = session.get(url, headers=get_headers(PC_UA, REWARDS_PANEL), timeout=15)
            if r.status_code != 200:
                log(f"    ❌ 页面 status={r.status_code}")
                continue
            # 2. 提取 IG/IID
            ig, iid = extract_ig_iid(r.text)
            log(f"    IG={ig[:8]}... IID={iid}")
            # 3. 调用 reportActivity 触发积分
            ok = report_activity(session, url, r.text, ig, iid)
            log(f"    {'✅ 积分已触发' if ok else '❌ 积分触发失败'}")
        except Exception as e:
            log(f"    ❌ 异常: {e}")
        time.sleep(random.randint(delay_min, delay_max))

    # 重新查状态
    try:
        r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
        done2, total2 = get_daily_set_status(r.text)
        if done2 is not None:
            log(f"  最终进度: {done2}/{total2}")
            return done2
    except Exception:
        pass
    return done or 0


def extract_quiz_from_html(html):
    """从页面 HTML 提取 quiz 问题和选项，返回 (question, options, user_id)"""
    # 提取选项：支持单引号和双引号属性
    opt_pattern = (r'''class=["'][^"']*btq_opt[^"']*["'][\s\S]*?'''
                   r'''href=["']([^"']+)["'][\s\S]*?'''
                   r'''acf-button-standard__label["'][^>]*>([^<]+)</div>''')
    options = []
    for m in re.finditer(opt_pattern, html):
        href = m.group(1).replace("&amp;", "&")
        text = m.group(2).strip()
        q_match = re.search(r'[?&]q=([^&]+)', href)
        correct = unquote_plus(q_match[1]) if q_match else ""
        options.append({"text": text, "href": href, "correct": correct})

    if not options:
        return None, None, ""

    # 提取问题文本（btq_opts 之前的最后一段文本）
    question = ""
    q_match = re.search(r'([^<>]{10,200})</div>\s*</div>\s*<div class=["\']btq_opts', html)
    if q_match:
        question = q_match.group(1).strip()
    if not question:
        # 备用：找 btq_title 之后的文本
        q_match = re.search(r'btq_title["\'][^>]*>([\s\S]{0,300})', html)
        if q_match:
            t = re.sub(r'<[^>]+>', '', q_match.group(1)).strip()
            question = t[:100]

    # 提取 UserId
    uid_match = re.search(r'"UserId"\s*:\s*"([^"]+)"', html)
    user_id = uid_match.group(1) if uid_match else ""

    return question, options, user_id


def complete_quiz(session, quiz_url, delay_min, delay_max):
    """完成一个 Quiz 的所有题目（自动提取正确答案）"""
    quiz_url = quiz_url.replace("www.bing.com", "cn.bing.com")
    current_url = quiz_url
    completed = 0

    for round_num in range(10):  # 最多 10 题，防止死循环
        try:
            r = session.get(current_url, headers=get_headers(PC_UA), timeout=15)
            if r.status_code != 200:
                break

            question, options, user_id = extract_quiz_from_html(r.text)
            if not options:
                # 只有第一次访问就没题目时，才提示已完成
                if round_num == 0:
                    log_title("======= 每日问答 =======")
                    total_q = extract_quiz_total(r.text)
                    if total_q:
                        log(f" 当前进度: {total_q}/{total_q}")
                    log(" ✅ 每日问答已全部完成")
                return 0

            # 有题目，第一次输出标题
            if round_num == 0:
                log_title("======= 每日问答 =======")

            # 正确答案 = 所有选项的 q 参数（都一样）
            correct_answer = options[0]["correct"]
            # 找到显示文本匹配正确答案的选项
            correct_opt = None
            for opt in options:
                if correct_answer in opt["text"]:
                    correct_opt = opt
                    break
            if not correct_opt:
                # 兜底：选最后一个
                correct_opt = options[-1]

            log(f"  {round_num+1}. {question[:45]}")
            log(f"     正在查找正确答案→ {correct_opt['text']}")

            # 1. POST quiz/record 记录答案
            try:
                record_body = {
                    "PartnerId": "BingQAUX",
                    "QuestionText": question,
                    "OptionText": correct_opt["text"],
                    "UserId": user_id,
                }
                session.post("https://www.bing.com/funapi/api/quiz/record?ajaxreq=1",
                             json=record_body,
                             headers={
                                 "User-Agent": PC_UA,
                                 "Content-Type": "application/json",
                                 "Referer": current_url,
                                 "X-Requested-With": "XMLHttpRequest",
                             }, timeout=10)
            except Exception as e:
                log(f"    quiz/record 异常: {e}")

            # 2. 提取 IG/IID，调用 reportActivity 触发积分
            ig, iid = extract_ig_iid(r.text)
            opt_full_url = correct_opt["href"]
            if opt_full_url.startswith("/"):
                opt_full_url = "https://cn.bing.com" + opt_full_url
            report_activity(session, opt_full_url, r.text, ig, iid)

            completed += 1

            # 3. 访问正确选项链接，获取下一题
            current_url = opt_full_url
            time.sleep(random.randint(delay_min, delay_max))

        except Exception as e:
            log(f"  第{round_num+1}题异常: {e}")
            break

    if completed > 0:
        log(f"  🎉 全部答完（共 {completed} 题）")
    return completed


def extract_quiz_urls(html):
    """从 Rewards 面板提取所有 Quiz URL（排除每日集活动）"""
    urls = []
    for m in re.finditer(r'"destinationUrl"\s*:\s*"(https?://[^"]*bing\.com/search\?[^"]*)"', html, re.I):
        url = m.group(1).replace("\\u0026", "&")
        low = url.lower()
        # 只取 quiz / quote 类型，排除每日集（含 DailySet）
        if ("quiz" in low or "quote" in low) and "dailyset" not in low and "rnoreward" not in low:
            if url not in urls:
                urls.append(url)
    return urls


def check_points(session):
    """查询积分（容错，rewards.bing.com 不通时从 cn.bing.com 面板提取）"""
    # 方式1：rewards.bing.com API（国际版，国内服务器可能不通）
    try:
        r = session.get(REWARDS_API, timeout=8, headers={
            "Accept": "application/json",
            "Referer": "https://rewards.bing.com/",
            "User-Agent": PC_UA,
        })
        if r.status_code == 200:
            data = r.json()
            pts = data.get("dashboard", {}).get("userStatus", {}).get("availablePoints", 0)
            if pts:
                return pts
    except Exception:
        pass
    # 方式2：从 cn.bing.com 面板 HTML 提取（国内服务器可通）
    try:
        r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=8)
        if r.status_code == 200:
            for pat in [r'"availablePoints"\s*:\s*(\d+)',
                        r'"Balance"\s*:\s*(\d+)',
                        r'(\d{1,3}(?:,\d{3})+)\s*<']:
                m = re.search(pat, r.text)
                if m:
                    return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


# ============== 主流程 ============
def main():
    print("作者By-cyt")
    cookie_str = os.getenv("by", "").strip()
    if not cookie_str:
        log("❌ 未设置环境变量 by")
        return

    # 支持多账号，用换行或 # 分隔
    cookies = [c.strip() for c in re.split(r'[\n#]', cookie_str) if c.strip()]
    total_accounts = len(cookies)

    delay_cfg = os.getenv("BING_DELAY", "3-8")
    try:
        d_min, d_max = map(int, delay_cfg.split("-"))
        if d_min > d_max:
            d_min, d_max = d_max, d_min
    except Exception:
        d_min, d_max = 3, 8

    # 每日搜索次数（国内版每天最多 15 点 = 5 次搜索有积分，可通过环境变量调整）
    try:
        search_times = int(os.getenv("BING_SEARCH_TIMES", "15"))
        search_times = max(1, min(search_times, 20))
    except Exception:
        search_times = 15

    # 最终积分查询前等待秒数（等积分延迟到账）
    try:
        wait_sec = int(os.getenv("BING_WAIT_SECONDS", "60"))
        wait_sec = max(0, min(wait_sec, 300))
    except Exception:
        wait_sec = 60

    for acc_idx, cookie in enumerate(cookies, 1):
        session = make_session(cookie)
        used_terms = set()

        # 账号名称和积分（第一行不用时间戳，第一个账号带总共X账号前缀）
        username = get_username(session)
        pts = check_points(session)
        if acc_idx == 1:
            line = f"总共{total_accounts}账号,第{acc_idx}个账号: {username}" if username else f"总共{total_accounts}账号,第{acc_idx}个账号:"
        else:
            line = f"第{acc_idx}个账号: {username}" if username else f"第{acc_idx}个账号:"
        if pts is not None:
            line += f"  💰 当前积分: {pts}"
        else:
            line += "  💰 积分查询失败"
        print(line)

        # 1. 每日搜索（先检查是否已搜满，已满则显示进度并跳过）
        search_done = False
        s_earned, s_limit = None, None
        try:
            r_panel = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
            s_earned, s_limit = get_daily_search_status(r_panel.text)
            if s_earned is not None and s_limit is not None and s_earned >= s_limit:
                search_done = True
        except Exception:
            pass

        if search_done:
            log_title("======= 每日搜索 =======")
            log(f" 当前进度: {s_earned}/{s_limit}")
            log(" ✅ 每日搜索已全部完成")
        else:
            log_title(f"===== 每日搜索（{search_times} 次） =====")
            for i in range(search_times):
                term = get_search_term()
                used_terms.add(term)
                ok = do_search(session, term)
                log(f"  搜索[{i+1}/{search_times}] '{term[:25]}': {'✅' if ok else '❌'}")
                if i < search_times - 1:
                    time.sleep(random.randint(d_min, d_max))

        # 2. 每日集活动
        complete_daily_set(session, d_min, d_max)

        # 3. 问答 Quiz（自动答题，已完成则显示进度并跳过）
        try:
            r = session.get(REWARDS_PANEL, headers=get_headers(PC_UA), timeout=15)
            quiz_urls = extract_quiz_urls(r.text)
            for qurl in quiz_urls:
                done, _ = get_quiz_panel_status(r.text, qurl)
                if done:
                    log_title("======= 每日问答 =======")
                    # 从Quiz页面提取总题数
                    total_q = None
                    try:
                        rq = session.get(qurl.replace("www.bing.com", "cn.bing.com"),
                                         headers=get_headers(PC_UA), timeout=10)
                        total_q = extract_quiz_total(rq.text)
                    except Exception:
                        pass
                    if total_q:
                        log(f" 当前进度: {total_q}/{total_q}")
                    log(" ✅ 每日问答已全部完成")
                    continue
                complete_quiz(session, qurl, d_min, d_max)
                time.sleep(random.randint(d_min, d_max))
        except Exception:
            pass

        # 等积分延迟到账后再统计
        if wait_sec > 0:
            log(f"⏳ 等待 {wait_sec} 秒让积分到账...")
            time.sleep(wait_sec)

        # 最终积分（不带时间戳）
        pts2 = check_points(session)
        if pts is not None and pts2 is not None:
            print(f"✅任务已全部完成！积分: {pts} → {pts2} (+{pts2 - pts})")
        elif pts2 is not None:
            print(f"✅任务已全部完成！当前积分: {pts2}")
        else:
            print("✅任务已全部完成（积分查询不可用）")

        # 账号之间加空行分隔
        if acc_idx < total_accounts:
            print()


if __name__ == "__main__":
    main()


# 当前脚本来自于 http://script.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cn 脚本库下载！
# 当前脚本来自于 http://2.345yun.cc 脚本库下载！
# 脚本库官方QQ群1群: 429274456
# 脚本库官方QQ群2群: 1077801222
# 脚本库官方QQ群3群: 433030897
# 脚本库中的所有脚本文件均来自热心网友上传和互联网收集。
# 脚本库仅提供文件上传和下载服务，不提供脚本文件的审核。
# 您在使用脚本库下载的脚本时自行检查判断风险。
# 所涉及到的 账号安全、数据泄露、设备故障、软件违规封禁、财产损失等问题及法律风险，与脚本库无关！均由开发者、上传者、使用者自行承担。