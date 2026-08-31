import requests
import json
import time
import hmac
import hashlib
import base64
import urllib.parse

# ====== 钉钉机器人配置 ======
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=a29ae898ee9691dd3573fd99c2de1e7c212b2dd10b7ac2d3a4537d65b0024fc5"
DINGTALK_SECRET = "SEC89a10192be26cbe3d2d4693979e20900703a45104145e3e8702adcb375da4669"

# ====== 生成加签签名（钉钉官方标准算法） ======
timestamp = str(round(time.time() * 1000))
secret_enc = DINGTALK_SECRET.encode("utf-8")
string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
string_to_sign_enc = string_to_sign.encode("utf-8")
hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))

# 拼接最终请求地址
final_url = f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"

# ====== 发送测试消息 ======
payload = {
    "msgtype": "markdown",
    "markdown": {
        "title": "线报推送测试",
        "text": "### 🧪 钉钉机器人测试\n\n如果你的钉钉群收到这条消息，说明：\n- Webhook 地址配置正确\n- 加签签名验证通过\n- 服务器网络访问正常"
    }
}

try:
    resp = requests.post(final_url, json=payload, timeout=10)
    result = resp.json()
    print("返回结果：", json.dumps(result, indent=2, ensure_ascii=False))
    
    if result.get("errcode") == 0:
        print("✅ 推送成功，请查看钉钉群")
    else:
        print("❌ 推送失败，错误原因：", result.get("errmsg"))
except Exception as e:
    print("❌ 请求异常：", str(e))
