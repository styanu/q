# -*- coding: utf-8 -*-
"""
葫芦侠三楼活动线报监控 - 青龙面板版
接口地址：https://tmini.net/api/calabash
功能：拉取线报 → 关键词过滤 → 去重 → PushPlus推送
定时建议：*/10 * * * *  每10分钟执行一次
环境变量：PUSHPLUS_TOKEN  填入你的PushPlus推送Token
"""

import requests
import json
import os
import time

# ===================== 配置区 =====================
# 线报API地址
API_URL = "https://tmini.net/api/calabash"

# 过滤关键词，只推送包含以下关键词的帖子
FILTER_KEYWORDS = ["【现金红包】", "【虚拟物品】", "【实物专区】"]

# PushPlus推送Token，也可通过青龙环境变量 PUSHPLUS_TOKEN 设置
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")

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


def push_notification(title, content):
    """PushPlus推送通知"""
    if not PUSHPLUS_TOKEN:
        print("[提示] 未配置PushPlus Token，跳过推送")
        return False
    
    push_url = f"https://www.pushplus.plus/send"
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html"
    }
    
    try:
        resp = requests.post(push_url, data=data, timeout=10)
        result = resp.json()
        if result.get("code") == 200:
            print(f"[推送成功] {title}")
            return True
        else:
            print(f"[推送失败] {result.get('msg', '未知错误')}")
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
    """格式化单条帖子内容为HTML"""
    title = post.get("title", "无标题")
    detail = post.get("detail", "无详情").replace("\n", "<br>")
    author = post.get("user", {}).get("nick", "匿名")
    hit = post.get("hit", 0)
    comment = post.get("commentCount", 0)
    
    html = f"""
    <div style="margin-bottom: 15px; padding: 10px; border: 1px solid #eee; border-radius: 8px;">
        <h3 style="margin: 0 0 8px 0; color: #d9534f;">{title}</h3>
        <p style="margin: 4px 0; color: #666; font-size: 12px;">
            作者：{author} | 浏览：{hit} | 评论：{comment}
        </p>
        <div style="margin-top: 8px; line-height: 1.5;">{detail}</div>
    </div>
    """
    return html


def main():
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
    content_html = ""
    for post in new_posts:
        content_html += format_post_content(post)
    
    push_title = f"【葫芦侠线报】新增 {len(new_posts)} 条活动提醒"
    
    # 5. 执行推送
    push_notification(push_title, content_html)
    print("========== 执行结束 ==========\n")


if __name__ == "__main__":
    main()
