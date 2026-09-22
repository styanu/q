# -*- coding: utf-8 -*-
"""
new Env('星穹铁道签到');

================================================================================
 米游社 · 崩坏：星穹铁道 每日签到（青龙面板单文件脚本）
================================================================================

 【功能】
   1. 自动获取米游社账号下绑定的全部星穹铁道角色（官服 / B 站服均可）
   2. 查询当日签到状态，未签到则自动签到，并展示当日奖励、累计签到天数
   3. 支持多个米游社账号，结果通过青龙内置通知 notify.send 推送

 【青龙配置】
   1. 脚本管理 → 新建任务，或把本文件放入 /ql/data/scripts/ 目录
   2. 定时规则示例（每天上午 8:17 执行，建议自选分钟降低风控概率）：
        17 8 * * *
   3. 环境变量 → 新建变量：
        变量名：STAR_RAIL_COOKIE
        变量值：米游社 Cookie（获取方式见下方说明）
      多账号用换行或 & 分隔，每个账号一条 Cookie。

 【获取 Cookie（电脑浏览器，推荐无痕窗口）】
   ※ 签到页 act.mihoyo.com 现在只显示“下载米游社APP”二维码、没有网页签到按钮，
     请改为在米游社官网登录后从接口请求中复制 Cookie：
   1. 用 Chrome/Edge 无痕窗口打开米游社官网并登录：
        https://www.miyoushe.com/sr/
   2. 按 F12 打开开发者工具 → Network（网络）面板 → 选 Fetch/XHR
   3. 在筛选(Filter)框输入：getUserGameUnreadCount
      （若列表为空，刷新一下页面或在官网内随便点一下）
   4. 点一条捕获到的请求 → Headers（标头）→ Request Headers（请求标头）
      → 找到 Cookie: ，复制冒号后面的整段值
   5. 粘贴到环境变量 STAR_RAIL_COOKIE 中
   ※ 整段复制即可，脚本会原样带上；其中应包含 cookie_token / cookie_token_v2、
     account_id 等字段。若脚本提示 -100 登录失效，重新按上述步骤获取即可。

   ※ Cookie 相当于账号凭证，请勿公开、勿提交到公开仓库。
   ※ 若频繁触发极验验证码，建议调大随机执行时间或手动签到一天。

 【本地调试】
   export STAR_RAIL_COOKIE='你的cookie'
   python3 starrail_checkin.py

  接口依据：社区维护项目 Womsxd/MihoyoBBSTools（act_id / salt / 请求头随米游社版本更新）
================================================================================
"""

import os
import re
import sys
import time
import json
import random
import string
import hashlib
import uuid

try:
    import requests
except ImportError:
    print("缺少 requests 依赖，请在青龙「依赖管理 → Python」中安装 requests")
    sys.exit(1)

# ------------------------------------------------------------------ #
# 常量（国服 · 崩坏：星穹铁道）
# ------------------------------------------------------------------ #
ACT_ID = "e202304121516551"          # 星铁签到活动 ID（长期固定）
GAME_BIZ = "hkrpg_cn"                # 星铁游戏 biz
APP_VERSION = "2.109.0"              # 米游社版本号（与 salt 对应）
CLIENT_TYPE = "5"                    # 5 = 手机网页端
SALT_WEB = "d9200c846b10886e8c874fc33c8f308b"   # 网页端签到 salt（DS1）

BASE_URL = "https://api-takumi.mihoyo.com"
URL_ROLES = BASE_URL + "/binding/api/getUserGameRolesByCookie"   # 角色列表
URL_HOME = BASE_URL + "/event/luna/home"                         # 奖励列表
URL_INFO = BASE_URL + "/event/luna/info"                         # 签到状态
URL_SIGN = BASE_URL + "/event/luna/sign"                         # 执行签到

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; Unspecified Device) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 "
    "miHoYoBBS/" + APP_VERSION
)

# 已知返回码
RET_ALREADY_SIGN = -5003   # 今日已签到


# ------------------------------------------------------------------ #
# 签名 / 请求头
# ------------------------------------------------------------------ #
def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def gen_ds_web() -> str:
    """网页端 DS1 签名：t,r,md5(salt=..&t=..&r=..)，r 为 6 位小写字母+数字。"""
    t = str(int(time.time()))
    r = "".join(random.sample(string.ascii_lowercase + string.digits, 6))
    c = md5(f"salt={SALT_WEB}&t={t}&r={r}")
    return f"{t},{r},{c}"


def gen_device_id(cookie: str) -> str:
    """用 cookie 稳定生成一个设备 ID（uuid3）。"""
    return str(uuid.uuid3(uuid.NAMESPACE_URL, cookie))


def build_headers(cookie: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": USER_AGENT,
        "x-rpc-app_version": APP_VERSION,
        "x-rpc-client_type": CLIENT_TYPE,
        "x-rpc-channel": "miyousheluodi",
        "X-Requested-With": "com.mihoyo.hyperion",
        "Origin": "https://act.mihoyo.com",
        "Referer": "https://act.mihoyo.com/",
        "DS": gen_ds_web(),
        "Cookie": cookie,
        "x-rpc-device_id": gen_device_id(cookie),
    }


# ------------------------------------------------------------------ #
# 业务逻辑
# ------------------------------------------------------------------ #
def http_request(method, url, cookie, **kwargs):
    """带简单重试的请求封装。"""
    headers = kwargs.pop("headers", None) or build_headers(cookie)
    last_err = None
    for i in range(3):
        try:
            resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
            return resp
        except requests.RequestException as e:
            last_err = e
            time.sleep(3)
    raise last_err


def get_roles(cookie: str) -> list:
    """获取该米游社账号绑定的全部星铁角色，返回 [(昵称, uid, region), ...]。"""
    resp = http_request(
        "GET", URL_ROLES, cookie,
        params={"game_biz": GAME_BIZ},
    )
    data = resp.json()
    if data.get("retcode") == -100:
        raise CookieInvalidError(data.get("message", "Cookie 无效或已过期"))
    if data.get("retcode") != 0:
        raise ApiError(f"获取角色列表失败：retcode={data.get('retcode')} "
                       f"message={data.get('message')}")
    roles = []
    for item in data.get("data", {}).get("list", []):
        roles.append((item.get("nickname", ""), str(item.get("game_uid", "")),
                      item.get("region", "")))
    return roles


def get_awards(cookie: str) -> list:
    """获取本月签到奖励列表。"""
    resp = http_request(
        "GET", URL_HOME, cookie,
        params={"lang": "zh-cn", "act_id": ACT_ID},
    )
    data = resp.json()
    if data.get("retcode") == 0:
        return data.get("data", {}).get("awards", [])
    return []


def get_sign_info(cookie: str, region: str, uid: str) -> dict:
    """查询签到状态。"""
    resp = http_request(
        "GET", URL_INFO, cookie,
        params={"lang": "zh-cn", "act_id": ACT_ID, "region": region, "uid": uid},
    )
    data = resp.json()
    if data.get("retcode") != 0:
        raise ApiError(f"获取签到状态失败：retcode={data.get('retcode')} "
                       f"message={data.get('message')}")
    return data.get("data", {})


def do_sign(cookie: str, region: str, uid: str) -> dict:
    """执行签到，返回响应 json。"""
    resp = http_request(
        "POST", URL_SIGN, cookie,
        json={"act_id": ACT_ID, "region": region, "uid": uid},
    )
    return resp.json()


def award_text(awards: list, day_index: int) -> str:
    """根据签到天数取奖励描述，day_index 从 0 开始。"""
    try:
        item = awards[day_index]
        return f"「{item.get('name')}」x{item.get('cnt')}"
    except (IndexError, KeyError, TypeError):
        return "奖励信息获取失败"


def sign_one_role(cookie: str, role: tuple, awards: list) -> str:
    """对单个角色完成签到，返回该角色的结果文本。"""
    nickname, uid, region = role
    title = f"{nickname}（UID {uid} / {region}）"

    info = get_sign_info(cookie, region, uid)

    # 首次绑定的角色需要先在米游社手动签到一次
    if info.get("first_bind"):
        return f"⚠️ {title}：首次绑定，请先在米游社手动签到一次"

    total_days = int(info.get("total_sign_day", 0))

    if info.get("is_sign"):
        reward = award_text(awards, total_days - 1)
        return f"✅ {title}：今日已签到，累计 {total_days} 天，今日奖励 {reward}"

    # 未签到 → 执行签到
    result = do_sign(cookie, region, uid)
    retcode = result.get("retcode")
    res_data = result.get("data", {}) or {}

    # 触发极验风控
    if retcode == 0 and res_data.get("success") == 1:
        return (f"⚠️ {title}：触发人机验证，本次未签到成功，请稍后手动签到或稍后重试\n"
                f"    （gt={res_data.get('gt')}, challenge={res_data.get('challenge')}）")

    if retcode == 0 and res_data.get("success") == 0:
        # 签到成功：累计天数 +1，当日奖励为列表中第 total_days 项
        reward = award_text(awards, total_days)
        return f"🎉 {title}：签到成功，累计 {total_days + 1} 天，今日奖励 {reward}"

    if retcode == RET_ALREADY_SIGN:
        reward = award_text(awards, total_days - 1)
        return f"✅ {title}：今日已签到，累计 {total_days} 天，今日奖励 {reward}"

    return (f"❌ {title}：签到失败，retcode={retcode} "
            f"message={result.get('message')} raw={json.dumps(result, ensure_ascii=False)}")


class CookieInvalidError(Exception):
    pass


class ApiError(Exception):
    pass


def parse_cookies(raw: str) -> list:
    """多账号：优先按换行、& 分隔；兼容青龙常见写法。"""
    if not raw:
        return []
    parts = re.split(r"[\n&]+", raw)
    cookies = []
    for p in parts:
        p = p.strip().strip(";").strip()
        if p and "=" in p:
            cookies.append(p)
    # 去重但保持顺序
    seen, result = set(), []
    for c in cookies:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def run_for_account(index: int, cookie: str) -> str:
    """处理一个米游社账号。"""
    lines = [f"━━ 账号 {index} ━━"]

    # Cookie 字段预检：签到接口需要登录态 token
    has_token = any(k in cookie for k in
                    ("cookie_token", "cookie_token_v2", "stoken", "ltoken"))
    has_uid = any(k in cookie for k in
                  ("account_id", "account_id_v2", "ltuid", "stuid"))
    if not has_token or not has_uid:
        missing = []
        if not has_token:
            missing.append("登录 token（cookie_token / cookie_token_v2）")
        if not has_uid:
            missing.append("账号 ID（account_id）")
        lines.append("❌ Cookie 缺少" + "、".join(missing) +
                     "，请按脚本顶部【获取 Cookie】步骤，从米游社官网登录后的 "
                     "getUserGameUnreadCount 请求中复制完整 Cookie。")
        return "\n".join(lines)

    try:
        lines = [f"━━ 账号 {index} ━━"]
        roles = get_roles(cookie)
    except CookieInvalidError as e:
        lines.append(f"❌ Cookie 无效或已过期，请重新获取：{e}")
        return "\n".join(lines)
    except ApiError as e:
        lines.append(f"❌ {e}")
        return "\n".join(lines)
    except Exception as e:
        lines.append(f"❌ 请求异常：{e}")
        return "\n".join(lines)

    if not roles:
        lines.append("⚠️ 该账号未绑定任何星穹铁道角色（请确认已在米游社绑定游戏角色）")
        return "\n".join(lines)

    awards = get_awards(cookie)

    for n, role in enumerate(roles):
        if n > 0:
            time.sleep(random.randint(3, 7))   # 多角色之间随机延时
        try:
            lines.append(sign_one_role(cookie, role, awards))
        except ApiError as e:
            lines.append(f"❌ {role[0]}（UID {role[1]}）：{e}")
        except Exception as e:
            lines.append(f"❌ {role[0]}（UID {role[1]}）：异常 {e}")
    return "\n".join(lines)


def main():
    raw_cookie = os.getenv("STAR_RAIL_COOKIE", "").strip()
    if not raw_cookie:
        print("未配置环境变量 STAR_RAIL_COOKIE，请在青龙面板添加后重试。")
        sys.exit(1)

    cookies = parse_cookies(raw_cookie)
    if not cookies:
        print("STAR_RAIL_COOKIE 内容格式不正确，请检查。")
        sys.exit(1)

    results = []
    for i, cookie in enumerate(cookies, start=1):
        if i > 1:
            time.sleep(random.randint(5, 10))  # 多账号之间随机延时
        results.append(run_for_account(i, cookie))

    message = "\n\n".join(results)
    print(message)

    # 青龙内置通知（容器外本地运行时静默跳过）
    try:
        from notify import send
        send("星穹铁道每日签到", message)
    except Exception:
        pass


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
