import requests
import json

# ====== 填入你的钉钉机器人完整Webhook地址 ======
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=a29ae898ee9691dd3573fd99c2de1e7c212b2dd10b7ac2d3a4537d65b0024fc5"
DINGTALK_SECRET = "SEC89a10192be26cbe3d2d4693979e20900703a45104145e3e8702adcb375da4669"
# 测试消息标题包含"线报"关键词，适配关键词模式的机器人
payload = {
    "msgtype": "markdown",
    "markdown": {
        "title": "线报推送测试",
        "text": "### 🧪 钉钉机器人测试\n\n如果你的钉钉群收到这条消息，说明：\n- Webhook 地址配置正确\n- 机器人安全验证通过\n- 服务器网络访问钉钉接口正常"
    }
}

try:
    resp = requests.post(DINGTALK_WEBHOOK, json=payload, timeout=10)
    result = resp.json()
    print("返回结果：", json.dumps(result, indent=2, ensure_ascii=False))
    
    if result.get("errcode") == 0:
        print("✅ 推送成功，请查看钉钉群")
    else:
        print("❌ 推送失败，错误原因：", result.get("errmsg"))
except Exception as e:
    print("❌ 请求异常：", str(e))
