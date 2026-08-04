# 电信签到+金豆抽奖 青龙优化版
# 环境变量 dxlin：手机号#服务密码#AndroidID，多账号换行或&分隔
# 依赖：pycryptodome requests certifi
import os
import sys
import json
import time
import random
import string
import base64
import certifi
import requests
from datetime import datetime
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5, DES3, AES
from Crypto.Util.Padding import pad, unpad
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# 尝试导入青龙通知模块
try:
    import notify
    HAS_NOTIFY = True
except ImportError:
    HAS_NOTIFY = False

# ========== 配置常量 ==========
KEYS = {
    'login_rsa': """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB
-----END PUBLIC KEY-----""",
    'data_rsa': """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+ugG5A8cZ3FqUKDwM57GM4io6JGcStivT8UdGt67PEOihLZTw3P7371+N47PrmsCpnTRzbTgcupKtUv8ImZalYk65dU8rjC/ridwhw9ffW2LBwvkEnDkkKKRi2liWIItDftJVBiWOh17o6gfbPoNrWORcAdcbpk2L+udld5kZNwIDAQAB
-----END PUBLIC KEY-----""",
    'des3': b'1234567`90koiuyhgtfrdews',
    'aes_def': b'34d7cb0bcdf07523',
    'aes_login': 'telecom_wap_2018'
}

global_logs = []
run_stats = {"success": 0, "fail": 0}

# ========== 工具函数 ==========
def log(msg: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    full_msg = f"[{timestamp}] {msg}"
    global_logs.append(full_msg)
    print(full_msg)

def mask_phone(s: str) -> str:
    if not s or len(s) < 7:
        return s
    return f"{s[:3]}****{s[-4:]}"

def ts() -> str:
    return datetime.now().strftime('%Y%m%d%H%M%S')

def rd_str(length: int) -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def encode_str(s: str) -> str:
    return ''.join(chr(ord(c) + 2) for c in s)

# ========== HTTP会话工厂 ==========
def create_session():
    class CustomSSLAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = create_urllib3_context(ciphers='DEFAULT@SECLEVEL=1:!aNULL:!eNULL:!MD5')
            ctx.check_hostname = False
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)

    session = requests.Session()
    session.verify = certifi.where()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; U; Android 12; zh-cn) AppleWebKit/533.1 (KHTML, like Gecko) Version/5.0 Mobile Safari/533.1'
    })
    session.mount('https://', CustomSSLAdapter())
    return session

# ========== 加密函数 ==========
def encrypt_des3(data, mode='enc'):
    cipher = DES3.new(KEYS['des3'], DES3.MODE_CBC, 8 * b'\0')
    if mode == 'enc':
        return cipher.encrypt(pad(data.encode(), 8)).hex()
    return unpad(cipher.decrypt(bytes.fromhex(data)), 8).decode()

def encrypt_aes(data, key=KEYS['aes_def'], b64=False):
    data = json.dumps(data, separators=(',', ':')) if isinstance(data, (dict, list)) else data
    cipher = AES.new(key if isinstance(key, bytes) else key.encode(), AES.MODE_ECB)
    enc = cipher.encrypt(pad(data.encode(), 16))
    return base64.b64encode(enc).decode() if b64 else enc.hex()

def encrypt_rsa(data, key_type='data', out='hex'):
    cipher = PKCS1_v1_5.new(RSA.import_key(KEYS[f'{key_type}_rsa']))
    data = json.dumps(data, separators=(',', ':')) if isinstance(data, (dict, list)) else data
    if out == 'hex':
        return ''.join(cipher.encrypt(data[i:i+32].encode()).hex() for i in range(0, len(data), 32))
    return base64.b64encode(cipher.encrypt(data.encode())).decode()

# ========== 请求封装（带重试） ==========
def api_req(session, url: str, method: str = 'POST', raw: bool = False, retry=2, **kwargs):
    for i in range(retry + 1):
        try:
            r = session.request(method, url, timeout=15, **kwargs)
            if raw:
                return r.text
            return r.json()
        except Exception as e:
            if i < retry:
                time.sleep(1)
                continue
            log(f"[网络异常] {url} - {str(e)}")
            return '' if raw else {}

# ========== 登录逻辑 ==========
def login_v2(session, phone: str, password: str, android_id: str):
    m_phone = mask_phone(phone)
    log(f"[登录] {m_phone} 开始执行登录")

    body = {
        "headerInfos": {
            "code": "userLoginNormal",
            "timestamp": ts(),
            "broadAccount": "",
            "broadToken": "",
            "clientType": "#11.0.0#channel8#Xiaomi 20#",
            "shopId": "20002",
            "source": "110003",
            "sourcePassword": "Sid98s",
            "token": "",
            "userLoginName": encode_str(phone)
        },
        "content": {
            "attach": "test",
            "fieldData": {
                "loginType": "4",
                "accountType": "",
                "loginAuthCipherAsymmertric": encrypt_rsa(
                    f"Xiaomi 20 8.0.0.{android_id[:12]}{phone}{ts()}{password}0$$$0.",
                    'login', 'b64'
                ),
                "deviceUid": "",
                "phoneNum": encode_str(phone),
                "isChinatelecom": "",
                "systemVersion": "8.0.0",
                "androidId": encode_str(android_id),
                "loginAuthCipher": "",
                "authentication": encode_str(password)
            }
        }
    }
    res = api_req(session, 'https://appgologin.189.cn:9031/login/client/userLoginNormal', json=body)
    if not isinstance(res, dict):
        log(f"[登录失败] {m_phone} 响应格式异常")
        return None

    login_data = res.get('responseData', {}).get('data', {}).get('loginSuccessResult')
    if not login_data:
        err_msg = res.get('responseData', {}).get('data', {}).get('resultMsg') or '账号密码错误/触发验证码'
        log(f"[登录失败] {m_phone}: {err_msg}")
        return None
    log(f"[登录成功] {m_phone} 账密验证通过")

    # 获取Ticket
    xml = f'''<Request>
        <HeaderInfos>
            <Code>getSingle</Code>
            <Timestamp>{ts()}</Timestamp>
            <BroadAccount></BroadAccount>
            <BroadToken></BroadToken>
            <ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType>
            <ShopId>20002</ShopId>
            <Source>110003</Source>
            <SourcePassword>Sid98s</SourcePassword>
            <Token>{login_data["token"]}</Token>
            <UserLoginName>{phone}</UserLoginName>
        </HeaderInfos>
        <Content>
            <Attach>test</Attach>
            <FieldData>
                <TargetId>{encrypt_des3(login_data["userId"])}</TargetId>
                <Url>4a6862274835b451</Url>
            </FieldData>
        </Content>
    </Request>'''
    xml_res = api_req(session, 'https://appgologin.189.cn:9031/map/clientXML', data=xml,
                      headers={'Content-Type': 'application/xml'}, raw=True)
    if not isinstance(xml_res, str) or '<Ticket>' not in xml_res:
        log(f"[Ticket失败] {m_phone} 未获取到票据")
        return None
    if '过期' in xml_res or '校验错误' in xml_res:
        log(f"[Ticket失败] {m_phone} 票据校验失效")
        return None

    try:
        ticket_enc = xml_res.split('<Ticket>')[1].split('</Ticket>')[0]
        uid = encrypt_des3(ticket_enc, 'dec')
    except Exception as e:
        log(f"[Ticket解析失败] {m_phone}: {str(e)}")
        return None

    # 统一登录获取Bearer（用于抽奖）
    user_info = {**login_data, 'uid': uid, 'phoneNbr': phone}
    auth_body = encrypt_aes(
        {"ticket": uid, "backUrl": "https%3A%2F%2Fwapact.189.cn%3A9001", "platformCode": "P201010301", "loginType": 2},
        KEYS['aes_login'], True
    )
    auth_res = api_req(session, 'https://wapact.189.cn:9001/unified/user/login', data=auth_body,
                       headers={'Content-Type': 'application/json'})
    if isinstance(auth_res, dict) and auth_res.get('code') == 0:
        user_info['Authorization'] = f"Bearer {auth_res['biz']['token']}"
        log(f"[凭证] {m_phone} 获取Bearer成功，抽奖功能可用")
    else:
        log(f"[凭证] {m_phone} 未获取Bearer，将跳过抽奖环节")

    return user_info

# ========== 任务执行 ==========
def sign_tasks(session, user: dict):
    m = mask_phone(user['phoneNbr'])
    log(f"[任务] {m} 开始执行每日任务")

    # SSO换取签到签名
    sso_url = f"https://wappark.189.cn/jt-sign/ssoHomLogin?ticket={user['uid']}"
    sso = api_req(session, sso_url, method='GET')
    if not isinstance(sso, dict) or not sso or 'sign' not in sso:
        log(f"[签到失败] {m} 获取签名失败，跳过签到任务")
        return
    sign_header = {'sign': sso['sign']}

    # 每日签到
    sign_res = api_req(session, 'https://wappark.189.cn/jt-sign/webSign/sign',
                       json={"encode": encrypt_aes({"phone": user['phoneNbr'], "date": int(time.time()*1000)})},
                       headers=sign_header)
    sign_msg = sign_res.get('resoultMsg', '执行完成') if isinstance(sign_res, dict) else '未知'
    log(f"[每日签到] {m}: {sign_msg}")

    # 连签/累签领奖
    def check_and_award(path, key, days_list, label):
        res = api_req(session, f'https://wappark.189.cn/jt-sign/{path}',
                      json={"para": encrypt_rsa({"phone": user['phoneNbr']})},
                      headers=sign_header)
        if not isinstance(res, dict):
            return
        days = str(res.get('data', {}).get(key) if 'data' in res else res.get(key, 0))
        log(f"[{label}] {m}: 已累计{days}天")
        if days in days_list:
            log(f"[{label}领奖] {m} 达标{days}天，领取奖励")
            api_req(session, 'https://wappark.189.cn/jt-sign/webSign/exchangePrize',
                    json={"para": encrypt_rsa({"phone": user['phoneNbr'], "type": days})},
                    headers=sign_header)

    check_and_award('api/home/userStatusInfo', 'signDay', ['7'], '连续签到')
    check_and_award('webSign/continueSignDays', 'continueSignDays', ['15', '28'], '累计签到')

    # 金豆转盘抽奖
    if 'Authorization' in user:
        log(f"[金豆抽奖] {m} 开始查询转盘活动")
        tab = api_req(session, f"https://wapact.189.cn:9001/gateway/golden/api/queryTurnTable?userType=1&_={int(time.time()*1000)}",
                     method='GET', headers={'Authorization': user['Authorization']})
        if isinstance(tab, dict) and tab.get('code') == 0:
            act_id = tab['biz']['wzTurntable']['code']
            chk = api_req(session, f"https://wapact.189.cn:9001/gateway/standQuery/detail/check?activityId={act_id}",
                         method='GET', headers={'Authorization': user['Authorization']})
            if isinstance(chk, dict) and chk.get('code') == 0:
                info = chk.get('biz', {}).get('resultInfo', {})
                remain = info.get('userMaximum', 0) - info.get('userCount', 0)
                log(f"[金豆抽奖] {m} 剩余可抽：{remain}次")
                for idx in range(remain):
                    lot_res = api_req(session, 'https://wapact.189.cn:9001/gateway/golden/api/lottery',
                                      json={"activityId": act_id},
                                      headers={'Authorization': user['Authorization']})
                    prize = lot_res.get('biz', {}).get('prizeName', '未中奖') if isinstance(lot_res, dict) else '异常'
                    log(f"[金豆抽奖] {m} 第{idx+1}次结果：{prize}")
                    time.sleep(2)
            else:
                log(f"[金豆抽奖] {m} 查询次数失败")
        else:
            log(f"[金豆抽奖] {m} 无可用转盘活动")
    else:
        log(f"[金豆抽奖] {m} 缺少Bearer凭证，跳过")

    # 浏览任务
    tasks_res = api_req(session, 'https://wappark.189.cn/jt-sign/webSign/homepage',
                        json={"para": encrypt_rsa({"phone": user['phoneNbr'], "shopId": "20001", "type": "hg_qd_zrwzjd"})},
                        headers=sign_header)
    if isinstance(tasks_res, dict):
        tasks = tasks_res.get('data', {}).get('biz', {}).get('adItems', [])
        do_count = 0
        for t in tasks:
            if str(t.get('taskState', '')) in ['0', '1'] and str(t.get('contentOne', '')) == '18':
                api_req(session, 'https://wappark.189.cn/jt-sign/webSign/polymerize',
                        json={"para": encrypt_rsa({"phone": user['phoneNbr'], "jobId": t['taskId']})},
                        headers=sign_header)
                do_count += 1
                time.sleep(2)
        log(f"[浏览任务] {m} 完成{do_count}个任务")

    # 宠物喂食
    log(f"[宠物喂食] {m} 开始执行")
    feed_count = 0
    for i in range(10):
        res = api_req(session, 'https://wappark.189.cn/jt-sign/paradise/food',
                      json={"para": encrypt_rsa({"phone": user['phoneNbr']})},
                      headers=sign_header)
        msg = res.get('resoultMsg', '') if isinstance(res, dict) else ''
        feed_count += 1
        if "最大" in msg or "已达" in msg or not msg:
            break
        time.sleep(1)
    log(f"[宠物喂食] {m} 共执行{feed_count}次")
    log(f"[任务完成] {m} 全部任务执行完毕")

# ========== 主程序 ==========
if __name__ == '__main__':
    log("===== 电信签到任务开始 =====")
    raw = os.environ.get('dxlin', '').strip()
    if not raw:
        log("❌ 未找到环境变量 dxlin，请按格式设置：手机号#服务密码#AndroidID")
        sys.exit(1)

    # 兼容换行和&两种分隔
    raw = raw.replace('&', '\n')
    accs = []
    for line in raw.split('\n'):
        line = line.strip()
        if not line or line.count('#') < 2:
            continue
        parts = line.split('#')
        accs.append([p.strip() for p in parts[:3]])

    if not accs:
        log("❌ 未解析到有效账号，格式应为：手机号#密码#AndroidID")
        sys.exit(1)
    log(f"共读取到 {len(accs)} 个账号")

    for idx, parts in enumerate(accs, 1):
        phone, pwd, android_id = parts[0], parts[1], parts[2]
        log(f"\n{'='*8} 账号[{idx}] {mask_phone(phone)} {'='*8}")

        try:
            user_session = create_session()
            user = login_v2(user_session, phone, pwd, android_id)
            if user:
                sign_tasks(user_session, user)
                run_stats["success"] += 1
            else:
                run_stats["fail"] += 1
        except Exception as e:
            log(f"💥 账号执行异常: {str(e)}")
            run_stats["fail"] += 1
        finally:
            try:
                user_session.close()
            except:
                pass
        time.sleep(2)

    # 运行统计
    log("\n===== 任务执行汇总 =====")
    log(f"总账号数：{len(accs)}")
    log(f"执行成功：{run_stats['success']}")
    log(f"执行失败：{run_stats['fail']}")

    # 推送通知
    if HAS_NOTIFY and global_logs:
        try:
            full_log = "\n".join(global_logs)
            notify.send('电信签到任务推送', full_log)
            log("通知推送成功")
        except Exception as e:
            log(f"通知推送失败: {str(e)}")