"""
cron: 30 59 8 * * *
const $ = new Env("翼支付合约领券-Ticket免登录稳定版");
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

# ===================== 配置区 填入抓包得到的ticket和手机号 =====================
PHONE = "你的手机号"
TICKET_STR = "粘贴你抓包getTicket接口返回的最终ticket字符串"

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
APP_TYPE = "116"
LOG_STORE = {}

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE
ssl_ctx.set_ciphers("DEFAULT@SECLEVEL=0")

# 工具函数
def rand16():
    return "".join(random.choices("0123456789", k=16))

def trace_id():
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices("0123456789", k=18))

def md5_upper(s):
    return hashlib.md5(s.encode()).hexdigest().upper()

def aes_cbc_encrypt(plain, key):
    cipher = AES.new(key.encode(), AES.MODE_CBC, b'\x00' * 16)
    return base64.b64encode(cipher.encrypt(pad(plain.encode(), 16))).decode()

def rsa_pub_encrypt(pub_key_str, content):
    pub_pem = f"-----BEGIN PUBLIC KEY-----\n{pub_key_str}\n-----END PUBLIC KEY-----"
    pub = rsa.PublicKey.load_pkcs1_openssl_pem(pub_pem.encode())
    return base64.b64encode(rsa.encrypt(content.encode(), pub)).decode()

def parse_time_str(time_str):
    h, m, s = map(int, time_str.split(":"))
    target_dt = datetime.datetime.now().replace(hour=h, minute=m, second=s, microsecond=0)
    return int(time.mktime(target_dt.timetuple()))

def build_req_param(origin_data, pub_key, product_no):
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

async def req_post(session, url, data):
    try:
        async with session.post(url, json=data, ssl=ssl_ctx) as resp:
            resp.raise_for_status()
            return await resp.json()
    except Exception as e:
        print(f"请求异常 {url}: {e}")
        return None

async def get_global_pubkey(session):
    p_no = str(int(time.time()))
    body = {"productNo": p_no, "requestType": "H5", "traceLogId": trace_id()}
    res = await req_post(session, "https://mapi-welcome.bestpay.com.cn/gapi/mapi-gateway/applyLoginFactor", body)
    if not res:
        return None, None
    return res["result"]["nonce"], p_no

async def get_session_key(session, phone, ticket, pub_key, p_no):
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
    return resp.get("result", {}).get("sessionKey") if resp else None

async def query_coupons(session, phone, skey, pub_key, p_no):
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
        msg = f"🎫 {c['batchName']} 满{c['minConsume']}减{c['denomination']} | {c['couponStartTime']} ~ {c['couponEndTime']}"
        LOG_STORE[phone].append(msg)
        print(msg)

async def get_contract_list(session, phone, skey, pub_key, p_no):
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

async def get_package_detail(session, phone, skey, order_no, pub_key, p_no):
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

async def get_equity_items(session, phone, skey, order_no, module_id, unit_ids, pub_key, p_no):
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

async def receive_one(session, phone, skey, order_no, module_id, ueid, eid, title, wait_ts, pub_key, p_no):
    if wait_ts > 0:
        sleep_sec = int(wait_ts - time.time())
        if 0 < sleep_sec < 600:
            print(f"⌛等待{sleep_sec}秒领取")
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
        "unitEquityId": ueid,
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
        res = await req_post(session, "https://mapi-h5.bestpay.com.cn/gapi/ep-product-center/RebateService/manualReceiveEquity", body)
        if not res:
            await asyncio.sleep(1)
            continue
        msg = res.get("errorMsg", "")
        if res.get("success"):
            msg = "领取成功"
        log = f"✅{phone}【{title}】{msg}"
        print(log)
        LOG_STORE[phone].append(log)
        if "成功" in msg or "已领" in msg or "上限" in msg:
            break
        await asyncio.sleep(0.8)

async def handle_package(session, phone, skey, pkg, pub_key, p_no):
    order_no = pkg["orderNo"]
    pkg_name = pkg["qyProductName"]
    detail = await get_package_detail(session, phone, skey, order_no, pub_key, p_no)
    if not detail:
        return
    data = detail.get("result", {})
    for mod in data.get("equityModuleInfoDTOList", []):
        mid = mod["moduleId"]
        mname = mod["moduleShowConfigDTO"]["moduleName"]
        target_list = TARGET_PACK.get(mname, [])
        wait = 0
        if target_list and ":" in target_list[-1]:
            wait = parse_time_str(target_list[-1])
        bind = []
        if mod.get("classifyDTOList"):
            for c in mod["classifyDTOList"]:
                bind.extend(c["lineDTOList"][0]["bindEquityList"])
        if mod.get("bindEquityList"):
            bind.extend(mod["bindEquityList"])
        ueids = [x["unitEquityId"] for x in bind]
        if not ueids:
            continue
        eq_list = await get_equity_items(session, phone, skey, order_no, mid, ueids, pub_key, p_no)
        if not eq_list:
            continue
        for eq in eq_list.get("result", []):
            title = f"{eq['bindEquityConfig']['equityMainTitle']} {eq['bindEquityConfig']['equitySubTitle']}"
            if SHOW_ALL_ITEM:
                print(f"检测权益：{pkg_name} -> {title}")
            if title not in target_list:
                continue
            if eq["lastDistributeStatus"] == "SUCCESS":
                LOG_STORE[phone].append(f"ℹ️{phone}【{title}】已领取")
                continue
            await receive_one(session, phone, skey, order_no, mid, eq["unitEquityId"], eq["equityId"], title, wait, pub_key, p_no)

async def main():
    LOG_STORE[PHONE] = []
    connector = aiohttp.TCPConnector(limit=200)
    async with aiohttp.ClientSession(connector=connector) as sess:
        pub_key, p_no = await get_global_pubkey(sess)
        if not pub_key:
            print("获取公钥失败")
            return
        skey = await get_session_key(sess, PHONE, TICKET_STR, pub_key, p_no)
        if not skey:
            print("ticket失效，请重新抓包更新")
            return
        print(f"\n===== 账号 {PHONE} 开始运行 =====")
        if QUERY_COUPON_LIST:
            print("\n--- 已领优惠券 ---")
            await query_coupons(sess, PHONE, skey, pub_key, p_no)
        contracts = await get_contract_list(sess, PHONE, skey, pub_key, p_no)
        if not contracts or not contracts.get("result", {}).get("salesProductList"):
            LOG_STORE[PHONE].append("无订购合约包")
        else:
            sem = asyncio.Semaphore(SEMAPHORE_NUM)
            tasks = []
            for item in contracts["result"]["salesProductList"]:
                for k in TARGET_PACK:
                    if k in item["qyProductName"]:
                        tasks.append(handle_package(sess, PHONE, skey, item, pub_key, p_no))
            async def wrap(t):
                async with sem:
                    await t
            await asyncio.gather(*[wrap(t) for t in tasks])
    print("\n===== 执行汇总 =====")
    for tel, logs in LOG_STORE.items():
        print(f"【{tel}】")
        for line in logs:
            print("  " + line)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
