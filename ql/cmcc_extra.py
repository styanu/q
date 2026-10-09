# -*- coding: utf-8 -*-
"""中国移动签到页 AI豆任务 拓展模块（cmcc_extra.py）


核心接口：
  POST /qwhdhub/api/mark/task/taskList        任务列表
  POST /qwhdhub/api/mark/task/taskInfo        任务详情（返回 taskType、scanTime、cToken）
  POST /qwhdhub/api/mark/task/finishTask      完成任务 {taskId, taskType}
  POST /qwhdhub/api/mark/task/getTaskAward    领取奖励

任务完成策略（参考 yupaiLy/cmcc-auto-checkin）：
  1. 对 http(s) jumpUrl：先 GET 到访目标页，停留 scanTime 秒
  2. 调用 finishTask，Referer 设为 jumpUrl（服务端校验 Referer=目标页）
  3. finishTask 参数只需 {taskId, taskType}，taskType 从 taskInfo 获取
  4. 返回"特殊处理"的任务走 hlwyxhdhub 握手（需 jumpUrl 含 taskToken）

实测可完成的任务类型：
  - taskType=2：中国移动内部页面浏览任务（到访PV即可）
  - 福利活动区部分任务
无法完成的任务类型：
  - taskType=6：外部APP跳转（需真实打开APP）
  - taskType=10：拼图/抽奖类（需真实交互）
"""

import logging
import random
import re
import sys
import time
from types import SimpleNamespace

import requests

log = logging.getLogger("cmcc_extra")
# 兜底：若被独立运行且未配置 root logger，给出基本输出
if not logging.root.handlers:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

API_MARK = "https://wx.10086.cn/qwhdhub/api/mark"
BASE = "https://wx.10086.cn"

# 跳转任务握手页（hlwyxhdhub 域）
OPEN_TASK_ENTRY = f"{BASE}/hlwyxhdhub/act-wedrecharge/index.html?pageId=1849008675699650560"


def _post(s: requests.Session, referer: str, url_or_path: str, data: dict) -> dict:
    """统一 POST helper。

    - url_or_path 以 http 开头时按完整 URL 使用（用于 hlwyxhdhub 等非 mark 域内接口）；
    - 否则视为 /qwhdhub/api/mark 下的相对路径，自动拼前缀。
    referer 由调用方按接口要求传入（finishTask 需传目标页 jumpUrl 作 Referer）。
    """
    headers = {
        "accept": "*/*",
        "content-type": "application/json;charset=UTF-8",
        "origin": BASE,
        "referer": referer,
        "login-check": "1",
        "x-requested-with": "XMLHttpRequest",
    }
    url = url_or_path if url_or_path.startswith("http") else f"{API_MARK}{url_or_path}"
    r = s.post(url, json=data, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def task_list(s, referer):
    return _post(s, referer, "/task/taskList", {})


def task_info(s, referer, task_id):
    return _post(s, referer, "/task/taskInfo", {"taskId": task_id})


def get_award(s, referer, task_id):
    return _post(s, referer, "/task/getTaskAward", {"taskId": task_id})


def open_finish_task(cfg, task: dict) -> bool:
    """跳转类任务握手：jumpUrl 含 taskToken 时走 hlwyxhdhub 握手。

    流程：换 hlwyxhdhub 会话 → getOneTaskInfo 取 cToken → 停留 scanTime → openFinish。
    """
    ju = str(task.get("jumpUrl") or "")
    m = re.search(r"taskToken=([^&]+)", ju)
    if not m:
        return False
    try:
        from cmcc_sign import exchange_session

        # 仅覆盖 act_url，其余字段（province/city/phone/...）沿用原 cfg
        wrapped = SimpleNamespace(**vars(cfg), act_url=OPEN_TASK_ENTRY)
        s2, ref2 = exchange_session(wrapped)
        info = _post(s2, ref2,
                     f"{BASE}/hlwyxhdhub/api/open/_pub/task/getOneTaskInfo",
                     {"jtToken": m.group(1)})
        d = info.get("data") or {}
        ct = d.get("cToken")
        scan = int(d.get("scanTime") or 0)
        if not ct:
            return False
        time.sleep(scan + 1)
        fin = _post(s2, ref2,
                    f"{BASE}/hlwyxhdhub/api/open/_pub/task/openFinish",
                    {"cToken": ct})
        return fin.get("code") == "SUCCESS"
    except Exception as e:
        log.debug("跳转任务握手失败: %s", e)
        return False


def open_finish_by_ctoken(s, c_token: str) -> tuple:
    """用 cToken 调用 hlwyxhdhub openFinish 完成任务。

    返回 (success: bool, msg: str)。
    部分任务需要原生 APP 签名（digitalSignature），纯脚本无法完成。
    """
    HLWYXHUB_URL = f"{BASE}/hlwyxhdhub/api/open/_pub/task/openFinish"
    HLWYXHUB_REF = f"{BASE}/hlwyxhdhub/act-wedrecharge/index.html?pageId=1849008675699650560"
    try:
        r = s.post(HLWYXHUB_URL, json={"cToken": c_token}, headers={
            "content-type": "application/json;charset=UTF-8",
            "origin": BASE,
            "referer": HLWYXHUB_REF,
            "login-check": "1",
            "x-requested-with": "XMLHttpRequest",
        }, timeout=30)
        r.raise_for_status()
        res = r.json()
        return res.get("code") == "SUCCESS", res.get("msg", "")
    except Exception as e:
        return False, str(e)


def try_finish_task(s, referer, cfg, task: dict) -> bool:
    """尝试完成任务。返回 True 表示任务已完成可领奖。

    策略：
      1. taskType=6（外部合作区）：用 cToken 调用 hlwyxhdhub openFinish
      2. 其他任务：到访 PV → finishTask {taskId, taskType}（Referer=jumpUrl）
      3. finishTask 返回"特殊处理"时也尝试 openFinish
    """
    tid = str(task.get("taskId") or "")
    jump_url = str(task.get("jumpUrl") or "")

    # 1. 获取 taskType、scanTime、cToken
    try:
        info = task_info(s, referer, tid)
        d = info.get("data") or {}
        task_type = str(d.get("taskType") or "")
        scan = int(d.get("scanTime") or 0)
        c_token = d.get("cToken") or ""
    except Exception as e:
        log.info("    获取详情失败: %s", e)
        return False

    # 2. 外部合作区任务（taskType=6）优先用 openFinish
    if task_type == "6" and c_token:
        ok, msg = open_finish_by_ctoken(s, c_token)
        if ok:
            log.info("    ✅ openFinish 成功")
            return True
        if "签名" in msg:
            log.info("    🔐 需要APP原生签名，跳过")
            return False
        log.info("    openFinish: %s", msg)

    # 3. 到访 PV：仅 http(s) 目标页可 GET
    if jump_url.startswith("http"):
        try:
            log.info("    到访: %s", jump_url[:80])
            s.get(jump_url, timeout=20, allow_redirects=True)
            if scan:
                time.sleep(scan + 1)
        except Exception as e:
            log.info("    到访失败: %s", str(e)[:60])

    # 4. finishTask，先用默认 referer
    res = _post(s, referer, "/task/finishTask",
                {"taskId": tid, "taskType": task_type})
    msg = res.get("msg") or ""

    # 5. 服务端校验 Referer=目标页：失败时用 jumpUrl 作 referer 重试
    if res.get("code") != "SUCCESS" and "未达到" in msg and jump_url.startswith("http"):
        try:
            res = _post(s, jump_url, "/task/finishTask",
                        {"taskId": tid, "taskType": task_type})
            msg = res.get("msg") or ""
        except Exception:
            pass

    # 6. "特殊处理"任务再试 openFinish
    if res.get("code") != "SUCCESS" and ("特殊处理" in msg or "openFinish" in msg):
        if c_token:
            ok, _ = open_finish_by_ctoken(s, c_token)
            if ok:
                return True

    if res.get("code") == "SUCCESS":
        log.info("    ✅ finishTask 成功: %s", res.get("msg"))
        return True

    log.info("    finishTask 失败: %s %s", res.get("code"), msg)
    return False


def run_mark_tasks(s: requests.Session, referer: str, cfg, dry_run: bool = False) -> str:
    lines = []
    claimed = 0
    failed = 0

    res = task_list(s, referer)
    if res.get("code") != "SUCCESS":
        return f"获取任务列表失败: {res.get('msg')}"

    tasks = (res.get("data") or {}).get("tasks") or []
    todo = [t for t in tasks if t.get("status") == 0]
    done_tasks = [t for t in tasks if t.get("status") != 0]
    log.info("共 %d 个任务，待办 %d 个，已完成 %d 个", len(tasks), len(todo), len(done_tasks))

    # 已完成的直接领奖
    for task in done_tasks:
        tid = task.get("taskId")
        name = task.get("taskName", "")
        award = task.get("awardNum", "?")
        if dry_run:
            lines.append(f"[dry] {name}: 已完成可领{award}")
            continue
        try:
            aw = get_award(s, referer, tid)
            if aw.get("code") == "SUCCESS":
                n = (aw.get("data") or {}).get("awardNum", "?")
                lines.append(f"✅ {name}: 领到{n}")
                claimed += 1
            else:
                msg = aw.get("msg") or ""
                if "未达到" in msg or "已" in msg:
                    lines.append(f"ℹ️  {name}: {msg}（已领取过）")
                    claimed += 1
                else:
                    lines.append(f"⚠️  {name}: {msg}")
                    failed += 1
        except Exception as e:
            lines.append(f"❌ {name}: 领奖异常 {e}")
            failed += 1
        time.sleep(random.uniform(0.8, 1.5))

    # 未完成的尝试完成
    for task in todo:
        tid = task.get("taskId")
        name = task.get("taskName", "")
        category = task.get("taskClasifiName", "")
        award = task.get("awardNum", "?")
        jump_url = task.get("jumpUrl") or ""

        log.info("[%s] %s (ID:%s) 奖励:%s", category, name, tid, award)

        if dry_run:
            lines.append(f"[dry] {name}: 未完成，链接:{jump_url[:40]}")
            continue

        try:
            finished = try_finish_task(s, referer, cfg, task)
        except Exception as e:
            log.info("    任务执行异常: %s", e)
            finished = False

        if finished:
            try:
                aw = get_award(s, referer, tid)
                if aw.get("code") == "SUCCESS":
                    n = (aw.get("data") or {}).get("awardNum", "?")
                    lines.append(f"✅ {name}: 领到{n}")
                    claimed += 1
                else:
                    msg = aw.get("msg") or ""
                    if "未达到" in msg or "已" in msg:
                        lines.append(f"ℹ️  {name}: {msg}（已领取过）")
                        claimed += 1
                    else:
                        lines.append(f"⚠️  {name}: {msg}")
                        failed += 1
            except Exception as e:
                lines.append(f"❌ {name}: 领奖异常 {e}")
                failed += 1
        else:
            lines.append(f"❌ {name}: 无法完成（需真实打开APP或交互）")
            failed += 1

        time.sleep(random.uniform(1, 2))

    summary = f"成功{claimed} 失败{failed}"
    log.info("任务执行完毕: %s", summary)
    return "\n".join(lines + [f"【汇总】{summary}"])


def run_games(cfg, dry_run=False):
    """拓展活动（周六游戏中心/追剧领福利/玩游戏抽话费），暂无实现。"""
    return []
#（注：内容由AI生成）
