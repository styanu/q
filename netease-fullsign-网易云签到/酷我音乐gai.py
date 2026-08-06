"""
酷我音乐金币任务脚本【优化版｜多账号&分隔】
环境变量 KWYY
格式：
单账号：手机号#密码
带备注：备注#手机号#密码
多账号用 & 分隔：KWYY="备注1#手机号1#密码1&备注2#手机号2#密码2"

环境变量可选：
VERBOSE=1 开启详细日志
ACCOUNT_DELAY=10 账号切换等待秒数
LOTTERY_VIDEO_TIMES=9 视频抽奖最大次数
MAX_RETRY=2 请求最大重试次数
PUSH_PLUS_TOKEN=xxx pushplus推送token
FORCE_PUSH=1 强制推送
FREEMIUM_LOOP=1 免费听歌时长循环次数
"""

import os
import base64
import random
import string
import uuid
import json
from urllib.parse import quote
import time
import re
import requests
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import urllib3
from datetime import datetime
from typing import Dict, List, Any, Optional

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====================== 配置常量区 ======================
SIGN_BASE = 'https://integralapi.kuwo.cn/api/v1/online/sign'
URL_NEW_USER_SIGN_LIST = SIGN_BASE + '/v1/earningSignIn/newUserSignList'
URL_USER_ASSET = SIGN_BASE + '/v1/earningSignIn/earningUserSignList'
URL_NEW_DO_LISTEN = SIGN_BASE + '/v1/earningSignIn/newDoListen'
URL_EVERYDAY_DO_LISTEN = SIGN_BASE + '/v1/earningSignIn/everydaymusic/doListen'
URL_BOX_RENEW = SIGN_BASE + '/new/boxRenew'
URL_NEW_BOX_LIST = SIGN_BASE + '/new/newBoxList'
URL_NEW_BOX_FINISH = SIGN_BASE + '/new/newBoxFinish'
FREEMIUM_SWITCH_URL = 'https://wapi.kuwo.cn/openapi/v1/user/freemium/h5/switches'

DONE_KEYWORDS = [
    '今天已完成任务',
    '已完成',
    '已领取',
    '已签到',
    '已达到当日观看额外视频次数',
    '已达',
    '上限',
    '次数用完',
    '免费次数用完了',
    '视频次数用完了',
]
VIDEO_LIMIT_KEYWORDS = [
    '已达到当日观看额外视频次数',
    '视频次数用完了',
    '免费次数用完了',
    '观看额外视频次数',
]

# 环境变量读取
VERBOSE: bool = os.getenv("VERBOSE", "0") == "1"
ACCOUNT_DELAY: int = int(os.getenv("ACCOUNT_DELAY", "10"))
LOTTERY_VIDEO_TIMES: int = int(os.getenv("LOTTERY_VIDEO_TIMES", "9"))
MAX_RETRY: int = int(os.getenv("MAX_RETRY", "2"))
FREEMIUM_LOOP: int = int(os.getenv("KUWO_FREEMIUM_LOOP", "1"))
PUSH_PLUS_TOKEN = os.getenv("PUSH_PLUS_TOKEN", "")
FORCE_PUSH: bool = os.getenv("FORCE_PUSH", "0") == "1"
if FREEMIUM_LOOP > 10:
    FREEMIUM_LOOP = 10

# 请求UA
COMMON_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 4a Build/TQ3A.230805.001.S2; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 Mobile Safari/537.36/ kuwopage"
)
LOGIN_UA = "Dalvik/2.1.0 (Linux; U; Android 10; MI 8 MIUI/V12.5.2.0.QEACNXM)"

# AES密钥
AES_KEY = b'ysiVkLJHHnvMWCHq'
AES_IV = b'ichYooX+Mb1gRetP'
GEN_Q_RAW_KEY = b'kwks&@69'.encode('UTF-8')

# 静态算法数组（原样保留，为加密签名使用）
STATIC_C = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576, 2097152, 4194304, 8388608, 16777216, 33554432, 67108864, 134217728, 268435456, 536870912, 1073741824, 2147483648, 4294967296, 8589934592, 17179869184, 34359738368, 68719476736, 137438953472, 274877906944, 549755813888, 1099511627776, 2199023255552, 4398046511104, 8796093022208, 17592186044416, 35184372088832, 70368744177664, 140737488355328, 281474976710656, 562949953421312, 1125899906842624, 2251799813685248, 4503599627370496, 9007199254740992, 18014398509481984, 36028797018963968, 72057594037927936, 144115188075855872, 288230376151711744, 576460752303423488, 1152921504606846976, 2305843009213693952, 4611686018427387904, -9223372036854775808]
STATIC_I = [56, 48, 40, 32, 24, 16, 8, 0, 57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18, 10, 2, 59, 51, 43, 35, 62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 60, 52, 44, 36, 28, 20, 12, 4, 27, 19, 11, 3]
STATIC_E = [31, 0, 1, 2, 3, 4, -1, -1, 3, 4, 5, 6, 7, 8, -1, -1, 7, 8, 9, 10, 11, 12, -1, -1, 11, 12, 13, 14, 15, 16, -1, -1, 15, 16, 17, 18, 19, 20, -1, -1, 19, 20, 21, 22, 23, 24, -1, -1, 23, 24, 25, 26, 27, 28, -1, -1, 27, 28, 29, 30, 31, 30, -1, -1]
STATIC_L = [0, 1048577, 3145731]
STATIC_G = [15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9, 1, 7, 23, 13, 31, 26, 2, 8, 18, 12, 29, 5, 21, 10, 3, 24]
STATIC_F = [[14, 4, 3, 15, 2, 13, 5, 3, 13, 14, 6, 9, 11, 2, 0, 5, 4, 1, 10, 12, 15, 6, 9, 10, 1, 8, 12, 7, 8, 11, 7, 0, 0, 15, 10, 5, 14, 4, 9, 10, 7, 8, 12, 3, 13, 1, 3, 6, 15, 12, 6, 11, 2, 9, 5, 0, 4, 2, 11, 14, 1, 7, 8, 13], [15, 0, 9, 5, 6, 10, 12, 9, 8, 7, 2, 12, 3, 13, 5, 2, 1, 14, 7, 8, 11, 4, 0, 3, 14, 11, 13, 6, 4, 1, 10, 15, 3, 13, 12, 11, 15, 3, 6, 0, 4, 10, 1, 7, 8, 4, 11, 14, 13, 8, 0, 6, 2, 15, 9, 5, 7, 1, 10, 12, 14, 2, 5, 9], [10, 13, 1, 11, 6, 8, 11, 5, 9, 4, 12, 2, 15, 3, 2, 14, 0, 6, 13, 1, 3, 15, 4, 10, 14, 9, 7, 12, 5, 0, 8, 7, 13, 1, 2, 4, 3, 6, 12, 11, 0, 13, 5, 14, 6, 8, 15, 2, 7, 10, 8, 15, 4, 9, 11, 5, 9, 0, 14, 3, 10, 7, 1, 12], [7, 10, 1, 15, 0, 12, 11, 5, 14, 9, 8, 3, 9, 7, 4, 8, 13, 6, 2, 1, 6, 11, 12, 2, 3, 0, 5, 14, 10, 13, 15, 4, 13, 3, 4, 9, 6, 10, 1, 12, 11, 0, 2, 5, 0, 13, 14, 2, 8, 15, 7, 4, 15, 1, 10, 7, 5, 6, 12, 11, 3, 8, 9, 14], [2, 4, 8, 15, 7, 10, 13, 6, 4, 1, 3, 12, 11, 7, 14, 0, 12, 2, 5, 9, 10, 13, 0, 3, 1, 11, 15, 5, 6, 8, 9, 14, 14, 11, 5, 6, 4, 1, 3, 10, 2, 12, 15, 0, 13, 2, 8, 5, 11, 8, 0, 15, 7, 14, 9, 4, 12, 7, 10, 9, 1, 13, 6, 3], [12, 9, 0, 7, 9, 2, 14, 1, 10, 15, 3, 4, 6, 12, 5, 11, 1, 14, 13, 0, 2, 8, 7, 13, 15, 5, 4, 10, 8, 3, 11, 6, 10, 4, 6, 11, 7, 9, 0, 6, 4, 2, 13, 1, 9, 15, 3, 8, 15, 3, 1, 14, 12, 5, 11, 0, 2, 12, 14, 7, 5, 10, 8, 13], [4, 1, 3, 10, 15, 12, 5, 0, 2, 11, 9, 6, 8, 7, 6, 9, 11, 4, 12, 15, 0, 3, 10, 5, 14, 13, 7, 8, 13, 14, 1, 2, 13, 6, 14, 9, 4, 1, 2, 14, 11, 13, 5, 0, 1, 10, 8, 3, 0, 11, 3, 5, 9, 4, 15, 2, 7, 8, 12, 15, 10, 7, 6, 12], [13, 7, 10, 0, 6, 9, 5, 15, 8, 4, 3, 10, 11, 14, 12, 5, 2, 11, 9, 6, 15, 12, 0, 3, 4, 1, 14, 13, 1, 2, 7, 8, 1, 2, 12, 15, 10, 4, 0, 3, 13, 14, 6, 9, 7, 8, 9, 6, 15, 1, 5, 12, 3, 10, 14, 5, 8, 7, 11, 0, 4, 13, 2, 11]]
STATIC_H = [39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25, 32, 0, 40, 8, 48, 16, 56, 24]
STATIC_D = [57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3, 61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7, 56, 48, 40, 32, 24, 16, 8, 0, 58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4, 62, 54, 46, 38, 30, 22, 14, 6]
STATIC_K = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]
STATIC_J = [13, 16, 10, 23, 0, 4, -1, -1, 2, 27, 14, 5, 20, 9, -1, -1, 22, 18, 11, 3, 25, 7, -1, -1, 15, 6, 26, 19, 12, 1, -1, -1, 40, 51, 30, 36, 46, 54, -1, -1, 29, 39, 50, 44, 32, 47, -1, -1, 43, 48, 38, 55, 33, 52, -1, -1, 45, 41, 49, 35, 28, 31, -1, -1]

DAILY_GOLD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily_gold_data.json')

# ====================== 工具函数 ======================
def log(msg: str, verbose: bool = True):
    if verbose or VERBOSE:
        print(msg)

def to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        text = str(value).strip()
        if text in ("", "null", "None"):
            return 0
        if "." in text:
            return int(float(text))
        return int(text)
    except Exception:
        return 0

def is_done_like(text: str) -> bool:
    if not text:
        return False
    s = str(text)
    return any(k in s for k in DONE_KEYWORDS)

def is_video_limit_like(text: str) -> bool:
    if not text:
        return False
    s = str(text)
    return any(k in s for k in VIDEO_LIMIT_KEYWORDS)

def build_common_headers() -> Dict[str, str]:
    return {
        'Host': 'integralapi.kuwo.cn',
        'Connection': 'keep-alive',
        'sec-ch-ua-platform': '"Android"',
        'User-Agent': COMMON_UA,
        'Accept': 'application/json, text/plain, */*',
        'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Android WebView";v="134"',
        'sec-ch-ua-mobile': '?1',
        'Origin': 'https://h5app.kuwo.cn',
        'X-Requested-With': 'cn.kuwo.player',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Dest': 'empty',
        'Referer': 'https://h5app.kuwo.cn/',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    }

def req_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """带重试请求封装"""
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRY + 1):
        try:
            resp = requests.request(method, url, timeout=30, **kwargs)
            return resp
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRY:
                time.sleep(2)
    raise last_err or RuntimeError("request failed")

# ====================== 酷我原始加密算法 原样保留 ======================
def func_a1(iArr: List[int], i2: int, j2: int) -> int:
    j3 = 0
    for i3 in range(i2):
        if iArr[i3] >= 0:
            jArr = STATIC_C
            if (jArr[iArr[i3]] & j2) != 0:
                j3 |= jArr[iArr[i3]]
    return j3

def func_a2(j2: int, jArr: List[int], i2: int):
    a2 = func_a1(STATIC_I, 56, j2)
    for i3 in range(16):
        jArr2 = STATIC_L
        iArr = STATIC_K
        a2 = ((a2 & ~jArr2[iArr[i3]]) >> iArr[i3]) | ((jArr2[iArr[i3]] & a2) << (28 - iArr[i3]))
        jArr[i3] = func_a1(STATIC_J, 64, a2)
    if i2 == 1:
        for i4 in range(8):
            j3 = jArr[i4]
            i5 = 15 - i4
            jArr[i4] = jArr[i5]
            jArr[i5] = j3

def func_a3(jArr: List[int], j2: int) -> int:
    p = [0] * 2
    q = [0] * 8
    m = func_a1(STATIC_D, 64, j2)
    iArr = p
    j3 = m
    iArr[0] = int(j3 & 4294967295)
    iArr[1] = int((j3 & -4294967296) >> 32)
    for i2 in range(16):
        o = iArr[1]
        o = func_a1(STATIC_E, 64, o)
        o ^= jArr[i2]
        for i3 in range(8):
            q[i3] = int((o >> (i3 * 8)) & 255)
        r = 0
        i4 = 7
        while True:
            t = i4
            i5 = t
            if i5 >= 0:
                i6 = r
                i6 <<= 4
                if i6 > 2147483647:
                    i6 = -4294967296 + i6
                i6 |= STATIC_F[i5][q[i5]]
                r = i6
                i4 = i5 - 1
            else:
                break
        o = r
        o = func_a1(STATIC_G, 32, o)
        iArr2 = p
        n = iArr2[0]
        iArr2[0] = iArr2[1]
        xor_val = n ^ o
        if -2147483648 < xor_val < 2147483647:
            iArr2[1] = int(xor_val)
            continue
        if xor_val >= 2147483647:
            iArr2[1] = xor_val - 4294967296
        else:
            iArr2[1] = xor_val + 4294967296
    iArr3 = p
    s = iArr3[0]
    iArr3[0] = iArr3[1]
    iArr3[1] = s
    m = ((iArr3[1] << 32) & -4294967296) | (4294967295 & iArr3[0])
    m = func_a1(STATIC_H, 64, m)
    return m

def generate_q(bArr: bytes, bArr2: bytes) -> str:
    length = len(bArr)
    jArr = [0] * 16
    j2 = 0
    j3 = 0
    for i3 in range(8):
        j3 |= bArr2[i3] << (i3 * 8)
    func_a2(j3, jArr, 0)
    i4 = length // 8
    jArr2 = [0] * i4
    for i5 in range(i4):
        for i6 in range(8):
            jArr2[i5] = jArr2[i5] | ((bArr[i5 * 8 + i6] & 255) << (i6 * 8))
    jArr3 = [0] * (((i4 + 1) * 8 + 1) // 8)
    for i7 in range(i4):
        jArr3[i7] = func_a3(jArr, jArr2[i7])
    i8 = length % 8
    i9 = i4 * 8
    i10 = length - i9
    r12 = [None] * i10
    r12[0:i10] = bArr[i9:i9 + i10]
    for i11 in range(i8):
        j2 |= (r12[i11] & 255) << (i11 * 8)
    jArr3[i4] = func_a3(jArr, j2)
    bArr3 = [None] * (len(jArr3) * 8)
    i12 = 0
    i13 = 0
    while i12 < len(jArr3):
        i14 = i13
        for i15 in range(8):
            bArr3[i14] = 255 & (jArr3[i12] >> (i15 * 8))
            i14 += 1
        i12 += 1
        i13 = i14
    return base64.b64encode(bytearray(bArr3)).decode()

def create_sx() -> str:
    timestamp = int(time.time() * 1000)
    combined_string = str(timestamp) + '12345678'
    return combined_string[:8]

def encrypt_devid(dev_id: str) -> str:
    padded_id = dev_id.ljust(16, '0')[:16]
    return base64.b64encode(padded_id.encode()).decode()

def get_q(username: str, password: str):
    dev_id = ''.join([random.choice(string.digits) for _ in range(10)])
    dev_name = '安卓设备'
    devType = 'arr'
    data = (
        f"username={quote(username)}&password={quote(base64.b64encode(password.encode()).decode())}"
        f"&dev_id={dev_id}&user={str(uuid.uuid4()).replace('-', '')}"
        f"&dev_name={quote(dev_name)}&urlencode=0&src=kwplayer_ar11.1.4.1_40.apk"
        f"&devResolution=720*1080&&from=android&devType={devType}&sx={create_sx()}&version=11.1.4.1"
    )
    q_value = generate_q(data.encode('UTF-8'), GEN_Q_RAW_KEY)
    encrypted_dev_id = encrypt_devid(dev_id)
    return q_value, encrypted_dev_id

def encrypt_phone(phone: str) -> str:
    if isinstance(phone, str):
        phone = phone.encode('utf-8')
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    padded_plaintext = pad(phone, AES.block_size)
    ciphertext = cipher.encrypt(padded_plaintext)
    return base64.b64encode(ciphertext).decode('utf-8')

def decrypt_phone(encrypted_phone: str) -> str:
    aes = AES.new(key=AES_KEY, mode=AES.MODE_CBC, iv=AES_IV)
    encrypted_data = base64.b64decode(encrypted_phone)
    decrypted_data = unpad(aes.decrypt(encrypted_data), AES.block_size, style='pkcs7')
    return decrypted_data.decode('UTF-8')

def generate_kuwo_token(device_id: str, timestamp: int) -> str:
    raw_string = str(device_id) + 'KUWO_COMIC' + str(timestamp)
    return hashlib.md5(raw_string.encode('utf-8')).hexdigest()

# ====================== 账号解析 支持&分割、带备注 ======================
def parse_account_item(account_str: str):
    """
    支持两种格式
    手机号#密码
    备注#手机号#密码
    返回 dict{"remark":"xxx","phone":"xxx","password":"xxx"}
    """
    parts = [x.strip() for x in account_str.split('#')]
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        phone, password = parts[0], parts[1]
        return {"remark": "", "phone": phone, "password": password}
    # len >=3：备注#手机号#密码，密码允许带#
    remark = parts[0]
    phone = parts[1]
    password = '#'.join(parts[2:])
    return {"remark": remark, "phone": phone, "password": password}

def get_accounts_from_env() -> List[Dict]:
    env_value = os.getenv('KWYY', '').strip()
    if not env_value:
        return []
    accounts = []
    account_strings = env_value.split('&')
    for s in account_strings:
        s = s.strip()
        if not s:
            continue
        item = parse_account_item(s)
        if item:
            accounts.append(item)
    return accounts

# ====================== 登录 ======================
def login(username: str, password: str):
    try:
        q, encrypted_dev_id = get_q(username, password)
        url = 'http://ar.i.kuwo.cn/US_NEW/kuwo/login_kw'
        headers = {
            'User-Agent': LOGIN_UA,
            'Accept': '*/*',
            'Host': 'ar.i.kuwo.cn',
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
        }
        params = {'f': 'ar', 'q': q}
        resp = req_with_retry("GET", url, headers=headers, params=params)
        set_cookie = resp.headers.get('Set-Cookie', '')
        username_match = re.search(r'uname3=([^;]+)', set_cookie)
        sid_match = re.search(r'websid=([^;]+)', set_cookie)
        uid_match = re.search(r'userid=([^;]+)', set_cookie)
        account_match = re.search(r't3kwid=([^;]+)', set_cookie)
        if all([username_match, sid_match, uid_match, account_match]):
            loginUid = uid_match.group(1)
            loginSid = sid_match.group(1)
            username_ret = username_match.group(1)
            appUid = account_match.group(1)
            return loginUid, loginSid, username_ret, appUid, encrypted_dev_id
        log('❌ 登录失败: Cookie解析失败')
        return None
    except Exception as e:
        log(f'❌ 登录异常: {e}')
        return None

# ====================== 任务函数 ======================
def open_treasure_box(loginUid, loginSid, appUid, encrypted_dev_id, gold_num=20, verbose=True):
    try:
        url = URL_NEW_BOX_FINISH
        r_value = random.random()
        params = {
            'apiversion': '46',
            'loginUid': loginUid,
            'loginSid': loginSid,
            'devId': encrypted_dev_id,
            'jfencv': 'devId',
            'appUid': appUid,
            'source': 'kwplayer_ar_12.0.4.1_newpcguanwangmobile.apk',
            'version': 'kwplayer_ar_12.0.4.1',
            'dynamicVer': '46',
            'kver': '1',
            'verifyStr': '',
            'adverSpace': '',
            'r': str(r_value),
            'action': 'new',
            'time': '',
            'goldNum': str(gold_num),
            'baseTaskGold': '0',
            'extraGoldnum': '0',
            'clickExtraGoldNum': '0',
            'yyzdSecondRewardFlag': '0',
            'secondRewardFlag': '0',
            'apiv': '6',
        }
        headers = build_common_headers()
        resp = req_with_retry("GET", url, headers=headers, params=params)
        if resp.status_code == 200:
            result = resp.json()
            if result.get('code') == 200:
                data = result.get('data', {})
                status = data.get('status', 0)
                if status == 1:
                    obtain = data.get('obtain', 0)
                    extra_num = data.get('extraNum', 0)
                    if verbose:
                        log(f'✅ 开宝箱成功: 获得 {obtain} 金币' + (f' (额外 {extra_num} 金币)' if extra_num else ''), verbose)
                    return {'success': True, 'obtain': obtain, 'extra_num': extra_num, 'description': '成功'}
                description = data.get('description', '未知错误')
                if verbose:
                    log(f'⚠️  开宝箱失败: {description}', verbose)
                return {'success': False, 'obtain': 0, 'description': description}
            error_msg = result.get('msg', '未知错误')
            if verbose:
                log(f'❌ 开宝箱请求失败: {error_msg}', verbose)
            return {'success': False, 'obtain': 0, 'description': error_msg}
        if verbose:
            log(f'❌ 请求失败，状态码: {resp.status_code}', verbose)
        return {'success': False, 'obtain': 0, 'description': f'HTTP {resp.status_code}'}
    except Exception as e:
        if verbose:
            log(f'❌ 开宝箱异常: {e}', verbose)
        return {'success': False, 'obtain': 0, 'description': str(e)}


def fetch_sign_list(loginUid, loginSid, appUid, extra_params=None, tag="任务列表", verbose=True):
    if extra_params is None:
        extra_params = {}
    try:
        params = {
            "loginUid": loginUid,
            "loginSid": loginSid,
            "appUid": appUid,
        }
        params.update(extra_params)
        headers = build_common_headers()
        resp = req_with_retry("GET", URL_NEW_USER_SIGN_LIST, headers=headers, params=params)
        if resp.status_code == 200:
            res = resp.json()
            if res.get("code") == 200:
                return {"success": True, "data": res.get("data", {})}
            return {"success": False, "msg": res.get("msg", "")}
        return {"success": False, "msg": f"HTTP {resp.status_code}"}
    except Exception as e:
        log(f"❌ {tag}异常:{e}", verbose)
        return {"success": False, "msg": str(e)}


def fetch_dynamic_task_payload(loginUid, loginSid, appUid, first_payload):
    if has_listen_task_config(first_payload):
        return first_payload
    dynamic_info = fetch_sign_list(
        loginUid,
        loginSid,
        appUid,
        extra_params={
            'dynamicVer': '39',
            'q36': '0302c7dcfc6616225938b018100018b19319',
        },
        tag='动态任务列表',
    )
    if dynamic_info.get('success'):
        payload = dynamic_info.get('data', {})
        dynamic_list = payload.get('dataList', [])
        if has_listen_task_config(payload) or (isinstance(dynamic_list, list) and dynamic_list):
            return payload
    return first_payload

def has_listen_task_config(task_payload):
    data_list = task_payload.get('dataList', [])
    if not isinstance(data_list, list):
        return False
    for item in data_list:
        if not isinstance(item, dict):
            continue
        task_type = str(item.get('taskType') or '').strip().lower()
        title = str(item.get('title') or '')
        listen_list = item.get('listenList')
        if task_type == 'listen' and isinstance(listen_list, list):
            return True
        if '听歌' in title and isinstance(listen_list, list):
            return True
        if isinstance(listen_list, list) and listen_list:
            return True
    return False

def extract_listen_segment_candidates(task_payload):
    data_list = task_payload.get('dataList', [])
    if not isinstance(data_list, list):
        return []
    candidates = []
    seen = set()
    for item in data_list:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '')
        task_type = str(item.get('taskType') or '').strip().lower()
        listen_list = item.get('listenList')
        if not isinstance(listen_list, list):
            continue
        if not (task_type == 'listen' or '听歌' in title or listen_list):
            continue
        for idx, listen_item in enumerate(listen_list, 1):
            if not isinstance(listen_item, dict):
                continue
            listen_time = listen_item.get('time')
            unit = listen_item.get('unit')
            gold = listen_item.get('goldNum')
            extra_gold = listen_item.get('extraGoldNum')
            if gold and str(gold).lower() != 'null':
                key = ('g', str(listen_time or ''), str(unit or ''), str(gold))
                if key not in seen:
                    seen.add(key)
                    candidates.append({
                        'kind': 'gold',
                        'idx': idx,
                        'params': {
                            'from': 'listen',
                            'goldNum': gold,
                            'listenTime': listen_time,
                            'unit': unit,
                        },
                    })
            if extra_gold and str(extra_gold).lower() != 'null':
                key = ('eg', str(listen_time or ''), '', str(extra_gold))
                if key not in seen:
                    seen.add(key)
                    candidates.append({
                        'kind': 'extra',
                        'idx': idx,
                        'params': {
                            'from': 'listen',
                            'extraGoldNum': extra_gold,
                            'listenTime': listen_time,
                        },
                    })
    return candidates


def run_new_do_listen_task(task_name, loginUid, loginSid, appUid, encrypted_phone, params_dict, verbose=True):
    try:
        url = URL_NEW_DO_LISTEN
        base_params = {
            'apiversion': '46',
            'loginUid': loginUid,
            'loginSid': loginSid,
            'appUid': appUid,
            'terminal': 'ar',
            'mobile': encrypted_phone,
            'apiv': '10',
            'dynamicVer': '46',
            'kver': '1',
        }
        base_params.update(params_dict)
        headers = build_common_headers()
        resp = req_with_retry("GET", url, headers=headers, params=base_params)
        if resp.status_code == 200:
            result = resp.json()
            if result.get('code') == 200:
                data = result.get('data', {})
                status = data.get('status', 0)
                obtain = data.get('obtain', 0)
                desc = data.get("description", "")
                if status == 1:
                    log(f"✅【{task_name}】成功，获得{obtain}金币", verbose)
                    return {"success": True, "obtain": obtain, "description": desc}
                else:
                    log(f"⚠️【{task_name}】{desc}", verbose)
                    return {"success": False, "obtain": 0, "description": desc}
            msg = result.get("msg", "未知")
            log(f"❌【{task_name}】请求失败:{msg}", verbose)
            return {"success": False, "obtain": 0, "description": msg}
        log(f"❌【{task_name}】HTTP {resp.status_code}", verbose)
        return {"success": False, "obtain":0, "description":f"HTTP{resp.status_code}"}
    except Exception as e:
        log(f"❌【{task_name}】异常:{e}", verbose)
        return {"success":False,"obtain":0,"description":str(e)}


def clock_bonus(loginUid, loginSid, appUid, encrypted_phone, verbose=True):
    clock_gold_num = 59
    try:
        task_payload = fetch_dynamic_task_payload(loginUid, loginSid, appUid, {})
        data_list = task_payload.get('dataList', [])
        if not isinstance(data_list, list):
            data_list = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
            subtitle = str(item.get('subTitle') or '')
            task_type = str(item.get('taskType') or '')
            if '打卡' in subtitle or task_type == 'clock':
                gold_num = to_int(item.get('goldNum'))
                if gold_num > 0:
                    clock_gold_num = gold_num
                    break
    except Exception:
        pass
    return run_new_do_listen_task(
        '整点领金币',
        loginUid,
        loginSid,
        appUid,
        encrypted_phone,
        {'from': 'clock', 'goldNum': str(clock_gold_num)},
        verbose=verbose,
    )

def watch_dada_ad(loginUid, loginSid, appUid, encrypted_dev_id, phone, verbose=True):
    timestamp = str(int(time.time() * 1000))
    dynamic_token = generate_kuwo_token(encrypted_dev_id, timestamp)
    url = URL_NEW_DO_LISTEN
    params = {
        'apiversion': '46',
        'adverSpace': '20130401',
        'verifyStr': '',
        'loginUid': loginUid,
        'loginSid': loginSid,
        'appUid': appUid,
        'terminal': 'ar',
        'from': 'videofix',
        'taskId': '',
        'goldNum': '50',
        'baseTaskGold': '0',
        'adverId': '',
        'token': '',
        'extraGoldNum': '0',
        'clickExtraGoldNum': '0',
        'secondRewardFlag': '0',
        'yyzdSecondRewardFlag': '0',
        'surpriseType': '',
        'mobile': phone,
        'apiv': '10',
        'dynamicVer': '46',
        'kver': '1',
        'rewardType': '0',
        'pFrom': '',
    }
    headers = build_common_headers()
    try:
        resp = req_with_retry("GET", url, headers=headers, params=params)
        if resp.status_code == 200:
            result = resp.json()
            if result.get('code') == 200:
                data = result.get('data', {})
                status = data.get('status', 0)
                if status == 1:
                    obtain = data.get('obtain', 0)
                    description = data.get('description', '成功')
                    log(f'✅ 广告观看成功: 获得 {obtain} 金币 - {description}', verbose)
                    return {'success': True, 'obtain': obtain, 'description': description}
                description = data.get('description', '未知错误')
                log(f'⚠️  广告观看失败: {description}', verbose)
                return {'success': False, 'obtain': 0, 'description': description}
            error_msg = result.get('msg', '未知错误')
            log(f'❌ 广告观看请求失败: {error_msg}', verbose)
            return {'success': False, 'obtain': 0, 'description': error_msg}
        log(f'❌ 请求失败，状态码: {resp.status_code}', verbose)
        return {'success': False, 'obtain': 0, 'description': f'HTTP {resp.status_code}'}
    except Exception as e:
        log(f'❌ 广告观看异常: {e}', verbose)
        return {'success': False, 'obtain': 0, 'description': str(e)}

def lottery_draw(loginUid, loginSid, appUid, source='kwplayer_ar_12.0.4.1_newpcguanwangmobile.apk', lottery_type='free', verbose=True):
    try:
        url = 'https://integralapi.kuwo.cn/api/v1/online/sign/loterry/getLucky'
        params = {'loginUid': loginUid, 'loginSid': loginSid, 'appUid': appUid, 'source': source, 'type': lottery_type}
        headers = build_common_headers()
        resp = req_with_retry("GET", url, headers=headers, params=params)
        if resp.status_code == 200:
            result = resp.json()
            code = result.get('code', 0)
            msg = result.get('msg', '未知')
            if code == 200:
                data = result.get('data', {})
                if not isinstance(data, dict):
                    data = {}
                reward_name = str(data.get('loterryname') or data.get('lotteryName') or msg)
                obtain = to_int(data.get('goldNum') or data.get('obtain') or data.get('awardScore') or data.get('score') or 0)
                if obtain <= 0:
                    match = re.search(r'(\d+)\s*金币', reward_name + ' ' + msg)
                    if match:
                        obtain = to_int(match.group(1))
                if verbose:
                    if obtain > 0:
                        log(f'🎉 抽奖成功: {reward_name} (+{obtain} 金币)', verbose)
                    else:
                        log(f'🎉 抽奖成功: {reward_name}', verbose)
                return {'success': True, 'message': msg, 'reward_name': reward_name, 'obtain': obtain, 'data': data}
            if verbose:
                log(f'❌ 抽奖失败: {msg}', verbose)
            return {'success': False, 'message': msg, 'data': {}}
        if verbose:
            log(f'❌ 请求失败，状态码: {resp.status_code}', verbose)
        return {'success': False, 'message': f'HTTP {resp.status_code}', 'data': {}}
    except Exception as e:
        if verbose:
            log(f'❌ 抽奖异常: {e}', verbose)
        return {'success': False, 'message': str(e), 'data': {}}

def run_activity_box_task(loginUid, loginSid, appUid, verbose=True):
    params = {
        'loginUid': loginUid,
        'loginSid': loginSid,
        'from': 'sign',
        'extra
