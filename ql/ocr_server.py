import base64, socket, sys

# 防重复启动：7777 已有 OCR 实例在监听时，本进程直接安静退出（返回成功），
# 避免定时任务重复绑定报 Address already in use；同时延后加载 ddddocr/onnxruntime。
def _already_running(host="127.0.0.1", port=7777):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()

if _already_running():
    print("7777 端口已有 OCR 实例在运行，本进程跳过重复启动。")
    sys.exit(0)

import ddddocr
from flask import Flask, request

app = Flask(__name__)
ocr = ddddocr.DdddOcr(show_ad=False)

@app.route("/classification", methods=["POST"])
def classification():
    img = base64.b64decode(request.get_json()["image"])
    return ocr.classification(img)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7777)
