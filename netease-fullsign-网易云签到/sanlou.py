# -*- coding: utf-8 -*-
"""
葫芦侠三楼活动线报监控 - 钉钉推送版
接口地址：https://tmini.net/api/calabash
功能：拉取线报 → 关键词过滤 → 去重 → 钉钉群机器人推送
定时建议：*/10 * * * *  每10分钟执行一次
环境变量：
  DINGTALK_WEBHOOK  钉钉机器人完整Webhook地址（必填）
  DINGTALK_SECRET   钉钉机器人加签密钥（开启加签时必填）
"""

import requests
import json
import os
import time
import hmac
import hashlib
import base64
import urllib.parse

# ===================== 配置区 =====================
# 线报API地址
API_URL = "https://tmini.net/api/calabash"

# 过滤关键词，只推送包含以下关键词的帖子
FILTER_KEYWORDS = ["【现金红包】", "【虚拟物品】", "【实物专区】"]

# 清空记录开关：True=清空历史记录并重新推送；False=正常去重模式
# 测试推送时改为True，用完务必改回False，避免重复推送
CLEAR_RECORD = True

# 钉钉机器人Webhook，优先读取环境变量
DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
# 钉钉机器人加签密钥（开启加签才需要，优先读取环境变量）
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

# 已推送帖子ID记录文件（保存在脚本同目录）
RECORD_FILE = os.path.join(os.path.dirname(__file__), "hlx_calabash_record.txt")

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}
# ==================================================


def load_sent_ids():
    """加载已推送过的帖子ID"""
    sent_set = set()
    if os.path.exists(RECORD_FILE):
        with open(RECORD_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and line.isdigit():
                    sent_set.add(int(line))
    return sent_set


def save_sent_id(post_id):
    """保存已推送的帖子ID"""
    with open(RECORD_FILE, "a", encoding="utf-8") as f:
        f.write(f"{post_id}\n")


def send_dingtalk(title, content):
    """钉钉机器人推送通知，自动兼容普通模式和加签模式"""
    if not DINGTALK_WEBHOOK:
        print("[提示] 未配置DINGTALK_WEBHOOK，跳过推送")
        return False

    webhook = DINGTALK_WEBHOOK

    # 配置了加签密钥则自动生成签名
    if DINGTALK_SECRET:
        try:
            timestamp = str(round(time.time() * 1000))
            secret_enc = DINGTALK_SECRET.encode("utf-8")
            string_to_sign = f"{timestamp}\n{DINGTALK_SECRET}"
            string_to_sign_enc = string_to_sign.encode("utf-8")
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            webhook = f"{webhook}&timestamp={timestamp}&sign={sign}"
        except Exception as e:
            print(f"[加签失败] {str(e)}")
            return False

    # 组装Markdown格式消息
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content
        }
    }

    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        result = resp.json()
        if result.get("errcode") == 0:
            print(f"[推送成功] {title}")
            return True
        else:
            print(f"[推送失败] {result.get('errmsg', '未知错误')}")
            return False
    except Exception as e:
        print(f"[推送异常] {str(e)}")
        return False


def get_activity_list():
    """从API获取线报列表"""
    try:
        resp = requests.get(API_URL, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        data = resp.json()
        if isinstance(data, list):
            return data
        else:
            print(f"[API返回异常] 数据格式错误：{data}")
            return []
    except Exception as e:
        print(f"[请求API失败] {str(e)}")
        return []


def format_post_content(post):
    """格式化单条帖子为Markdown格式（适配钉钉渲染）"""
    title = post.get("title", "无标题")
    detail = post.get("detail", "无详情").strip()
    author = post.get("user", {}).get("nick", "匿名")
    hit = post.get("hit", 0)
    comment = post.get("commentCount", 0)

    markdown = f"""
### 📌 {title}
👤 作者：{author} | 👁️ 浏览：{hit} | 💬 评论：{comment}
---
{detail}
"""
    return markdown


def main():
    # 清空历史记录逻辑
    if CLEAR_RECORD:
        open(RECORD_FILE, "w").close()
        print("[操作] 已清空所有历史推送记录")

    print(f"========== {time.strftime('%Y-%m-%d %H:%M:%S')} 开始执行 ==========")

    # 1. 加载已推送记录
    sent_ids = load_sent_ids()
    print(f"已推送历史记录：{len(sent_ids)} 条")

    # 2. 获取线报数据
    post_list = get_activity_list()
    if not post_list:
        print("未获取到任何线报数据，结束执行")
        return

    print(f"本次获取线报总数：{len(post_list)} 条")

    # 3. 过滤+去重
    new_posts = []
    for post in post_list:
        pid = post.get("postID")
        title = post.get("title", "")

        # 跳过已推送
        if pid in sent_ids:
            continue

        # 关键词过滤
        if any(kw in title for kw in FILTER_KEYWORDS):
            new_posts.append(post)
            save_sent_id(pid)

    if not new_posts:
        print("暂无符合条件的新线报")
        return

    print(f"符合条件的新线报：{len(new_posts)} 条")

    # 4. 组装推送内容
    content_md = ""
    for post in new_posts:
        content_md += format_post_content(post)

    push_title = f"【葫芦侠线报】新增 {len(new_posts)} 条活动提醒"

    # 5. 执行推送
    send_dingtalk(push_title, content_md)
    print("========== 执行结束 ==========\n")


if __name__ == "__main__":
    main()
