# -*- coding: utf-8 -*-
"""
new Env('星穹铁道签到');

================================================================================
 米游社 · 崩坏：星穹铁道 每日签到（青龙面板单文件脚本 · 全令牌版）
================================================================================

 【功能】
   1. 自动获取米游社账号下绑定的全部星铁角色（官服 / B 站服均可），查询并完成签到
   2. 展示当日奖励、累计签到天数；结果通过青龙内置通知 notify.send 推送
   3. 支持多个米游社账号（& 或换行分隔），单个账号失效不影响其它账号
   4. 【全令牌兼容】自动识别 v1 / v2 登录令牌：
        cookie_token、cookie_token_v2、ltoken、ltoken_v2、stoken、stoken_v2、
        account_id(_v2)、ltuid(_v2)、stuid、mid、account_mid_v2、ltmid_v2、login_ticket
   5. 【stoken 自动续期】当 cookie_token 失效(返回 -100)时，若提供了长效令牌
      stoken，脚本会自动调用官方接口换取新的 cookie_token 并重试，实现长期免维护；
      刷新后的凭证会缓存到本地文件（权限 600），下次运行优先复用。

 【两种使用模式】
   · 短期模式：环境变量只放签到 Cookie（含 cookie_token / cookie_token_v2）。
     网页令牌通常几天~一两周失效，失效后需重新抓 Cookie。
   · 长期模式（推荐）：环境变量放【含 stoken 的全套 Cookie】（可用配套油猴脚本
     “复制米哈游”得到，或从米游社 App 抓包获取）。此后 cookie_token 失效会自动
     用 stoken 续期，stoken 长效（通常数月），基本不用再手动维护。

 【青龙配置】
   1. 脚本管理 → 新建任务，或把本文件放入 /ql/data/scripts/ 目录
   2. 定时规则示例（每天上午 8:17，建议自选分钟降低风控概率）：17 8 * * *
   3. 环境变量 → 新建变量：
        变量名：STAR_RAIL_COOKIE
        变量值：一个或多个账号的 Cookie（多账号用 & 或换行分隔）
      可选变量：
        STAR_RAIL_CACHE_DIR  自定义凭证缓存目录（默认自动选择可写目录）

   多账号示例（& 连接，单行即可）：
     账号1的整段Cookie & 账号2的整段Cookie

 【如何获取 Cookie / stoken】
   · 签到 Cookie（cookie_token_v2 等，电脑浏览器）：
       1) 无痕窗口登录 https://www.miyoushe.com/sr/
       2) 访问签到页停留几秒：
          https://act.mihoyo.com/bbs/event/signin/hkrpg/index.html?act_id=e202304121516551
       3) 地址栏打开（retcode:0 即登录态生效）：
          https://api-takumi.mihoyo.com/binding/api/getUserGameRolesByCookie?game_biz=hkrpg_cn
       4) F12 → Network → 该请求 → Request Headers → Cookie，整段复制
   · stoken（长期续期令牌，普通网页登录不下发，二选一获取）：
       a) 米游社 App 抓包：用 Reqable / HttpCanary / Stream / Thor / Charles 等
          HTTPS 抓包工具，抓取 App 内请求，复制含 stoken(或 stoken_v2)、stuid、
          mid 的整段 Cookie；
       b) 配合本项目的油猴“通用 Token/Cookie 抓取器”，在能下发 stoken 的登录/
          授权页面自动收集后点“复制米哈游”。
     v2 版 stoken（值以 v2_ 开头）必须同时带 mid 字段，脚本会自动校验并提示。

 【安全】
   · Cookie / stoken 等同账号密码，请勿公开、勿提交到公开仓库。
   · 缓存文件仅保存在运行本机（默认权限 600），脚本不含任何对外上传凭证的逻辑。
   · 若频繁触发极验验证码，建议调大随机执行时间或手动签到一天。

 【本地调试】
   export STAR_RAIL_COOKIE='你的cookie'
   python3 starrail_checkin.py

  接口依据：社区维护项目 Womsxd/MihoyoBBSTools（act_id / salt / 续期接口）
================================================================================
"""

import os
import re
import sys
import json
import time
import random
import string
import hashlib
import uuid
import tempfile

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
# stoken 换取 cookie_token（长效令牌续期）
URL_CT_BY_STOKEN = BASE_URL + "/auth/api/getCookieAccountInfoBySToken"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 12; Unspecified Device) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/103.0.5060.129 Mobile Safari/537.36 "
    "miHoYoBBS/" + APP_VERSION
)

CACHE_FILENAME = ".starrail_checkin_cache.json"
RET_ALREADY_SIGN = -5003            # 今日已签到
RET_NOT_LOGIN = -100                # 登录态失效


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


def gen_device_id(seed: str) -> str:
    """用种子稳定生成一个设备 ID（uuid3）。"""
    return str(uuid.uuid3(uuid.NAMESPACE_URL, seed or "starrail_checkin"))


def build_headers(cookie: str) -> dict:
    """签到业务接口请求头（带 DS）。"""
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


def build_refresh_headers(stoken_cookie: str, seed: str) -> dict:
    """stoken 续期接口请求头（无 DS / Origin / Referer）。"""
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": USER_AGENT,
        "x-rpc-app_version": APP_VERSION,
        "x-rpc-client_type": CLIENT_TYPE,
        "x-rpc-channel": "miyousheluodi",
        "X-Requested-With": "com.mihoyo.hyperion",
        "Cookie": stoken_cookie,
        "x-rpc-device_id": gen_device_id(seed),
    }


# ------------------------------------------------------------------ #
# Cookie / 令牌解析
# ------------------------------------------------------------------ #
def cookie_to_dict(cookie: str) -> dict:
    """把 Cookie 字符串解析为有序 dict（保留首次出现顺序）。"""
    out = {}
    for part in str(cookie).split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and k not in out:
            out[k] = v
    return out


def dict_to_cookie(d: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in d.items() if v != "")


def first_value(d: dict, names) -> str:
    for n in names:
        v = d.get(n)
        if v:
            return v
    return ""


class Identity:
    """从 Cookie 中提取的账号身份与各类令牌。"""
    def __init__(self, cookie: str):
        self.raw = cookie
        self.d = cookie_to_dict(cookie)
        self.uid = first_value(self.d, [
            "stuid", "account_id", "account_id_v2", "ltuid", "ltuid_v2", "login_uid"])
        self.mid = first_value(self.d, ["mid", "account_mid_v2", "ltmid_v2"])
        self.stoken = first_value(self.d, ["stoken", "stoken_v2"])
        self.cookie_token = self.d.get("cookie_token", "")
        self.cookie_token_v2 = self.d.get("cookie_token_v2", "")
        self.ltoken = first_value(self.d, ["ltoken", "ltoken_v2"])

    @property
    def has_any_login_token(self) -> bool:
        return bool(self.stoken or self.cookie_token or
                    self.cookie_token_v2 or self.ltoken)

    @property
    def stoken_is_v2(self) -> bool:
        return self.stoken.startswith("v2_")

    def token_kinds(self) -> str:
        kinds = []
        if self.cookie_token:
            kinds.append("cookie_token")
        if self.cookie_token_v2:
            kinds.append("cookie_token_v2")
        if self.ltoken:
            kinds.append("ltoken")
        if self.stoken:
            kinds.append("stoken(v2)" if self.stoken_is_v2 else "stoken(v1)")
        return "+".join(kinds) if kinds else "无令牌"


# ------------------------------------------------------------------ #
# 本地凭证缓存（按 uid 保存刷新后的 Cookie，权限 600）
# ------------------------------------------------------------------ #
def find_cache_file() -> str:
    custom_dir = os.getenv("STAR_RAIL_CACHE_DIR", "").strip()
    candidates = []
    if custom_dir:
        candidates.append(os.path.join(custom_dir, CACHE_FILENAME))
    candidates += [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_FILENAME),
        os.path.join("/ql/data/config", CACHE_FILENAME),
        os.path.join("/ql/data", CACHE_FILENAME),
        os.path.join(os.path.expanduser("~"), CACHE_FILENAME),
        os.path.join(tempfile.gettempdir(), CACHE_FILENAME),
    ]
    for path in candidates:
        try:
            d = os.path.dirname(path) or "."
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".write_test")
            with open(test, "w") as f:
                f.write("1")
            os.remove(test)
            return path
        except OSError:
            continue
    return ""


CACHE_FILE = find_cache_file()


def load_cache() -> dict:
    if not CACHE_FILE:
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    if not CACHE_FILE:
        return
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(CACHE_FILE, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def merge_cookie(env_cookie: str, cached_cookie: str) -> str:
    """以环境变量 Cookie 为准，缓存补充环境变量里缺失的字段（如刷新出的 cookie_token）。"""
    if not cached_cookie:
        return env_cookie
    merged = cookie_to_dict(cached_cookie)   # 缓存打底
    merged.update(cookie_to_dict(env_cookie))  # 环境变量覆盖
    return dict_to_cookie(merged)


# ------------------------------------------------------------------ #
# HTTP
# ------------------------------------------------------------------ #
def http_request(method, url, headers, **kwargs):
    last_err = None
    for _ in range(3):
        try:
            return requests.request(method, url, headers=headers, timeout=20, **kwargs)
        except requests.RequestException as e:
            last_err = e
            time.sleep(3)
    raise last_err


# ------------------------------------------------------------------ #
# 业务接口
# ------------------------------------------------------------------ #
def get_roles(cookie: str) -> list:
    resp = http_request("GET", URL_ROLES, build_headers(cookie),
                        params={"game_biz": GAME_BIZ})
    data = resp.json()
    if data.get("retcode") == RET_NOT_LOGIN:
        raise CookieInvalidError(data.get("message", "Cookie 无效或已过期"))
    if data.get("retcode") != 0:
        raise ApiError(f"获取角色列表失败：retcode={data.get('retcode')} "
                       f"message={data.get('message')}")
    return [(i.get("nickname", ""), str(i.get("game_uid", "")), i.get("region", ""))
            for i in data.get("data", {}).get("list", [])]


def get_awards(cookie: str) -> list:
    resp = http_request("GET", URL_HOME, build_headers(cookie),
                        params={"lang": "zh-cn", "act_id": ACT_ID})
    data = resp.json()
    return data.get("data", {}).get("awards", []) if data.get("retcode") == 0 else []


def get_sign_info(cookie: str, region: str, uid: str) -> dict:
    resp = http_request("GET", URL_INFO, build_headers(cookie),
                        params={"lang": "zh-cn", "act_id": ACT_ID,
                                "region": region, "uid": uid})
    data = resp.json()
    if data.get("retcode") == RET_NOT_LOGIN:
        raise CookieInvalidError(data.get("message", "登录态失效"))
    if data.get("retcode") != 0:
        raise ApiError(f"获取签到状态失败：retcode={data.get('retcode')} "
                       f"message={data.get('message')}")
    return data.get("data", {})


def do_sign(cookie: str, region: str, uid: str) -> dict:
    resp = http_request("POST", URL_SIGN, build_headers(cookie),
                        json={"act_id": ACT_ID, "region": region, "uid": uid})
    return resp.json()


def award_text(awards: list, day_index: int) -> str:
    try:
        item = awards[day_index]
        return f"「{item.get('name')}」x{item.get('cnt')}"
    except (IndexError, KeyError, TypeError):
        return "奖励信息获取失败"


# ------------------------------------------------------------------ #
# 账号会话：封装 stoken 自动续期与失败重试
# ------------------------------------------------------------------ #
class CookieInvalidError(Exception):
    pass


class ApiError(Exception):
    pass


class StokenError(Exception):
    pass


class AccountSession:
    def __init__(self, index: int, cookie: str, cache: dict):
        self.index = index
        self.cache = cache
        self.cookie = cookie
        self.ident = Identity(cookie)
        self.notes = []                 # 运行过程中的提示信息
        self.refreshed = False         # 本次是否已执行过续期

        # 用缓存补全环境变量缺失字段
        if self.ident.uid and self.ident.uid in cache:
            merged = merge_cookie(cookie, cache[self.ident.uid].get("cookie", ""))
            if merged != cookie:
                self.cookie = merged
                self.ident = Identity(merged)

    # 用 stoken 换取新的 cookie_token（v1），返回是否成功
    def refresh_with_stoken(self) -> bool:
        ident = self.ident
        if not ident.stoken:
            raise StokenError("cookie_token 已失效，且未提供 stoken，无法自动续期；"
                              "请重新抓 Cookie，或补充含 stoken 的全套 Cookie。")
        if not ident.uid:
            raise StokenError("缺少账号 ID（stuid/account_id），无法用 stoken 续期。")
        if ident.stoken_is_v2 and not ident.mid:
            raise StokenError("v2 版 stoken 必须同时提供 mid 字段，否则无法续期。")

        stoken_cookie = f"stuid={ident.uid}; stoken={ident.stoken}"
        if ident.stoken_is_v2:
            stoken_cookie += f"; mid={ident.mid}"

        resp = http_request("GET", URL_CT_BY_STOKEN,
                            build_refresh_headers(stoken_cookie, self.cookie))
        data = resp.json()
        if data.get("retcode") != 0:
            raise StokenError(f"stoken 续期失败（retcode={data.get('retcode')}，"
                              f"message={data.get('message')}）；stoken 可能已失效，"
                              f"请重新获取全套 Cookie。")
        new_ct = (data.get("data") or {}).get("cookie_token")
        if not new_ct:
            raise StokenError("续期接口未返回 cookie_token。")

        d = cookie_to_dict(self.cookie)
        d["cookie_token"] = new_ct      # 注入/替换 v1 cookie_token
        # 补全账号 ID，保证后续接口身份完整
        d.setdefault("account_id", ident.uid)
        if ident.mid:
            d.setdefault("mid", ident.mid)
        self.cookie = dict_to_cookie(d)
        self.ident = Identity(self.cookie)
        self.refreshed = True
        self.notes.append("🔄 cookie_token 已用 stoken 自动续期")
        self._persist()
        return True

    def _persist(self):
        if self.ident.uid:
            self.cache[self.ident.uid] = {"cookie": self.cookie, "time": int(time.time())}

    # 执行业务调用；遇 -100 自动续期并重试一次
    def call(self, func, *args, **kwargs):
        try:
            return func(self.cookie, *args, **kwargs)
        except CookieInvalidError:
            if self.refreshed:
                raise
            self.refresh_with_stoken()   # 失败会抛 StokenError
            return func(self.cookie, *args, **kwargs)

    def sign_one_role(self, role, awards) -> str:
        nickname, uid, region = role
        title = f"{nickname}（UID {uid} / {region}）"
        info = self.call(get_sign_info, region, uid)

        if info.get("first_bind"):
            return f"⚠️ {title}：首次绑定，请先在米游社手动签到一次"

        total_days = int(info.get("total_sign_day", 0))
        if info.get("is_sign"):
            return f"✅ {title}：今日已签到，累计 {total_days} 天，今日奖励 {award_text(awards, total_days - 1)}"

        # 未签到 → 签到（-100 由 call 自动续期；sign 接口返回体单独判断）
        result = self._do_sign_with_retry(region, uid)
        retcode = result.get("retcode")
        res_data = result.get("data", {}) or {}

        if retcode == RET_NOT_LOGIN:
            # sign 接口直接返回 -100：续期后再签一次
            if not self.refreshed:
                self.refresh_with_stoken()
                result = self._do_sign_with_retry(region, uid)
                retcode = result.get("retcode")
                res_data = result.get("data", {}) or {}

        if retcode == 0 and res_data.get("success") == 1:
            return (f"⚠️ {title}：触发人机验证，本次未签到成功，请稍后手动签到或稍后重试\n"
                    f"    （gt={res_data.get('gt')}, challenge={res_data.get('challenge')}）")
        if retcode == 0 and res_data.get("success") == 0:
            reward = award_text(awards, total_days)
            return f"🎉 {title}：签到成功，累计 {total_days + 1} 天，今日奖励 {reward}"
        if retcode == RET_ALREADY_SIGN:
            return f"✅ {title}：今日已签到，累计 {total_days} 天，今日奖励 {award_text(awards, total_days - 1)}"
        return (f"❌ {title}：签到失败，retcode={retcode} "
                f"message={result.get('message')} raw={json.dumps(result, ensure_ascii=False)}")

    def _do_sign_with_retry(self, region, uid) -> dict:
        try:
            return self.call(do_sign, region, uid)
        except CookieInvalidError:
            return {"retcode": RET_NOT_LOGIN, "message": "登录态失效", "data": {}}


def parse_cookies(raw: str) -> list:
    """多账号：按换行、& 分隔；去重保持顺序。"""
    if not raw:
        return []
    out, seen = [], set()
    for p in re.split(r"[\n&]+", raw):
        c = p.strip().strip(";").strip()
        if c and "=" in c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def run_for_account(index: int, cookie: str, cache: dict) -> str:
    head = f"━━ 账号 {index} ━━"
    ident = Identity(cookie)

    # 预检：必须有账号 ID + 至少一种登录令牌
    if not ident.uid or not ident.has_any_login_token:
        missing = []
        if not ident.uid:
            missing.append("账号 ID（account_id / stuid）")
        if not ident.has_any_login_token:
            missing.append("登录令牌（cookie_token / cookie_token_v2 / ltoken / stoken）")
        return (f"{head}\n❌ Cookie 不可用：缺少{'、'.join(missing)}。\n"
                f"    请按脚本顶部说明，从 Network 请求头复制完整 Cookie（需含令牌字段），"
                f"长期免维护请提供含 stoken 的全套 Cookie。")

    sess = AccountSession(index, cookie, cache)
    tag = f"[UID {sess.ident.uid} · {sess.ident.token_kinds()}]"
    lines = [head, f"🔹 {tag}"]

    try:
        roles = sess.call(get_roles)
    except StokenError as e:
        lines.append(f"❌ {e}")
        return "\n".join(lines)
    except CookieInvalidError as e:
        lines.append(f"❌ Cookie 无效：{e}（且无法自动续期，请重新获取）")
        return "\n".join(lines)
    except ApiError as e:
        lines.append(f"❌ {e}")
        return "\n".join(lines)
    except Exception as e:
        lines.append(f"❌ 请求异常：{type(e).__name__}: {e}")
        return "\n".join(lines)

    if not roles:
        lines.append("⚠️ 该账号未绑定任何星铁角色（请确认已在米游社绑定游戏角色）")
        return "\n".join(lines)

    try:
        awards = sess.call(get_awards)
    except Exception:
        awards = []

    for n, role in enumerate(roles):
        if n > 0:
            time.sleep(random.randint(3, 7))
        try:
            lines.append(sess.sign_one_role(role, awards))
        except StokenError as e:
            lines.append(f"❌ {role[0]}（UID {role[1]}）：{e}")
        except ApiError as e:
            lines.append(f"❌ {role[0]}（UID {role[1]}）：{e}")
        except Exception as e:
            lines.append(f"❌ {role[0]}（UID {role[1]}）：异常 {type(e).__name__}: {e}")

    for note in sess.notes:
        lines.append(note)
    sess._persist()
    if sess.refreshed:
        save_cache(cache)
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

    cache = load_cache()
    results = []
    for i, cookie in enumerate(cookies, start=1):
        if i > 1:
            time.sleep(random.randint(5, 10))
        results.append(run_for_account(i, cookie, cache))

    save_cache(cache)
    message = "\n\n".join(results)
    print(message)
    if CACHE_FILE:
        print(f"\n[凭证缓存] {CACHE_FILE}")

    try:
        from notify import send
        send("星穹铁道每日签到", message)
    except Exception:
        pass


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
