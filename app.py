from flask import Flask, request, abort
import os
import pandas as pd
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

# 載入環境變數
load_dotenv()

app = Flask(__name__)

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 股票代號對應表
STOCK_SYMBOLS = {
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

# 幫助訊息
HELP_TEXT = """📊 可用功能指令：
1️⃣ 即時 AI 對話：直接輸入問題
2️⃣ 指定日期收盤價：台積電 2023-07-01
3️⃣ 平均價格（全期間）：台積電 平均
4️⃣ 區間平均：台積電 平均 2023-01-01 2023-06-30
5️⃣ 最近 N 天平均：台積電 最近10天
6️⃣ 最高/最低：台積電 最高 | 台積電 最低
7️⃣ 多股票同一天：台積電 鴻海 聯發科 2023-07-01
輸入「幫助」隨時查看此清單
"""

# 讀取股票 CSV
def load_stock_data(symbol):
    filepath = os.path.join(DATA_DIR, f"{symbol}.csv")
    if not os.path.exists(filepath):
        return None
    df = pd.read_csv(filepath)
    if "Date" not in df.columns:
        raise ValueError(f"{symbol} 缺少 Date 欄位")
    df["Date"] = pd.to_datetime(df["Date"])
    return df

# 指令處理
def process_command(text):
    parts = text.strip().split()
    if text in ["幫助", "help", "說明"]:
        return HELP_TEXT

    replies = []
    try:
        # 多股票 + 日期
        if len(parts) >= 2 and parts[-1].count("-") == 2:
            date = pd.to_datetime(parts[-1])
            stocks = parts[:-1]
            for stock in stocks:
                if stock in STOCK_SYMBOLS:
                    df = load_stock_data(STOCK_SYMBOLS[stock])
                    if df is not None:
                        row = df[df["Date"] == date]
                        if not row.empty:
                            price = float(row["Close"].values[0])
                            replies.append(f"{stock} {date.date()} 收盤價: {price:.2f}")
                        else:
                            replies.append(f"⚠ 找不到 {stock} {date.date()} 的股價紀錄")
            return "\n".join(replies) if replies else "⚠ 找不到資料"

        # 平均價格
        if len(parts) == 2 and parts[1] == "平均":
            stock = parts[0]
            if stock in STOCK_SYMBOLS:
                df = load_stock_data(STOCK_SYMBOLS[stock])
                if df is not None:
                    price = float(df["Close"].mean())
                    return f"{stock} 平均收盤價: {price:.2f}"

        # 區間平均
        if len(parts) == 4 and parts[1] == "平均":
            stock = parts[0]
            start, end = pd.to_datetime(parts[2]), pd.to_datetime(parts[3])
            df = load_stock_data(STOCK_SYMBOLS[stock])
            if df is not None:
                mask = (df["Date"] >= start) & (df["Date"] <= end)
                subset = df.loc[mask]
                if not subset.empty:
                    price = float(subset["Close"].mean())
                    return f"{stock} {start.date()}~{end.date()} 平均收盤價: {price:.2f}"

        # 最近 N 天平均
        if len(parts) == 2 and parts[1].startswith("最近"):
            stock = parts[0]
            n = int(parts[1].replace("最近", "").replace("天", ""))
            df = load_stock_data(STOCK_SYMBOLS[stock])
            if df is not None:
                subset = df.tail(n)
                price = float(subset["Close"].mean())
                return f"{stock} 最近{n}天平均收盤價: {price:.2f}"

        # 最高/最低
        if len(parts) == 2 and parts[1] in ["最高", "最低"]:
            stock, cmd = parts
            df = load_stock_data(STOCK_SYMBOLS[stock])
            if df is not None:
                price = float(df["Close"].max() if cmd == "最高" else df["Close"].min())
                return f"{stock} 歷史{cmd}價: {price:.2f}"

        return "⚠ 指令格式錯誤，輸入「幫助」查看說明"

    except Exception as e:
        return f"⚠ 錯誤: {str(e)}"


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
    user_text = event.message.text
    reply_text = process_command(user_text)
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
