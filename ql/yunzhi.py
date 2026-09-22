#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云智手机 / 云蜘 AI 每日福利 + 开学季活动 自动脚本（青龙面板）
============================================================
功能（按顺序执行）：
  1. 首页「今日登录福利」弹窗自动领取（云机空间服务时长等）
  2. 指定权益默认领取（默认 benefitConfigId=158「云机空间服务（新开）」，自动续期第一台云机）
  3. 开学季活动每日任务：领取已完成任务的抽奖次数（每日登录 / 每日AI对话 / 首次充值），
     并把获得的抽奖次数全部自动抽完

钉钉机器人通知（可选，两套变量名都兼容，优先用青龙标准的 DINGTALK_*）：
  DINGTALK_WEBHOOK 钉钉机器人完整 webhook 地址（https://oapi.dingtalk.com/robot/send?access_token=xxx）
  DINGTALK_SECRET  钉钉机器人加签密钥（SEC 开头，无加签留空）
  （也兼容旧变量 DD_BOT_TOKEN=access_token片段 / DD_BOT_SECRET）

青龙环境变量：
  YUNZHI_TOKEN       必填，登录 token。可直接粘贴：纯 token、分享链接(?access_token=...)、
                     或整段 Cookie(CG_CLINET_USER_TOKEN_YUN=...)，脚本会自动提取；多账号用 & 或换行分隔
  YUNZHI_CHANNEL     选填，渠道码，默认 00000042
  YUNZHI_BENEFIT_IDS 选填，要默认领取的权益 configId，逗号分隔，默认 158；填 0 或 none 跳过
  YUNZHI_ACT_ID      选填，抽奖活动 ID，默认 1028；填 0 或 none 跳过
  YUNZHI_DRAW_CAP    选填，单次运行抽奖硬上限，默认 30（防异常）

cron 建议：每天 1~2 次，例如 17 8,20 * * *
依赖：仅 Python3 标准库。
"""

import os
import re
import sys
import time
import json
import hmac
import base64
import hashlib
import uuid
import urllib.parse
import urllib.request
import urllib.error

# ---------------- 固定配置（前端逆向，勿随意改） ----------------
HOST = "https://yunzhi.new-gm.cn"
HMAC_PATH = "/yunzhi"                      # 主站 / 活动抽奖接口前缀
API_BASE = HOST + "/yunzhi/api"
HMAC_SECRET = "8822FF81B6623e6f338d6F2A7F49DA83"   # HMAC-SHA256 头签名密钥
BODY_SALT = "7f9e2d08c1b5a3709e4f6d2a8c0e1b3f"     # 活动权益接口 body MD5 盐值
CHANNEL_DEFAULT = "00000042"
APP_VERSION = "10310"
DEVICE_TYPE = "3"
CLIENT_H5 = "h5"
CLIENT_APP = "app"
API_VERSION = "1"
DROP_HEADERS = {
    "content-length", "host", "connection", "accept-encoding",
    "user-agent", "sign", "content-type", "accept", "cache-control",
}
UA = ("Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")


# ==================== 通用 HTTP ====================
def _http(url, method, headers, data=None):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        if v is not None:
            req.add_header(k, v)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json, text/plain, */*")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"code": -1, "message": f"HTTP {e.code}"}
    except Exception as e:
        return -1, {"code": -1, "message": str(e)}


def _sorted_kv(obj):
    if not obj:
        return ""
    return "&".join(f"{k}={'' if obj[k] is None else obj[k]}" for k in sorted(obj.keys()))


def _sorted_headers(h):
    items = [(k, v) for k, v in h.items() if k.lower() not in DROP_HEADERS]
    items.sort(key=lambda x: x[0].lower())
    return "&".join(f"{k}={v}" for k, v in items)


# ==================== 客户端 A：HMAC-SHA256 头签名 ====================
class YunzhiClient:
    """主站接口 + 抽奖活动接口（请求头 HMAC-SHA256 签名）。"""

    def __init__(self, token, channel):
        self.token = token
        self.channel = channel

    def _headers(self):
        return {
            "authorization": self.token,
            "request_id": str(uuid.uuid4()),
            "timestamp": str(int(time.time() * 1000)),
            "version": APP_VERSION,
            "device_type": DEVICE_TYPE,
            "device_no": uuid.uuid4().hex[:16],
            "client_type": CLIENT_H5,
            "channel_code": self.channel,
            "api_version": API_VERSION,
        }

    def call(self, method, path, params=None, body=None):
        full_path = HMAC_PATH + path
        headers = self._headers()
        query_str = _sorted_kv(params)
        body_str = _sorted_kv(body) if body is not None else ""
        signing = (f"{method.upper()}\n{full_path}\n{query_str}\n{body_str}\n"
                   f"{_sorted_headers(headers)}\n")
        headers["sign"] = hmac.new(HMAC_SECRET.encode(), signing.encode(),
                                   hashlib.sha256).hexdigest()

        url = HOST + full_path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        headers["Cookie"] = f"CG_CLINET_USER_TOKEN_YUN={self.token}; channel_code={self.channel}"
        return _http(url, method, headers, data)

    def get(self, path, params=None):
        return self.call("GET", path, params=params)

    def post(self, path, body=None, params=None):
        return self.call("POST", path, params=params, body=body)


# ==================== 客户端 B：活动权益接口（body MD5 签名） ====================
def _body_md5_sign(payload):
    n = dict(payload or {})
    n["timestamp"] = str(int(time.time() * 1000))
    keys = sorted(k for k in n if k != "sign" and n[k] is not None)
    raw = "&".join(f"{k}={n[k]}" for k in keys)
    n["sign"] = hashlib.md5((raw + BODY_SALT).encode()).hexdigest()
    return n


class BenefitClient:
    """活动页 /api/benefit/* 接口，body 带 timestamp + MD5 sign。"""

    def __init__(self, token, channel):
        self.token = token
        self.channel = channel

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "device_type": DEVICE_TYPE,
            "client_type": CLIENT_APP,
            "channel_code": self.channel,
            "version": "",
            "device_no": "",
            "Authorization": self.token,
        }

    def post(self, path, payload=None):
        body = _body_md5_sign(payload or {})
        return _http(API_BASE + path, "POST", self._headers(),
                     json.dumps(body).encode())


# ==================== 业务 1：首页登录福利弹窗 ====================
def claim_home_popups(cli: YunzhiClient):
    out = []
    st, res = cli.get("/api/content/home-popups/init")
    if res.get("code") != 0:
        return [f"❌ 登录福利查询失败：{res.get('message')}"]
    popups = (res.get("data") or {}).get("popups") or []
    claimable = [p for p in popups if p.get("canClaim") or p.get("state") == "CAN_CLAIM"]
    if not claimable:
        out.append("ℹ️ 首页登录福利：今日已领取或暂无可领")
        return out
    for p in claimable:
        pid = p.get("popupId")
        name = p.get("popupName") or p.get("memberBenefitName") or f"#{pid}"
        benefit = p.get("memberBenefitName") or ""
        st, r = cli.post(f"/api/content/home-popups/{pid}/claim")
        d = r.get("data") or {}
        if r.get("code") == 0 and d.get("success"):
            out.append(f"🎁 首页福利【{name}】{benefit} 领取成功")
        else:
            out.append(f"⚠️ 首页福利【{name}】{d.get('failReason') or r.get('message')}")
        time.sleep(1)
    return out


# ==================== 业务 2：指定权益默认领取（如云机空间 158） ====================
def claim_benefit(bc: BenefitClient, config_id):
    out = []
    tag = f"权益{config_id}"
    st, res = bc.post("/benefit/user/benefit", {"benefitConfigId": int(config_id)})
    if res.get("code") != 0:
        return [f"⚠️ {tag} 查询失败：{res.get('message')}"]
    data = res.get("data") or {}
    name = data.get("benefitName", tag)
    quota = data.get("remainingQuota") or 0
    items = data.get("userItems") or []
    devices = data.get("cloudDevices") or []
    if quota <= 0 or not items:
        out.append(f"ℹ️ 【{name}】暂无可领次数（remainingQuota={quota}）")
        return out

    user_item_id = items[0].get("userItemId")
    # 默认续期第一台云机；没有云机则新开（resourceId 留空）
    resource_id = devices[0].get("vendorResourceId", "") if devices else ""
    st, r = bc.post("/benefit/claim",
                    {"userItemId": user_item_id, "resourceId": resource_id})
    d = r.get("data") or {}
    if r.get("code") != 0 or not d.get("claimId"):
        return [f"⚠️ 【{name}】领取失败：{d.get('errorMsg') or r.get('message')}"]
    claim_id = d.get("claimId")

    # 轮询发放状态：status 1=成功
    final_status, last_msg = d.get("status"), d.get("errorMsg")
    for _ in range(6):
        time.sleep(2)
        st, rs = bc.post("/benefit/claim/status", {"claimId": claim_id})
        rd = rs.get("data") or {}
        final_status = rd.get("status", final_status)
        last_msg = rd.get("errorMsg") or last_msg
        if final_status == 1:
            target = f"云机 {resource_id}" if resource_id else "新开云机"
            out.append(f"🎁 【{name}】领取成功，发放至 {target}（claimId={claim_id}）")
            return out
        if final_status not in (0, None):
            break
    if final_status in (0, None):
        out.append(f"⏳ 【{name}】已提交，发放中（claimId={claim_id}），稍后到账")
    else:
        out.append(f"⚠️ 【{name}】发放异常：{last_msg or final_status}")
    return out


# ==================== 业务 3：每日任务领取 + 自动抽奖 ====================
def tasks_and_lottery(cli: YunzhiClient, act_id, draw_cap):
    out = []
    aid = str(act_id)
    # 1) 查询任务
    st, res = cli.get("/api/content/lottery/page-info", {"activityId": aid})
    if res.get("code") != 0:
        return [f"⚠️ 活动{aid}任务查询失败：{res.get('message')}"]
    data = res.get("data") or {}
    tasks = data.get("taskList") or []
    name_map = {"LOGIN": "每日登录", "AI_CHAT": "每日AI对话", "PAY_FIRST": "首次充值"}

    # 2) 领取所有「已完成待领取(status=1)」的任务；也兜底直接 claim 一次由服务端判定
    new_draws = 0
    remain = 0
    for t in tasks:
        code = t.get("taskCode")
        status = t.get("status")
        label = name_map.get(code, code)
        if status == 2:
            continue
        st, r = cli.get("/api/content/lottery/claim",
                        {"taskCode": code, "activityId": aid})
        d = r.get("data") or {}
        if r.get("code") == 0 and d.get("success"):
            gc = d.get("grantCount") or 0
            new_draws += gc
            remain = max(remain, d.get("remainLotteryCount") or 0)
            out.append(f"✅ 任务【{label}】领取抽奖次数 +{gc}")
        else:
            msg = d.get("message") or r.get("message") or "未完成或不可领"
            if status == 1:
                out.append(f"⚠️ 任务【{label}】领取失败：{msg}")
        time.sleep(1)

    # 待抽次数：优先服务端返回的 remain，否则用本次新增次数
    draws = remain if remain > 0 else new_draws
    if draws <= 0:
        out.append("ℹ️ 今日任务无新增抽奖次数（可能已领取/已抽完）")
        return out
    draws = min(draws, draw_cap)

    # 3) 自动抽奖
    out.append(f"🎰 开始自动抽奖 {draws} 次…")
    win = []
    for i in range(draws):
        st, r = cli.post(f"/api/content/activities/{aid}/lottery")
        d = r.get("data") or {}
        if r.get("code") != 0:
            out.append(f"⚠️ 第{i+1}次抽奖失败：{r.get('message')}（code={r.get('code')}）")
            break
        prize = d.get("winningPrize") or {}
        pname = prize.get("name", "未知奖品")
        pclass = str(prize.get("prizeClass", ""))
        if pclass == "1":   # 1=真实中奖并发放，0=未中奖兜底
            win.append(pname)
            out.append(f"🎉 第{i+1}次中奖：{pname}")
        else:
            out.append(f"🍀 第{i+1}次：{pname}（未中实物）")
        time.sleep(1.5)
    if win:
        out.append("🏆 本次中奖：" + "、".join(win))
    else:
        out.append("本次未中实物奖品")
    return out


# ==================== 钉钉通知 ====================
def dingtalk_push(title, content):
    # 优先青龙标准变量 DINGTALK_WEBHOOK（完整地址）/ DINGTALK_SECRET；
    # 兼容旧变量 DD_BOT_TOKEN（仅 access_token 片段）/ DD_BOT_SECRET。
    webhook = (os.environ.get("DINGTALK_WEBHOOK", "") or "").strip()
    dd_token = (os.environ.get("DD_BOT_TOKEN", "") or "").strip()
    if not webhook and dd_token:
        webhook = f"https://oapi.dingtalk.com/robot/send?access_token={dd_token}"
    if not webhook:
        return
    # 容错：若把 access_token 片段误填进 WEBHOOK，自动补全
    if webhook and not webhook.startswith("http"):
        webhook = f"https://oapi.dingtalk.com/robot/send?access_token={webhook}"

    secret = ((os.environ.get("DINGTALK_SECRET", "") or "").strip()
              or (os.environ.get("DD_BOT_SECRET", "") or "").strip())
    url = webhook
    if secret and secret.upper().startswith("SEC"):
        ts = str(round(time.time() * 1000))
        sign = urllib.parse.quote_plus(base64.b64encode(
            hmac.new(secret.encode(), f"{ts}\n{secret}".encode(),
                     hashlib.sha256).digest()))
        sep = "&" if "?" in url else "?"
        url += f"{sep}timestamp={ts}&sign={sign}"
    payload = json.dumps({
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"### {title}\n\n{content}"},
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode())
            print("[钉钉]", "推送成功" if resp.get("errcode") == 0 else resp)
    except Exception as e:
        print("[钉钉] 推送异常：", e)


# ==================== 入口 ====================
def parse_ids(raw, default):
    raw = (raw or "").strip().lower()
    if raw in ("", "none", "null"):
        return default
    if raw in ("0", "off", "false", "no"):
        return []
    out = []
    for x in raw.replace("，", ",").split(","):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def run_account(token, channel, benefit_ids, act_id, draw_cap):
    lines = []
    cli = YunzhiClient(token, channel)
    # 登录校验
    st, info = cli.get("/api/user/info")
    if info.get("code") != 0:
        return [f"❌ 登录失败：{info.get('message')}（请更新 YUNZHI_TOKEN）"]
    u = info.get("data") or {}
    lines.append(f"✅ 登录：{u.get('phone','?')} (uid={u.get('id','?')})")

    # 1 首页登录福利
    lines.append("—— 首页登录福利 ——")
    lines.extend(claim_home_popups(cli))

    # 2 指定权益默认领取
    if benefit_ids:
        bc = BenefitClient(token, channel)
        lines.append("—— 权益默认领取 ——")
        for bid in benefit_ids:
            lines.extend(claim_benefit(bc, bid))

    # 3 每日任务 + 抽奖
    if act_id:
        lines.append(f"—— 开学季活动(actId={act_id}) 任务与抽奖 ——")
        lines.extend(tasks_and_lottery(cli, act_id, draw_cap))
    return lines


def extract_tokens(raw):
    """从纯 token / 分享链接(access_token=) / Cookie(CG_CLINET_USER_TOKEN_YUN=) 中
    提取全部 JWT（eyJ 开头），自动去重；兼容多账号（& 或换行分隔）。"""
    raw = raw or ""
    found = re.findall(r'eyJ[A-Za-z0-9_.\-]+', raw)
    out = []
    for t in found:
        if t not in out:
            out.append(t)
    if out:
        return out
    # 兜底：非 JWT 形式时按 & / 换行切分
    return [t.strip() for t in raw.replace("\n", "&").split("&") if t.strip()]


def main():
    raw = os.environ.get("YUNZHI_TOKEN", "").strip()
    if not raw:
        print("❌ 未配置环境变量 YUNZHI_TOKEN")
        sys.exit(1)
    channel = os.environ.get("YUNZHI_CHANNEL", CHANNEL_DEFAULT).strip() or CHANNEL_DEFAULT
    benefit_ids = parse_ids(os.environ.get("YUNZHI_BENEFIT_IDS"), ["158"])
    act_id_list = parse_ids(os.environ.get("YUNZHI_ACT_ID"), ["1028"])
    act_id = act_id_list[0] if act_id_list else None
    try:
        draw_cap = int(os.environ.get("YUNZHI_DRAW_CAP", "30"))
    except ValueError:
        draw_cap = 30

    tokens = extract_tokens(raw)
    print(f"===== 云智每日福利  共 {len(tokens)} 个账号 =====\n")
    report = []
    for i, tok in enumerate(tokens, 1):
        head = f"【账号 {i}】"
        print(head)
        try:
            res = run_account(tok, channel, benefit_ids, act_id, draw_cap)
        except Exception as e:
            res = [f"❌ 执行异常：{e}"]
        for x in res:
            print("  " + x)
        print()
        report.append(head)
        report.extend("  " + x for x in res)

    body = "\n".join(report)
    print("===== 汇总 =====\n" + body)
    dingtalk_push("云智每日福利 & 活动抽奖", body)


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
