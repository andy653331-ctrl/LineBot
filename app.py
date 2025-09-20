from flask import Flask, request, abort
import requests
import os
from dotenv import load_dotenv  # 讀取 .env 檔

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 載入 .env
load_dotenv()

app = Flask(__name__)

# LINE Bot 設定
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# OpenRouter (DeepSeek Free) API
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def call_deepseek(user_message):
    """呼叫 DeepSeek API"""
    if not OPENROUTER_API_KEY:
        print("❌ [ERROR] 沒有找到 OPENROUTER_API_KEY，請檢查 .env")
        return "⚠️ 系統沒有設定 AI 金鑰，請通知管理員。"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek/deepseek-chat-v3.1:free",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_message}
        ]
    }

    try:
        # Debug: 印出 header（避免全洩漏，只印前40碼）
        print(f"[DEBUG] Authorization header = Bearer {OPENROUTER_API_KEY[:40]}...")

        resp = requests.post(OPENROUTER_URL, headers=headers, json=data)
        resp_json = resp.json()

        # Debug log
        print(f"[User] {user_message}")
        print(f"[DeepSeek raw] {resp_json}")

        if "choices" in resp_json:
            reply = resp_json["choices"][0]["message"]["content"]
            print(f"[AI] {reply}")
            return reply
        else:
            return f"⚠️ AI 錯誤: {resp_json}"

    except Exception as e:
        return f"⚠️ 呼叫 API 發生錯誤: {str(e)}"


@app.route("/callback", methods=["POST"])
def callback():
    """LINE Webhook 入口"""
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理 LINE 文字訊息"""
    user_text = event.message.text
    reply_text = call_deepseek(user_text)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


if __name__ == "__main__":
    app.run(port=3000, debug=True)
