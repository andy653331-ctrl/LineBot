from flask import Flask, request, abort
import os
import re
import requests
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime

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

# 載入環境變數
load_dotenv()

app = Flask(__name__)

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 股票清單
STOCKS = {
    "台積電": "TSM",
    "鴻海": "HNHPF",
    "聯發科": "2454.TW",
    "聯電": "2303.TW",
    "瑞昱": "2379.TW",
    "中華電": "CHT",
    "大立光": "3008.TW",
    "廣達": "2382.TW",
    "光寶科": "2301.TW",
    "緯穎": "6669.TW",
}

DATA_DIR = "stock_data"


# =============== 股票輔助函式 =================
def load_stock_data(symbol):
    """讀取股票 CSV"""
    filepath = os.path.join(DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(filepath):
        return None
    df = pd.read_csv(filepath)
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def get_price_on_date(df, query_date):
    """查詢指定日期，若休市則往前找最近交易日"""
    query_date = pd.to_datetime(query_date)
    row = df[df["Date"] == query_date]
    if row.empty:
        row = df[df["Date"] <= query_date].tail(1)
    if not row.empty:
        return row.iloc[0]["Close"], row.iloc[0]["Date"]
    return None, None


def get_average(df, start=None, end=None):
    if start and end:
        mask = (df["Date"] >= pd.to_datetime(start)) & (df["Date"] <= pd.to_datetime(end))
        return df.loc[mask, "Close"].mean()
    return df["Close"].mean()


def get_recent_avg(df, days):
    return df.tail(days)["Close"].mean()


def get_max_min(df, mode="max"):
    if mode == "max":
        row = df.loc[df["Close"].idxmax()]
    else:
        row = df.loc[df["Close"].idxmin()]
    return row["Close"], row["Date"]


# =============== AI 模式 =================
def call_deepseek(user_message):
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
        return f"⚠️ AI 錯誤: {resp_json}"
    except Exception as e:
        return f"⚠️ 呼叫 API 發生錯誤: {str(e)}"


# =============== LINE Webhook =================
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
    reply_text = process_command(user_text)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


# =============== 指令解析 =================
def process_command(text):
    # 多股票同一天
    multi_match = re.match(r"(.+)\s+(\d{4}-\d{2}-\d{2})", text)
    if multi_match:
        stocks = multi_match.group(1).split()
        date = multi_match.group(2)
        reply = []
        for name in stocks:
            if name in STOCKS:
                df = load_stock_data(STOCKS[name])
                if df is not None:
                    price, actual_date = get_price_on_date(df, date)
                    if price:
                        reply.append(f"{name} {actual_date.date()} 收盤價：{price:.2f}")
        return "\n".join(reply) if reply else "⚠️ 找不到資料"

    # 平均（全期間）
    avg_match = re.match(r"(.+)\s+平均$", text)
    if avg_match:
        name = avg_match.group(1)
        if name in STOCKS:
            df = load_stock_data(STOCKS[name])
            if df is not None:
                avg = get_average(df)
                return f"{name} 平均收盤價：{avg:.2f}"

    # 區間平均
    range_match = re.match(r"(.+)\s+平均\s+(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})", text)
    if range_match:
        name, start, end = range_match.groups()
        if name in STOCKS:
            df = load_stock_data(STOCKS[name])
            if df is not None:
                avg = get_average(df, start, end)
                return f"{name} {start} ~ {end} 平均收盤價：{avg:.2f}"

    # 最近N天
    recent_match = re.match(r"(.+)\s+最近(\d+)天", text)
    if recent_match:
        name, days = recent_match.groups()
        if name in STOCKS:
            df = load_stock_data(STOCKS[name])
            if df is not None:
                avg = get_recent_avg(df, int(days))
                return f"{name} 最近{days}天平均收盤價：{avg:.2f}"

    # 最高 / 最低
    max_min_match = re.match(r"(.+)\s+(最高|最低)", text)
    if max_min_match:
        name, mode = max_min_match.groups()
        if name in STOCKS:
            df = load_stock_data(STOCKS[name])
            if df is not None:
                price, date = get_max_min(df, "max" if mode == "最高" else "min")
                return f"{name} {mode}價：{price:.2f} ({date.date()})"

    # 單一股票指定日期
    date_match = re.match(r"(.+)\s+(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        name, date = date_match.groups()
        if name in STOCKS:
            df = load_stock_data(STOCKS[name])
            if df is not None:
                price, actual_date = get_price_on_date(df, date)
                if price:
                    return f"{name} {actual_date.date()} 收盤價：{price:.2f}"
                else:
                    return f"⚠️ 找不到 {date} 的股價記錄"

    # 如果都不是 → 進 AI 模式
    return call_deepseek(text)


# ============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=True)
