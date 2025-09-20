from flask import Flask, request, abort
import requests
import os
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

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

# 股票對照表
stock_map = {
    "台積電": "TSM",
    "鴻海": "HNHPF",
    "聯發科": "2454.TW",
    "聯電": "2303.TW",
    "瑞昱": "2379.TW",
    "中華電": "CHT",
    "大立光": "3008.TW",
    "廣達": "2382.TW",
    "光寶科": "2301.TW",
    "緯穎": "6669.TW"
}


# ========== 功能函式 ==========

def call_deepseek(user_message):
    """呼叫 DeepSeek AI"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY.strip()}",
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
        resp = requests.post(OPENROUTER_URL, headers=headers, json=data)
        resp_json = resp.json()
        if "choices" in resp_json:
            return resp_json["choices"][0]["message"]["content"]
        else:
            return f"⚠️ AI 錯誤: {resp_json}"
    except Exception as e:
        return f"⚠️ 呼叫 AI 錯誤: {str(e)}"


def get_realtime_price(symbol):
    """即時股價"""
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.history(period="1d")["Close"].iloc[-1]
        return f"{symbol} 即時收盤價：{price:.2f}"
    except Exception:
        return f"⚠️ 無法取得 {symbol} 即時股價"


def get_historical_price(symbol, date):
    """歷史股價（從 stock_data CSV 讀取）"""
    filepath = f"stock_data/{symbol}.csv"
    if not os.path.exists(filepath):
        return f"⚠️ 找不到 {symbol} 的歷史資料檔"
    df = pd.read_csv(filepath)
    df["Date"] = pd.to_datetime(df["Date"])
    row = df[df["Date"] == pd.to_datetime(date)]
    if row.empty:
        return f"⚠️ 找不到 {date} 的股價紀錄"
    price = row.iloc[0]["Close"]
    return f"{symbol} 在 {date} 的收盤價：{price:.2f}"


def get_average_price(symbol, start=None, end=None, days=None):
    """平均價（全期間 / 區間 / 最近N天）"""
    filepath = f"stock_data/{symbol}.csv"
    if not os.path.exists(filepath):
        return f"⚠️ 找不到 {symbol} 的歷史資料檔"
    df = pd.read_csv(filepath)
    df["Date"] = pd.to_datetime(df["Date"])

    if days:
        df = df.tail(days)
    elif start and end:
        df = df[(df["Date"] >= pd.to_datetime(start)) & (df["Date"] <= pd.to_datetime(end))]

    if df.empty:
        return f"⚠️ 找不到指定範圍的資料"

    avg = df["Close"].mean()
    return f"{symbol} 平均收盤價：{avg:.2f}"


def get_high_low(symbol, mode="high"):
    """最高 / 最低價"""
    filepath = f"stock_data/{symbol}.csv"
    if not os.path.exists(filepath):
        return f"⚠️ 找不到 {symbol} 的歷史資料檔"
    df = pd.read_csv(filepath)

    if mode == "high":
        price = df["High"].max()
        return f"{symbol} 歷史最高價：{price:.2f}"
    else:
        price = df["Low"].min()
        return f"{symbol} 歷史最低價：{price:.2f}"


# ========== LINE Webhook ==========
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    reply_text = None

    # 幫助指令
    if user_text in ["幫助", "help"]:
        reply_text = (
            "📌 可用功能指令：\n"
            "1️⃣ 即時 AI 對話：直接輸入問題\n"
            "2️⃣ 指定日期收盤價：台積電 2023-07-01\n"
            "3️⃣ 平均價格（全期間）：台積電 平均\n"
            "4️⃣ 區間平均：台積電 平均 2023-01-01 2023-06-30\n"
            "5️⃣ 最近 N 天平均：台積電 最近10天\n"
            "6️⃣ 最高/最低：台積電 最高 | 台積電 最低\n"
            "7️⃣ 多股票同一天：台積電 鴻海 聯發科 2023-07-01"
        )

    else:
        parts = user_text.split()
        # 格式：股票 日期
        if len(parts) == 2 and parts[0] in stock_map:
            name, arg = parts
            symbol = stock_map[name]

            if "-" in arg:  # 日期
                reply_text = get_historical_price(symbol, arg)
            elif arg == "平均":
                reply_text = get_average_price(symbol)
            elif arg == "最高":
                reply_text = get_high_low(symbol, "high")
            elif arg == "最低":
                reply_text = get_high_low(symbol, "low")
            elif "最近" in arg:
                days = int(arg.replace("最近", "").replace("天", ""))
                reply_text = get_average_price(symbol, days=days)
            else:
                reply_text = get_realtime_price(symbol)

        # 格式：股票 平均 start end
        elif len(parts) == 4 and parts[0] in stock_map and parts[1] == "平均":
            name, _, start, end = parts
            symbol = stock_map[name]
            reply_text = get_average_price(symbol, start=start, end=end)

        # 格式：多股票 日期
        elif len(parts) >= 2 and parts[-1].count("-") == 2:
            date = parts[-1]
            names = parts[:-1]
            replies = []
            for n in names:
                if n in stock_map:
                    replies.append(get_historical_price(stock_map[n], date))
            reply_text = "\n".join(replies) if replies else "⚠️ 沒有有效的股票名稱"

        # 預設走 AI
        else:
            reply_text = call_deepseek(user_text)

    # 回覆 LINE
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
