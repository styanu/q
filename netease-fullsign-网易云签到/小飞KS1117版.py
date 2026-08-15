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

＃已经很完美了。不要乱改了
＃已开源 
import os
import json
import base64
import random
import time
import re
import sys
from urllib import parse as querystring
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import threading
# 全局打印锁，解决多线程日志错乱
print_lock = threading.Lock()
# 全局会话复用，减少连接开销
_global_session = requests.Session()
# ===================== 1. 全局常量配置 =====================
DNS_SERVERS = ["114.114.114.114", "223.5.5.5", "8.8.8.8"]
SIGN_API = {
    "KUAISHOU": "http://103.24.218.196:6162",
    "NEBULA": "http://103.24.218.196:6161"
}
# 抽离硬编码常量，不改动原逻辑
_CONST = {
    "MIN_WATCH_SLEEP_MS": 2000,
    "WATCH_OFFSET_MS": 15000,
    "SIGN_RETRY": 2,
    "AD_FETCH_RETRY": 3,
    "PROXY_CHECK_RETRY": 2
}
# ===================== 2. 环境变量读取工具 =====================
def get_env(key, default=None):
    val = os.getenv(key, "")
    return val.strip() if val else default
def get_env_int(key, default):
    try:
        return int(get_env(key, str(default)))
    except (ValueError, TypeError):
        return default
def get_env_float(key, default):
    try:
        return float(get_env(key, str(default)))
    except (ValueError, TypeError):
        return default
# ===================== 3. 任务配置解析 =====================
TASK_NAME_MAP = {"box": "宝箱广告", "look": "看广告得金币", "search": "搜索广告"}
VALID_TASK_KEYS = ["box", "look", "search"]
def parse_task_list():
    task_env = get_env("KS_TASKS", "")
    if not task_env:
        return {"list": VALID_TASK_KEYS.copy(), "names": "、".join([TASK_NAME_MAP[t] for t in VALID_TASK_KEYS])}
    input_tasks = [t.strip().lower() for t in task_env.split(",") if t.strip()]
    input_tasks = [t for t in input_tasks if t in VALID_TASK_KEYS]
    if not input_tasks:
        return {"list": VALID_TASK_KEYS.copy(), "names": "、".join([TASK_NAME_MAP[t] for t in VALID_TASK_KEYS])}
    return {"list": input_tasks, "names": "、".join([TASK_NAME_MAP[t] for t in input_tasks])}
TASK_CONFIG = parse_task_list()
# ===================== 4. 功能总开关 =====================
FUNCTION_CONFIG = {
    "AD_CLICK_ENABLE": get_env("KS_AD_CLICK", "true") != "false",
    "RAISE_ACCOUNT_ENABLE": get_env("KS_RAISE_ENABLE", "true") != "false",
    "AUTO_CHANGE_DID_ENABLE": get_env("KS_AUTO_CHANGE_DID", "true") != "false",
    "LOW_COIN_CHANGE_DID_ENABLE": get_env("KS_LOW_COIN_CHANGE_DID", "true") != "false",
    "EXTRA_TASK_ENABLE": get_env("KS_EXTRA_TASK_ENABLE", "true") != "false",  # 突破2500上限总开关
}
# ===================== 5. 参数配置 =====================
LOW_COIN_CONFIG = {
    "THRESHOLD": get_env_int("KS_LOW_COIN_THRESHOLD", 5),
    "CONTINUOUS_LIMIT": get_env_int("KS_LOW_COIN_CONTINUOUS_LIMIT", 3),
}
AUTO_CHANGE_DID_CONFIG = {
    "MAX_CHANGE_COUNT": get_env_int("KS_DID_MAX_COUNT", 15),
    "CHANGE_DELAY_MIN": get_env_int("KS_DID_DELAY_MIN", 1000),
    "CHANGE_DELAY_MAX": get_env_int("KS_DID_DELAY_MAX", 3000),
}
GLOBAL_CONFIG = {
    "TOTAL_ROUNDS": get_env_int("KS_ROUNDS", 200),
    "CONCURRENCY": min(get_env_int("KS_CONCURRENCY", 10), 200),
    "LOW_REWARD_THRESHOLD": get_env_int("KS_LOW_REWARD", 10),
    "LOW_REWARD_LIMIT": get_env_int("KS_LOW_REWARD_LIMIT", 6),
    "AD_FAIL_LIMIT": get_env_int("KS_AD_FAIL_LIMIT", 8),
    "CONTINUOUS_1COIN_LIMIT": get_env_int("KS_1COIN_LIMIT", 10),
    "SCRIPT_VERSION": "小飞专享版",
    "MAX_KSCK_INDEX": get_env_int("KS_MAX_KSCK_INDEX", 666)
}
SimConfig = {
    "WATCH_MIN": get_env_int("KS_WATCH_MIN", 40),
    "WATCH_MAX": get_env_int("KS_WATCH_MAX", 55),
    "SWIPE_RATE": get_env_float("KS_SWIPE_RATE", 0.85),
    "AD_CLICK_RATE": get_env_float("KS_AD_CLICK_RATE", 0.7),
    "REST_INTERVAL": get_env_int("KS_REST_INTERVAL", 5),
    "REST_MIN": get_env_int("KS_REST_MIN", 3000),
    "REST_MAX": get_env_int("KS_REST_MAX", 8000),
    "AD_CLICK_STAY_MIN": get_env_int("KS_CLICK_STAY_MIN", 3000),
    "AD_CLICK_STAY_MAX": get_env_int("KS_CLICK_STAY_MAX", 8000),
    "AD_CLICK_BACK_RATE": get_env_float("KS_AD_CLICK_BACK_RATE", 0.95),
    "RAISE_LIKE_RATE": get_env_float("KS_RAISE_LIKE_RATE", 0.3),
    "RAISE_FOLLOW_RATE": get_env_float("KS_RAISE_FOLLOW_RATE", 0.05),
    "RAISE_COMMENT_READ_RATE": get_env_float("KS_RAISE_COMMENT_RATE", 0.2),
    "RAISE_VIDEO_WATCH_MIN": get_env_int("KS_RAISE_WATCH_MIN", 5000),
    "RAISE_VIDEO_WATCH_MAX": get_env_int("KS_RAISE_WATCH_MAX", 15000),
    "RAISE_SWIPE_COUNT_MIN": get_env_int("KS_RAISE_SWIPE_MIN", 2),
    "RAISE_SWIPE_COUNT_MAX": get_env_int("KS_RAISE_SWIPE_MAX", 5),
}
SEARCH_KEYWORDS = get_env("KS_SEARCH_KEYWORDS", "")
if SEARCH_KEYWORDS:
    SEARCH_CONFIG = {"KEYWORDS": [k.strip() for k in SEARCH_KEYWORDS.split(",") if k.strip()]}
else:
    SEARCH_CONFIG = {"KEYWORDS": ["短剧小说", "热门视频", "美食教程", "生活小技巧", "搞笑段子", "影视解说"]}
# ===================== 6. 全彩色兼容日志系统 =====================
class Log:
    RED = "\033[1;31m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[1;34m"
    MAGENTA = "\033[1;35m"
    CYAN = "\033[1;36m"
    WHITE = "\033[1;37m"
    END = "\033[0m"
    # Windows终端自动关闭彩色，避免乱码
    if sys.platform == "win32":
        RED = GREEN = YELLOW = BLUE = MAGENTA = CYAN = WHITE = END = ""
    @staticmethod
    def _print(color, text):
        with print_lock:
            print(f"{color}{text}{Log.END}", flush=True)
    @staticmethod
    def time():
        t = time.localtime()
        h = str(t.tm_hour).zfill(2)
        m = str(t.tm_min).zfill(2)
        s = str(t.tm_sec).zfill(2)
        return f"[{h}:{m}:{s}]"
    @staticmethod
    def line():
        return "----------------------------------------"
    @staticmethod
    def banner():
        print("", flush=True)
        Log._print(Log.YELLOW, Log.line())
        Log._print(Log.YELLOW, "=== ks双端 小飞专享版 ===")
        Log._print(Log.CYAN, "=== KS双端意外奖励加强版 ===")
        Log._print(Log.YELLOW, Log.line())
    @staticmethod
    def title(text):
        print("", flush=True)
        Log._print(Log.MAGENTA, f"===== {text} =====")
    @staticmethod
    def subTitle(text):
        Log._print(Log.CYAN, f">> {text}")
    @staticmethod
    def accountHeader(index, total, remark, platform):
        print("", flush=True)
        Log._print(Log.BLUE, Log.line())
        Log._print(Log.BLUE, f"账号 {index}/{total} | {remark}")
        Log._print(Log.BLUE, f"平台: {platform}")
        Log._print(Log.BLUE, Log.line())
    @staticmethod
    def progress(current, total):
        percent = int((current / total) * 100)
        return f"进度: {current}/{total} ({percent}%)"
    @staticmethod
    def info(text):
        Log._print(Log.BLUE, f"{Log.time()} [信息] {text}")
    @staticmethod
    def success(text):
        Log._print(Log.GREEN, f"{Log.time()} [成功] {text}")
    @staticmethod
    def reward(text):
        Log._print(Log.YELLOW, text)
    @staticmethod
    def warn(text):
        Log._print(Log.YELLOW, f"{Log.time()} [警告] {text}")
    @staticmethod
    def error(text):
        Log._print(Log.RED, f"{Log.time()} [错误] {text}")
    @staticmethod
    def accountStats(data):
        print("", flush=True)
        Log._print(Log.BLUE, Log.line())
        Log._print(Log.BLUE, f"执行完成 | {data['remark']}")
        Log._print(Log.BLUE, Log.line())
        status = "正常完成" if data['success'] else "执行异常"
        status_color = Log.GREEN if data['success'] else Log.RED
        Log._print(status_color, f"状态: {status}")
        Log._print(Log.YELLOW, f"本次收益: {data['totalReward']} 金币")
        Log._print(Log.WHITE, f"最终金币: {data['finalCoin']}")
        Log._print(Log.WHITE, f"耗时: {data['useTime']}")
        Log._print(Log.BLUE, Log.line())
    @staticmethod
    def summaryTable(results):
        Log.title("全账号执行汇总")
        total_reward = sum(r["totalReward"] for r in results)
        success_count = len([r for r in results if r["success"]])
        for res in results:
            color = Log.GREEN if res["success"] else Log.RED
            Log._print(color, f"{res['index']}. {res['remark']}  {res['totalReward']}金币")
        Log._print(Log.YELLOW, Log.line())
        Log._print(Log.WHITE, f"总账号: {len(results)} | 成功: {success_count}")
        Log._print(Log.YELLOW, f"总收益: {total_reward} 金币")
        Log._print(Log.YELLOW, Log.line())
        print("", flush=True)
    @staticmethod
    def format_time(ms):
        s = int(ms / 1000)
        m = int(s / 60)
        if m > 0:
            return f"{m}分{s % 60}秒"
        return f"{s}秒"
# ===================== 7. 广告解析模块（含翻倍+突破上限检测） =====================
class AdParser:
    invalid_texts = {"立即下载", "免费下载", "了解详情", "查看详情", "立即安装", "立即体验", "下载", "查看", "预约", "领取", "去看看", "了解更多"}
    @staticmethod
    def add_valid_content(content_set, content):
        if not isinstance(content, str):
            return
        clean = content.strip()
        if len(clean) < 2 or clean in AdParser.invalid_texts:
            return
        content_set.add(clean)
    @staticmethod
    def parse(ad_raw_data):
        default_ret = {
            "title": "无广告数据", "expectedCoin": 1, "creativeId": "", "llsid": "",
            "hasRewardEnd": False, "isMultiple": False, "multiple": 1, "baseCoin": 1, "hasExtraTask": False
        }
        if not ad_raw_data:
            return default_ret
        res = default_ret.copy()
        ad = ad_raw_data.get("ad", {})
        res["creativeId"] = ad.get("creativeId", "")
        exp_tag = ad_raw_data.get("exp_tag", "")
        if exp_tag:
            sp = exp_tag.split("/")
            if len(sp) >= 2:
                res["llsid"] = sp[1].split("_")[0]
        # 基础预计金币解析
        try:
            ext_data = json.loads(ad.get("extData", "{}"))
            res["expectedCoin"] = int(float(ext_data.get("awardCoin", 0)))
        except Exception:
            pass
        if res["expectedCoin"] == 0:
            inspire = ad.get("adDataV2", {}).get("inspirePersonalize") or ad.get("adDataV2", {}).get("inspireAdInfo", {}).get("inspirePersonalize")
            if inspire:
                res["expectedCoin"] = int(float(inspire.get("awardValue", inspire.get("neoValue", 1))))
        # ========== 【直播激励翻倍逻辑】识别广告是否带翻倍属性 ==========
        try:
            inspire_info = None
            # 多层级提取翻倍配置
            if ad_raw_data.get("liveInspireAwardInfo"):
                inspire_info = ad_raw_data["liveInspireAwardInfo"]
            elif ad.get("liveInspireAwardInfo"):
                inspire_info = ad["liveInspireAwardInfo"]
            elif ad.get("adDataV2", {}).get("inspireAdInfo", {}).get("liveInspireAwardInfo"):
                inspire_info = ad["adDataV2"]["inspireAdInfo"]["liveInspireAwardInfo"]
            if inspire_info and inspire_info.get("enableLiveInspireAwardCoinMultiple") is True:
                amount = inspire_info.get("liveInspireAwardCoinAmount", 0)
                if amount > 0:
                    res["isMultiple"] = True  # 标记翻倍广告
                    res["multiple"] = inspire_info.get("liveInspireAwardCoinMultiple", 1)  # 翻倍倍数
                    res["baseCoin"] = inspire_info.get("liveInspireAwardCoinCount", 1)    # 基础金币
                    res["expectedCoin"] = int(float(amount))  # 预计收益按翻倍后计算
        except Exception:
            pass
        # ========== 【突破2500上限逻辑】检测广告是否支持额外任务 ==========
        try:
            templates = ad.get("adDataV2", {}).get("templateDatas", [])
            if isinstance(templates, list):
                # 存在resourceType=1的模板即支持额外任务，可突破上限
                res["hasExtraTask"] = any(t.get("resourceType") == 1 for t in templates)
        except Exception:
            pass
        # 广告标题提取
        content_pool = set()
        ad_data_v2 = ad.get("adDataV2", {})
        product = ad_data_v2.get("product") or ad.get("product", {})
        AdParser.add_valid_content(content_pool, product.get("name"))
        AdParser.add_valid_content(content_pool, ad_data_v2.get("adTitle"))
        AdParser.add_valid_content(content_pool, ad_data_v2.get("mainTitle"))
        AdParser.add_valid_content(content_pool, ad.get("title"))
        AdParser.add_valid_content(content_pool, ad_raw_data.get("caption"))
        content_list = list(content_pool)
        res["title"] = content_list[0] if content_list else "无有效广告标题"
        res["hasRewardEnd"] = ad_data_v2.get("onceAgainRewardInfo", {}).get("hasMore", False)
        return res
# ===================== 8. 工具函数 =====================
def generate_match_did(original_did):
    if not original_did or not original_did.strip():
        hex_chars = "0123456789abcdef"
        rand = "".join(random.choice(hex_chars) for _ in range(16))
        return f"ANDROID_{rand}"
    original = original_did.strip()
    match_prefix = re.match(r"^([^0-9a-f]*)", original)
    prefix = match_prefix.group(1) if match_prefix else "ANDROID_"
    target_len = len(original) - len(prefix)
    hex_chars = "0123456789abcdef"
    new_part = "".join(random.choice(hex_chars) for _ in range(target_len))
    new_did = prefix + new_part
    # 修复：长度不一致返回原DID，避免错误ID导致风控
    if len(new_did) == len(original):
        return new_did
    return original
class Tool:
    @staticmethod
    def mask_proxy(proxy):
        if not proxy:
            return "直连"
        m = re.match(r"^(socks5://)([^:@]+)(?::([^@]+))?@(.+)$", proxy)
        if m:
            return f"{m.group(1)}{m.group(2)}:***@{m.group(4)}"
        return proxy
    @staticmethod
    def sleep(min_ms, max_ms=None):
        if max_ms is None:
            delay = min_ms
        else:
            delay = random.randint(min_ms, max_ms)
        time.sleep(delay / 1000)
    @staticmethod
    def random_coord(min_v, max_v):
        return random.randint(min_v, max_v)
    @staticmethod
    def random_rate(rate):
        return random.random() < rate
    @staticmethod
    def build_proxy_dict(proxy_url):
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}
    @staticmethod
    def check_proxy_ip(proxy):
        # 完全照搬ksjs1检测逻辑，使用ip9.com.cn接口
        if not proxy:
            return "直连"
        proxies = Tool.build_proxy_dict(proxy)
        try:
            resp = _global_session.get("https://ip9.com.cn/get", headers={"User-Agent": "Mozilla/5.0"}, timeout=8, proxies=proxies)
            data = resp.json()
            ip = data.get("ip") or (data.get("data") or {}).get("ip")
            if ip:
                return ip
        except Exception:
            pass
        return None
    @staticmethod
    def check_local_ip():
        try:
            resp = _global_session.get("https://ip.3322.net", timeout=3, proxies=None)
            ip = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", resp.text.strip())
            return ip.group() if ip else "127.0.0.1"
        except Exception:
            return "127.0.0.1"
    @staticmethod
    def request(options, proxy=None):
        url = options.get("url")
        method = options.get("method", "GET").upper()
        headers = options.get("headers", {})
        body = options.get("body")
        form = options.get("form")
        timeout = options.get("timeout", 10000) / 1000
        proxies = Tool.build_proxy_dict(proxy)
        try:
            data = None
            if form and method == "POST":
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
                if isinstance(form, dict):
                    data = querystring.urlencode(form)
                else:
                    data = form
            elif body:
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/json"
                data = json.dumps(body)
            resp = _global_session.request(method=method, url=url, headers=headers, data=data, timeout=timeout, proxies=proxies)
            try:
                resp_json = resp.json() if resp.content else None
            except Exception:
                resp_json = None
            return {"body": resp_json, "status": resp.status_code}
        except Exception as e:
            return {"body": None, "status": 0, "error": str(e)}
# ===================== 9. 签名接口封装 =====================
class Sign:
    @staticmethod
    def get_enc_sign(base64_data, platform_type):
        url = f"{SIGN_API[platform_type]}/encsign"
        for _ in range(_CONST["SIGN_RETRY"]):
            req = Tool.request({
                "method": "POST",
                "url": url,
                "headers": {"Content-Type": "application/json"},
                "body": {"data": base64_data},
                "timeout": 12000
            })
            body = req["body"]
            if body and body.get("status"):
                return body["data"]
            Tool.sleep(800, 1200)
        return None
    @staticmethod
    def get_ns_sign(req_info, platform_type):
        url = f"{SIGN_API[platform_type]}/nssig"
        for _ in range(_CONST["SIGN_RETRY"]):
            req = Tool.request({
                "method": "POST",
                "url": url,
                "headers": {"Content-Type": "application/json"},
                "body": {
                    "path": req_info["urlpath"],
                    "data": req_info["reqdata"],
                    "salt": req_info["salt"]
                },
                "timeout": 12000
            })
            body = req["body"]
            if body and body.get("data"):
                d = body["data"]
                return {
                    "sig": d["sig"],
                    "__NStokensig": d["nstokensig"],
                    "__NS_sig3": d["nssig3"],
                    "__NS_xfalcon": d.get("nssig4", "")
                }
            Tool.sleep(800, 1200)
        return None
# ===================== 10. 平台配置 =====================
PLATFORM_KUAISHOU = {
    "type": "KUAISHOU",
    "name": "快手普通版",
    "userInfoUrl": "https://encourage.kuaishou.com/rest/wd/encourage/account/basicInfo",
    "host": "encourage.kuaishou.com",
    "adClientKey": "3c2cd3f3",
    "reportClientKey": "3c2cd3f3",
    "tasks": {
        "box": {
            "name": "宝箱广告", "businessId": 604, "posId": 20345, "subPageId": 100024063,
            "requestSceneType": 1, "taskType": 1, "pageId": 100011251
        },
        "look": {
            "name": "看广告得金币", "businessId": 671, "posId": 24068, "subPageId": 100026368,
            "requestSceneType": 1, "taskType": 1, "pageId": 100011251
        },
        "search": {
            "name": "搜索广告", "businessId": 7077, "posId": 216267, "subPageId": 100161535,
            "pageId": 10014, "requestSceneType": 1, "taskType": 2,
            "linkUrl": "eyJwYWdlSWQiOjEwMDE0LCJzdWJQYWdlSWQiOjEwMDE2MTUzNSwicG9zSWQiOjIxNjI2NywiYnVzaW5lc3NJZCI6NzA3NywiZXh0UGFyYW1zIjoiYzc4OWI1ZTAzMjMxOTUwZjcyM2ZjMWE1ZGJjYzgwNmYzMDE1OTcyZWE0Mzc2NmNlNDYwNTk2ZDgzMGVjNTE5MDM0OGEwNTlkOTA2NWYwZGY1ZjkwY2YwMjEwMGVhMmQzYzU0YjUyZDBlNGUxY2Q0NmMxN2ExZDU3YmRhY2EyMzVlM2U1NjYzN2JmZGQzMThiZWMzNTgzOWU1YzIxNWUyNzMzY2IyMzQ2ZGQ1NDYyODc1NDdlMjc4OWYxMjZjZWU5NWZhYzg4N2IxMzM2MzBlZTEzYTVmYTlhODYzNDYxODQ5MjM0NDk3ZGY3ZTRmOWYyYzk2ZjQ5YzViMGExNzQ2NGE2MGM0MDg1MzU2NTY2ZDc4NGIxYjY3NzY3MzYzYjg3IiwiY3VzdG9tRGF0YSI6eyJleGl0SW5mbyI6eyJ0b2FzdERlc2MiOm51bGwsInJvYXN0SW1nVXJsIjpudWxsfX0sInBlbmRhbnRUeXBlIjoxLCJkaXNwbGF5VHlwZSI6Miwic2luZ2xlUGFnZUlkIjowLCJzaW5nbGVTdWJQYWdlSWQiOjAsIm5vYW5uZWwiOjAsIm5vd250ZG93blJlcG9ydCI6ZmFsc2UsInRoZW1lVHlwZSI6MCwibWl4ZWRBZCI6dHJ1ZSwiZnVsbE1peGVkIjp0cnVlLCJhdXRvUmVwb3J0Ijp0cnVlLCJmcm9tVGFza0NlbnRlciI6dHJ1ZSwic2VhcmNoSW5zcGlyZVNjaGVtZUluZm8iOm51bGwsImFtb3VudCI6MH0="
        }
    }
}
PLATFORM_NEBULA = {
    "type": "NEBULA",
    "name": "快手极速版",
    "userInfoUrl": "https://nebula.kuaishou.com/rest/n/nebula/activity/earn/overview/basicInfo",
    "host": "nebula.kuaishou.com",
    "adClientKey": "2ac2a76d",
    "reportClientKey": "2ac2a76d",
    "tasks": {
        "box": {
            "name": "宝箱广告", "pageId": 11101, "subPageId": 100024064, "businessId": 606, "posId": 20346,
            "requestSceneType": 1, "taskType": 1
        },
        "look": {
            "name": "看广告得金币", "pageId": 11101, "subPageId": 100026367, "businessId": 672, "posId": 24067,
            "requestSceneType": 1, "taskType": 1
        },
        "search": {
            "name": "搜索广告", "pageId": 11014, "subPageId": 100161537, "businessId": 7076, "posId": 216268,
            "requestSceneType": 1, "taskType": 1,
            "linkUrl": "eyJwYWdlSWQiOjExMDE0LCJzdWJQYWdlSWQiOjEwMDE2MTUzNywicG9zSWQiOjIxNjI2OCwiYnVzaW5lc3NJZCI6NzA3NiwiZXh0UGFyYW1zIjoiYjc4OWI1ZTAzMjMxOTUwZjcyM2ZjMWE1ZGJjYzgwNmYzMDE1OTcyZWE0Mzc2NmNlNDYwNTk2ZDgzMGVjNTE5MDM0OGEwNTlkOTA2NWYwZGY1ZjkwY2YwMjEwMGVhMmQzYzU0YjUyZDBlNGUxY2Q0NmMxN2ExZDU3YmRhY2EyMzVlM2U1NjYzN2JmZGQzMThiZWMzNTgzOWU1YzIxNWUyNzMzY2IyMzQ2ZGQ1NDYyODc1NDdlMjc4OWYxMjZjZWU5NWZhYzg4N2IxMzM2MzBlZTEzYTVmYTlhODYzNDYxODQ5MjM0NDk3ZGY3ZTRmOWYyYzk2ZjQ5YzViMGExNzQ2NGE2MGM0MDg1MzU2NTY2ZDc4NGIxYjY3NzY3MzYzYjg3IiwiY3VzdG9tRGF0YSI6eyJleGl0SW5mbyI6eyJ0b2FzdERlc2MiOm51bGwsInJvYXN0SW1nVXJsIjpudWxsfX0sInBlbmRhbnRUeXBlIjoxLCJkaXNwbGF5VHlwZSI6Miwic2luZ2xlUGFnZUlkIjowLCJzaW5nbGVTdWJQYWdlSWQiOjAsIm5vYW5uZWwiOjAsIm5vd250ZG93blJlcG9ydCI6ZmFsc2UsInRoZW1lVHlwZSI6MCwibWl4ZWRBZCI6dHJ1ZSwiZnVsbE1peGVkIjp0cnVlLCJhdXRvUmVwb3J0Ijp0cnVlLCJmcm9tVGFza0NlbnRlciI6dHJ1ZSwic2VhcmNoSW5zcGlyZVNjaGVtZUluZm8iOm51bGwsImFtb3VudCI6MH0="
        }
    }
}
# ===================== 11. 真人模拟行为 =====================
class HumanSim:
    @staticmethod
    def ad_interact(ad_info):
        if not FUNCTION_CONFIG["AD_CLICK_ENABLE"] and not FUNCTION_CONFIG["RAISE_ACCOUNT_ENABLE"]:
            return
        if FUNCTION_CONFIG["AD_CLICK_ENABLE"] and Tool.random_rate(SimConfig["AD_CLICK_RATE"]):
            Tool.sleep(500, 1500)
            stay = Tool.random_coord(SimConfig["AD_CLICK_STAY_MIN"], SimConfig["AD_CLICK_STAY_MAX"])
            Tool.sleep(stay)
            if Tool.random_rate(0.6):
                HumanSim.page_scroll()
                Tool.sleep(1000, 3000)
            if Tool.random_rate(SimConfig["AD_CLICK_BACK_RATE"]):
                Tool.sleep(500, 1000)
        if Tool.random_rate(SimConfig["SWIPE_RATE"]):
            HumanSim.page_scroll()
    @staticmethod
    def page_scroll(count=1):
        for _ in range(count):
            Tool.sleep(300, 800)
            Tool.sleep(200, 500)
    @staticmethod
    def raise_video_browse():
        if not FUNCTION_CONFIG["RAISE_ACCOUNT_ENABLE"]:
            return
        Log.subTitle("养号浏览")
        swipe = Tool.random_coord(SimConfig["RAISE_SWIPE_COUNT_MIN"], SimConfig["RAISE_SWIPE_COUNT_MAX"])
        for _ in range(swipe):
            watch = Tool.random_coord(SimConfig["RAISE_VIDEO_WATCH_MIN"], SimConfig["RAISE_VIDEO_WATCH_MAX"])
            Tool.sleep(watch)
            if Tool.random_rate(SimConfig["RAISE_LIKE_RATE"]):
                Tool.sleep(200, 600)
            if Tool.random_rate(SimConfig["RAISE_COMMENT_READ_RATE"]):
                Tool.sleep(1000, 3000)
                HumanSim.page_scroll(2)
            Tool.sleep(300, 800)
        Log.success(f"养号完成，浏览{swipe}个视频")
# ===================== 12. 账号核心执行类 =====================
class KuaishouAccount:
    def __init__(self, options):
        self.index = options["index"]
        self.total = options["total"]
        self.remark = options["remark"]
        self.originalCookie = options["cookie"]
        self.cookie = options["cookie"]
        self.salt = options["salt"]
        self.proxy = options["proxy"]
        self.platform = options["platform"]
        self.taskConfig = self.platform["tasks"]
        self.tasksToRun = [t for t in TASK_CONFIG["list"] if t in self.taskConfig]
        self.currentTaskIndex = 0
        self.adFailCount = 0
        self.continuous1Coin = 0
        self.lowRewardStreak = 0
        self.changeDidCount = 0
        self.stopAll = False
        self.taskLimit = {}
        self.taskStats = {}
        self.taskTotalProfit = 0
        self.continuousLowCoinCount = 0
        for t in self.tasksToRun:
            self.taskStats[t] = {"success": 0, "failed": 0, "reward": 0}
            self.taskLimit[t] = False
        self.userInfo = {"nickname": "未知昵称", "coin": 0, "cash": 0}
        self.exitIP = ""
        self.mod = ""
        self.egid = ""
        self.did = ""
        self.originalDid = ""
        self.userId = ""
        self.apiSt = ""
        self.appver = ""
        self.queryBase = ""
        # 设备参数字段
        self.kcv = ""
        self.kpf = ""
        self.ver = ""
        self.android_os = ""
        self.boardPlatform = ""
        self.androidApiLevel = ""
        self.country_code = ""
        self.sys = ""
        self.sw = ""
        self.sh = ""
        self.abi = ""
        self.userRecoBit = ""
        self.earphoneMode = ""
        self.isp = ""
        self.language = ""
        self.net = ""
        self.did_tag = ""
        self.app = ""
        self.osType = 1
        self.osVersion = ""
        self.parse_cookie()
        if len(self.tasksToRun) == 0:
            self.stopAll = True
    def parse_cookie(self):
        cookie = self.cookie
        mod_match = re.search(r"mod=([^;]+)", cookie)
        egid_match = re.search(r"egid=([^;]+)", cookie)
        did_match = re.search(r"did=([^;]+)", cookie)
        uid_match = re.search(r"userId=([^;]+)", cookie)
        api_st_match = re.search(r"kuaishou\.api_st=([^;]+)", cookie)
        appver_match = re.search(r"appver=([^;]+)", cookie)
        # 全量设备字段从Cookie提取，无则随机生成
        kcv_match = re.search(r"kcv=([^;]+)", cookie)
        kpf_match = re.search(r"kpf=([^;]+)", cookie)
        ver_match = re.search(r"ver=([^;]+)", cookie)
        android_os_match = re.search(r"android_os=([^;]+)", cookie)
        boardPlatform_match = re.search(r"boardPlatform=([^;]+)", cookie)
        androidApiLevel_match = re.search(r"androidApiLevel=([^;]+)", cookie)
        country_code_match = re.search(r"country_code=([^;]+)", cookie)
        sys_match = re.search(r"sys=([^;]+)", cookie)
        sw_match = re.search(r"sw=([^;]+)", cookie)
        sh_match = re.search(r"sh=([^;]+)", cookie)
        abi_match = re.search(r"abi=([^;]+)", cookie)
        userRecoBit_match = re.search(r"userRecoBit=([^;]+)", cookie)
        earphoneMode_match = re.search(r"earphoneMode=([^;]+)", cookie)
        isp_match = re.search(r"isp=([^;]+)", cookie)
        language_match = re.search(r"language=([^;]+)", cookie)
        net_match = re.search(r"net=([^;]+)", cookie)
        did_tag_match = re.search(r"did_tag=([^;]+)", cookie)
        app_match = re.search(r"app=([^;]+)", cookie)
        self.mod = mod_match.group(1) if mod_match else "Xiaomi(23116PN5BC)"
        self.egid = egid_match.group(1) if egid_match else ""
        self.did = did_match.group(1) if did_match else ""
        self.originalDid = self.did
        self.userId = uid_match.group(1) if uid_match else ""
        self.apiSt = api_st_match.group(1) if api_st_match else ""
        self.appver = appver_match.group(1) if appver_match else "13.7.20.10468"
        # Cookie优先，无则随机兜底
        self.kcv = kcv_match.group(1) if kcv_match else str(random.randint(1500, 1700))
        self.kpf = kpf_match.group(1) if kpf_match else "ANDROID_PHONE"
        self.ver = ver_match.group(1) if ver_match else f"{random.randint(10,12)}.{random.randint(0,9)}"
        self.android_os = android_os_match.group(1) if android_os_match else "0"
        self.boardPlatform = boardPlatform_match.group(1) if boardPlatform_match else random.choice(["pineapple", "star", "kona", "lito", "sm8250", "lahaina"])
        self.androidApiLevel = androidApiLevel_match.group(1) if androidApiLevel_match else str(random.randint(31, 35))
        self.country_code = country_code_match.group(1) if country_code_match else "cn"
        self.sys = sys_match.group(1) if sys_match else f"ANDROID_{random.randint(12,15)}"
        self.sw = sw_match.group(1) if sw_match else str(random.choice([720, 1080, 1440]))
        self.sh = sh_match.group(1) if sh_match else str(random.choice([1600, 2340, 2400, 2560]))
        self.abi = abi_match.group(1) if abi_match else random.choice(["arm64", "armeabi-v7a"])
        self.userRecoBit = userRecoBit_match.group(1) if userRecoBit_match else "0"
        self.earphoneMode = earphoneMode_match.group(1) if earphoneMode_match else "1"
        self.isp = isp_match.group(1) if isp_match else random.choice(["CUCC", "CMCC", "CTCC"])
        self.language = language_match.group(1) if language_match else "zh-cn"
        self.net = net_match.group(1) if net_match else random.choice(["WIFI", "4G", "5G"])
        self.did_tag = did_tag_match.group(1) if did_tag_match else "0"
        self.app = app_match.group(1) if app_match else "0"
        self.osVersion = str(random.randint(12, 15))
        self.queryBase = f"mod={self.mod}&appver={self.appver}&egid={self.egid}&did={self.did}"
    def change_did(self, reason):
        if not FUNCTION_CONFIG["AUTO_CHANGE_DID_ENABLE"]:
            return False
        if self.changeDidCount >= AUTO_CHANGE_DID_CONFIG["MAX_CHANGE_COUNT"]:
            Log.warn(f"换DID已达上限{AUTO_CHANGE_DID_CONFIG['MAX_CHANGE_COUNT']}次，停止更换")
            return False
        try:
            old_did = self.did
            new_did = generate_match_did(old_did)
            if len(new_did) != len(old_did):
                return False
            self.did = new_did
            self.cookie = re.sub(r"did=[^;]+", f"did={new_did}", self.cookie)
            self.queryBase = f"mod={self.mod}&appver={self.appver}&egid={self.egid}&did={self.did}"
            self.continuous1Coin = 0
            self.lowRewardStreak = 0
            self.adFailCount = 0
            self.continuousLowCoinCount = 0
            self.changeDidCount += 1
            Log.warn(f"触发换DID | 原因: {reason} | 累计{self.changeDidCount}次")
            Tool.sleep(AUTO_CHANGE_DID_CONFIG["CHANGE_DELAY_MIN"], AUTO_CHANGE_DID_CONFIG["CHANGE_DELAY_MAX"])
            return True
        except Exception:
            # 异常回滚原始Cookie，避免坏ID跑全程
            self.cookie = self.originalCookie
            self.parse_cookie()
            return False
    def init_ip(self):
        try:
            if self.proxy:
                ip = Tool.check_proxy_ip(self.proxy)
                if ip:
                    self.exitIP = ip
                    Log.info(f"代理出口IP: {ip}")
                else:
                    self.proxy = None
                    self.exitIP = Tool.check_local_ip()
                    Log.warn(f"代理连接失败，切换直连 | IP: {self.exitIP}")
            else:
                self.exitIP = Tool.check_local_ip()
                Log.info(f"直连模式 | IP: {self.exitIP}")
        except Exception:
            self.stopAll = True
    def get_imp_ext(self, task):
        if "搜索" in task["name"]:
            word = random.choice(SEARCH_CONFIG["KEYWORDS"])
            return json.dumps({
                "openH5AdCount": 2,
                "sessionLookedCompletedCount": "1",
                "sessionType": "1",
                "searchKey": word,
                "triggerType": "2",
                "disableReportToast": "true",
                "businessEnterAction": "7",
                "neoParams": task.get("linkUrl", "")
            })
        return "{}"
    def get_user_info(self):
        headers = {
            "Host": self.platform["host"],
            "User-Agent": "kwai-android aegon/3.56.0",
            "Cookie": self.cookie
        }
        res = Tool.request({
            "method": "GET",
            "url": self.platform["userInfoUrl"],
            "headers": headers,
            "timeout": 8000
        }, self.proxy)
        body = res["body"]
        if body and body.get("result") == 1 and body.get("data"):
            data = body["data"]
            user_data = data.get("userData", {})
            if self.platform["type"] == "KUAISHOU":
                self.userInfo = {
                    "nickname": user_data.get("nickname", "未知昵称"),
                    "coin": int(float(data.get("coinAmount", 0))),
                    "cash": float(data.get("cashAmountDisplay", 0))
                }
            else:
                self.userInfo = {
                    "nickname": user_data.get("nickname", "未知昵称"),
                    "coin": int(float(data.get("totalCoin", 0))),
                    "cash": float(data.get("allCash", 0))
                }
            self.remark = self.userInfo["nickname"]
            Log.success(f"登录成功 | {self.userInfo['nickname']} | 金币: {self.userInfo['coin']} | 余额: {self.userInfo['cash']:.2f}元")
            return True
        Log.error("Cookie已过期或无效")
        self.stopAll = True
        return False
    def get_ad_info(self, task_key):
        task = self.taskConfig[task_key]
        task_name = task["name"]
        ad_url = "/rest/e/reward/mixed/ad"
        for _ in range(_CONST["AD_FETCH_RETRY"]):
            common_data = {
                "encData": "|encData|",
                "sign": "|sign|",
                "cs": "false",
                "client_key": self.platform["adClientKey"],
                "videoModelCrowdTag": "1_23",
                "os": "android",
                "kuaishou.api_st": self.apiSt
            }
            # 设备参数全部动态读取，不再写死固定值
            device_data = {
                "earphoneMode": self.earphoneMode,
                "mod": self.mod,
                "appver": self.appver,
                "isp": self.isp,
                "language": self.language,
                "ud": self.userId,
                "did_tag": self.did_tag,
                "net": self.net,
                "kcv": self.kcv,
                "app": self.app,
                "kpf": self.kpf,
                "ver": self.ver,
                "android_os": self.android_os,
                "boardPlatform": self.boardPlatform,
                "kpn": self.platform["type"],
                "androidApiLevel": self.androidApiLevel,
                "country_code": self.country_code,
                "sys": self.sys,
                "sw": self.sw,
                "sh": self.sh,
                "abi": self.abi,
                "userRecoBit": self.userRecoBit
            }
            imp_data = {
                "appInfo": {
                    "appId": "kuaishou" if self.platform["type"] == "KUAISHOU" else "kuaishou_nebula",
                    "name": self.platform["name"],
                    "packageName": "com.smile.gifmaker" if self.platform["type"] == "KUAISHOU" else "com.kuaishou.nebula",
                    "version": self.appver,
                    "versionCode": -1
                },
                "deviceInfo": {
                    "osType": self.osType,
                    "osVersion": self.osVersion,
                    "deviceId": self.did,
                    "screenSize": {"width": int(self.sw), "height": int(self.sh)},
                    "ftt": ""
                },
                "userInfo": {"userId": self.userId, "age": 0, "gender": ""},
                "impInfo": [{
                    "pageId": task.get("pageId", 100011251),
                    "subPageId": task["subPageId"],
                    "action": 0,
                    "browseType": 4 if "搜索" in task["name"] else 3,
                    "impExtData": self.get_imp_ext(task),
                    "mediaExtData": "{}"
                }]
            }
            try:
                base64_imp = base64.b64encode(json.dumps(imp_data).encode("utf-8")).decode("utf-8")
            except Exception:
                self.adFailCount += 1
                return None
            enc_sign = Sign.get_enc_sign(base64_imp, self.platform["type"])
            if not enc_sign:
                Tool.sleep(1000, 2000)
                continue
            common_data["encData"] = enc_sign["encdata"]
            common_data["sign"] = enc_sign["sign"]
            post_data = querystring.urlencode(common_data) + "&" + querystring.urlencode(device_data)
            ns_sign = Sign.get_ns_sign({
                "urlpath": ad_url,
                "reqdata": post_data,
                "salt": self.salt
            }, self.platform["type"])
            if not ns_sign:
                Tool.sleep(1000, 2000)
                continue
            req_query = {
                **device_data,
                "sig": ns_sign["sig"],
                "__NS_sig3": ns_sign["__NS_sig3"],
                "__NS_xfalcon": ns_sign["__NS_xfalcon"],
                "__NStokensig": ns_sign["__NStokensig"]
            }
            final_url = f"https://api.e.kuaishou.com{ad_url}?{querystring.urlencode(req_query)}"
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Host": "api.e.kuaishou.com",
                "User-Agent": "kwai-android aegon/3.56.0",
                "Cookie": self.cookie
            }
            res = Tool.request({
                "method": "POST",
                "url": final_url,
                "headers": headers,
                "form": common_data,
                "timeout": 10000
            }, self.proxy)
            if res["status"] == 0 or not res["body"]:
                Tool.sleep(1000, 2000)
                continue
            body = res["body"]
            if body.get("errorMsg") != "OK":
                Tool.sleep(1000, 2000)
                continue
            if not body.get("feeds") or len(body["feeds"]) == 0:
                Tool.sleep(1000, 2000)
                continue
            self.adFailCount = 0
            return AdParser.parse(body["feeds"][0])
        # 全部重试失败
        Log.warn(f"【{task_name}】广告获取失败：多次重试无结果")
        self.adFailCount += 1
        # 达到失败上限自动换DID
        if self.adFailCount >= GLOBAL_CONFIG["AD_FAIL_LIMIT"]:
            self.change_did(f"连续{self.adFailCount}次广告失败")
        return None
    # 构建奖励标签（翻倍+突破上限）
    def build_reward_tags(self, ad_info):
        tags = []
        if ad_info["isMultiple"]:
            tags.append(f"{ad_info['baseCoin']}×{ad_info['multiple']}翻倍")
        if FUNCTION_CONFIG["EXTRA_TASK_ENABLE"] and ad_info["hasExtraTask"]:
            tags.append("突破上限")
        return f" | {' | '.join(tags)}" if tags else ""
    # ========== 【突破2500上限逻辑】奖励签名生成+额外任务追加 ==========
    def gen_report_sign(self, cid, llsid, task, ad_info):
        # 基础激励任务（taskType=1/2）
        neo_infos = [{
            "creativeId": cid,
            "extInfo": "",
            "llsid": llsid,
            "requestSceneType": task["requestSceneType"],
            "taskType": task["taskType"],
            "watchExpId": "",
            "watchStage": 0
        }]
        # 追加额外任务（taskType=3），触发突破2500上限结算
        if FUNCTION_CONFIG["EXTRA_TASK_ENABLE"] and ad_info["hasExtraTask"]:
            neo_infos.append({
                "clientExtInfo": '{"serialPaySuccess":false}',
                "creativeId": cid,
                "extInfo": "",
                "llsid": llsid,
                "adExtInfo": "",
                "materialTime": 0,
                "watchAdTime": 0,
                "requestSceneType": task["requestSceneType"],
                "taskType": 3,
                "watchExpId": "",
                "watchStage": 0
            })
        biz_str = json.dumps({
            "businessId": task["businessId"],
            "endTime": int(time.time() * 1000),
            "extParams": "",
            "mediaScene": "video",
            "neoInfos": neo_infos,
            "pageId": task.get("pageId", 100011251),
            "posId": task["posId"],
            "reportType": 0,
            "sessionId": "",
            "startTime": int(time.time() * 1000) - 30000,
            "subPageId": task["subPageId"]
        })
        post_data = f"bizStr={querystring.quote(biz_str)}&cs=false&client_key={self.platform['reportClientKey']}"
        full_data = f"{self.queryBase}&{post_data}"
        sign = Sign.get_ns_sign({
            "urlpath": "/rest/r/ad/task/report",
            "reqdata": full_data,
            "salt": self.salt
        }, self.platform["type"])
        if sign:
            return {"sign": sign, "postData": post_data}
        return None
    def submit_report(self, cid, llsid, task_key, ad_info):
        task = self.taskConfig[task_key]
        task_name = task["name"]
        sign_data = self.gen_report_sign(cid, llsid, task, ad_info)
        if not sign_data:
            Log.warn(f"【{task_name}】奖励上报失败：签名生成失败")
            return {"success": False, "reward": 0}
        sign = sign_data["sign"]
        post_data = sign_data["postData"]
        final_url = f"https://api.e.kuaishou.com/rest/r/ad/task/report?{self.queryBase}&sig={sign['sig']}&__NS_sig3={sign['__NS_sig3']}&__NS_xfalcon={sign['__NS_xfalcon']}&__NStokensig={sign['__NStokensig']}"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Host": "api.e.kuaishou.com",
            "User-Agent": "kwai-android aegon/3.56.0",
            "Cookie": self.cookie
        }
        res = Tool.request({
            "method": "POST",
            "url": final_url,
            "headers": headers,
            "form": post_data,
            "timeout": 10000
        }, self.proxy)
        if res["status"] == 0:
            Log.warn(f"【{task_name}】奖励上报失败：网络异常({res.get('error','连接超时')})")
            self.taskStats[task_key]["failed"] += 1
            return {"success": False, "reward": 0}
        body = res["body"]
        if not body:
            Log.warn(f"【{task_name}】奖励上报失败：接口返回空数据")
            self.taskStats[task_key]["failed"] += 1
            return {"success": False, "reward": 0}
        if body.get("result") == 1:
            coin = int(float(body.get("data", {}).get("neoAmount", 0)))
            self.taskStats[task_key]["reward"] += coin
            self.taskTotalProfit += coin
            self.userInfo["coin"] += coin
            if FUNCTION_CONFIG["LOW_COIN_CHANGE_DID_ENABLE"] and coin > 0:
                if coin < LOW_COIN_CONFIG["THRESHOLD"]:
                    self.continuousLowCoinCount += 1
                    if self.continuousLowCoinCount >= LOW_COIN_CONFIG["CONTINUOUS_LIMIT"]:
                        self.change_did(f"连续{self.continuousLowCoinCount}次低金币(<{LOW_COIN_CONFIG['THRESHOLD']})")
                else:
                    self.continuousLowCoinCount = 0
            if coin == 1:
                self.continuous1Coin += 1
            else:
                self.continuous1Coin = 0
            if coin <= GLOBAL_CONFIG["LOW_REWARD_THRESHOLD"]:
                self.lowRewardStreak += 1
            else:
                self.lowRewardStreak = 0
            if self.continuous1Coin >= GLOBAL_CONFIG["CONTINUOUS_1COIN_LIMIT"]:
                self.change_did(f"连续{GLOBAL_CONFIG['CONTINUOUS_1COIN_LIMIT']}次1金币")
            if self.lowRewardStreak >= GLOBAL_CONFIG["LOW_REWARD_LIMIT"]:
                self.change_did(f"连续{GLOBAL_CONFIG['LOW_REWARD_LIMIT']}次低收益")
            self.taskStats[task_key]["success"] += 1
            return {"success": True, "reward": coin, "hasRewardEnd": ad_info["hasRewardEnd"]}
        limit_codes = [20107, 20108, 1003, 415]
        if body.get("result") in limit_codes:
            Log.warn(f"【{task_name}】今日已达上限")
            self.taskLimit[task_key] = True
            return {"success": False, "reward": 0, "limit": True}
        err_msg = body.get("error_msg", body.get("errorMsg", f"错误码{body.get('result','未知')}"))
        Log.warn(f"【{task_name}】奖励上报失败：{err_msg}")
        self.taskStats[task_key]["failed"] += 1
        return {"success": False, "reward": 0}
    def run_box_task(self):
        task_key = "box"
        task = self.taskConfig[task_key]
        if self.taskLimit[task_key] or self.stopAll:
            return {"success": False}
        Log.subTitle(f"执行【{task['name']}】")
        ad_info = self.get_ad_info(task_key)
        if not ad_info:
            return {"success": False}
        watch_time = Tool.random_coord(SimConfig["WATCH_MIN"], SimConfig["WATCH_MAX"])
        HumanSim.ad_interact(ad_info)
        # 修复：观看时长计算负数问题，强制兜底最小值
        sleep_ms = watch_time * 1000 - _CONST["WATCH_OFFSET_MS"]
        Tool.sleep(max(sleep_ms, _CONST["MIN_WATCH_SLEEP_MS"]))
        res = self.submit_report(ad_info["creativeId"], ad_info["llsid"], task_key, ad_info)
        if res["success"]:
            platform_tag = "极速" if self.platform["type"] == "NEBULA" else "普通"
            Log.reward(f"[{self.userInfo['nickname']}] [{platform_tag}]预计{ad_info['expectedCoin']}实时{res['reward']}累计{self.taskTotalProfit}")
        return res
    def run_look_task(self):
        task_key = "look"
        task = self.taskConfig[task_key]
        if self.taskLimit[task_key] or self.stopAll:
            return {"success": False}
        Log.subTitle(f"执行【{task['name']}】")
        ad_info = self.get_ad_info(task_key)
        if not ad_info:
            return {"success": False}
        watch_time = Tool.random_coord(SimConfig["WATCH_MIN"], SimConfig["WATCH_MAX"])
        HumanSim.ad_interact(ad_info)
        sleep_ms = watch_time * 1000 - _CONST["WATCH_OFFSET_MS"]
        Tool.sleep(max(sleep_ms, _CONST["MIN_WATCH_SLEEP_MS"]))
        res = self.submit_report(ad_info["creativeId"], ad_info["llsid"], task_key, ad_info)
        if res["success"]:
            platform_tag = "极速" if self.platform["type"] == "NEBULA" else "普通"
            Log.reward(f"[{self.userInfo['nickname']}] [{platform_tag}]预计{ad_info['expectedCoin']}实时{res['reward']}累计{self.taskTotalProfit}")
        return res
    def run_search_task(self):
        task_key = "search"
        task = self.taskConfig[task_key]
        if self.taskLimit[task_key] or self.stopAll:
            return {"success": False}
        Log.subTitle(f"执行【{task['name']}】")
        ad_info = self.get_ad_info(task_key)
        if not ad_info:
            return {"success": False}
        watch_time = Tool.random_coord(SimConfig["WATCH_MIN"], SimConfig["WATCH_MAX"])
        HumanSim.ad_interact(ad_info)
        sleep_ms = watch_time * 1000 - _CONST["WATCH_OFFSET_MS"]
        Tool.sleep(max(sleep_ms, _CONST["MIN_WATCH_SLEEP_MS"]))
        res = self.submit_report(ad_info["creativeId"], ad_info["llsid"], task_key, ad_info)
        if res["success"]:
            platform_tag = "极速" if self.platform["type"] == "NEBULA" else "普通"
            Log.reward(f"[{self.userInfo['nickname']}] [{platform_tag}]预计{ad_info['expectedCoin']}实时{res['reward']}累计{self.taskTotalProfit}")
        return res
    def get_next_task(self):
        available = [t for t in self.tasksToRun if not self.taskLimit[t]]
        if not available:
            Log.warn("所有任务已达今日上限，结束执行")
            self.stopAll = True
            return None
        # 修复：下标越界问题，安全取模
        task = available[self.currentTaskIndex % len(available)]
        self.currentTaskIndex += 1
        return task
    def run_round(self, round_idx, total_rounds):
        if self.stopAll:
            return
        Log._print(Log.BLUE, Log.line())
        Log.info(f"{Log.progress(round_idx, total_rounds)}")
        task_key = self.get_next_task()
        if not task_key:
            return
        method_name = f"run_{task_key}_task"
        getattr(self, method_name)()
        if round_idx % SimConfig["REST_INTERVAL"] == 0 and not self.stopAll:
            HumanSim.raise_video_browse()
        Tool.sleep(SimConfig["REST_MIN"], SimConfig["REST_MAX"])
    def run(self):
        start_time = int(time.time() * 1000)
        Log.accountHeader(self.index, self.total, self.remark, self.platform["name"])
        self.init_ip()
        if self.stopAll:
            return self.build_result(False, 0, start_time)
        ok = self.get_user_info()
        if not ok or self.stopAll:
            return self.build_result(False, 0, start_time)
        Log.info(f"总轮数: {GLOBAL_CONFIG['TOTAL_ROUNDS']} | 任务: {TASK_CONFIG['names']}")
        features = []
        if FUNCTION_CONFIG["EXTRA_TASK_ENABLE"]:
            features.append("突破2500上限")
        if FUNCTION_CONFIG["LOW_COIN_CHANGE_DID_ENABLE"]:
            features.append("低金币换DID")
        if features:
            Log.info(f"功能: {' | '.join(features)}")
        for r in range(1, GLOBAL_CONFIG["TOTAL_ROUNDS"] + 1):
            if self.stopAll:
                break
            self.run_round(r, GLOBAL_CONFIG["TOTAL_ROUNDS"])
        return self.build_result(True, self.taskTotalProfit, start_time)
    def build_result(self, success, total_reward, start_ms):
        use_ms = int(time.time() * 1000) - start_ms
        return {
            "index": self.index,
            "remark": self.remark,
            "platform": self.platform["name"],
            "success": success,
            "totalReward": total_reward,
            "finalCoin": self.userInfo["coin"],
            "useTime": Log.format_time(use_ms)
        }
# ===================== 13. 账号解析（已修复多账号体系） =====================
def parse_account_config(config_string):
    parts = str(config_string or "").strip().split("#")
    if len(parts) < 2:
        return None
    remark = None
    cookie = None
    salt = None
    proxy_url = None
    if len(parts) == 4:
        remark, cookie, salt, proxy_url = parts
    elif len(parts) == 3:
        if "socks5://" in parts[2] or "|" in parts[2]:
            cookie, salt, proxy_url = parts
        else:
            remark, cookie, salt = parts
    elif len(parts) == 2:
        cookie, salt = parts
    else:
        return None
    if proxy_url:
        proxy_url = proxy_url.strip()
        if "|" in proxy_url:
            ip, port, username, password = proxy_url.split("|")
            proxy_url = f"socks5://{username}:{password}@{ip}:{port}"
        elif not re.match(r"^socks5://.+", proxy_url, re.IGNORECASE):
            proxy_url = None
    return {"remark": remark or None, "salt": salt.strip(), "cookie": cookie.strip(), "proxy_url": proxy_url}

def parse_accounts():
    accounts = []
    exists = set()
    idx = 1

    # 方式1：原有 ksck/KSCK 多行配置（完全兼容旧版）
    env_str = get_env("ksck", get_env("KSCK", ""))
    lines = env_str.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line in exists:
            continue
        acc = parse_account_config(line)
        if not acc or not acc["cookie"] or not acc["salt"]:
            continue
        kpn_match = re.search(r"kpn=([^;]+)", acc["cookie"])
        kpn = kpn_match.group(1).upper() if kpn_match else "NEBULA"
        platform = PLATFORM_KUAISHOU if kpn == "KUAISHOU" else PLATFORM_NEBULA
        accounts.append({
            "index": idx,
            "total": 0,
            "remark": acc["remark"] or f"账号{idx}",
            "cookie": acc["cookie"],
            "salt": acc["salt"],
            "proxy": acc["proxy_url"],
            "platform": platform
        })
        exists.add(line)
        idx += 1

    # 方式2：新增 ksck1/ksck2/... 序号式配置（对齐ksjs1）
    max_index = GLOBAL_CONFIG["MAX_KSCK_INDEX"]
    for i in range(1, max_index + 1):
        key = f"ksck{i}"
        line = get_env(key, "").strip()
        if not line or line in exists:
            continue
        acc = parse_account_config(line)
        if not acc or not acc["cookie"] or not acc["salt"]:
            continue
        kpn_match = re.search(r"kpn=([^;]+)", acc["cookie"])
        kpn = kpn_match.group(1).upper() if kpn_match else "NEBULA"
        platform = PLATFORM_KUAISHOU if kpn == "KUAISHOU" else PLATFORM_NEBULA
        accounts.append({
            "index": idx,
            "total": 0,
            "remark": acc["remark"] or f"账号{idx}",
            "cookie": acc["cookie"],
            "salt": acc["salt"],
            "proxy": acc["proxy_url"],
            "platform": platform
        })
        exists.add(line)
        idx += 1

    total = len(accounts)
    for acc in accounts:
        acc["total"] = total
    Log.success(f"加载完成 | 共{total}个有效账号")
    return accounts
# ===================== 14. 多账号并发执行 =====================
def handle_account(opts):
    try:
        acc = KuaishouAccount(opts)
        return acc.run()
    except Exception as e:
        with print_lock:
            Log.error(f"账号{opts['remark']}异常: {str(e)}")
        return {
            "index": opts["index"],
            "remark": opts["remark"],
            "platform": opts["platform"]["name"],
            "success": False,
            "totalReward": 0,
            "finalCoin": 0,
            "useTime": "0秒"
        }
def run_concurrent(accounts, concurrency):
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(handle_account, acc) for acc in accounts]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda x: x["index"])
    return results
# ===================== 15. 主入口 =====================
def main():
    Log.banner()
    accounts = parse_accounts()
    if len(accounts) == 0:
        Log.error("未找到有效账号，请检查环境变量ksck配置")
        return
    results = run_concurrent(accounts, GLOBAL_CONFIG["CONCURRENCY"])
    Log.summaryTable(results)
    Log.success("全部执行完成")
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        Log.error(f"脚本异常: {str(e)}")
        sys.exit(1)


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