from flask import Flask, request, abort
import os
import pandas as pd
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 初始化 Flask
app = Flask(__name__)
load_dotenv()

# LINE 設定
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# 股票資料夾
STOCK_DIR = "stock_data"

# 股票代碼對照
STOCK_SYMBOLS = {
    "台積電": "TSM",
    "鴻海": "HNHPF",
    "聯發科": "2454.TW",
    "聯電": "2303.TW",
    "瑞昱": "2379.TW",
    "中華電": "CHT",
    "大立光": "3008.TW",
    "廣達": "2382.TW",
    "光寶": "2301.TW",
    "緯穎": "6669.TW"
}


def load_stock_data(symbol):
    """讀取 CSV 並處理格式"""
    file_path = os.path.join(STOCK_DIR, f"{symbol}.csv")
    if not os.path.exists(file_path):
        return None

    df = pd.read_csv(file_path)
    if "Date" not in df.columns or "Close" not in df.columns:
        return None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df["High"] = pd.to_numeric(df.get("High"), errors="coerce")
    df["Low"] = pd.to_numeric(df.get("Low"), errors="coerce")
    df = df.dropna(subset=["Close"])
    return df


def process_command(text):
    parts = text.strip().split()
    if not parts:
        return "⚠️ 指令格式錯誤，輸入「幫助」查看指令"

    # 幫助清單
    if parts[0] == "幫助":
        return (
            "📊 可用功能指令：\n"
            "1️⃣ 即時 AI 對話：直接輸入問題\n"
            "2️⃣ 指定日期收盤價：台積電 2023-07-01\n"
            "3️⃣ 平均價格（全期間）：台積電 平均\n"
            "4️⃣ 區間平均：台積電 平均 2023-01-01 2023-06-30\n"
            "5️⃣ 最近 N 天平均：台積電 最近10天\n"
            "6️⃣ 最高/最低：台積電 最高 | 台積電 最低\n"
            "7️⃣ 多股票同一天：台積電 鴻海 聯發科 2023-07-01"
        )

    stock_name = parts[0]
    if stock_name not in STOCK_SYMBOLS:
        return "⚠️ 找不到該股票代號"

    symbol = STOCK_SYMBOLS[stock_name]
    df = load_stock_data(symbol)
    if df is None:
        return f"⚠️ 沒有 {stock_name} 的歷史資料"

    # 指令解析
    try:
        if len(parts) == 2 and parts[1].count("-") == 2:
            # 指定日期收盤價
            date = pd.to_datetime(parts[1], errors="coerce")
            row = df[df["Date"] == date]
            if not row.empty:
                return f"{stock_name} {parts[1]} 收盤價：{row.iloc[0]['Close']:.2f}"
            else:
                return f"⚠️ 找不到 {stock_name} {parts[1]} 的股價紀錄"

        elif len(parts) == 2 and parts[1] == "平均":
            # 全部平均
            avg_price = df["Close"].mean()
            return f"{stock_name} 全期間平均收盤價：{avg_price:.2f}"

        elif len(parts) == 4 and parts[1] == "平均":
            # 區間平均
            start, end = pd.to_datetime(parts[2]), pd.to_datetime(parts[3])
            mask = (df["Date"] >= start) & (df["Date"] <= end)
            avg_price = df.loc[mask, "Close"].mean()
            return f"{stock_name} {parts[2]} ~ {parts[3]} 平均收盤價：{avg_price:.2f}"

        elif len(parts) == 2 and parts[1].startswith("最近"):
            # 最近 N 天平均
            days = int(parts[1].replace("最近", "").replace("天", ""))
            avg_price = df.tail(days)["Close"].mean()
            return f"{stock_name} 最近 {days} 天平均收盤價：{avg_price:.2f}"

        elif len(parts) == 2 and parts[1] in ["最高", "最低"]:
            if parts[1] == "最高":
                price = df["Close"].max()
                return f"{stock_name} 歷史最高收盤價：{price:.2f}"
            else:
                price = df["Close"].min()
                return f"{stock_name} 歷史最低收盤價：{price:.2f}"

        elif len(parts) >= 2 and parts[-1].count("-") == 2:
            # 多股票同一天
            date = pd.to_datetime(parts[-1])
            results = []
            for s in parts[:-1]:
                if s in STOCK_SYMBOLS:
                    sym = STOCK_SYMBOLS[s]
                    dfx = load_stock_data(sym)
                    if dfx is not None:
                        row = dfx[dfx["Date"] == date]
                        if not row.empty:
                            results.append(f"{s} 收盤價：{row.iloc[0]['Close']:.2f}")
                        else:
                            results.append(f"{s} {parts[-1]} 沒有資料")
            return "\n".join(results) if results else "⚠️ 沒有任何股票的資料"

    except Exception as e:
        return f"⚠️ 錯誤: {str(e)}"

    return "⚠️ 無法識別的指令，輸入「幫助」查看用法"


# LINE Webhook
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

    if not reply_text:
        reply_text = "⚠️ 系統無法處理您的請求"

    if len(reply_text) > 4900:  # 避免超過 LINE 限制
        reply_text = reply_text[:4900] + "…(回覆過長已截斷)"

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
