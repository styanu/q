# -*- coding: utf-8 -*-
"""
UC极速版 · 任务刷法 + 真实养号（二合一终极版）
- 任务模式：刷福利中心视频任务获取元宝
- 养号模式：模拟真人浏览信息流、观看视频、互动，提升权重
- 智能切换：任务刷完自动养号，任务重置自动恢复
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
import random
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ========== 路径和停止文件 ==========
HERE = Path(__file__).resolve().parent
RESULT_PATH = HERE / "uc_ultimate_result.json"
STOP_PATH = HERE / "STOP_VIDEO_FARM.txt"
MODE_PATH = HERE / "UC_MODE.txt"

# ========== 常量 ==========
HOST_CORAL2 = "https://coral2.uc.cn"
HOST_CORAL_TASK = "https://coral-task.uc.cn"
FARM_SALT = "sy5th908xb9bmgiz2ssy0cykzezkq1jf"
MODULE_TASK = "8ee46ec7f90543a290e8667c02c0ecb2"
APP_ID_H5 = "_dft_uclite_piggy"
APP_ID_TASK = "uclite_piggy_task"
FVE = "3.9.46"
SIGN_RPC_DEFAULT = "http://127.0.0.1:17890"

# 视频任务模板（原版）
VIDEO_TIDS: List[Tuple[str, int]] = [
    ("1789725", 9671),
    ("39823", 9671),
    ("1795864", 9671),
    ("1795863", 9655),
    ("1792321", 9671),
    ("1795844", 9671),
    ("1794063", 9806),
]

UA = (
    "Mozilla/5.0 (Linux; U; Android 16; zh-CN; V2426A Build/BQ2A.250705.001) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/100.0.4896.58 "
    "UCBrowser/18.9.4.1458 Mobile Safari/537.36"
)

TOKEN_KEYS = (
    "kps", "ut", "st", "uid", "ds", "mt", "de", "dn", "ni", "lb", "wf",
    "ch", "ve", "sn", "mi", "bd", "fr", "pr", "nn", "pc", "od", "oc",
)

# ========== 防风控配置 ==========
ENABLE_NURTURE = os.getenv("UC_NURTURE", "1").lower() in ("1", "true", "yes")
DELAY_RANGE_STR = os.getenv("UC_DELAY_RANGE", "5,15")
try:
    DELAY_MIN, DELAY_MAX = map(float, DELAY_RANGE_STR.split(","))
except:
    DELAY_MIN, DELAY_MAX = 5.0, 15.0
MAX_EMPTY_LIMIT = int(os.getenv("UC_MAX_EMPTY", "5"))
INVALID_THRESHOLD = 3
JITTER_RANGE = (-2.0, 4.0)
BAN_CODES = ("ACCOUNT_BANNED", "ACCOUNT_DISABLED", "TOKEN_EXPIRED", "USER_BLOCKED", "FORBIDDEN")

# ========== 养号行为配置 ==========
P_LIKE = float(os.environ.get("UC_P_LIKE", "30"))          # 点赞概率%
P_COMMENT = float(os.environ.get("UC_P_COMMENT", "25"))    # 看评论概率%
P_FAV = float(os.environ.get("UC_P_FAV", "8"))             # 收藏概率%
P_FOLLOW = float(os.environ.get("UC_P_FOLLOW", "30"))      # 关注概率%
P_AD = float(os.environ.get("UC_P_AD", "60"))              # 看广告概率%
AD_MIN = int(os.environ.get("UC_AD_MIN", "5") or "5")
AD_MAX = int(os.environ.get("UC_AD_MAX", "30") or "30")
P_PAUSE = float(os.environ.get("UC_P_PAUSE", "12"))        # 暂停概率%
P_BACK = float(os.environ.get("UC_P_BACK", "6"))           # 回看概率%
P_SHARE = float(os.environ.get("UC_P_SHARE", "5"))         # 分享概率%

# ========== DNS 环境变量 ==========
os.environ.setdefault("DNS_SERVER", "463d89.dns.nextdns.io")

# ========== 日志函数 ==========
def log(msg: str, level: str = "信息") -> None:
    print(f"[{time.strftime('%H:%M:%S')}][{level}] {msg}", flush=True)

# ========== 辅助函数 ==========
def should_stop() -> bool:
    return STOP_PATH.exists()

def get_mode() -> int:
    env_mode = os.getenv("UC_MODE", "").strip()
    if env_mode in ("0", "1"):
        return int(env_mode)
    try:
        if MODE_PATH.exists():
            txt = MODE_PATH.read_text(encoding="utf-8").strip()
            if txt in ("0", "1"):
                return int(txt)
    except Exception:
        pass
    return 0

def _parse_kv_blob(blob: str) -> Dict[str, str]:
    blob = (blob or "").strip()
    out = {}
    if not blob:
        return out
    if blob.startswith("{") and blob.endswith("}"):
        try:
            j = json.loads(blob)
            if isinstance(j, dict):
                for k, v in j.items():
                    out[str(k)] = str(v)
                return out
        except Exception:
            pass
    sep = "&" if "&" in blob else (";" if ";" in blob else "\n")
    for part in blob.split(sep):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out

def parse_accounts(raw: str) -> List[Dict[str, Any]]:
    accounts = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "#" not in s:
            log(f"账号行缺少 # 分隔符: {s[:40]}…", "警告")
            continue
        label, _, token_str = s.partition("#")
        label = label.strip()
        token_str = token_str.strip()
        kv = _parse_kv_blob(token_str)
        tok = {}
        for k in TOKEN_KEYS:
            v = kv.get(k)
            if v:
                tok[k] = v
        if not tok.get("kps"):
            for alt in ("X-U-KPS-WG", "X_U_KPS_WG", "KPS"):
                if kv.get(alt):
                    tok["kps"] = kv[alt]
                    break
        user = label or f"acc{len(accounts)+1}"
        if not tok.get("kps"):
            log(f"账号行缺少 kps: {line[:40]}…", "警告")
            continue
        if not tok.get("ut"):
            log(f"账号行缺少 ut: {label}", "警告")
        accounts.append({
            "label": label or user,
            "user": user,
            "token": tok,
        })
    return accounts

def notify(title: str, content: str) -> None:
    try:
        from notify import send
        send(title, content)
    except Exception:
        pass

# ========== SignRPC ==========
class SignRPC:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.trust_env = False

    def ok(self) -> bool:
        try:
            return bool(self.s.get(self.base + "/", timeout=5).json().get("ok"))
        except Exception:
            return False

    def farm_sign(self, plain: str) -> str:
        last = None
        for i in range(2):
            try:
                j = self.s.post(
                    self.base + "/farm_sign",
                    json={"plain": plain, "salt": "", "op": "farm_sign"},
                    timeout=70,
                ).json()
            except Exception as e:
                last = str(e)
                log(f"加签异常 重试{i+1}: {e}", "警告")
                time.sleep(8 + i * 8)
                continue
            if j.get("ok") and j.get("sign"):
                return str(j["sign"])
            last = j.get("error") or j
            log(f"加签失败 重试{i+1}: {last}", "警告")
            time.sleep(12 + i * 10)
        raise RuntimeError(f"加签失败: {last}")

# ========== Client（任务刷取 + 真实养号） ==========
class Client:
    def __init__(self, tok: Dict[str, Any], rpc_url: str) -> None:
        self.tok = tok
        self.kps = tok["kps"]
        self.ut = tok.get("ut") or ""
        self.rpc = SignRPC(rpc_url)
        self.s = requests.Session()
        self.s.trust_env = False
        self.ua_pool = [
            UA,
            "Mozilla/5.0 (Linux; Android 15; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
            "Mozilla/5.0 (Linux; Android 13; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.5993.111 Mobile Safari/537.36",
        ]
        self._ua_index = 0

    def _rotate_ua(self) -> str:
        ua = self.ua_pool[self._ua_index % len(self.ua_pool)]
        self._ua_index += 1
        return ua

    def headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self._rotate_ua(),
            "Accept": "application/json",
            "Origin": "https://broccoli.uc.cn",
            "Referer": "https://broccoli.uc.cn/",
            "X-U-KPS-WG": self.kps,
            "Content-Type": "application/json;charset=UTF-8",
        }

    def qbase(self) -> Dict[str, str]:
        t = self.tok
        return {
            "uc_param_str": "dsdnfrpfbivessbtbmnilauputogpintnwmtsvcppcprsnnnchmicgodmekplobdmicgodcadebcaaoclbwf",
            "kps": self.kps,
            "ut": self.ut,
            "fr": "android",
            "pr": "UCLite",
            "ve": t.get("ve") or "18.9.4.1458",
            "ch": t.get("ch") or "",
            "ds": t.get("ds") or "",
            "mt": t.get("mt") or "",
            "de": t.get("de") or "",
            "dn": t.get("dn") or "",
            "ni": t.get("ni") or "",
            "lb": t.get("lb") or "",
            "wf": t.get("wf") or "",
            "sn": t.get("sn") or "",
            "mi": t.get("mi") or "",
            "bd": t.get("bd") or "",
            "appId": APP_ID_H5,
        }

    # ---------- 视频任务获取（原版） ----------
    def list_video_tasks(self) -> List[Dict[str, Any]]:
        self._random_sleep()
        q = self.qbase()
        q.update({
            "__t": str(int(time.time() * 1000)),
            "entry": "toolbar",
            "evSub": "uclite_fuli_index",
            "codes": "uc_piggy_task_nest,uc_piggy_limit_time,uc_piggy_xssvideo_fuli",
            "requestId": str(uuid.uuid4()),
            "fve": FVE,
            "activeUser": "1",
            "prioritySize": "1",
        })
        r = self.s.get(
            f"{HOST_CORAL2}/uclite/queryByMultiResource",
            params=q, headers=self.headers(), timeout=25,
        )
        j = r.json() if r.text.startswith("{") else {}
        out = []
        for _, block in (j.get("data") or {}).items():
            if not isinstance(block, dict):
                continue
            for t in block.get("taskList") or []:
                ev = str(t.get("event") or "")
                name = str(t.get("name") or "")
                gc = str(t.get("groupCode") or "")
                if ev == "video_ad_new" or "视频" in name or gc in ("video", "video_advanced"):
                    ri = t.get("rewardItems") or [{}]
                    out.append({
                        "id": str(t.get("id")),
                        "name": t.get("name"),
                        "dayTimes": t.get("dayTimes"),
                        "publishId": t.get("publishId") or 9671,
                        "amount": (ri[0] or {}).get("amount"),
                    })
        return out

    def claim_video(self, tid: str, publish_id: int) -> Dict[str, Any]:
        self._random_sleep()
        def _do_coral2(rid: str, sign: str) -> Dict[str, Any]:
            body = {
                "kps": self.kps, "appId": APP_ID_H5, "moduleCode": MODULE_TASK,
                "useUtCompleteTask": False, "publishId": int(publish_id),
                "fve": FVE, "tid": int(tid), "type": "complete", "value": 1,
                "requestId": rid, "sign": sign, "salt": FARM_SALT,
            }
            r = self.s.post(
                f"{HOST_CORAL2}/uclite/trigger",
                params=self.qbase(), json=body, headers=self.headers(), timeout=30,
            )
            try:
                return r.json()
            except Exception:
                return {"raw": r.text[:200]}

        def _do_coral_task(rid: str, sign: str) -> Dict[str, Any]:
            params = {
                "appId": APP_ID_TASK, "moduleCode": MODULE_TASK,
                "value": "1", "type": "complete", "kps": self.kps,
                "requestId": rid, "salt": FARM_SALT, "sign": sign,
                "tid": str(tid), "_ch": "native",
                "uc_param_str": "utpcsnnnvebipfdnprfrcgch",
                "ve": self.tok.get("ve") or "18.9.4.1458",
                "fr": "android", "ut": self.ut, "entry": "toolbar",
                "from": "", "pr": "UCLite", "ch": self.tok.get("ch") or "",
            }
            r = self.s.get(
                f"{HOST_CORAL_TASK}/task/trigger",
                params=params, headers={"User-Agent": self._rotate_ua(), "X-U-KPS-WG": self.kps},
                timeout=30,
            )
            try:
                return r.json()
            except Exception:
                return {"raw": r.text[:200]}

        rid = str(uuid.uuid4())
        try:
            sign = self.rpc.farm_sign(f"{self.ut}{tid}complete1{rid}{FARM_SALT}")
        except Exception as e:
            return {"tid": tid, "ok": False, "error": f"加签失败: {e}"}
        j = _do_coral2(rid, sign)
        path = "coral2"
        prz = self.prize(j if isinstance(j, dict) else {})
        good = bool(j.get("success") and j.get("code") == "OK" and isinstance(prz, int) and prz > 0)

        if not good:
            rid2 = str(uuid.uuid4())
            try:
                sign2 = self.rpc.farm_sign(f"{self.ut}{tid}complete1{rid2}{FARM_SALT}")
            except Exception as e:
                if j.get("success") and j.get("code") == "OK":
                    cur = (j.get("data") or {}).get("curTask") or {}
                    return {"tid": tid, "ok": True, "code": j.get("code"),
                            "msg": j.get("msg"), "prize": prz,
                            "dayTimes": cur.get("dayTimes"), "path": path}
                return {"tid": tid, "ok": False, "code": j.get("code"),
                        "msg": j.get("msg"), "error": f"回退加签失败: {e}"}
            j2 = _do_coral_task(rid2, sign2)
            p2 = self.prize(j2 if isinstance(j2, dict) else {})
            if j2.get("success") and j2.get("code") == "OK" and isinstance(p2, int) and p2 > 0:
                j, path, prz = j2, "coral-task", p2
            elif (not (j.get("success") and j.get("code") == "OK")) and j2.get("success") and j2.get("code") == "OK":
                j, path, prz = j2, "coral-task", p2
            elif not (j.get("success") and j.get("code") == "OK"):
                return {"tid": tid, "ok": False, "code": j.get("code") or j2.get("code"),
                        "msg": j.get("msg") or j2.get("msg"),
                        "fallback_code": j2.get("code"), "path": path}

        cur = (j.get("data") or {}).get("curTask") or {}
        prize = self.prize(j)
        ok = bool(j.get("success") and j.get("code") == "OK")
        return {"tid": tid, "ok": ok, "code": j.get("code"), "msg": j.get("msg"),
                "prize": prize, "dayTimes": cur.get("dayTimes"), "path": path}

    @staticmethod
    def prize(j: Dict[str, Any]) -> Optional[int]:
        data = j.get("data") or {}
        pr = data.get("prizes") or []
        if pr:
            try:
                amt = (pr[0].get("rewardItem") or pr[0]).get("amount")
                if amt is not None:
                    return int(amt)
            except Exception:
                pass
        cur = data.get("curTask") or {}
        for ri in cur.get("rewardItems") or []:
            try:
                if ri.get("amount") is not None:
                    return int(ri.get("amount"))
            except Exception:
                pass
        if data.get("amount") is not None:
            try:
                return int(data.get("amount"))
            except Exception:
                pass
        return None

    def _random_sleep(self) -> None:
        wait = random.uniform(DELAY_MIN, DELAY_MAX) + random.uniform(*JITTER_RANGE)
        wait = max(0.5, wait)
        time.sleep(wait)

    # ---------- 真实养号（从模板搬运） ----------
    def nurture_actions(self) -> None:
        """执行一组养号动作（浏览、观看、互动）"""
        if not ENABLE_NURTURE:
            return
        # 随机选择动作类型：浏览信息流、观看视频、看短剧、阅读文章
        actions = [
            self._browse_feed,
            self._watch_video_from_feed,
            self._browse_drama,
            self._read_article,
        ]
        # 每次执行 1~3 个动作
        for _ in range(random.randint(1, 3)):
            action = random.choice(actions)
            try:
                action()
                time.sleep(random.uniform(2.0, 6.0) + random.uniform(*JITTER_RANGE))
            except Exception as e:
                log(f"养号动作异常: {e}", "警告")

    # ---------- 获取信息流 ----------
    def _get_feed(self, channel_id: int = 20317, count: int = 20) -> List[Dict]:
        url = "https://iflow.uczzd.cn/iflow/api/v2/channel/{}".format(channel_id)
        extra = {
            "method": "his", "ftime": "0", "recoid": "",
            "count": str(count), "content_ratio": "100", "content_length": "2048",
            "no_op": "0", "dft_cid": "100",
            "req_index": "0", "ch_req_index": "0",
            "first_refresh": "1",
            "install_time": str(int(time.time() * 1000) - random.randint(300000, 900000)),
            "from_cid": "100",
        }
        params = self.qbase()
        params.update({k: str(v) for k, v in extra.items() if v is not None})
        # 使用 iflow 专用 UA
        headers = self.headers()
        headers["User-Agent"] = UA
        try:
            r = self.s.post(url, params=params, headers=headers, timeout=15)
            data = r.json()
            articles = data.get("data", {}).get("articles", {})
            if isinstance(articles, dict):
                items = list(articles.values())
            elif isinstance(articles, list):
                items = articles
            else:
                items = []
            return items
        except Exception as e:
            log(f"获取信息流失败: {e}", "警告")
            return []

    def _browse_feed(self) -> None:
        """浏览信息流，随机滚动"""
        log("养号：浏览信息流", "调试")
        items = self._get_feed(count=10)
        if not items:
            return
        # 随机浏览 3~8 条
        for item in random.sample(items, min(len(items), random.randint(3, 8))):
            if should_stop():
                break
            title = item.get("title", "")[:30]
            log(f"  浏览: {title}", "调试")
            # 模拟滑动停留
            time.sleep(random.uniform(2.0, 5.0) + random.uniform(*JITTER_RANGE))
            # 随机互动
            if random.random() < P_LIKE / 100:
                aid = str(item.get("id", ""))
                if aid:
                    self._like_article(aid, item)
            if random.random() < P_COMMENT / 100 * 0.5:
                aid = str(item.get("id", ""))
                if aid:
                    self._view_comments(aid)
            # 随机暂停
            if random.random() < P_PAUSE / 100:
                time.sleep(random.uniform(1.0, 3.0))

    def _watch_video_from_feed(self) -> None:
        """从信息流中选取一个视频观看"""
        log("养号：观看视频", "调试")
        items = self._get_feed(count=15)
        videos = [item for item in items if item.get("videos") or item.get("small_video")]
        if not videos:
            return
        item = random.choice(videos)
        title = item.get("title", "")[:30]
        log(f"  观看视频: {title}", "调试")
        # 提取视频信息
        v = item.get("videos", [{}])[0] if item.get("videos") else item.get("small_video", {})
        vurl = v.get("url", "")
        duration = v.get("length", 30000) // 1000
        watch_time = min(max(int(duration * random.uniform(0.5, 0.95)), 5), 90)
        # 模拟观看（下载流）
        if vurl.startswith("http"):
            self._stream_video(vurl, watch_time)
        else:
            time.sleep(watch_time)
        # 互动
        aid = str(item.get("id", ""))
        if aid:
            if random.random() < P_LIKE / 100:
                self._like_article(aid, item)
            if random.random() < P_COMMENT / 100:
                self._view_comments(aid)
        if random.random() < P_PAUSE / 100:
            time.sleep(random.uniform(1.0, 3.0))

    def _browse_drama(self) -> None:
        """浏览短剧"""
        log("养号：浏览短剧", "调试")
        # 短剧频道 10800
        items = self._get_feed(channel_id=10800, count=10)
        if not items:
            return
        drama = random.choice(items)
        title = drama.get("title", "")[:30]
        log(f"  短剧: {title}", "调试")
        # 模拟观看 1~2 集
        show_attr = drama.get("show_attr_info", {})
        total_ep = show_attr.get("total_episode", 0)
        if total_ep > 0:
            watch_ep = random.randint(1, min(3, total_ep))
        else:
            watch_ep = random.randint(1, 2)
        for ep in range(watch_ep):
            time.sleep(random.uniform(30, 90))
            if random.random() < 0.2:
                time.sleep(random.uniform(3, 8))
        # 互动
        aid = str(drama.get("id", ""))
        if aid:
            if random.random() < P_LIKE / 100:
                self._like_article(aid, drama)
            if random.random() < P_COMMENT / 100 * 0.6:
                self._view_comments(aid)

    def _read_article(self) -> None:
        """阅读文章"""
        log("养号：阅读文章", "调试")
        items = self._get_feed(count=10)
        articles = [item for item in items if not item.get("videos") and not item.get("small_video")]
        if not articles:
            return
        item = random.choice(articles)
        title = item.get("title", "")[:30]
        log(f"  阅读: {title}", "调试")
        # 阅读时长
        content_len = item.get("content_length", 500)
        read_time = min(max(int(content_len / 200), 5), 35)
        time.sleep(random.uniform(read_time * 0.6, read_time * 1.2))
        # 互动
        aid = str(item.get("id", ""))
        if aid:
            if random.random() < P_LIKE / 100:
                self._like_article(aid, item)
            if random.random() < P_COMMENT / 100 * 0.5:
                self._view_comments(aid)

    def _stream_video(self, vurl: str, watch_seconds: int) -> None:
        """流式下载视频模拟观看"""
        try:
            headers = {
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Encoding": "identity;q=1, *;q=0",
                "Range": "bytes=0-",
                "Referer": "https://iflow.uczzd.cn/",
            }
            resp = requests.get(vurl, headers=headers, stream=True, timeout=30, verify=False)
            if resp.status_code not in (200, 206):
                resp.close()
                return
            chunk_size = 65536
            total = 0
            start = time.time()
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    break
                total += len(chunk)
                if time.time() - start >= watch_seconds:
                    break
            resp.close()
        except Exception:
            # 失败则 sleep 模拟
            time.sleep(watch_seconds)

    def _like_article(self, aid: str, item: Dict = None) -> None:
        """点赞文章"""
        # 使用 iflow cmt/like 接口
        url = f"https://iflow.uczzd.cn/iflow/api/v1/cmt/article/like/{aid}"
        params = {
            "uc_param_str": "dnnivebichfrmintcpgieiwidsudpf",
            "dn": self.tok.get("dn", ""),
            "ni": self.tok.get("ni", ""),
            "ut": self.tok.get("ut", ""),
        }
        try:
            r = self.s.post(url, params=params, timeout=10)
            if r.status_code == 200:
                log("养号：点赞成功", "调试")
        except Exception:
            pass

    def _view_comments(self, aid: str) -> None:
        """看评论"""
        url = f"https://m.uczzd.cn/iflow/api/v2/cmt/article/{aid}/comments/bypop"
        params = {"app": "uclite15m-iflow", "bid": "800", "count": "20", "flat": "1"}
        try:
            r = self.s.get(url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", {})
                comments = data.get("comments", [])
                cnt = len(comments) if isinstance(comments, list) else 0
                if cnt > 0:
                    read_count = min(random.randint(2, 8), cnt)
                    log(f"养号：看了{read_count}条评论", "调试")
                    time.sleep(read_count * 1.5)
        except Exception:
            pass

    def is_banned_response(self, response: Dict[str, Any]) -> bool:
        code = str(response.get("code") or "")
        msg = str(response.get("msg") or "")
        for ban in BAN_CODES:
            if ban in code.upper() or ban in msg.upper():
                return True
        if response.get("success") is False and "封禁" in msg:
            return True
        return False

# ========== 辅助：视频任务候选 ==========
def video_cands(api_tasks: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
    m: Dict[str, int] = {t: p for t, p in VIDEO_TIDS}
    for t in api_tasks:
        tid = str(t.get("id") or "")
        if tid:
            try:
                m[tid] = int(t.get("publishId") or m.get(tid) or 9671)
            except Exception:
                m[tid] = m.get(tid) or 9671
    return list(m.items())

# ========== 单账号主循环（任务 + 养号融合） ==========
def run_one_account(account: Any, rpc: str) -> Dict[str, Any]:
    if isinstance(account, dict):
        user = str(account.get("user") or account.get("label") or "acc")
        preset_token = dict(account.get("token") or {})
        label = str(account.get("label") or user)
    else:
        user, preset_token, label = str(account), {}, str(account)

    log("=" * 48)
    log(f"账号 {label} 开始")
    log("=" * 48)

    if not preset_token.get("kps"):
        raise RuntimeError(f"账号 {label} 缺少 kps")
    tok = dict(preset_token)
    tok.setdefault("user", user)
    if not tok.get("ut"):
        raise RuntimeError(f"账号 {label} 缺少 ut")

    client = Client(tok, rpc)
    res: Dict[str, Any] = {
        "user": user,
        "claims": [],
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_coin": 0,
        "nurture_stats": {"videos": 0, "dramas": 0, "articles": 0, "likes": 0, "comments": 0},
    }

    # ========== 任务状态 ==========
    progress: Dict[str, int] = {}
    target: Dict[str, int] = {}
    full: Set[str] = set()
    dead: Set[str] = set()
    miss: Dict[str, int] = {}
    empty: Dict[str, int] = {}
    invalid: Dict[str, int] = {}
    got_prize: Set[str] = set()
    cands = []
    active = []

    def refresh_tasks():
        nonlocal cands, active
        tasks = client.list_video_tasks()
        tmp_cands = []
        for t in tasks:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            day = t.get("dayTimes") if isinstance(t.get("dayTimes"), dict) else {}
            try:
                dp = int(day.get("progress")) if day.get("progress") is not None else -1
            except:
                dp = -1
            try:
                dt = int(day.get("target")) if day.get("target") is not None else -1
            except:
                dt = -1
            amt = t.get("amount") or 0
            if tid in full or tid in dead:
                continue
            if dt > 0 and dp >= dt:
                full.add(tid)
                continue
            tmp_cands.append((tid, t.get("publishId", 9671), amt, dp, dt))
        tmp_cands.sort(key=lambda x: x[2], reverse=True)
        cands = [(tid, pub) for tid, pub, _, _, _ in tmp_cands]
        active = [(tid, pub) for tid, pub in cands if tid not in full and tid not in dead]
        for tid, pub, amt, dp, dt in tmp_cands:
            if dt > 0:
                target[tid] = dt
            if dp > 0:
                progress[tid] = dp
        log(f"任务列表刷新，当前可刷 {len(active)} 个", "调试")

    refresh_tasks()

    ok_n = prize_sum = 0
    tick = 0
    no_gain_rounds = 0
    account_banned = False
    idle_rounds = 0
    IDLE_CHECK_INTERVAL = 10

    # 养号计数器
    nurture_round = 0

    while True:
        if should_stop():
            res["stop_reason"] = "停止文件"
            log("检测到停止文件", "信息")
            break

        mode = get_mode()
        if mode == 1:
            log("当前模式：强制养号", "信息")
            # 执行较长的养号
            for _ in range(random.randint(3, 6)):
                if should_stop():
                    break
                client.nurture_actions()
                time.sleep(random.uniform(2.0, 5.0))
            time.sleep(random.uniform(5, 15))
            no_gain_rounds = 0
            continue

        # ----- 任务模式 -----
        active = [(tid, pub) for tid, pub in cands if tid not in full and tid not in dead]

        if not active:
            log("当前无任务，进入养号模式", "信息")
            # 执行养号
            for _ in range(random.randint(3, 6)):
                if should_stop():
                    break
                client.nurture_actions()
                time.sleep(random.uniform(2.0, 5.0))
            # 每隔一段时间刷新任务列表
            idle_rounds += 1
            if idle_rounds % IDLE_CHECK_INTERVAL == 0:
                refresh_tasks()
                active = [(tid, pub) for tid, pub in cands if tid not in full and tid not in dead]
                if active:
                    log("发现新任务，回到任务模式", "成功")
                    idle_rounds = 0
                    no_gain_rounds = 0
                    continue
            time.sleep(random.uniform(5, 15))
            no_gain_rounds = 0
            continue

        # 排序任务
        def _rank(item):
            tid, _ = item
            sc = 0
            if tid in got_prize:
                sc += 1000
            if progress.get(tid, 0) > 0:
                sc += 100 + int(progress.get(tid) or 0)
            sc -= int(miss.get(tid, 0)) * 50
            sc -= int(empty.get(tid, 0)) * 5
            sc -= int(invalid.get(tid, 0)) * 100
            return -sc
        active_sorted = sorted(active, key=_rank)

        tick += 1
        if tick == 1 or tick % 20 == 0:
            log(f"任务进度点#{tick} 待刷{[t for t,_ in active_sorted]}")
        round_prize = 0
        round_ok = 0

        for tid, pub in active_sorted:
            if should_stop():
                break
            if tid in full or tid in dead:
                continue
            if tid in progress and tid in target and progress[tid] > 0 and progress[tid] >= target[tid]:
                full.add(tid)
                log(f"任务 {tid} 已达上限 {progress[tid]}/{target[tid]}")
                continue

            # 任务间隙养号（概率 30%）
            if random.random() < 0.3:
                client.nurture_actions()

            item = client.claim_video(tid, pub)

            if client.is_banned_response(item):
                log(f"账号 {label} 疑似被封禁！响应: {item}", "错误")
                account_banned = True
                res["stop_reason"] = "账号被封禁"
                notify("UC刷视频封号", f"账号 {label} 被封禁，请检查！")
                break

            # 处理结果
            code = str(item.get("code") or "")
            pr = item.get("prize")
            day = item.get("dayTimes") if isinstance(item.get("dayTimes"), dict) else {}
            try:
                dp = int(day.get("progress")) if day.get("progress") is not None else None
            except:
                dp = None
            try:
                dt = int(day.get("target")) if day.get("target") is not None else target.get(tid)
            except:
                dt = target.get(tid)
            if dt is not None and dt > 0:
                target[tid] = dt

            old_progress = progress.get(tid, 0)
            new_progress = dp
            ok = item.get("ok") and isinstance(pr, int) and pr > 0 and (new_progress is not None and new_progress > old_progress)

            if new_progress is not None:
                progress[tid] = new_progress

            item["old_progress"] = old_progress
            item["new_progress"] = new_progress
            item["valid"] = ok
            item["tick"] = tick
            res["claims"].append(item)

            if ok:
                got_prize.add(tid)
                empty[tid] = 0
                miss[tid] = 0
                invalid[tid] = 0
                ok_n += 1
                round_ok += 1
                prize_sum += int(pr)
                round_prize += int(pr)
                res["total_coin"] = res.get("total_coin", 0) + int(pr)
                log(f"成功 任务{tid} 奖={pr} 进度={new_progress}/{target.get(tid, '?')} 累计奖~{prize_sum}", "成功")
                if tid in progress and tid in target and progress[tid] > 0 and progress[tid] >= target[tid]:
                    full.add(tid)
                    log(f"任务 {tid} 已满")
                refresh_tasks()
            else:
                # 失败处理
                if code in ("TASK_DAY_LIMIT", "DAY_LIMIT", "TIMES_LIMIT"):
                    full.add(tid)
                    log(f"任务 {tid} 日限，停止")
                elif code in ("TASK_NOT_FOUND", "ILLEGAL_TYPE"):
                    miss[tid] = miss.get(tid, 0) + 1
                    if miss[tid] >= 1:
                        dead.add(tid)
                        log(f"任务 {tid} 连续 {code}，移出")
                    else:
                        log(f"任务 {tid} {code}，尝试 {miss[tid]}/1")
                else:
                    empty[tid] = empty.get(tid, 0) + 1
                    log(f"任务 {tid} 未完成，连续{empty[tid]}次")
                    if empty[tid] >= MAX_EMPTY_LIMIT:
                        invalid[tid] = invalid.get(tid, 0) + 1
                        if invalid[tid] >= INVALID_THRESHOLD:
                            dead.add(tid)
                            log(f"任务 {tid} 可疑次数过多，移出")
                        else:
                            empty[tid] = 0
                            log(f"任务 {tid} 冷却60秒")
                            time.sleep(60 + random.uniform(*JITTER_RANGE))

            # 冷却
            _sleep = 5.0
            if invalid.get(tid, 0) > 0:
                _sleep = max(_sleep, 20.0)
            if empty.get(tid, 0) >= 3:
                _sleep = max(_sleep, 15.0)
            jitter = random.uniform(*JITTER_RANGE)
            _sleep = max(1.0, _sleep + jitter)
            time.sleep(_sleep)

        if account_banned:
            break

        alive = [t for t, _ in cands if t not in full and t not in dead]
        log(f"批次完成: 本批奖+{round_prize} 成功{round_ok} 待刷{len(alive)} 已满{sorted(full)} 失效{sorted(dead)}")

        if not alive:
            log("所有任务已满或失效，进入养号模式等待重置")
            no_gain_rounds = 0
            # 长时间养号
            for _ in range(5):
                if should_stop():
                    break
                client.nurture_actions()
                time.sleep(random.uniform(3, 8))
            refresh_tasks()
            continue

        if round_prize <= 0 and round_ok <= 0:
            no_gain_rounds += 1
        else:
            no_gain_rounds = 0
        if no_gain_rounds >= 200:
            res["stop_reason"] = "长时间无收益"
            log("长时间无收益，结束")
            break

        time.sleep(random.uniform(2.0, 5.0))

    res.update({
        "ok_count": ok_n,
        "prize_sum": prize_sum,
        "rounds": tick,
        "full": sorted(full),
        "dead": sorted(dead),
        "ended": time.strftime("%Y-%m-%d %H:%M:%S"),
        "banned": account_banned,
    })
    log(f"账号结束: 成功{ok_n} 累计奖~{prize_sum} {res.get('stop_reason', '')}")
    return res

# ========== 主入口 ==========
def main() -> int:
    log("UC极速版 · 任务+养号二合一最终版")
    raw = os.getenv("UC_ACCOUNTS", "").strip()
    if not raw:
        log("请配置 UC_ACCOUNTS", "错误")
        return 2
    accounts = parse_accounts(raw)
    if not accounts:
        log("解析账号失败", "错误")
        return 2

    rpc = os.getenv("UC_SIGN_RPC", "").strip() or SIGN_RPC_DEFAULT
    if not SignRPC(rpc).ok():
        log(f"SignRPC 不可用: {rpc}", "错误")
        return 2

    log(f"共 {len(accounts)} 个账号")
    all_res = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "accounts": []}
    for acc in accounts:
        try:
            one = run_one_account(acc, rpc)
            all_res["accounts"].append(one)
        except Exception as e:
            lab = acc.get("label", "?")
            log(f"账号 {lab} 失败: {e}", "错误")
            all_res["accounts"].append({"user": lab, "error": str(e)})

    RESULT_PATH.write_text(json.dumps(all_res, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"结果已保存 → {RESULT_PATH.name}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("中断", "警告")
        raise SystemExit(130)