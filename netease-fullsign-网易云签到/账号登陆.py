"""
cron: 30 59 8 * * *
const $ = new Env("翼支付5G合约自动领券-账号密码登录版");
"""
import asyncio
import aiohttp
import json
import rsa
import base64
import hashlib
import random
import datetime
import sys
import time
import os
import ssl
from Crypto.Cipher import AES, DES3
from Crypto.Util.Padding import pad, unpad

# ===================== 【配置区 只改这里】=====================
# 电信手机号
ACCOUNT_PHONE = "13800138000"
# 电信APP/营业厅服务密码（6位数字）
ACCOUNT_PASSWORD = "123456"
# ticket缓存文件
CACHE_FILE = "dx_ticket_cache.json"
# 缓存有效期 10天
TICKET_VALID_SEC = 10 * 24 * 60 * 60

# 要领取的权益包配置
TARGET_PACK = {
    '橙翼权益': ['话费充值券包 价值9元', '话费充值券包 价值18元', '话费充值券包 价值24元', '爱奇艺 视频月卡', '8:59:59'],
    'N选权益包': ['领5元话费券赠170个权益币 None'],
    'N选权益包-加副-9元': ['领160个权益币 None'],
    '流量权益包-19元': ['领160个权益币 None'],
    '天翼云盘橙意包': ['领160个权益币 None'],
    '5g升级权益合约': ['领腾讯会员周卡赠送100个权益币 None'],
    '节日促销-权益N选1合约-9元': ['翼支付通用券 18元券包'],
    "河南15元出行权益包": ["150个权益币 180天有效期"],
    "15元N选权益小合约": ["话费+腾讯周卡券包 10元话费+腾讯周卡"],
}
SHOW_ALL_ITEM = 1
QUERY_COUPON_LIST = 1
SKIP_NOT_START = 1
BLACK_COUPON = ["北冰洋5元饮品券", "北冰洋15元饮品券", None]
SEMAPHORE_NUM = 10
RETRY_TIMES = 5

# 全局常量
APP_TYPE = "116"
LOG_STORE = {}
QL_NOTIFY = 0
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE
ssl_ctx.set_ciphers("DEFAULT@SECLEVEL=0")

# ===================== 工具加密函数 =====================
def des3_encrypt(text: str) -> str:
    key = b'1234567`90koiuyhgtfrdews'
    iv = b'\x00' * 8
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    return cipher.encrypt(pad(text.encode("utf-8"), 8)).hex()

def des3_decrypt(hex_str: str) -> str:
    key = b'1234567`90koiuyhgtfrdews'
    iv = b'\x00' * 8
    data = bytes.fromhex(hex_str)
    cipher = DES3.new(key, DES3.MODE_CBC, iv)
    return unpad(cipher.decrypt(data), 8).decode("utf-8")

def shift_encode(s: str) -> str:
    return "".join(chr(ord(c) + 2) for c in s)

def rsa_pub_encrypt(pub_key_str: str, content: str) -> str:
    pub_pem = f"-----BEGIN PUBLIC KEY-----\n{pub_key_str}\n-----END PUBLIC KEY-----"
    pub = rsa.PublicKey.load_pkcs1_openssl_pem(pub_pem.encode())
    return base64.b64encode(rsa.encrypt(content.encode(), pub)).decode()

def aes_cbc_encrypt(plain: str, key: str) -> str:
    cipher = AES.new(key.encode(), AES.MODE_CBC, b'\x00' * 16)
    return base64.b64encode(cipher.encrypt(pad(plain.encode(), 16))).decode()

def rand16() -> str:
    return "".join(random.choices("0123456789", k=16))

def trace_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices("0123456789", k=18))

def md5_upper(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest().upper()

def parse_time_str(time_str: str) -> int:
    h, m, s = map(int, time_str.split(":"))
    target_dt = datetime.datetime.now().replace(hour=h, minute=m, second=s, microsecond=0)
    return int(time.mktime(target_dt.timetuple()))

# ===================== Ticket缓存读写 =====================
def load_cache_ticket() -> str | None:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if cache.get("phone") != ACCOUNT_PHONE:
            return None
        create_ts = cache.get("create_ts", 0)
        if time.time() - create_ts > TICKET_VALID_SEC:
            print("✅ 缓存Ticket已过期，重新账号密码登录")
            os.remove(CACHE_FILE)
            return None
        return cache.get("ticket")
    except Exception:
        return None

def save_cache_ticket(ticket: str):
    data = {
        "phone": ACCOUNT_PHONE,
        "ticket": ticket,
        "create_ts": time.time()
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✅ Ticket已缓存，有效期10天，下次免密登录")

# ===================== 账号密码登录核心（电信原版加密接口） =====================
async def account_pwd_login(session: aiohttp.ClientSession, pub_global_key: str) -> str | None:
    """账号+密码加密请求登录，返回ticket"""
    url = "https://auth.10000.com/api/v2/login/pwdLogin"
    phone_enc = shift_encode(ACCOUNT_PHONE)
    pwd_enc = des3_encrypt(ACCOUNT_PASSWORD)

    req_body = {
        "account": phone_enc,
        "password": pwd_enc,
        "deviceId": "WEB_WX_H5",
        "clientType": "h5",
        "appVersion": "8.0.0"
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        async with session.post(url, json=req_body, headers=headers, ssl=ssl_ctx) as resp:
            res = await resp.json()
            if res.get("code") != 0:
                print(f"❌ 账号密码登录失败：{res.get('msg')}")
                return None
            # 提取登录返回的加密ticket
            encrypt_ticket = res["data"]["ticket"]
            # 调用原有getTicket接口二次解析业务ticket（和旧脚本逻辑对齐）
            ticket = await get_final_ticket(session, encrypt_ticket, pub_global_key)
            if ticket:
                save_cache_ticket(ticket)
            return ticket
    except Exception as e:
        print(f"❌ 登录请求异常: {str(e)}")
        return None

async def get_final_ticket(session: aiohttp.ClientSession, encrypt_str: str, pub_key: str) -> str | None:
    """二次解密获取最终可用ticket"""
    url = "https://auth.10000.com/api/v2/login/getTicket"
    body = {
        "encryptData": encrypt_str,
        "publicKey": pub_key
    }
    async with session.post(url, json=body, ssl=ssl_ctx) as resp:
        res = await resp.json()
        if res.get("code") != 0:
            return None
        return des3_decrypt(res["data"]["ticket"])

# ===================== 公共请求封装 =====================
async def req_post(session: aiohttp.ClientSession, url: str, data: dict):
    try:
        async with session.post(url, json=data, ssl=ssl_ctx) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        print(f"🔻 请求异常 {url}: {e}")
        return None

def build_req_param(origin_data: dict, pub_key: str, product_no: str) -> dict:
    raw_json = json.dumps(origin_data)
    rk = rand16()
    key_encrypt = rsa_pub_encrypt(pub_key, rk)
    data_encrypt = aes_cbc_encrypt(raw_json, rk)
    return {
        "encyType": "C005",
        "data": data_encrypt,
        "fromChannelId": "H5",
        "key": key_encrypt,
        "productNo": product_no,
        "sign": md5_upper(raw_json)
    }

# ===================== 业务接口：获取SessionKey、查券、领权益 =====================
async def get_session_key(session: aiohttp.ClientSession, phone: str, ticket: str, pub_key: str, p_no: str):
    payload = {
        "appType": APP_TYPE,
        "agreeId": "20201016030100056487302393758758",
        "encryptData": ticket,
        "systemType": "",
        "imei": "",
        "mtMac": "",
        "wifiMac": "",
        "location": ""
    }
    body = build_req_param(payload, pub_key, p_no)
    resp = await req_post(session, "https://mapi-welcome.bestpay.com.cn/gapi/AppFusionLogin/authorizeAndRegister", body)
    if not resp:
        return None
    return resp.get("result", {}).get("sessionKey")

async def query_my_coupons(session: aiohttp.ClientSession, phone: str, skey: str, pub_key: str, p_no: str):
    payload = {
        "encyType": "C005",
        "appType": APP_TYPE,
        "agreeId": "20210518030100134138528408797188",
        "fromChannelId": "H5",
        "traceLogId": "",
        "productNo": phone,
        "sessionKey": skey,
        "pageNo": "1",
        "pageSize": "100"
    }
    body = build_req_param(payload, pub_key, p_no)
    resp = await req_post(session, "https://mapi-h5.bestpay.com.cn/gapi/5gproduct/vipProduct/equitySpecialZoneService/queryUserNoUseEquity", body)
    if not resp:
        return
    all_coupons = []
    for item in resp.get("result", {}).get("queryNoUserInfoList", []):
        all_coupons.extend(item.get("batchList", []))
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    for c in all_coupons:
        if c["batchName"] in BLACK_COUPON:
            continue
        start_date = c["couponStartTime"].split(" ")[0]
        if SKIP_NOT_START and int(start_date.replace("-", "")) > int(today.replace("-", "")):
            continue
        msg = f"🎫 {c['batchName']} 满{c['minConsume']}减{c['denomination']} | 有效期：{c['couponStartTime']} ~ {c['couponEndTime']}"
        LOG_STORE[phone].append(msg)
        print(msg)

async def get_my_contract_list(session: aiohttp.ClientSession, phone: str, skey: str, pub_key: str, p_no: str):
    payload = {
        "encyType": "C005",
        "appType": APP_TYPE,
        "fromChannelId": "H5",
        "productNo": phone,
        "sessionKey": skey,
        "currentPage": 1,
        "displayOrderType": "DEFAULT",
        "pageSize": 70
    }
    body = build_req_param(payload, pub_key, p_no)
    return await req_post(session, "https://mapi-h5.bestpay.com.cn/gapi/5gproduct/vipProduct/query/pageOrderedSales", body)

async def get_package_detail(session: aiohttp.ClientSession, phone: str, skey: str, order_no: str, pub_key: str, p_no: str):
    payload = {
        "encyType": "C005",
        "orderNo": order_no,
        "appType": APP_TYPE,
        "agreeId": "20211216030100210919654787383364",
        "productNo": phone,
        "phoneNo": phone,
        "requestNo": rand16(),
        "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sessionKey": skey,
        "requestSystem": "equity-novel-h5",
        "operator": "",
        "traceLogId": ""
    }
    body = build_req_param(payload, pub_key, p_no)
    return await req_post(session, "https://mapi-h5.bestpay.com.cn/gapi/ep-product-center/EquityPackageService/queryEquityPackageDetailCustomer", body)

async def get_package_equity_list(session: aiohttp.ClientSession, phone: str, skey: str, order_no: str, module_id: str, unit_ids: list, pub_key: str, p_no: str):
    payload = {
        "encyType": "C005",
        "orderNo": order_no,
        "appType": APP_TYPE,
        "agreeId": "20211216030100210919654787383364",
        "productNo": phone,
        "phoneNo": phone,
        "sessionKey": skey,
        "unitEquityIdList": unit_ids,
        "currentPeriodNumber": "1",
        "moduleId": module_id
    }
    body = build_req_param(payload, pub_key, p_no)
    return await req_post(session, "https://mapi-h5.bestpay.com.cn/gapi/op-product-system/EquityPackageService/queryOrderedEquityPackage", body)

async def receive_equity(session: aiohttp.ClientSession, phone: str, skey: str, order_no: str, module_id: str, unit_eid: str, eid: str, title: str, wait_ts: int, pub_key: str, p_no: str):
    if wait_ts > 0:
        sleep_sec = int(wait_ts - time.time())
        if 0 < sleep_sec < 600:
            print(f"⌛ 等待{sleep_sec}秒到领取时间...")
            await asyncio.sleep(sleep_sec)
    payload = {
        "equityId": eid,
        "orderNo": order_no,
        "equityModuleId": module_id,
        "appId": None,
        "encyType": "C005",
        "appType": APP_TYPE,
        "agreeId": "20211216030100210919654787383364",
        "fromChannelId": "h5",
        "timestamp": int(time.time() * 1000),
        "priceType": "SALES_PRICE",
        "unitEquityId": unit_eid,
        "productNo": phone,
        "phoneNo": phone,
        "requestNo": rand16(),
        "requestDate": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sessionKey": skey,
        "requestSystem": "equity-novel-h5",
        "operator": "",
        "traceLogId": ""
    }
    body = build_req_param(payload, pub_key, p_no)
    for _ in range(RETRY_TIMES):
        resp = await req_post(session, "https://mapi-h5.bestpay.com.cn/gapi/ep-product-center/RebateService/manualReceiveEquity", body)
        if not resp:
            await asyncio.sleep(1)
            continue
        msg = resp.get("errorMsg", "")
        if resp.get("success"):
            msg = "领取成功"
        log_line = f"✅ {phone}【{title}】{msg}"
        print(log_line)
        LOG_STORE[phone].append(log_line)
        if "成功" in msg or "上限" in msg or "已领" in msg:
            break
        await asyncio.sleep(0.8)

async def process_single_package(session: aiohttp.ClientSession, phone: str, skey: str, item, pub_key: str, p_no: str):
    order_num = item["orderNo"]
    pkg_name = item["qyProductName"]
    detail = await get_package_detail(session, phone, skey, order_num, pub_key, p_no)
    if not detail:
        return
    res_data = detail.get("result", {})
    module_list = res_data.get("equityModuleInfoDTOList", [])
    for mod in module_list:
        mid = mod["moduleId"]
        mname = mod["moduleShowConfigDTO"]["moduleName"]
        target_list = TARGET_PACK.get(mname, [])
        wait_time = 0
        if len(target_list) > 0 and ":" in target_list[-1]:
            wait_time = parse_time_str(target_list[-1])
        bind_items = []
        if mod.get("classifyDTOList"):
            for cls in mod["classifyDTOList"]:
                for line in cls["lineDTOList"]:
                    bind_items.extend(line["bindEquityList"])
        if mod.get("bindEquityList"):
            bind_items.extend(mod["bindEquityList"])
        unit_eids = [x["unitEquityId"] for x in bind_items]
        if not unit_eids:
            continue
        equity_res = await get_package_equity_list(session, phone, skey, order_num, mid, unit_eids, pub_key, p_no)
        if not equity_res:
            continue
        for eq in equity_res.get("result", []):
            eq_title = f"{eq['bindEquityConfig']['equityMainTitle']} {eq['bindEquityConfig']['equitySubTitle']}"
            if SHOW_ALL_ITEM:
                print(f"📦 检测权益：{pkg_name} -> {eq_title}")
            if eq_title not in target_list:
                continue
            ueid = eq["unitEquityId"]
            eid = eq["equityId"]
            if eq["lastDistributeStatus"] == "SUCCESS":
                LOG_STORE[phone].append(f"ℹ️ {phone}【{eq_title}】已领取过")
                continue
            await receive_equity(session, phone, skey, order_num, mid, ueid, eid, eq_title, wait_time, pub_key, p_no)

# ===================== 主执行入口 =====================
async def main():
    tcp_conn = aiohttp.TCPConnector(limit=200, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=tcp_conn) as sess:
        # 1. 获取全局公钥
        product_no = str(int(time.time()))
        pub_req_body = {
            "productNo": product_no,
            "requestType": "H5",
            "traceLogId": trace_id()
        }
        pub_resp = await req_post(sess, "https://mapi-welcome.bestpay.com.cn/gapi/mapi-gateway/applyLoginFactor", pub_req_body)
        if not pub_resp:
            print("❌ 获取全局公钥失败，程序退出")
            return
        global_pub_key = pub_resp["result"]["nonce"]

        # 2. 获取有效Ticket（缓存优先，失效走账号密码登录）
        valid_ticket = load_cache_ticket()
        if not valid_ticket:
            print("🔐 开始执行账号密码登录...")
            valid_ticket = await account_pwd_login(sess, global_pub_key)
            if not valid_ticket:
                print("❌ 登录失败，终止运行")
                return

        # 3. 获取业务SessionKey
        session_key = await get_session_key(sess, ACCOUNT_PHONE, valid_ticket, global_pub_key, product_no)
        if not session_key:
            print("❌ SessionKey获取失败，删除缓存重新登录")
            if os.path.exists(CACHE_FILE):
                os.remove(CACHE_FILE)
            return

        LOG_STORE[ACCOUNT_PHONE] = []
        print(f"\n================ 开始执行账号 {ACCOUNT_PHONE} ================")

        # 4. 查询已到账优惠券
        if QUERY_COUPON_LIST:
            print("\n--- 已持有优惠券列表 ---")
            await query_my_coupons(sess, ACCOUNT_PHONE, session_key, global_pub_key, product_no)

        # 5. 遍历合约包自动领权益
        contract_data = await get_my_contract_list(sess, ACCOUNT_PHONE, session_key, global_pub_key, product_no)
        if not contract_data or not contract_data.get("result", {}).get("salesProductList"):
            LOG_STORE[ACCOUNT_PHONE].append("无已订购的5G权益合约包")
        else:
            sem = asyncio.Semaphore(SEMAPHORE_NUM)
            tasks = []
            for pkg in contract_data["result"]["salesProductList"]:
                for key in TARGET_PACK:
                    if key in pkg["qyProductName"]:
                        tasks.append(process_single_package(sess, ACCOUNT_PHONE, session_key, pkg, global_pub_key, product_no))
            async def wrap_task(t):
                async with sem:
                    await t
            await asyncio.gather(*[wrap_task(t) for t in tasks])

    # 输出最终汇总日志
    print("\n==================== 执行汇总 ====================")
    for tel, logs in LOG_STORE.items():
        print(f"【手机号：{tel}】")
        for line in logs:
            print(f"  {line}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
