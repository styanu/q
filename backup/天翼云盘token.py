#!/usr/bin/env python3
# cron: 35 8 * * *
# new Env("天翼云盘Cookie签到")
import sys
import os
import time
import json
import requests

# 青龙通知
def send_notify(title, content):
    try:
        sys.path.append("/ql/config")
        from notify import send
        send(title, content)
    except Exception as e:
        print(f"通知失败:{e}")

# 读取环境变量
cookie_str = os.getenv("TY_COOKIE", "")

def sign(cookie):
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36 Ecloud/8.6.3",
        "Cookie": cookie,
        "Referer": "https://m.cloud.189.cn/zhuanti/2016/sign/index.jsp"
    }
    res1 = res2 = res3 = res4 = ""

    # 每日签到
    rand = str(round(time.time()*1000))
    sign_url = f"https://api.cloud.189.cn/mkt/userSign.action?rand={rand}&clientType=TELEANDROID&version=8.6.3&model=SM-G930K"
    resp = requests.get(sign_url, headers=headers, timeout=15)
    ret = resp.json()
    if ret.get("isSign") == "false":
        res1 = f"✅未签到，获得 {ret.get('netdiskBonus')}M 空间"
    elif ret.get("isSign") == "true":
        res1 = f"ℹ️今日已签到，获得 {ret.get('netdiskBonus')}M 空间"
    else:
        res1 = f"❌签到接口返回异常：{resp.text}"

    # 三次抽奖
    draw_list = [
        ("TASK_SIGNIN","ACT_SIGNIN"),
        ("TASK_SIGNIN_PHOTOS","ACT_SIGNIN"),
        ("TASK_2022_FLDFS_KJ","ACT_SIGNIN")
    ]
    out = []
    for tid,aid in draw_list:
        durl = f"https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId={tid}&activityId={aid}"
        dr = requests.get(durl, headers=headers, timeout=15)
        dj = dr.json()
        if dj.get("errorCode"):
            out.append("抽奖：已完成/无奖励")
        else:
            out.append(f"🎁抽奖获得：{dj.get('description')}")
    res2,res3,res4 = out

    msg = f"{res1}\n{res2}\n{res3}\n{res4}"
    print(msg)
    return msg


def main():
    if not cookie_str:
        tip = "❌未配置环境变量 TY_COOKIE，请抓取网页Cookie填入"
        print(tip)
        send_notify("天翼云盘签到", tip)
        return
    try:
        content = sign(cookie_str)
        send_notify("天翼云盘签到结果", content)
    except Exception as e:
        err = f"❌运行异常：{str(e)}"
        print(err)
        send_notify("天翼云盘签到异常", err)


if __name__ == "__main__":
    main()