#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云智手机（play.cn / yunzhi.new-gm.cn）「开学有礼」每日自动领奖 - 青龙面板脚本
=========================================================================
功能（每个账号依次执行，全程不触碰任何付费/订购/充值接口）：
  1. 今日登录福利：对话次数发放(balanceIssued)、首页弹窗礼包(home-popups)、销售礼包(try-claim)
  2. 我的权益 - 云机空间服务等「可自动领取」权益：自动给【已有云机续有效期】（不会新开云机）
  3. 每日签到（solidActivities 签到 + 累计奖励 claim）
  4. 抽奖任务：领取「每日登录 LOGIN」「每日AI对话 AI_CHAT」的抽奖次数（PAY_FIRST 付费任务跳过）
  5. 幸运抽奖：把当日抽奖次数全部抽完，并记录每个奖品
  6. 汇总对话次数余额，多账号合并后通过钉钉机器人推送

仅依赖 requests，青龙 Python3 环境可直接运行。

======================== 青龙环境变量 ========================
【多账号 token（必填）】二选一：
  YZ_TOKENS   : 多账号，支持 换行 / 英文逗号 / 分号 / 空格 分隔；
                每个账号可写纯 JWT，也可写  "备注:JWT"  或  "备注::JWT"  形式。
  YZ_TOKEN    : 单账号时可只填这一个。
  例（YZ_TOKENS，多个用换行）：
     eyJhbGciOi....（账号A的 CG_CLINET_USER_TOKEN_YUN）
     小号:eyJhbGciOi....（账号B）

【钉钉机器人（可选）】
  DD_BOT_TOKEN  : 钉钉自定义机器人 Webhook 的 access_token
  DD_BOT_SECRET : 机器人「加签」密钥（推荐用加签；不填则只用 access_token）

【可选覆盖（一般不用改）】
  YZ_CHANNEL   : 渠道码，默认活动渠道 00000019
  YZ_ACT_ID    : 抽奖活动 id，默认 1028
  YZ_SIGN_CATID: 签到活动 catid，默认 3

说明：
  * token 即登录后 cookie 名 CG_CLINET_USER_TOKEN_YUN 的 JWT（约 30 天有效，过期需重新获取）。
  * 脚本不会把 token 打印到日志，也不会写入任何文件；只在请求头 authorization 中使用。
  * 定时建议：每天 0 点过后执行，例如 cron  `37 0 * * *`（任务按自然日 0 点重置）。
"""

import os
import re
import sys
import json
import time
import hmac
import base64
import hashlib
import uuid
import random
import string
import traceback
from urllib.parse import quote, urlencode

try:
    import requests
except ImportError:
    print("缺少 requests 依赖，请在青龙 Python 环境安装：pip3 install requests")
    sys.exit(1)


# ========================= 常量 =========================
HOST = "https://yunzhi.new-gm.cn"
HMAC_SECRET = "8822FF81B6623e6f338d6F2A7F49DA83"   # 网关 HMAC-SHA256 密钥
BODY_SECRET = "7f9e2d08c1b5a3709e4f6d2a8c0e1b3f"   # 业务 body MD5 签名密钥

DEFAULT_CHANNEL = os.getenv("YZ_CHANNEL", "00000019")
ACT_ID = os.getenv("YZ_ACT_ID", "1028")
SIGN_CATID = os.getenv("YZ_SIGN_CATID", "3")

# 参与 HMAC 头签名的白名单（与前端 common.js 完全一致）
_SIGN_HEADER_KEYS = [
    "channel_code", "request_id", "timestamp", "version", "device_type",
    "device_no", "client_type", "authorization", "api_version",
]
# 需要付费的抽奖任务，坚决不做
SKIP_TASK_CODES = {"PAY_FIRST"}
# 云机类 matchType：领取时给「已有云机续有效期」
CLOUD_MATCH_TYPES = {"CLOUD_DEVICE", "CLOUD_DEVICE_RENEW"}


# ========================= 工具函数 =========================
def _sorted_kv(obj):
    """按 key 字典序排序，生成 k=v&k=v（仅过滤 None，保留空字符串）。"""
    if not obj:
        return ""
    items = {k: v for k, v in obj.items() if v is not None}
    return "&".join("{}={}".format(k, items[k]) for k in sorted(items.keys()))


def md5_body_sign(params, secret=BODY_SECRET):
    """业务 body 签名：参数排序拼接后追加密钥做 MD5（hex 小写）。"""
    plain = _sorted_kv({k: v for k, v in params.items() if k != "sign"})
    return hashlib.md5((plain + secret).encode("utf-8")).hexdigest()


def hmac_sign(method, path, query, body, headers):
    """网关 HMAC-SHA256 头签名（与前端 generateSign 一致，分隔符为 \\n）。"""
    method = method.upper()
    query_str = _sorted_kv(query)
    body_str = _sorted_kv(body) if method in ("POST", "PUT", "PATCH", "DELETE") else ""
    low = {k.lower(): v for k, v in headers.items()}
    header_obj = {}
    for key in _SIGN_HEADER_KEYS:
        val = low.get(key)
        if val is not None:
            header_obj[key] = val
    header_str = _sorted_kv(header_obj)
    raw = "{}\n{}\n{}\n{}\n{}\n".format(method, path, query_str, body_str, header_str)
    return hmac.new(HMAC_SECRET.encode("utf-8"), raw.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def uuid_req():
    return str(uuid.uuid4())


def hex32_req():
    """AI 主站 request_id：32 位无横线 hex（第 13 位为 4，第 17 位为 8/9/a/b）。"""
    s = list("".join(random.choice("0123456789abcdef") for _ in range(32)))
    s[12] = "4"
    s[16] = random.choice("89ab")
    return "".join(s)


def stable_device_no(seed):
    """由 token 派生稳定的 16 位 hex 设备号（模拟前端 localStorage 持久化）。"""
    return hashlib.md5(("yz:" + seed).encode("utf-8")).hexdigest()[:16]


def decode_jwt(tok):
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}


# ========================= 单账号客户端 =========================
class YunzhiClient(object):
    def __init__(self, token, alias=""):
        self.token = token.strip()
        self.alias = alias or ""
        self.http = requests.Session()
        self.http.headers.update({"Accept": "application/json, text/plain, */*"})
        jwt = decode_jwt(self.token)
        self.uid = str(jwt.get("sub") or jwt.get("userId") or "")
        self.exp = jwt.get("exp") or 0
        self.device_no = stable_device_no(self.token)
        self.lines = []          # 当日结果明细
        self.auth_failed = False

    # ---------- 备注名 ----------
    @property
    def name(self):
        if self.alias:
            return self.alias
        return "userId {}".format(self.uid) if self.uid else "账号"

    def add(self, text):
        self.lines.append(text)

    # ---------- 统一请求 ----------
    def _request(self, method, path, profile="lottery", query=None, json_body=None,
                 extra_headers=None, send_json_body=True):
        """
        profile:
          lottery : 抽奖/任务页（client_type=app, version="", 有横线 request_id）
          signin  : 签到页（client_type=h5, version=1.0.0）
          ai      : AI 主站（client_type=h5, version=10310, 32位 request_id, 随机 device_no）
          benefit : 权益模块（不走 HMAC 头签名，仅 authorization + body MD5）
        """
        query = query or {}
        url = HOST + path
        if query:
            url += "?" + urlencode(query)

        if profile == "ai":
            base_headers = {
                "channel_code": DEFAULT_CHANNEL,
                "version": "10310",
                "device_type": "3",
                "device_no": self.device_no,
                "client_type": "h5",
                "authorization": self.token,
                "api_version": "1",
                "timestamp": str(int(time.time() * 1000)),
                "request_id": hex32_req(),
            }
        elif profile == "signin":
            base_headers = {
                "channel_code": DEFAULT_CHANNEL,
                "version": "1.0.0",
                "device_type": "3",
                "device_no": "",
                "client_type": "h5",
                "authorization": self.token,
                "api_version": "1",
                "timestamp": str(int(time.time() * 1000)),
                "request_id": uuid_req(),
            }
        elif profile == "benefit":
            headers = {
                "Content-Type": "application/json",
                "device_type": "3",
                "client_type": "app",
                "channel_code": DEFAULT_CHANNEL,
                "version": "",
                "device_no": "",
                "Authorization": self.token,
            }
            if extra_headers:
                headers.update(extra_headers)
            data = None
            if method.upper() != "GET" and json_body is not None:
                data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            return self._do(method, url, headers, data)
        else:  # lottery
            base_headers = {
                "channel_code": DEFAULT_CHANNEL,
                "version": "",
                "device_type": "3",
                "device_no": "",
                "client_type": "app",
                "authorization": self.token,
                "api_version": "1",
                "timestamp": str(int(time.time() * 1000)),
                "request_id": uuid_req(),
            }

        if extra_headers:
            base_headers.update(extra_headers)

        sign = hmac_sign(method, path, query, json_body or {}, base_headers)
        headers = dict(base_headers)
        headers["sign"] = sign

        data = None
        if method.upper() != "GET" and json_body is not None and send_json_body:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        return self._do(method, url, headers, data)

    def _do(self, method, url, headers, data, retries=1):
        for attempt in range(retries + 1):
            try:
                resp = self.http.request(method, url, headers=headers, data=data, timeout=20)
                try:
                    return resp.status_code, resp.json()
                except Exception:
                    return resp.status_code, {"code": resp.status_code,
                                             "message": resp.text[:200]}
            except Exception as e:
                if attempt >= retries:
                    return -1, {"code": -1, "message": "网络错误: {}".format(e)}
                time.sleep(1.5)

    def _ok(self, body):
        code = body.get("code")
        if code in (0, 200):
            return True
        if code in (-1401, 401, 403) or body.get("status") in (401, 403):
            self.auth_failed = True
        msg = str(body.get("message") or body.get("text") or body.get("msg") or "")
        if re.search(r"登录已过期|未授权|token[^\u4e00-\u9fa5]*(无效|失效|过期)|unauthorized|forbidden",
                     msg, re.I):
            self.auth_failed = True
        return False

    # ---------- body MD5 签名封装（权益模块） ----------
    def _signed_body(self, params):
        body = dict(params or {})
        body["timestamp"] = str(int(time.time() * 1000))
        body["sign"] = md5_body_sign(body)
        return body

    # ============================================================
    # 1) 今日登录福利
    # ============================================================
    def step_login_welfare(self):
        # 1.1 对话次数发放（幂等，未发放则发，已发放则返回余额）
        try:
            body = self._signed_body({})
            sc, rj = self._request("POST", "/yunzhi/api/benefit/dialogue/balanceIssued",
                                   profile="ai", json_body=body)
            if self._ok(rj):
                d = rj.get("data") or {}
                self.add("今日登录福利-对话次数：已结算（当前对话余额 {} 次）".format(
                    d.get("totalBalance", "?")))
            else:
                self.add("今日登录福利-对话次数：{}".format(rj.get("message", "失败")))
        except Exception:
            self.add("今日登录福利-对话次数：异常")

        # 1.2 首页弹窗礼包
        try:
            sc, rj = self._request("GET", "/yunzhi/api/content/home-popups/init",
                                   profile="ai")
            popups = ((rj.get("data") or {}).get("popups")) or []
            if not popups:
                self.add("首页弹窗礼包：今日无待领弹窗")
            for p in popups:
                pid = p.get("popupId") or p.get("id")
                name = p.get("popupName") or p.get("memberBenefitName") or "弹窗礼包"
                if not pid:
                    continue
                c2, r2 = self._request("POST",
                                       "/yunzhi/api/content/home-popups/{}/claim".format(pid),
                                       profile="ai")
                if self._ok(r2):
                    self.add("首页弹窗礼包：{} 领取成功".format(name))
                else:
                    self.add("首页弹窗礼包：{} {}".format(name, r2.get("message", "失败")))
        except Exception:
            self.add("首页弹窗礼包：异常")

        # 1.3 销售礼包 try-claim（GET 即触发领取，幂等）
        try:
            sc, rj = self._request("GET",
                                   "/yunzhi/api/content/home-popups/sales-gift/try-claim",
                                   profile="ai")
            if self._ok(rj):
                items = ((rj.get("data") or {}).get("items")) or []
                if items:
                    names = [i.get("benefitName") or i.get("popupName") or "礼包" for i in items]
                    self.add("销售礼包：已领取（{}）".format("、".join(names)))
                else:
                    self.add("销售礼包：今日已领取/无可领")
            else:
                self.add("销售礼包：{}".format(rj.get("message", "失败")))
        except Exception:
            self.add("销售礼包：异常")

    # ============================================================
    # 2) 我的权益 - 云机空间等自动领取（给已有云机续期）
    # ============================================================
    def step_benefit_claim(self):
        sc, rj = self._request("GET", "/yunzhi/api/benefit/user/optionalAuto/list",
                               profile="benefit")
        if not self._ok(rj):
            self.add("云机空间等权益：查询失败（{}）".format(rj.get("message", "失败")))
            return
        benefits = ((rj.get("data") or {}).get("benefits")) or []
        claimable = [b for b in benefits if (b.get("remainingQuota") or 0) > 0]
        if not claimable:
            self.add("云机空间服务：今日已领取/无次数（跳过）")
            return

        for b in claimable:
            cfg_id = b.get("benefitConfigId")
            bname = b.get("benefitName") or "权益{}".format(cfg_id)
            quota = b.get("remainingQuota") or 0
            # 随心选类（需要人工选择具体权益）脚本不擅自选择，跳过并提示
            if b.get("isOptional") or b.get("recordId") or b.get("optional") == 1:
                self.add("{}：为随心选权益（需手动选择，已跳过，剩余{}次）".format(bname, quota))
                continue
            try:
                self._claim_one_benefit(cfg_id, bname)
            except Exception:
                self.add("{}：领取异常".format(bname))

    def _claim_one_benefit(self, cfg_id, bname):
        # 详情：取 userItemId / cloudDevices / matchType
        body = self._signed_body({"benefitConfigId": cfg_id})
        sc, rj = self._request("POST", "/yunzhi/api/benefit/user/benefit",
                               profile="benefit", json_body=body)
        if not self._ok(rj):
            self.add("{}：详情获取失败（{}）".format(bname, rj.get("message", "失败")))
            return
        d = rj.get("data") or {}
        user_items = d.get("userItems") or []
        if (d.get("remainingQuota") or 0) <= 0 or not user_items:
            self.add("{}：暂无可领资格（跳过）".format(bname))
            return
        user_item_id = user_items[0].get("userItemId")
        resource_id = ""
        match_type = d.get("matchType")
        cloud_devices = d.get("cloudDevices") or []
        if match_type in CLOUD_MATCH_TYPES and cloud_devices:
            # 默认给第一台现有云机「续有效期」，不新开云机
            resource_id = cloud_devices[0].get("vendorResourceId") or ""
        claim_body = self._signed_body({
            "userItemId": user_item_id,
            "resourceId": resource_id or "",
        })
        c2, r2 = self._request("POST", "/yunzhi/api/benefit/claim",
                               profile="benefit", json_body=claim_body)
        if not self._ok(r2):
            self.add("{}：{}".format(bname, r2.get("message", "领取失败")))
            return
        data2 = r2.get("data") or {}
        claim_id = data2.get("claimId")
        status = data2.get("status")
        # status: 0/3 处理中，1 成功，2 失败；轮询 claim/status
        if claim_id is not None and status in (0, 3, None):
            status = self._poll_claim_status(claim_id)
        if status == 1:
            tip = "（已为云机 {} 续有效期）".format(resource_id) if resource_id else ""
            self.add("{}：领取成功{}".format(bname, tip))
        elif status == 2:
            self.add("{}：领取失败（平台处理失败，可稍后手动查看）".format(bname))
        else:
            self.add("{}：已提交，处理中（可在权益记录查看）".format(bname))

    def _poll_claim_status(self, claim_id, times=6, interval=2):
        for _ in range(times):
            time.sleep(interval)
            body = self._signed_body({"claimId": claim_id})
            sc, rj = self._request("POST", "/yunzhi/api/benefit/claim/status",
                                   profile="benefit", json_body=body)
            if self._ok(rj):
                st = (rj.get("data") or {}).get("status")
                if st in (1, 2):
                    return st
        return None

    # ============================================================
    # 3) 每日签到
    # ============================================================
    def step_sign(self):
        base = "/yunzhi/api/content/solidActivities/{}".format(SIGN_CATID)
        sc, rj = self._request("GET", base + "/sign_in/status", profile="signin")
        if not self._ok(rj):
            self.add("每日签到：状态查询失败（{}）".format(rj.get("message", "失败")))
            return
        d = rj.get("data") or {}
        already = bool(d.get("todaySigned"))
        cum_days = d.get("cumulativeDays")
        if already:
            self.add("每日签到：今日已签到（累计 {} 天）".format(cum_days))
        else:
            c2, r2 = self._request("POST", base + "/sign_in", profile="signin")
            if self._ok(r2):
                self.add("每日签到：签到成功（累计 {} 天）".format(cum_days))
            else:
                msg = r2.get("message", "失败")
                self.add("每日签到：{}".format(msg))
                if "已签到" in str(msg):
                    pass
        # 累计奖励：仅在记录标记 triggered 且未领取时领取
        try:
            self._claim_sign_cumulative(base)
        except Exception:
            pass

    def _claim_sign_cumulative(self, base):
        sc, rj = self._request("GET", base + "/sign_in/records", profile="signin")
        if not self._ok(rj):
            return
        data = rj.get("data")
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = data.get("records") or data.get("list") or []
        for rec in records:
            triggered = rec.get("triggered")
            received = rec.get("received") or rec.get("claimed") or rec.get("status")
            day = rec.get("accumulation_days") or rec.get("accumulationDays") or \
                rec.get("dayThreshold") or rec.get("day")
            if triggered and not received and day:
                body = {"dayThreshold": day}
                c2, r2 = self._request("POST", base + "/sign_in/claim",
                                       profile="signin", json_body=body)
                if self._ok(r2):
                    self.add("签到累计奖励（第{}天）：领取成功".format(day))
                else:
                    self.add("签到累计奖励（第{}天）：{}".format(
                        day, r2.get("message", "失败")))

    # ============================================================
    # 4) 抽奖任务次数领取 + 5) 抽奖
    # ============================================================
    def step_lottery(self):
        # 4.1 任务页初始化
        sc, rj = self._request(
            "GET", "/yunzhi/api/content/lottery/page-info",
            profile="lottery", query={"activityId": ACT_ID})
        tasks = []
        if self._ok(rj):
            tasks = ((rj.get("data") or {}).get("taskList")) or []
        else:
            self.add("抽奖任务：初始化失败（{}）".format(rj.get("message", "失败")))

        # 4.2 领取任务抽奖次数（LOGIN / AI_CHAT；付费任务跳过）
        for t in tasks:
            code = t.get("taskCode")
            tname = t.get("taskName") or code
            if code in SKIP_TASK_CODES:
                self.add("抽奖任务「{}」：付费任务，已跳过".format(tname))
                continue
            if code not in ("LOGIN", "AI_CHAT"):
                continue
            c2, r2 = self._request(
                "GET", "/yunzhi/api/content/lottery/claim",
                profile="lottery",
                query={"taskCode": code, "activityId": ACT_ID},
                extra_headers={"user_id": self.uid, "access_token": self.token})
            d2 = r2.get("data") or {}
            if self._ok(r2) and d2.get("success"):
                self.add("抽奖任务「{}」：抽奖次数 +{}（{}）".format(
                    tname, d2.get("grantCount", t.get("grantCount", 1)),
                    d2.get("message", "领取成功")))
            else:
                # 已领过 / AI_CHAT 今日尚未完成对话 / 其他未达成，服务端均返回提示
                tip = d2.get("message") or r2.get("message") or "未达成或已领取"
                self.add("抽奖任务「{}」：{}".format(tname, tip))

        # 4.3 查询剩余抽奖次数
        sc, rj = self._request(
            "POST",
            "/yunzhi/api/content/activities/{}/users_lottery_info".format(ACT_ID),
            profile="lottery", json_body=None,
            extra_headers={"user_id": self.uid, "access_token": self.token})
        free = 0
        if self._ok(rj):
            free = (rj.get("data") or {}).get("userFreeLotteryCount") or 0

        # 5) 抽完所有次数
        prizes = []
        if free <= 0:
            self.add("幸运抽奖：今日剩余 0 次（已抽完/无次数）")
        guard = 0
        while free > 0 and guard < free + 2:
            guard += 1
            c2, r2 = self._request(
                "POST",
                "/yunzhi/api/content/activities/{}/lottery".format(ACT_ID),
                profile="lottery", json_body=None,
                extra_headers={"user_id": self.uid, "access_token": self.token})
            code = r2.get("code")
            if code in (-1803, -1804):
                break
            if self._ok(r2):
                d = r2.get("data") or {}
                prize = d.get("prizeName") or d.get("prize_name") or d.get("name") \
                    or d.get("rewardName") or (d.get("prize") or {}).get("name") \
                    or json.dumps(d, ensure_ascii=False)[:60]
                prizes.append(str(prize))
                free -= 1
                time.sleep(1.2)
            elif code == -1801:
                time.sleep(1.0)
                continue
            else:
                self.add("幸运抽奖：{}".format(r2.get("message", "异常，停止抽奖")))
                break
        if prizes:
            for i, p in enumerate(prizes, 1):
                self.add("幸运抽奖第{}次：{}".format(i, p))

    # ---------- 汇总执行 ----------
    def run(self):
        start = [
            "==== {} ====".format(self.name),
        ]
        try:
            self.step_login_welfare()
            self.step_benefit_claim()
            self.step_sign()
            self.step_lottery()
        except Exception:
            self.add("执行异常：{}".format(traceback.format_exc(limit=2).splitlines()[-1]))
        # token 到期提醒
        if self.exp:
            days_left = (self.exp - time.time()) / 86400
            if days_left <= 3:
                self.lines.append("⚠️ 该账号 token 将于 {} 天后过期，请尽快更新".format(
                    round(days_left, 1)))
        if self.auth_failed:
            self.lines.append("❌ 登录态已失效，请重新提供 CG_CLINET_USER_TOKEN_YUN")
        return start + self.lines


# ========================= 钉钉通知 =========================
def dingtalk_notify(content):
    token = os.getenv("DD_BOT_TOKEN", "").strip()
    if not token:
        return False, "未配置 DD_BOT_TOKEN，跳过钉钉推送"
    secret = os.getenv("DD_BOT_SECRET", "").strip()
    webhook = "https://oapi.dingtalk.com/robot/send?access_token={}".format(token)
    if secret:
        ts = str(round(time.time() * 1000))
        string_to_sign = "{}\n{}".format(ts, secret)
        sign = base64.b64encode(
            hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                     hashlib.sha256).digest())
        sign = quote(sign.decode("utf-8"), safe="")
        webhook += "&timestamp={}&sign={}".format(ts, sign)
    headers = {"Content-Type": "application/json"}
    payload = {"msgtype": "text", "text": {"content": content}}
    try:
        r = requests.post(webhook, headers=headers, json=payload, timeout=15)
        j = r.json()
        if j.get("errcode") == 0:
            return True, "钉钉推送成功"
        return False, "钉钉推送失败：{}".format(j)
    except Exception as e:
        return False, "钉钉推送异常：{}".format(e)


# ========================= 多账号解析 =========================
def parse_accounts():
    raw = os.getenv("YZ_TOKENS", "").strip() or os.getenv("YZ_TOKEN", "").strip()
    if not raw:
        return []
    accounts = []
    # 按行/逗号/分号/空白切分（这些字符不会出现在 JWT 内部），支持 "备注:JWT" / "备注::JWT"
    for seg in re.split(r"[\n,;\s]+", raw.strip()):
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"^(.+?)::(.+)$", seg) or re.match(r"^([^:]+):([A-Za-z0-9_\-\.]+)$", seg)
        if m and "." in m.group(2):
            accounts.append((m.group(1).strip(), m.group(2).strip()))
        else:
            accounts.append(("", seg))
    # 去重（按 token）
    seen, result = set(), []
    for alias, tok in accounts:
        if tok not in seen:
            seen.add(tok)
            result.append((alias, tok))
    return result


def main():
    accounts = parse_accounts()
    if not accounts:
        print("未检测到账号 token，请在青龙环境变量配置 YZ_TOKENS（或 YZ_TOKEN）。")
        sys.exit(0)

    today = time.strftime("%Y-%m-%d", time.localtime())
    blocks = []
    any_auth_fail = False
    for idx, (alias, tok) in enumerate(accounts, 1):
        client = YunzhiClient(tok, alias=alias)
        block = client.run()
        blocks.append("\n".join(block))
        if client.auth_failed:
            any_auth_fail = True
        if idx < len(accounts):
            time.sleep(2)

    title = "{} 云智手机每日领奖{}".format(
        today, "（有账号登录失效 ⚠️）" if any_auth_fail else "")
    report = title + "\n\n" + "\n\n".join(blocks)

    print("\n" + report + "\n")
    ok, msg = dingtalk_notify(report)
    print(msg)


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
