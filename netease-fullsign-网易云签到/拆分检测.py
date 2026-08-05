import os

kwyy = os.getenv("KWYY","")
print(f"原始串:{kwyy}")
acc_list = kwyy.split("&")
print(f"分割后账号总数：{len(acc_list)}")
for idx,acc in enumerate(acc_list):
    print(f"第{idx+1}号原始：{acc}")
    parts = acc.split("#")
    print(f"  切割片段:{parts},片段数量:{len(parts)}")