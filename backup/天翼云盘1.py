#!/usr/bin/env python3
# cron: 30 8 * * *
# new Env("天翼云盘签到")
# 来自吾爱论坛，原作者 Sten，适配青龙面板修复
import sys
import os
import time
import re
import json
import base64
import hashlib
import hmac
import random
import rsa
import requests

BI_RM = list("0123456789abcdefghijklmnopqrstuvwxyz")
B64MAP = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

# ========== 读取青龙环境变量，不要改这里，去面板设置环境变量 ==========
username = os.getenv("TY_USER", "")
password = os.getenv("TY_PWD", "")

# 青龙通知适配
def send_notify(title, content):
    try:
        sys.path.append("/ql/config")
        from notify import send
        send(title, content)
    except Exception as e:
        print(f"通知发送失败：{str(e)}")


def int2char(a):
    return BI_RM[a]


def b64tohex(a):
    d = ""
    e = 0
    c = 0
    for i in range(len(a)):
        if list(a)[i] != "=":
            v = B64MAP.index(list(a)[i])
            if 0 == e:
                e = 1
                d += int2char(v >> 2)
                c = 3 & v
            elif 1 == e:
                e = 2
                d += int2char(c << 2 | v >> 4)
                c = 15 & v
            elif 2 == e:
                e = 3
                d += int2char(c)
                d += int2char(v >> 2)
                c = 3 & v
            else:
                e = 0
                d += int2char(c << 2 | v >> 4)
                d += int2char(15 & v)
    if e == 1:
        d += int2char(c << 2)
    return d


def rsa_encode(j_rsakey, string):
    rsa_key = f"-----BEGIN PUBLIC KEY-----\n{j_rsakey}\n-----END PUBLIC KEY-----"
    pubkey = rsa.PublicKey.load_pkcs1_openssl_pem(rsa_key.encode())
    result = b64tohex((base64.b64encode(rsa.encrypt(f'{string}'.encode(), pubkey))).decode())
    return result


def calculate_md5_sign(params):
    return hashlib.md5('&'.join(sorted(params.split('&'))).encode('utf-8')).hexdigest()


def login(username, password):
    s = requests.Session()
    urlToken = "https://m.cloud.189.cn/udb/udb_login.jsp?pageId=1&pageKey=default&clientType=wap&redirectURL=https://m.cloud.189.cn/zhuanti/2021/shakeLottery/index.html"
    r = s.get(urlToken, timeout=15)
    pattern = r"https?://[^\s'\"]+"
    match = re.search(pattern, r.text)
    if not match:
        raise Exception("登录页获取跳转url失败")
    url = match.group()

    r = s.get(url, timeout=15)
    pattern = r"<a id=\"j-tab-login-link\"[^>]*href=\"([^\"]+)\""
    match = re.search(pattern, r.text)
    if not match:
        raise Exception("获取登录href失败")
    href = match.group(1)

    r = s.get(href, timeout=15)
    captchaToken = re.findall(r"captchaToken' value='(.+?)'", r.text)[0]
    lt = re.findall(r'lt = "(.+?)"', r.text)[0]
    returnUrl = re.findall(r"returnUrl= '(.+?)'", r.text)[0]
    paramId = re.findall(r'paramId = "(.+?)"', r.text)[0]
    j_rsakey = re.findall(r'j_rsaKey" value="(\S+)"', r.text, re.M)[0]
    s.headers.update({"lt": lt})

    username_rsa = rsa_encode(j_rsakey, username)
    password_rsa = rsa_encode(j_rsakey, password)
    url = "https://open.e.189.cn/api/logbox/oauth2/loginSubmit.do"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:74.0) Gecko/20100101 Firefox/76.0',
        'Referer': 'https://open.e.189.cn/',
    }
    data = {
        "appKey": "cloud",
        "accountType": '01',
        "userName": f"{{RSA}}{username_rsa}",
        "password": f"{{RSA}}{password_rsa}",
        "validateCode": "",
        "captchaToken": captchaToken,
        "returnUrl": returnUrl,
        "mailSuffix": "@189.cn",
        "paramId": paramId
    }
    r = s.post(url, data=data, headers=headers, timeout=15)
    json_ret = r.json()
    if json_ret['result'] != 0:
        raise Exception(f"登录失败：{json_ret['msg']}")
    print(json_ret['msg'])
    redirect_url = json_ret['toUrl']
    s.get(redirect_url, timeout=15)
    return s


def main():
    if not username or not password:
        print("❌请设置环境变量 TY_USER、TY_PWD")
        send_notify("天翼云盘签到", "❌未配置账号密码，请设置TY_USER、TY_PWD环境变量")
        return

    res1 = res2 = res3 = res4 = ""
    try:
        s = login(username, password)
        rand = str(round(time.time() * 1000))
        surl = f'https://api.cloud.189.cn/mkt/userSign.action?rand={rand}&clientType=TELEANDROID&version=8.6.3&model=SM-G930K'
        url = f'https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_SIGNIN&activityId=ACT_SIGNIN'
        url2 = f'https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_SIGNIN_PHOTOS&activityId=ACT_SIGNIN'
        url3 = f'https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_2022_FLDFS_KJ&activityId=ACT_SIGNIN'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 5.1.1; SM-G930K Build/NRD90M; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36 Ecloud/8.6.3 Android/22 clientId/355325117317828 clientModel/SM-G930K imsi/460071114317824 clientChannelId/qq proVersion/1.0.6',
            "Referer": "https://m.cloud.189.cn/zhuanti/2016/sign/index.jsp?albumBackupOpened=1",
            "Host": "m.cloud.189.cn",
            "Accept-Encoding": "gzip, deflate",
        }
        response = s.get(surl, headers=headers, timeout=15)
        netdiskBonus = response.json()['netdiskBonus']
        if response.json()['isSign'] == "false":
            res1 = f"✅未签到，签到获得{netdiskBonus}M空间"
        else:
            res1 = f"ℹ️已经签到过了，签到获得{netdiskBonus}M空间"
        print(res1)

        # 抽奖1
        response = s.get(url, headers=headers, timeout=15)
        if "errorCode" not in response.text:
            description = response.json()['description']
            res2 = f"🎁抽奖获得{description}"
            print(res2)
        else:
            res2 = "抽奖1无奖励或已完成"

        # 抽奖2
        response = s.get(url2, headers=headers, timeout=15)
        if "errorCode" not in response.text:
            description = response.json()['description']
            res3 = f"🎁抽奖获得{description}"
            print(res3)
        else:
            res3 = "抽奖2无奖励或已完成"

        # 抽奖3
        response = s.get(url3, headers=headers, timeout=15)
        if "errorCode" not in response.text:
            description = response.json()['description']
            res4 = f"🎁链接3抽奖获得{description}"
            print(res4)
        else:
            res4 = "抽奖3无奖励或已完成"

        content = f"{res1}\n{res2}\n{res3}\n{res4}"
        send_notify("天翼云盘签到", content)

    except Exception as e:
        err_msg = f"❌脚本异常：{str(e)}"
        print(err_msg)
        send_notify("天翼云盘签到-异常", err_msg)


if __name__ == "__main__":
    main()
    # 删掉原脚本末尾 time.sleep ，防止青龙任务卡住不退出